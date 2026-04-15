"""Default handlers for SDK events: QR scanner, clipboard, biometry."""

import asyncio
import logging
import os
import platform
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

# JS code injected at runtime to open camera QR scanner inside the WebView.
# Uses BarcodeDetector if available, otherwise loads jsQR from CDN.
# Video is drawn to a visible <canvas> (WKWebView can't render <video> with getUserMedia).
QR_CAMERA_JS = (Path(__file__).parent / "qr_camera.js").read_text()


class BiometryEmulator:
    """Biometry emulation for desktop — full BiometricManager lifecycle.

    Real Telegram clients use platform keychain (Face ID, fingerprint).
    On desktop there's no biometric hardware, so this emulates the entire
    flow: init -> grant access -> store token -> authenticate -> return token.

    Without this, any Mini App that uses BiometricManager gets
    ``available: false`` and can't function.
    """

    def __init__(self):
        self._access_granted = False
        self._token = ""
        self._device_id = "tgwebview_desktop"

    def _info(self):
        return {
            "available": True,
            "type": "fingerprint",
            "access_requested": self._access_granted,
            "access_granted": self._access_granted,
            "token_saved": bool(self._token),
            "device_id": self._device_id,
        }

    async def handle(self, data):
        action = data.get("action", "")

        if action == "get_info":
            return self._info()

        if action == "request_access":
            self._access_granted = True
            log.info("Biometry access granted")
            return self._info()

        if action == "request_auth":
            if not self._access_granted:
                return None
            log.info("Biometry auth -> token: %s", self._token[:20] if self._token else "(empty)")
            return {"token": self._token}

        if action == "update_token":
            inner = data.get("data", {})
            self._token = inner.get("token", "") if isinstance(inner, dict) else ""
            log.info("Biometry token updated (%d chars)", len(self._token))
            return True

        if action == "open_settings":
            return True

        return None


async def qr_from_screen():
    """Interactive area screenshot -> opencv QR scan."""
    system = platform.system()
    try:
        tmp = tempfile.mktemp(suffix=".png")
        if system == "Darwin":
            proc = await asyncio.create_subprocess_exec(
                "screencapture", "-ix", tmp,
                stderr=asyncio.subprocess.PIPE,
            )
        elif system == "Linux":
            proc = await asyncio.create_subprocess_exec(
                "gnome-screenshot", "-a", "-f", tmp,
                stderr=asyncio.subprocess.PIPE,
            )
        elif system == "Windows":
            ps = (
                f"Add-Type -A System.Windows.Forms;"
                f"$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
                f"$bmp=New-Object Drawing.Bitmap($b.Width,$b.Height);"
                f"[Drawing.Graphics]::FromImage($bmp).CopyFromScreen("
                f"$b.Location,[Drawing.Point]::Empty,$b.Size);"
                f"$bmp.Save('{tmp}')"
            )
            proc = await asyncio.create_subprocess_exec(
                "powershell", "-command", ps,
                stderr=asyncio.subprocess.PIPE,
            )
        else:
            return None
        await proc.communicate()
        if proc.returncode != 0:
            return None
        import cv2
        img = cv2.imread(tmp)
        os.unlink(tmp)
        if img is None:
            return None
        data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
        if data:
            log.info("QR from screen: %s", data[:80])
        return data if data else None
    except ImportError:
        log.debug("opencv not installed, screen QR unavailable")
        return None
    except Exception as e:
        log.debug("Screen QR failed: %s", e)
        return None



async def clipboard_read(data):
    """Read system clipboard via platform-native command."""
    system = platform.system()
    cmd = {
        "Darwin": ["pbpaste"],
        "Linux": ["xclip", "-selection", "clipboard", "-o"],
        "Windows": ["powershell", "-command", "Get-Clipboard"],
    }.get(system)
    if not cmd:
        return ""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode() if proc.returncode == 0 else ""
    except Exception as e:
        log.warning("Clipboard read failed: %s", e)
        return ""

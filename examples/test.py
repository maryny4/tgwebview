#!/usr/bin/env python3
"""
Test script for tgwebview — opens examples/index.html in a native WebView
with the full SDK bridge injected. No Telegram account needed.

Uses real system integrations:
  - QR: screenshot scan or camera (opencv)
  - Clipboard: system clipboard (pbpaste / xclip / powershell)
  - Biometry: full emulation with token storage
  - Camera/Mic: getUserMedia auto-granted via WKUIDelegate (macOS)
  - CloudStorage: in-memory dict (no MTProto)

Usage:
    python examples/test.py
    python examples/test.py --dark
    python examples/test.py --platform android --debug
"""

import argparse
import asyncio
import json
import logging
import os
import platform
import sys
import tempfile
import threading
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("test")

ROOT = Path(__file__).parent
PACKAGE = ROOT.parent / "webview_runner"
INJECT_JS = (PACKAGE / "inject.js").read_text()

sys.path.insert(0, str(ROOT.parent))
from webview_runner.constants import THEME_LIGHT, THEME_DARK

MOCK_BOT_INFO = {"name": "Test Bot", "id": 123456789}

# ── Bridge message constants ──

_MSG_EVENT = "__TG_EVENT__:"
_MSG_INVOKE = "__TG_INVOKE__:"
_MSG_CLOUD = "__TG_CLOUD_STORAGE__:"
_MSG_WRITE = "__TG_WRITE_ACCESS__"
_MSG_POPUP = "__TG_POPUP__:"
_MSG_CLOSE = "__TG_CLOSE__"
_MSG_LINK = "__TG_OPEN_LINK__:"
_MSG_CONSOLE = "__TG_CONSOLE__:"

# ── CloudStorage (in-memory) ──

CLOUD_STORAGE = {}


def cloud_storage_handle(method, params):
    if method == "saveStorageValue":
        CLOUD_STORAGE[params["key"]] = params["value"]
        return True
    if method == "getStorageValues":
        return {k: CLOUD_STORAGE.get(k, "") for k in params.get("keys", [])}
    if method == "deleteStorageValues":
        for k in params.get("keys", []):
            CLOUD_STORAGE.pop(k, None)
        return True
    if method == "getStorageKeys":
        return list(CLOUD_STORAGE.keys())
    return {"error": f"Unknown method: {method}"}


# ── Biometry emulator ──

class BiometryEmulator:
    def __init__(self):
        self._access_granted = False
        self._token = ""

    def handle(self, data):
        action = data.get("action", "")
        if action == "get_info":
            return self._info()
        if action == "request_access":
            self._access_granted = True
            log.info("Biometry: access granted")
            return self._info()
        if action == "request_auth":
            if not self._access_granted:
                return None
            log.info("Biometry: auth → token=%s", self._token[:20] if self._token else "(empty)")
            return {"token": self._token}
        if action == "update_token":
            inner = data.get("data", {})
            self._token = inner.get("token", "") if isinstance(inner, dict) else ""
            log.info("Biometry: token updated (%d chars)", len(self._token))
            return True
        if action == "open_settings":
            return True
        return None

    def _info(self):
        return {
            "available": True, "type": "fingerprint",
            "access_requested": self._access_granted,
            "access_granted": self._access_granted,
            "token_saved": bool(self._token),
            "device_id": "tgwebview_test",
        }


# ── QR Scanner ──

async def qr_from_screen():
    """Interactive area screenshot → opencv QR scan."""
    system = platform.system()
    try:
        tmp = tempfile.mktemp(suffix=".png")
        if system == "Darwin":
            proc = await asyncio.create_subprocess_exec(
                "screencapture", "-ix", tmp, stderr=asyncio.subprocess.PIPE)
        elif system == "Linux":
            proc = await asyncio.create_subprocess_exec(
                "gnome-screenshot", "-a", "-f", tmp, stderr=asyncio.subprocess.PIPE)
        elif system == "Windows":
            ps = (f"Add-Type -A System.Windows.Forms;"
                  f"$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
                  f"$bmp=New-Object Drawing.Bitmap($b.Width,$b.Height);"
                  f"[Drawing.Graphics]::FromImage($bmp).CopyFromScreen($b.Location,[Drawing.Point]::Empty,$b.Size);"
                  f"$bmp.Save('{tmp}')")
            proc = await asyncio.create_subprocess_exec(
                "powershell", "-command", ps, stderr=asyncio.subprocess.PIPE)
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


from webview_runner.defaults import QR_CAMERA_JS

_MSG_QR_RESULT = "__TG_QR_RESULT__:"
_qr_camera_future = None


async def qr_from_camera_js(window_ref, loop):
    """Open camera QR scanner inside WebView via getUserMedia."""
    global _qr_camera_future
    window = window_ref[0]
    if not window:
        return None

    _qr_camera_future = loop.create_future()

    def inject():
        window.evaluate_js(QR_CAMERA_JS)

    threading.Thread(target=inject, daemon=True).start()

    try:
        return await asyncio.wait_for(_qr_camera_future, timeout=60)
    except asyncio.TimeoutError:
        return None


# ── Clipboard ──

async def read_clipboard():
    system = platform.system()
    cmd = {"Darwin": ["pbpaste"], "Linux": ["xclip", "-selection", "clipboard", "-o"],
           "Windows": ["powershell", "-command", "Get-Clipboard"]}.get(system)
    if not cmd:
        return ""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await proc.communicate()
        return stdout.decode() if proc.returncode == 0 else ""
    except Exception:
        return ""


# ── Bridge ──

class Bridge:
    _CONSOLE_LOG_LEVELS = {
        "log": logging.INFO, "info": logging.INFO, "debug": logging.DEBUG,
        "warn": logging.WARNING, "error": logging.ERROR,
    }

    def __init__(self, window_ref, loop, biometry, win_width, win_height):
        self._window_ref = window_ref
        self._loop = loop
        self._bio = biometry
        self._win_w = win_width
        self._win_h = win_height

    @property
    def window(self):
        return self._window_ref[0]

    def handle_bridge(self, text):
        log.debug("Bridge ← %s", text[:120])

        if text == _MSG_CLOSE:
            if self.window:
                self.window.destroy()
            return
        if text == _MSG_WRITE:
            log.info("Write access → granted")
            if self.window:
                self.window.evaluate_js(
                    "receiveEvent('write_access_requested', JSON.stringify({status:'allowed'}))")
            return

        dispatch = (
            (_MSG_EVENT,   self._handle_event),
            (_MSG_INVOKE,  self._handle_invoke),
            (_MSG_CLOUD,   self._handle_cloud),
            (_MSG_POPUP,   self._handle_popup),
            (_MSG_LINK,    self._handle_link),
            (_MSG_QR_RESULT, self._handle_qr_result),
            (_MSG_CONSOLE, self._handle_console),
        )
        for prefix, handler in dispatch:
            if text.startswith(prefix):
                handler(text[len(prefix):])
                return

    def _handle_event(self, payload):
        sep = payload.find(":")
        if sep == -1:
            return
        event_name = payload[:sep]
        event_data = payload[sep + 1:]
        log.info("Event: %s", event_name)

        data = {}
        try:
            data = json.loads(event_data) if event_data else {}
        except Exception:
            pass

        # Dispatch to real handlers on the async loop
        future = asyncio.run_coroutine_threadsafe(
            self._handle_event_async(event_name, data), self._loop)

        def on_done(fut):
            try:
                result = fut.result()
            except Exception:
                result = None
            result_json = "null" if result is None else json.dumps(result)
            safe_name = json.dumps(event_name)
            if self.window:
                self.window.evaluate_js(
                    f"__tg_resolve_event({safe_name}, {result_json})")

        future.add_done_callback(on_done)

    async def _handle_event_async(self, name, data):
        if name == "qr_scan":
            source = data.get("source", "screen")
            if source == "camera":
                result = await qr_from_camera_js(self._window_ref, self._loop)
            else:
                result = await qr_from_screen()
            if result:
                log.info("QR result (%s): %s", source, result[:80])
            return result

        if name == "clipboard":
            text = await read_clipboard()
            log.info("Clipboard: %s", text[:60] if text else "(empty)")
            return text

        if name == "biometry":
            return self._bio.handle(data)

        # Everything else: no handler → null → JS uses default
        return None

    def _handle_invoke(self, payload_str):
        try:
            payload = json.loads(payload_str)
        except Exception:
            return
        req_id = payload.get("req_id", "")
        method = payload.get("method", "")
        params = payload.get("params", {})
        safe_req_id = json.dumps(str(req_id))
        try:
            result = cloud_storage_handle(method, params if isinstance(params, dict) else json.loads(params))
            result_json = json.dumps(result)
            js = f"receiveEvent('custom_method_invoked', {{req_id:{safe_req_id},result:{result_json}}})"
        except Exception as e:
            safe_err = json.dumps(str(e))
            js = f"receiveEvent('custom_method_invoked', {{req_id:{safe_req_id},error:{safe_err}}})"
        if self.window:
            self.window.evaluate_js(js)

    def _handle_cloud(self, payload_str):
        try:
            request = json.loads(payload_str)
        except Exception:
            return
        req_id = request.get("req_id", "")
        method = request.get("method", "")
        params = request.get("params", {})
        safe_req_id = json.dumps(str(req_id))
        try:
            result = cloud_storage_handle(method, params)
            result_json = json.dumps(result)
            js = f"receiveEvent('custom_method_invoked', {{req_id:{safe_req_id},result:{result_json}}})"
        except Exception as e:
            safe_err = json.dumps(str(e))
            js = f"receiveEvent('custom_method_invoked', {{req_id:{safe_req_id},error:{safe_err}}})"
        if self.window:
            self.window.evaluate_js(js)

    def _handle_popup(self, payload_str):
        try:
            params = json.loads(payload_str)
        except Exception:
            return
        title = params.get("title", "")
        message = params.get("message", "")
        buttons = params.get("buttons", [])
        if not message or not buttons:
            return

        def show_dialog():
            btn_ids = [b.get("id", "") for b in buttons]
            btn_types = [b.get("type", "default") for b in buttons]
            try:
                has_cancel = any(t in ("cancel", "close") for t in btn_types)
                if len(buttons) == 1 and btn_types[0] in ("ok", "close"):
                    self.window.create_confirmation_dialog(title or "Info", message)
                    result_id = btn_ids[0]
                elif has_cancel:
                    ok = self.window.create_confirmation_dialog(title or "Confirm", message)
                    result_id = next(
                        (b["id"] for b in buttons if b.get("type") not in ("cancel", "close")),
                        btn_ids[0]) if ok else next(
                        (b["id"] for b in buttons if b.get("type") in ("cancel", "close")), "")
                else:
                    self.window.create_confirmation_dialog(title or "Info", message)
                    result_id = btn_ids[0]
            except Exception:
                result_id = btn_ids[0] if btn_ids else ""
            safe_id = json.dumps(result_id)
            self.window.evaluate_js(
                f"receiveEvent('popup_closed', {{button_id:{safe_id}}})")

        threading.Thread(target=show_dialog, daemon=True).start()

    def _handle_qr_result(self, data):
        global _qr_camera_future
        log.info("QR camera result: %s", data[:80] if data else "(empty)")
        if _qr_camera_future and not _qr_camera_future.done():
            self._loop.call_soon_threadsafe(_qr_camera_future.set_result, data if data else None)

    def _handle_link(self, url):
        log.info("Open link: %s", url)
        webbrowser.open(url)

    def _handle_console(self, payload):
        sep = payload.find(":")
        if sep == -1:
            return
        level_str = payload[:sep]
        message = payload[sep + 1:]
        level = self._CONSOLE_LOG_LEVELS.get(level_str, logging.INFO)
        logging.getLogger("js").log(level, "[%s] %s", level_str, message)


# ── HTTP server ──

def start_http_server(directory, port=0):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(directory), **kwargs)
        def log_message(self, format, *args):
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


# ── Camera delegate (macOS) ──

def install_camera_delegate(webview_instance):
    """Auto-grant getUserMedia on macOS WKWebView."""
    if platform.system() != "Darwin":
        return
    try:
        from Foundation import NSObject

        class _TGTestMediaDelegate(NSObject):
            def webView_requestMediaCapturePermissionForOrigin_initiatedByFrame_type_decisionHandler_(
                self, webView, origin, frame, type_, handler
            ):
                handler(1)  # WKPermissionDecision.grant

        delegate = _TGTestMediaDelegate.alloc().init()
        webview_instance._tg_cam_delegate = delegate
        webview_instance.setUIDelegate_(delegate)
        log.info("Camera delegate installed")
    except Exception as e:
        log.debug("Camera delegate not installed: %s", e)


# ── Main ──

def main():
    parser = argparse.ArgumentParser(description="tgwebview test — SDK feature tester")
    parser.add_argument("--dark", action="store_true", help="Use dark theme")
    parser.add_argument("--platform", default="tdesktop", choices=["tdesktop", "android", "ios"])
    parser.add_argument("--mode", default="fullsize", choices=["compact", "fullsize", "fullscreen"])
    parser.add_argument("--width", type=int, default=420)
    parser.add_argument("--height", type=int, default=750)
    parser.add_argument("--debug", action="store_true", help="Enable WebView inspector")
    args = parser.parse_args()

    import webview

    theme = THEME_DARK if args.dark else THEME_LIGHT
    ua_map = {
        "android": "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 Chrome/131.0.6778.200 Mobile Safari/537.36",
        "ios": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_2 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148",
    }
    ua = ua_map.get(args.platform)

    server, port = start_http_server(ROOT)
    url = f"http://127.0.0.1:{port}/index.html#tgWebAppVersion=8.0&tgWebAppPlatform={args.platform}"
    log.info("Test page: %s", url)

    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()

    inject_parts = [
        "window.__tg_verbose__ = true;",
        f"window.__tg_theme_params__ = {json.dumps(theme)};",
        f"window.__tg_bot_info__ = {json.dumps(MOCK_BOT_INFO)};",
        "window.__tg_mtproto__ = true;",
        'window.__tg_routed_events__ = ["qr_scan","clipboard","biometry"];',
    ]
    if args.mode == "fullscreen":
        inject_parts.append("window.__tg_fullscreen__ = true;")
    inject_parts.append(INJECT_JS)
    full_inject = "\n".join(inject_parts)

    biometry = BiometryEmulator()
    window_ref = [None]
    bridge = Bridge(window_ref, loop, biometry, args.width, args.height)

    window = webview.create_window(
        "tgwebview Test", width=args.width, height=args.height,
        js_api=bridge, frameless=True)
    window_ref[0] = window

    def on_started():
        window.events.shown.wait()

        system = platform.system()
        if system == "Darwin":
            from webview.platforms.cocoa import BrowserView
            from WebKit import WKUserScript
            bv = BrowserView.instances[window.uid]
            wv = bv.webview
            controller = wv.configuration().userContentController()
            script = WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
                full_inject, 0, False)
            controller.addUserScript_(script)
            install_camera_delegate(wv)
        elif system == "Windows":
            from webview.platforms.edgechromium import BrowserView
            bv = BrowserView.instances[window.uid]
            bv.webview.CoreWebView2.AddScriptToExecuteOnDocumentCreated(full_inject)
        elif system == "Linux":
            from gi.repository import WebKit2
            from webview.platforms.gtk import BrowserView
            bv = BrowserView.instances[window.uid]
            manager = bv.webview.get_user_content_manager()
            script = WebKit2.UserScript(
                full_inject, WebKit2.UserContentInjectedFrames.TOP_FRAME,
                WebKit2.UserScriptInjectionTime.START)
            manager.add_script(script)

        window.load_url(url)
        log.info("Test page loaded")

    start_kwargs = {"func": on_started, "private_mode": False, "debug": args.debug}
    if ua:
        start_kwargs["user_agent"] = ua

    log.info("Starting (%s, %s, %dx%d)", args.platform,
             "dark" if args.dark else "light", args.width, args.height)
    webview.start(**start_kwargs)

    server.shutdown()
    loop.call_soon_threadsafe(loop.stop)
    log.info("Done")

    if platform.system() == "Darwin":
        os._exit(0)


if __name__ == "__main__":
    main()

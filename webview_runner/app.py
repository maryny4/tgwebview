"""WebApp controller — the main entry point for Telegram Mini App WebView."""

import asyncio
import json
import logging
import platform
import threading
from pathlib import Path

from .bridge import Bridge
from .constants import THEME_LIGHT, DEFAULT_WIDTH, DEFAULT_HEIGHT, PLATFORMS, MODES
from .defaults import BiometryEmulator, QR_CAMERA_JS, qr_from_screen, clipboard_read
from .injectors import add_init_script

log = logging.getLogger(__name__)

INJECT_JS = (Path(__file__).parent / "inject.js").read_text()


class WebApp:
    """Programmable Telegram Mini App WebView controller.

    Args:
        bot:            Bot username (``"@name"`` or ``"name"``).
        client:         Unstarted MTProto client (Telethon, Pyrogram, or Kurigram).
        platform:       Platform identifier sent to Telegram
                        (``"tdesktop"``, ``"android"``, ``"ios"``).
        mode:           Window mode (``"compact"``, ``"fullsize"``, ``"fullscreen"``).
        launch:         How to resolve the Mini App URL:
                        ``"auto"`` — try main app, fall back to menu button;
                        ``"main"`` — RequestMainWebView only;
                        ``"menu"`` — RequestWebView (menu button) only.
        theme_params:   Theme colors dict (use ``THEME_LIGHT`` or ``THEME_DARK``).
        width:          Custom window width in pixels (default: 384).
        height:         Custom window height in pixels (default: 694).
        verbose:        Forward JS ``console.*`` output to Python logging.
        debug:          Enable WebView inspector (right-click -> Inspect).
        user_agent:     Override the User-Agent header.
        inject_js:      Custom JavaScript string injected at document-start
                        (after the SDK bridge is initialized).
    """

    def __init__(self, bot, *, client,
                 platform="tdesktop", mode="fullsize", launch="auto",
                 theme_params=None, verbose=False, debug=False,
                 user_agent=None, width=None, height=None,
                 inject_js=None):
        self._bot = bot
        self._client_raw = client

        self._platform_name = platform
        self._mode = mode
        self._launch = launch
        self._theme_params = theme_params
        self._verbose = verbose
        self._debug = debug
        self._user_agent_override = user_agent
        self._width_override = width
        self._height_override = height
        self._inject_js = inject_js

        self._handlers = {}
        self._ready_handler = None
        self._window = None
        self._loop = None

        self._url = None
        self._bot_info = {}
        self._query_id = 0
        self._adapter = None
        self._prolong_task = None

    def on(self, event_name):
        """Decorator to register an async handler for a Mini App SDK event."""
        def decorator(fn):
            self._handlers[event_name] = fn
            return fn
        return decorator

    @property
    def on_ready(self):
        """Decorator to register an async callback fired when WebView is loaded."""
        def decorator(fn):
            self._ready_handler = fn
            return fn
        return decorator

    async def js(self, code):
        """Execute JavaScript in the WebView and return the result."""
        if not self._window:
            raise RuntimeError("WebView not started")
        future = asyncio.get_event_loop().create_future()

        def do_eval():
            try:
                result = self._window.evaluate_js(code)
                self._loop.call_soon_threadsafe(future.set_result, result)
            except Exception as e:
                self._loop.call_soon_threadsafe(future.set_exception, e)

        threading.Thread(target=do_eval, daemon=True).start()
        return await future

    def close(self):
        """Close the WebView window."""
        if self._window:
            self._window.destroy()

    async def dump_html(self):
        """Return the full HTML of the current page."""
        return await self.js("document.documentElement.outerHTML")

    async def dump_cookies(self):
        """Return all cookies as a string."""
        return await self.js("document.cookie")

    async def dump_local_storage(self):
        """Return all localStorage as a dict."""
        result = await self.js(
            "(function(){var o={};for(var i=0;i<localStorage.length;i++)"
            "{var k=localStorage.key(i);o[k]=localStorage.getItem(k);}return JSON.stringify(o);})()"
        )
        if result:
            return json.loads(result)
        return {}

    async def dump_session_storage(self):
        """Return all sessionStorage as a dict."""
        result = await self.js(
            "(function(){var o={};for(var i=0;i<sessionStorage.length;i++)"
            "{var k=sessionStorage.key(i);o[k]=sessionStorage.getItem(k);}return JSON.stringify(o);})()"
        )
        if result:
            return json.loads(result)
        return {}

    # ── Default handlers ──

    def _register_defaults(self):
        """Register built-in handlers for events without a user handler."""
        if "qr_scan" not in self._handlers:
            self._handlers["qr_scan"] = self._default_qr_scan
        if "clipboard" not in self._handlers:
            self._handlers["clipboard"] = clipboard_read
        if "biometry" not in self._handlers:
            self._handlers["biometry"] = BiometryEmulator().handle

    async def _default_qr_scan(self, data):
        """Scan QR code — ``source`` field controls method."""
        source = data.get("source", "screen") if isinstance(data, dict) else "screen"
        if source == "camera":
            return await self._qr_from_camera()
        return await qr_from_screen()

    async def _qr_from_camera(self):
        """Open camera QR scanner inside the WebView."""
        if not self._window:
            return None

        self._qr_future = self._loop.create_future()

        def inject():
            self._window.evaluate_js(QR_CAMERA_JS)

        threading.Thread(target=inject, daemon=True).start()

        try:
            return await asyncio.wait_for(self._qr_future, timeout=60)
        except asyncio.TimeoutError:
            return None

    def _resolve_qr_result(self, data):
        """Called from bridge when JS camera scanner sends result."""
        if hasattr(self, "_qr_future") and not self._qr_future.done():
            result = data if data else None
            self._loop.call_soon_threadsafe(self._qr_future.set_result, result)

    # ── Run ──

    def run(self):
        """Start the WebView. Blocks until the window is closed."""
        import webview

        self._register_defaults()

        profile = PLATFORMS.get(self._platform_name, PLATFORMS["tdesktop"])
        mode_ratio = MODES.get(self._mode, 1.0)

        width = self._width_override or DEFAULT_WIDTH
        height = self._height_override or int(DEFAULT_HEIGHT * mode_ratio)

        ua = self._user_agent_override or profile.get("user_agent")

        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._loop.run_forever, daemon=True
        )
        self._loop_thread.start()

        self._setup_client_sync()

        bot_name = self._bot_info.get("name", "Mini App")
        js_bot_info = {
            "name": self._bot_info.get("name", "Mini App"),
            "id": self._bot_info.get("id", 0),
        }

        bridge = Bridge(self)
        self._window = webview.create_window(
            bot_name,
            width=width, height=height,
            js_api=bridge,
            frameless=True,
        )

        inject_parts = []
        if self._verbose:
            inject_parts.append("window.__tg_verbose__ = true;")
        if self._mode == "fullscreen":
            inject_parts.append("window.__tg_fullscreen__ = true;")
        if self._theme_params:
            inject_parts.append(f"window.__tg_theme_params__ = {json.dumps(self._theme_params)};")

        inject_parts.append(f"window.__tg_bot_info__ = {json.dumps(js_bot_info)};")
        inject_parts.append("window.__tg_mtproto__ = true;")

        routed = list(self._handlers.keys())
        inject_parts.append(f"window.__tg_routed_events__ = {json.dumps(routed)};")

        inject_parts.append(INJECT_JS)

        if self._inject_js:
            inject_parts.append(self._inject_js)

        full_inject = "\n".join(inject_parts)

        def on_started():
            self._window.events.shown.wait()
            add_init_script(self._window, full_inject)
            self._window.load_url(self._url)

            if self._query_id:
                self._prolong_task = asyncio.run_coroutine_threadsafe(
                    self._prolong_loop(), self._loop
                )

            if self._ready_handler and self._loop:
                self._window.events.loaded.wait()
                asyncio.run_coroutine_threadsafe(
                    self._ready_handler(), self._loop
                )

        start_kwargs = {"func": on_started, "private_mode": False, "debug": self._debug}
        if ua:
            start_kwargs["user_agent"] = ua

        webview.start(**start_kwargs)

        self._cleanup_sync()
        log.info("WebView closed")

        if platform.system() == "Darwin":
            import os as _os
            _os._exit(0)

    def _setup_client_sync(self):
        """Detect adapter, start client, resolve URL — all on the internal loop."""
        from .adapters import detect_adapter

        self._adapter = detect_adapter(self._client_raw)
        theme = self._theme_params or THEME_LIGHT

        async def setup():
            await self._adapter.start()
            url, bot_info, query_id = await self._adapter.resolve_url(
                self._bot,
                platform=self._platform_name,
                theme_params=theme,
                launch=self._launch,
            )
            self._url = url
            self._bot_info = bot_info
            self._query_id = query_id
            log.info("Resolved URL for %s (query_id=%s)", self._bot, query_id)

        future = asyncio.run_coroutine_threadsafe(setup(), self._loop)
        future.result(timeout=30)

    async def _prolong_loop(self):
        """Send prolongWebView every 60s to keep the session alive."""
        while True:
            await asyncio.sleep(60)
            try:
                await self._adapter.prolong_web_view(self._query_id)
                log.debug("prolongWebView sent (query_id=%s)", self._query_id)
            except Exception as e:
                log.warning("prolongWebView failed: %s", e)

    def _cleanup_sync(self):
        """Stop prolong timer, disconnect client, stop event loop."""
        if self._prolong_task:
            self._prolong_task.cancel()

        if self._adapter:
            future = asyncio.run_coroutine_threadsafe(
                self._adapter.disconnect(), self._loop
            )
            try:
                future.result(timeout=5)
            except Exception:
                pass
            log.debug("MTProto client disconnected")

        self._loop.call_soon_threadsafe(self._loop.stop)
        self._loop_thread.join(timeout=2)


def open_webapp(bot, **kwargs):
    """One-call convenience wrapper — all kwargs forwarded to ``WebApp()``.

    Requires at minimum ``client=`` keyword argument.
    """
    app = WebApp(bot, **kwargs)
    app.run()

"""Python-side handler for JS->Python bridge messages."""

import asyncio
import json
import logging
import threading
import webbrowser

log = logging.getLogger(__name__)

# Bridge message prefixes — must match inject.js __tg_send() calls.
MSG_EVENT = "__TG_EVENT__:"
MSG_INVOKE = "__TG_INVOKE__:"
MSG_CLOUD = "__TG_CLOUD_STORAGE__:"
MSG_WRITE = "__TG_WRITE_ACCESS__"
MSG_POPUP = "__TG_POPUP__:"
MSG_CLOSE = "__TG_CLOSE__"
MSG_LINK = "__TG_OPEN_LINK__:"
MSG_CONSOLE = "__TG_CONSOLE__:"
MSG_QR_RESULT = "__TG_QR_RESULT__:"


class Bridge:
    """Routes incoming bridge messages from JS to Python handlers.

    Receives string messages via pywebview ``js_api`` and dispatches
    them based on prefix to the appropriate handler.
    """

    _CONSOLE_LOG_LEVELS = {
        "log": logging.INFO,
        "info": logging.INFO,
        "debug": logging.DEBUG,
        "warn": logging.WARNING,
        "error": logging.ERROR,
    }

    def __init__(self, webapp):
        self._app = webapp
        self._dispatch = (
            (MSG_EVENT,     self._handle_event),
            (MSG_INVOKE,    self._handle_invoke),
            (MSG_CLOUD,     self._handle_cloud_storage),
            (MSG_POPUP,     self._handle_popup),
            (MSG_LINK,      self._handle_link),
            (MSG_QR_RESULT, self._handle_qr_result),
            (MSG_CONSOLE,   self._handle_console),
        )

    def handle_bridge(self, text):
        """Route an incoming bridge message to the appropriate handler."""
        if text == MSG_CLOSE:
            log.info("bridge.close")
            self._app._window.destroy()
            return
        if text == MSG_WRITE:
            self._handle_write_access()
            return
        for prefix, handler in self._dispatch:
            if text.startswith(prefix):
                handler(text[len(prefix):])
                return
        log.warning("Unknown bridge message: %.100s", text)

    def _handle_qr_result(self, data):
        """Receive QR scan result from in-WebView camera scanner."""
        log.info("QR camera result: %s", data[:80] if data else "(empty)")
        self._app._resolve_qr_result(data)

    def _handle_link(self, url):
        """Open an external URL in the system browser."""
        log.info("bridge.open_link: %s", url)
        webbrowser.open(url)

    def _handle_event(self, payload):
        """Route a __TG_EVENT__ message: event_name:json_data"""
        sep = payload.find(":")
        if sep == -1:
            return
        event_name = payload[:sep]
        event_data = payload[sep + 1:]
        self._dispatch_event(event_name, event_data)

    def _dispatch_event(self, event_name, data_json):
        """Dispatch event to registered Python handler, send result back to JS."""
        handler = self._app._handlers.get(event_name)
        if not handler:
            self._app._window.evaluate_js(
                f"__tg_resolve_event('{event_name}', null)"
            )
            return

        loop = self._app._loop
        if not loop:
            log.warning("Event '%s' has handler but no event loop", event_name)
            self._app._window.evaluate_js(
                f"__tg_resolve_event('{event_name}', null)"
            )
            return

        async def run_handler():
            try:
                result = await handler(json.loads(data_json) if data_json else {})
                return result
            except Exception as exc:
                log.error("Handler '%s' failed: %s", event_name, exc)
                return None

        future = asyncio.run_coroutine_threadsafe(run_handler(), loop)

        def on_done(fut):
            try:
                result = fut.result()
            except Exception:
                result = None
            js_result = "null" if result is None else json.dumps(result)
            safe_name = json.dumps(event_name)
            self._app._window.evaluate_js(
                f"__tg_resolve_event({safe_name}, {js_result})"
            )

        future.add_done_callback(on_done)

    def _handle_invoke(self, payload_str):
        """Handle invokeCustomMethod."""
        try:
            payload = json.loads(payload_str)
        except (json.JSONDecodeError, ValueError) as e:
            log.error("Invalid JSON in invokeCustomMethod: %s", e)
            return

        req_id = payload.get("req_id", "")
        method = payload.get("method", "")
        params = json.dumps(payload.get("params", {}))
        safe_req_id = json.dumps(str(req_id))

        handler = self._app._handlers.get("invoke")
        loop = self._app._loop
        if not handler or not loop:
            self._app._window.evaluate_js(
                f"receiveEvent('custom_method_invoked', {{req_id:{safe_req_id},error:'NO_HANDLER'}})"
            )
            return

        future = asyncio.run_coroutine_threadsafe(handler(method, params), loop)

        def on_done(fut):
            try:
                result_data = fut.result()
                js = f"receiveEvent('custom_method_invoked', {{req_id:{safe_req_id},result:{result_data}}})"
            except BaseException as exc:
                safe_err = json.dumps(str(exc))
                log.error("invokeCustomMethod failed (req_id=%s): %s", req_id, exc)
                js = f"receiveEvent('custom_method_invoked', {{req_id:{safe_req_id},error:{safe_err}}})"
            self._app._window.evaluate_js(js)

        future.add_done_callback(on_done)

    def _handle_popup(self, payload_str):
        """Show a popup dialog via pywebview."""
        try:
            params = json.loads(payload_str)
        except (json.JSONDecodeError, ValueError):
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
                window = self._app._window
                has_cancel = any(t in ("cancel", "close") for t in btn_types)

                if len(buttons) == 1 and btn_types[0] in ("ok", "close"):
                    window.create_confirmation_dialog(title or "Info", message)
                    result_id = btn_ids[0]
                elif has_cancel:
                    ok = window.create_confirmation_dialog(title or "Confirm", message)
                    if ok:
                        result_id = next(
                            (b["id"] for b in buttons if b.get("type") not in ("cancel", "close")),
                            btn_ids[0],
                        )
                    else:
                        result_id = next(
                            (b["id"] for b in buttons if b.get("type") in ("cancel", "close")),
                            "",
                        )
                else:
                    window.create_confirmation_dialog(title or "Info", message)
                    result_id = btn_ids[0]
            except Exception as e:
                log.warning("Popup dialog failed (%s), using first button", e)
                result_id = btn_ids[0] if btn_ids else ""

            safe_id = json.dumps(result_id)
            self._app._window.evaluate_js(
                f"receiveEvent('popup_closed', {{button_id:{safe_id}}})"
            )

        threading.Thread(target=show_dialog, daemon=True).start()

    def _handle_cloud_storage(self, payload_str):
        """Forward CloudStorage methods to Telegram via bots.invokeWebViewCustomMethod."""
        try:
            request = json.loads(payload_str)
        except (json.JSONDecodeError, ValueError) as e:
            log.error("Invalid JSON in CloudStorage request: %s", e)
            return

        req_id = request.get("req_id", "")
        method = request.get("method", "")
        params = request.get("params", {})

        adapter = self._app._adapter
        loop = self._app._loop

        if not adapter or not loop:
            safe_req_id = json.dumps(str(req_id))
            self._app._window.evaluate_js(
                f"receiveEvent('custom_method_invoked', {{req_id:{safe_req_id},error:'NO_CLIENT'}})"
            )
            return

        future = asyncio.run_coroutine_threadsafe(
            adapter.invoke_custom_method(method, params), loop
        )

        def on_done(fut):
            safe_req_id = json.dumps(str(req_id))
            try:
                result = fut.result()
                result_json = json.dumps(result)
                js = f"receiveEvent('custom_method_invoked', {{req_id:{safe_req_id},result:{result_json}}})"
            except Exception as exc:
                safe_err = json.dumps(str(exc))
                log.error("CloudStorage %s failed: %s", method, exc)
                js = f"receiveEvent('custom_method_invoked', {{req_id:{safe_req_id},error:{safe_err}}})"
            self._app._window.evaluate_js(js)

        future.add_done_callback(on_done)

    def _handle_write_access(self):
        """Handle write_access via MTProto: canSendMessage -> allowSendMessage."""
        adapter = self._app._adapter
        loop = self._app._loop

        if not adapter or not loop:
            self._app._window.evaluate_js(
                "receiveEvent('write_access_requested', JSON.stringify({status:'cancelled'}))"
            )
            return

        async def do_write_access():
            already_allowed = await adapter.can_send_message()
            if already_allowed:
                return "allowed"
            await adapter.allow_send_message()
            return "allowed"

        future = asyncio.run_coroutine_threadsafe(do_write_access(), loop)

        def on_done(fut):
            try:
                status = fut.result()
            except Exception as exc:
                log.error("write_access failed: %s", exc)
                status = "cancelled"
            self._app._window.evaluate_js(
                f"receiveEvent('write_access_requested', JSON.stringify({{status:'{status}'}}))"
            )

        future.add_done_callback(on_done)

    def _handle_console(self, payload):
        """Forward JS console output to Python logging."""
        sep_idx = payload.find(":")
        if sep_idx == -1:
            return
        level_str = payload[:sep_idx]
        message = payload[sep_idx + 1:]
        level = self._CONSOLE_LOG_LEVELS.get(level_str, logging.INFO)
        logging.getLogger("webview_runner.console").log(level, "[JS %s] %s", level_str, message)

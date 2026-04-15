"""Platform-specific JavaScript injection and camera delegate."""

import logging
import platform

log = logging.getLogger(__name__)


def install_camera_delegate(wk_webview):
    """Auto-grant getUserMedia on macOS WKWebView via WKUIDelegate."""
    try:
        from Foundation import NSObject

        class _TGMediaDelegate(NSObject):
            def webView_requestMediaCapturePermissionForOrigin_initiatedByFrame_type_decisionHandler_(
                self, webView, origin, frame, type_, handler
            ):
                handler(1)  # WKPermissionDecision.grant

        delegate = _TGMediaDelegate.alloc().init()
        wk_webview._tg_media_delegate = delegate  # prevent GC
        wk_webview.setUIDelegate_(delegate)
    except Exception as e:
        log.debug("Camera delegate not installed: %s", e)


def _inject_darwin(window, source):
    from webview.platforms.cocoa import BrowserView
    from WebKit import WKUserScript

    bv = BrowserView.instances[window.uid]
    wv = bv.webview
    controller = wv.configuration().userContentController()
    script = WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
        source, 0, False
    )
    controller.addUserScript_(script)
    install_camera_delegate(wv)


def _inject_windows(window, source):
    from webview.platforms.edgechromium import BrowserView

    bv = BrowserView.instances[window.uid]
    bv.webview.CoreWebView2.AddScriptToExecuteOnDocumentCreated(source)


def _inject_linux(window, source):
    from gi.repository import WebKit2
    from webview.platforms.gtk import BrowserView

    bv = BrowserView.instances[window.uid]
    manager = bv.webview.get_user_content_manager()
    script = WebKit2.UserScript(
        source, WebKit2.UserContentInjectedFrames.TOP_FRAME,
        WebKit2.UserScriptInjectionTime.START,
    )
    manager.add_script(script)


def _inject_unsupported(window, source):
    raise RuntimeError(f"Unsupported platform: {platform.system()}")


_INJECTORS = {
    "Darwin": _inject_darwin,
    "Windows": _inject_windows,
    "Linux": _inject_linux,
}


def add_init_script(window, source):
    """Inject JavaScript at document-start using platform-native APIs.

    Supported platforms:
        - macOS: WKUserScript (WebKit)
        - Windows: CoreWebView2.AddScriptToExecuteOnDocumentCreated (Edge/Chromium)
        - Linux: WebKit2.UserScript (WebKitGTK)
    """
    system = platform.system()
    injector = _INJECTORS.get(system, _inject_unsupported)
    injector(window, source)

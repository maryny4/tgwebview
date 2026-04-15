"""
webview-runner — Programmable WebView wrapper for Telegram Mini Apps.

Supports Telethon, Pyrogram, and Kurigram (auto-detected from client type).
All Mini App SDK events are routable to async Python handlers.
MTProto features (CloudStorage, write_access, prolongWebView) work automatically.

Usage:
    from telethon import TelegramClient
    from webview_runner import WebApp

    app = WebApp("@botname", client=TelegramClient("session", api_id, api_hash))
    app.run()
"""

import logging

__version__ = "0.1.0"

_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("[%(levelname).1s %(name)s] %(message)s"))
_logger = logging.getLogger(__name__)
_logger.addHandler(_handler)
_logger.setLevel(logging.INFO)

from .app import WebApp, open_webapp
from .constants import THEME_LIGHT, THEME_DARK

__all__ = ["WebApp", "open_webapp", "THEME_LIGHT", "THEME_DARK", "__version__"]

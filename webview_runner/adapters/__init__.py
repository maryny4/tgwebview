"""
MTProto adapter layer — supports Telethon and Pyrogram (including forks like kurigram).

User passes their own (unstarted) client; we detect the library and wrap it.

Note: kurigram installs as the ``pyrogram`` Python package (drop-in replacement),
so ``from pyrogram import Client`` works for both pyrogram and kurigram.
"""

import logging
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)


class MTProtoAdapter(ABC):
    """Abstract base for MTProto client adapters.

    Each adapter wraps a single library's client and exposes
    the exact MTProto calls that WebApp needs.  The client is
    started/stopped by the adapter on WebApp's internal event loop.
    """

    @abstractmethod
    async def start(self):
        """Connect and authenticate the client."""

    @abstractmethod
    async def disconnect(self):
        """Disconnect the client."""

    @abstractmethod
    async def resolve_url(self, bot, platform, theme_params, launch="auto"):
        """Resolve Mini App URL.

        Args:
            launch: "auto" (try main, fallback to menu), "main", or "menu".

        Returns:
            (url, bot_info, query_id)
        """

    @abstractmethod
    async def invoke_custom_method(self, method, params):
        """Call bots.invokeWebViewCustomMethod. Returns parsed result."""

    @abstractmethod
    async def can_send_message(self):
        """Call bots.canSendMessage. Returns bool."""

    @abstractmethod
    async def allow_send_message(self):
        """Call bots.allowSendMessage."""

    @abstractmethod
    async def prolong_web_view(self, query_id):
        """Call messages.prolongWebView."""


def detect_adapter(client) -> MTProtoAdapter:
    """Wrap a user-supplied client in the appropriate adapter.

    Supported clients:
      - ``telethon.TelegramClient``
      - ``pyrogram.Client`` (also kurigram — it installs as ``pyrogram``)

    Raises TypeError if the client type is not recognized.
    """
    module = type(client).__module__

    if module.startswith("telethon"):
        from ._telethon import TelethonAdapter
        return TelethonAdapter(client)

    if module.startswith("pyrogram"):
        from ._pyrogram import PyrogramAdapter
        return PyrogramAdapter(client)

    raise TypeError(
        f"Unsupported client type: {module}.{type(client).__qualname__}. "
        "Pass a TelegramClient (telethon) or Client (pyrogram/kurigram)."
    )

"""Pyrogram adapter — works with pyrogram and forks that install as ``pyrogram`` (kurigram)."""

import json
import logging

from . import MTProtoAdapter

log = logging.getLogger(__name__)


class PyrogramAdapter(MTProtoAdapter):
    """Adapter for pyrogram.Client and compatible forks (kurigram)."""

    def __init__(self, client):
        self._client = client
        self._raw = None         # pyrogram.raw module, resolved lazily
        self._peer = None        # InputPeerUser
        self._input_user = None  # InputUser

    @property
    def raw(self):
        """Lazy import of pyrogram.raw to avoid top-level ImportError."""
        if self._raw is None:
            from pyrogram import raw
            self._raw = raw
        return self._raw

    async def start(self):
        await self._client.start()

    async def disconnect(self):
        await self._client.stop()

    async def _resolve_bot(self, bot):
        """Resolve bot username to peer + InputUser via raw TL."""
        username = bot.lstrip("@")
        resolved = await self._client.invoke(
            self.raw.functions.contacts.ResolveUsername(username=username)
        )
        user = resolved.users[0]
        self._peer = self.raw.types.InputPeerUser(
            user_id=user.id, access_hash=user.access_hash,
        )
        self._input_user = self.raw.types.InputUser(
            user_id=user.id, access_hash=user.access_hash,
        )
        return user

    async def _get_menu_url(self):
        """Get menu button URL from bot_info via GetFullUser."""
        full = await self._client.invoke(
            self.raw.functions.users.GetFullUser(id=self._input_user)
        )
        bi = full.full_user.bot_info
        menu_btn = getattr(bi, "menu_button", None) if bi else None
        return getattr(menu_btn, "url", None)

    async def _request_main(self, platform, theme_data):
        result = await self._client.invoke(
            self.raw.functions.messages.RequestMainWebView(
                peer=self._peer,
                bot=self._input_user,
                platform=platform,
                theme_params=theme_data,
            )
        )
        log.info("Resolved via RequestMainWebView")
        return result

    async def _request_menu(self, platform, theme_data, url):
        result = await self._client.invoke(
            self.raw.functions.messages.RequestWebView(
                peer=self._peer,
                bot=self._peer,
                platform=platform,
                url=url,
                theme_params=theme_data,
                from_bot_menu=True,
            )
        )
        log.info("Resolved via RequestWebView (menu button)")
        return result

    async def resolve_url(self, bot, platform, theme_params, launch="auto"):
        user = await self._resolve_bot(bot)
        theme_data = self.raw.types.DataJSON(data=json.dumps(theme_params))

        if launch == "main":
            result = await self._request_main(platform, theme_data)
        elif launch == "menu":
            menu_url = await self._get_menu_url()
            if not menu_url:
                raise RuntimeError(f"Bot {bot} has no menu button URL")
            result = await self._request_menu(platform, theme_data, menu_url)
        else:  # auto
            try:
                result = await self._request_main(platform, theme_data)
            except Exception as e:
                log.debug("RequestMainWebView failed (%s), trying menu button", e)
                menu_url = await self._get_menu_url()
                if not menu_url:
                    raise RuntimeError(
                        f"Bot {bot} has no Main Mini App and no menu button URL"
                    ) from e
                result = await self._request_menu(platform, theme_data, menu_url)

        bot_info = {
            "name": getattr(user, "first_name", None) or str(bot),
            "id": user.id,
        }
        query_id = getattr(result, "query_id", 0)
        return result.url, bot_info, query_id

    async def invoke_custom_method(self, method, params):
        params_str = json.dumps(params) if not isinstance(params, str) else params
        result = await self._client.invoke(
            self.raw.functions.bots.InvokeWebViewCustomMethod(
                bot=self._input_user,
                custom_method=method,
                params=self.raw.types.DataJSON(data=params_str),
            )
        )
        return json.loads(result.data)

    async def can_send_message(self):
        return await self._client.invoke(
            self.raw.functions.bots.CanSendMessage(bot=self._input_user)
        )

    async def allow_send_message(self):
        await self._client.invoke(
            self.raw.functions.bots.AllowSendMessage(bot=self._input_user)
        )

    async def prolong_web_view(self, query_id):
        return await self._client.invoke(
            self.raw.functions.messages.ProlongWebView(
                peer=self._peer,
                bot=self._input_user,
                query_id=query_id,
            )
        )

"""Telethon adapter for MTProto calls."""

import json
import logging

from . import MTProtoAdapter

log = logging.getLogger(__name__)


class TelethonAdapter(MTProtoAdapter):
    """Adapter for telethon.TelegramClient."""

    def __init__(self, client):
        self._client = client
        self._peer = None
        self._input_user = None

    async def start(self):
        await self._client.start()

    async def disconnect(self):
        await self._client.disconnect()

    async def _resolve_bot(self, bot):
        """Resolve bot username to peer + InputUser via raw TL."""
        from telethon.tl.functions.contacts import ResolveUsernameRequest
        from telethon.tl.types import InputUser

        username = bot.lstrip("@")
        resolved = await self._client(ResolveUsernameRequest(username=username))
        user = resolved.users[0]
        self._peer = user
        self._input_user = InputUser(user_id=user.id, access_hash=user.access_hash)
        return user

    async def _get_menu_url(self):
        """Get menu button URL from bot_info via GetFullUser."""
        from telethon.tl.functions.users import GetFullUserRequest

        full = await self._client(GetFullUserRequest(self._input_user))
        bi = full.full_user.bot_info
        menu_btn = getattr(bi, "menu_button", None) if bi else None
        return getattr(menu_btn, "url", None)

    async def _request_main(self, platform, theme_data):
        from telethon.tl.functions.messages import RequestMainWebViewRequest

        result = await self._client(RequestMainWebViewRequest(
            peer=self._peer,
            bot=self._input_user,
            platform=platform,
            theme_params=theme_data,
        ))
        log.info("Resolved via RequestMainWebView")
        return result

    async def _request_menu(self, platform, theme_data, url):
        from telethon.tl.functions.messages import RequestWebViewRequest

        result = await self._client(RequestWebViewRequest(
            peer=self._peer,
            bot=self._peer,
            platform=platform,
            url=url,
            theme_params=theme_data,
            from_bot_menu=True,
        ))
        log.info("Resolved via RequestWebView (menu button)")
        return result

    async def resolve_url(self, bot, platform, theme_params, launch="auto"):
        from telethon.tl.types import DataJSON

        user = await self._resolve_bot(bot)
        theme_data = DataJSON(data=json.dumps(theme_params))

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
        from telethon.tl.functions.bots import InvokeWebViewCustomMethodRequest
        from telethon.tl.types import DataJSON

        params_str = json.dumps(params) if not isinstance(params, str) else params
        result = await self._client(InvokeWebViewCustomMethodRequest(
            bot=self._input_user,
            custom_method=method,
            params=DataJSON(data=params_str),
        ))
        return json.loads(result.data)

    async def can_send_message(self):
        from telethon.tl.functions.bots import CanSendMessageRequest
        return await self._client(CanSendMessageRequest(bot=self._input_user))

    async def allow_send_message(self):
        from telethon.tl.functions.bots import AllowSendMessageRequest
        await self._client(AllowSendMessageRequest(bot=self._input_user))

    async def prolong_web_view(self, query_id):
        from telethon.tl.functions.messages import ProlongWebViewRequest
        return await self._client(ProlongWebViewRequest(
            peer=self._peer,
            bot=self._input_user,
            query_id=query_id,
        ))

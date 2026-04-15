"""CLI entry point: python -m webview_runner @botname --session test --api-id 2040 --api-hash ..."""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="webview-runner",
        description="Open a Telegram Mini App in a native WebView.",
    )
    parser.add_argument("bot", help="Bot username (e.g. @botname)")
    parser.add_argument("--session", required=True, help="Telethon/Pyrogram session name or path")
    parser.add_argument("--api-id", type=int, required=True, help="Telegram API ID")
    parser.add_argument("--api-hash", required=True, help="Telegram API hash")
    parser.add_argument("--library", choices=["telethon", "pyrogram"],
                        default="telethon", help="MTProto library (default: telethon)")
    parser.add_argument("--platform", choices=["tdesktop", "android", "ios"],
                        default="tdesktop", help="Platform identifier for Telegram")
    parser.add_argument("--launch", choices=["auto", "main", "menu"],
                        default="auto", help="Launch mode: main app, menu button, or auto-detect")
    parser.add_argument("--mode", choices=["compact", "fullsize", "fullscreen"],
                        default="fullsize", help="Window mode")
    parser.add_argument("--width", type=int, help="Custom window width")
    parser.add_argument("--height", type=int, help="Custom window height")
    parser.add_argument("--dark", action="store_true", help="Use dark theme")
    parser.add_argument("--debug", action="store_true", help="Enable WebView inspector")
    parser.add_argument("--verbose", action="store_true", help="Forward JS console to terminal")

    args = parser.parse_args()

    if args.library == "telethon":
        try:
            from telethon import TelegramClient
        except ImportError:
            sys.exit("telethon not installed. Run: pip install telethon")
        client = TelegramClient(args.session, args.api_id, args.api_hash)
    else:
        try:
            from pyrogram import Client
        except ImportError:
            sys.exit("pyrogram/kurigram not installed. Run: pip install kurigram")
        client = Client(args.session, api_id=args.api_id, api_hash=args.api_hash)

    from .constants import THEME_DARK, THEME_LIGHT
    from .app import WebApp

    app = WebApp(
        args.bot,
        client=client,
        platform=args.platform,
        launch=args.launch,
        mode=args.mode,
        theme_params=THEME_DARK if args.dark else THEME_LIGHT,
        width=args.width,
        height=args.height,
        debug=args.debug,
        verbose=args.verbose,
    )
    app.run()


if __name__ == "__main__":
    main()

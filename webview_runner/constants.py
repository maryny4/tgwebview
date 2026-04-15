"""
Mini App theme palettes and platform configuration.

Theme colors are extracted from TDesktop source code:
  - Light: Telegram/SourceFiles/window/window_theme.cpp (default palette)
  - Dark:  night.tdesktop-theme palette file
"""

DEFAULT_WIDTH = 384
DEFAULT_HEIGHT = 694

PLATFORMS = {
    "tdesktop": {"user_agent": None},
    "android": {
        "user_agent": (
            "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro Build/UQ1A.240105.002; wv) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
            "Chrome/131.0.6778.200 Mobile Safari/537.36"
        ),
    },
    "ios": {
        "user_agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_2 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
        ),
    },
}

# Height multipliers applied to DEFAULT_HEIGHT for each window mode.
MODES = {
    "compact": 0.55,
    "fullsize": 1.0,
    "fullscreen": 1.0,
}

THEME_LIGHT = {
    "bg_color": "#ffffff",                    # windowBg
    "text_color": "#000000",                  # windowFg
    "hint_color": "#999999",                  # windowSubTextFg
    "link_color": "#168acd",                  # windowActiveTextFg
    "button_color": "#40a7e3",                # windowBgActive
    "button_text_color": "#ffffff",           # windowFgActive
    "secondary_bg_color": "#f1f1f1",          # boxDividerBg
    "header_bg_color": "#ffffff",             # windowBg
    "accent_text_color": "#168acd",           # lightButtonFg
    "section_bg_color": "#ffffff",            # lightButtonBg
    "section_header_text_color": "#168acd",   # windowActiveTextFg
    "subtitle_text_color": "#999999",         # windowSubTextFg
    "destructive_text_color": "#d14e4e",      # attentionButtonFg
    "section_separator_color": "#e7e7e7",     # mix(windowBg, shadowFg)
    "bottom_bar_bg_color": "#ffffff",         # windowBg
}

THEME_DARK = {
    "bg_color": "#17212b",                    # windowBg
    "text_color": "#f5f5f5",                  # windowFg
    "hint_color": "#708499",                  # windowSubTextFg
    "link_color": "#6ab3f3",                  # windowActiveTextFg
    "button_color": "#5288c1",                # windowBgActive
    "button_text_color": "#ffffff",           # windowFgActive
    "secondary_bg_color": "#232e3c",          # boxDividerBg
    "header_bg_color": "#17212b",             # windowBg
    "accent_text_color": "#6ab2f2",           # lightButtonFg
    "section_bg_color": "#17212b",            # lightButtonBg
    "section_header_text_color": "#6ab3f3",   # windowActiveTextFg
    "subtitle_text_color": "#708499",         # windowSubTextFg
    "destructive_text_color": "#ec3942",      # attentionButtonFg
    "section_separator_color": "#101821",     # mix(windowBg, shadowFg)
    "bottom_bar_bg_color": "#17212b",         # windowBg
}

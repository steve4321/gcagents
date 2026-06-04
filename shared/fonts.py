"""Font fallback map for CJK and RTL locales.

When a VN game is localized to a non-Latin script (Japanese, Korean,
Simplified/Traditional Chinese, Arabic, Hebrew), the system fonts on
itch.io browsers may not have those glyphs. This module returns a CSS
``font-family`` fallback list per locale.

The fallback chains are designed to be safe to embed in any build:
* Latin locales get a plain ``sans-serif`` fallback.
* CJK locales get ``Noto Sans <JP/KR/SC>`` then generic ``sans-serif``.
* RTL locales (Arabic, Hebrew) get ``Noto Sans Arabic/Hebrew`` then
  generic ``sans-serif`` and ``serif`` (Arabic numerals are sometimes
  more readable in serif).
"""

from __future__ import annotations

from typing import Optional


LATIN_LOCALES: frozenset[str] = frozenset({"en", "es", "pt", "de", "fr", "it", "pl", "tr", "vi", "id"})

CJK_LOCALES: frozenset[str] = frozenset({"ja", "ko", "zh", "zh-CN", "zh-TW"})

RTL_LOCALES: frozenset[str] = frozenset({"ar", "he", "fa", "ur"})

FONT_FALLBACK: dict[str, list[str]] = {
    "ja":     ["'Noto Sans JP'", "sans-serif"],
    "ko":     ["'Noto Sans KR'", "sans-serif"],
    "zh-CN":  ["'Noto Sans SC'", "sans-serif"],
    "zh-TW":  ["'Noto Sans TC'", "sans-serif"],
    "zh":     ["'Noto Sans SC'", "'Noto Sans TC'", "sans-serif"],
    "ar":     ["'Noto Sans Arabic'", "serif", "sans-serif"],
    "he":     ["'Noto Sans Hebrew'", "sans-serif"],
    "fa":     ["'Noto Sans Arabic'", "sans-serif"],
    "ur":     ["'Noto Sans Arabic'", "sans-serif"],
}


def get_font_family(locale: str) -> str:
    """Return a CSS ``font-family`` value for the given locale."""
    if locale in FONT_FALLBACK:
        return ", ".join(FONT_FALLBACK[locale])
    if locale in LATIN_LOCALES:
        return "sans-serif"
    return "sans-serif"


def is_cjk_locale(locale: str) -> bool:
    return locale in CJK_LOCALES


def is_rtl_locale(locale: str) -> bool:
    return locale in RTL_LOCALES


def text_direction(locale: str) -> str:
    """Return CSS ``direction`` value: ``'ltr'`` or ``'rtl'``."""
    return "rtl" if is_rtl_locale(locale) else "ltr"


def font_assets_to_embed(locales: list[str]) -> list[str]:
    """Return the set of Noto font files that should be bundled for these locales.

    Each entry is a Noto Sans subset filename (e.g. ``NotoSansJP-Regular.otf``)
    that should be downloaded and embedded in the game build to guarantee
    CJK/RTL glyphs render correctly even if the user's browser does not
    have them.
    """
    assets: set[str] = set()
    for loc in locales:
        if loc in {"ja"}:
            assets.add("NotoSansJP-Regular.otf")
        elif loc in {"ko"}:
            assets.add("NotoSansKR-Regular.otf")
        elif loc in {"zh-CN", "zh"}:
            assets.add("NotoSansSC-Regular.otf")
        elif loc in {"zh-TW"}:
            assets.add("NotoSansTC-Regular.otf")
        elif loc in {"ar", "fa", "ur"}:
            assets.add("NotoSansArabic-Regular.otf")
        elif loc in {"he"}:
            assets.add("NotoSansHebrew-Regular.otf")
    return sorted(assets)

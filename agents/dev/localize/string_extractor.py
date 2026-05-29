"""Extract translatable strings from generated game code."""
from __future__ import annotations

import json
import re
from pathlib import Path

from loguru import logger


def extract_strings(game_dist_path: str | Path) -> dict[str, str]:
    """Extract all translatable strings from a game's dist directory.

    Returns dict mapping string_id -> original English string.
    """
    dist = Path(game_dist_path)
    strings: dict[str, str] = {}
    counter = 0

    for html_file in dist.glob("**/*.html"):
        content = html_file.read_text(encoding="utf-8", errors="ignore")
        text_nodes = re.findall(r'>([^<]{2,})<', content)
        for text in text_nodes:
            text = text.strip()
            if text and not text.startswith(("{", "//", "/*", "<!")):
                key = f"str_{counter:03d}"
                strings[key] = text
                counter += 1

    for js_file in dist.glob("**/*.js"):
        content = js_file.read_text(encoding="utf-8", errors="ignore")
        js_strings = re.findall(r'["\']([A-Z][^"\']{2,})["\']', content)
        for text in js_strings:
            text = text.strip()
            if (
                any(c.isalpha() for c in text)
                and not text.startswith(("http", "function", "var ", "let ", "const "))
            ):
                key = f"str_{counter:03d}"
                strings[key] = text
                counter += 1

    logger.info(f"Extracted {len(strings)} translatable strings")
    return strings


def inject_localization(
    game_dist_path: str | Path,
    translations: dict[str, dict[str, str]],
) -> dict:
    """Inject localized strings into the game.

    Args:
        game_dist_path: Path to game dist/
        translations: {locale: {string_id: translated_string}}

    Returns:
        dict with: locales, loc_file_path
    """
    dist = Path(game_dist_path)
    loc_dir = dist / "assets" / "loc"
    loc_dir.mkdir(parents=True, exist_ok=True)

    locales = list(translations.keys())

    loc_data: dict[str, dict[str, str]] = {"en": {}}
    for locale, strings in translations.items():
        loc_data[locale] = strings

    loc_js = f"""// Auto-generated localization
window.GameLoc = {{
  data: {json.dumps(loc_data, ensure_ascii=False)},
  locale: navigator.language.split('-')[0] || 'en',
  get: function(key) {{
    var loc = this.data[this.locale] || this.data['en'] || {{}};
    return loc[key] || this.data['en'][key] || key;
  }},
  setLocale: function(loc) {{
    this.locale = loc;
    if (typeof onLocaleChange === 'function') onLocaleChange(loc);
  }}
}};
"""

    loc_path = loc_dir / "loc.js"
    loc_path.write_text(loc_js, encoding="utf-8")

    index = dist / "index.html"
    if index.exists():
        html = index.read_text(encoding="utf-8")
        if "loc.js" not in html:
            html = html.replace(
                "</head>",
                '<script src="assets/loc/loc.js"></script>\n</head>',
            )
            index.write_text(html, encoding="utf-8")

    return {"locales": locales, "loc_file_path": str(loc_path)}

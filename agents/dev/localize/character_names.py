"""Character name localization for VN games.

Proper nouns (character names) need special translation handling:
* Names may be transliterated (Alice → アリス / 愛麗絲 / أليس)
* Names may be kept in original (preserved in katakana for Japanese)
* Names may be adapted culturally (e.g., shorten for Japanese style)

This module:
1. Extracts character names from the project's data files
2. Builds a per-locale translation table (name → translated name)
3. Produces a JSON map that the localization injection step can splice
   into the game's runtime locale switcher

Design: pure functions, no API calls. The actual name translation is
left to the LLM step (called separately), which produces the
``translated_names`` dict this module then formats.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TARGET_LOCALES: tuple[str, ...] = (
    "ja", "ko", "zh-CN", "es", "pt", "de", "fr", "ru", "ar", "hi", "th", "vi", "id", "tr", "it", "pl",
)


def build_name_translation_template(
    character_names: list[str],
    locales: list[str] | None = None,
) -> dict[str, dict[str, str]]:
    """Build an empty per-locale translation table for the given names.

    Returns a 2-level dict: ``{locale: {character_name: ""}}`` with empty
    values ready for LLM fill-in.
    """
    locales = locales or list(TARGET_LOCALES)
    out: dict[str, dict[str, str]] = {}
    for loc in locales:
        out[loc] = {name: "" for name in character_names}
    return out


def fill_name_translations(
    template: dict[str, dict[str, str]],
    translations: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    """Merge LLM-produced translations into the template (in place)."""
    for loc, name_map in translations.items():
        if loc not in template:
            template[loc] = {}
        for name, translated in name_map.items():
            template[loc][name] = translated
    return template


def load_character_names_from_project(data_dir: str | Path) -> list[str]:
    """Read ``characters.json`` and return the list of character names."""
    chars_path = Path(data_dir) / "characters.json"
    if not chars_path.exists():
        return []
    try:
        data = json.loads(chars_path.read_text(encoding="utf-8", errors="ignore"))
    except (json.JSONDecodeError, OSError):
        return []
    return [c["name"] for c in data.get("characters", []) if isinstance(c, dict) and c.get("name")]


def write_name_locale_files(
    translations: dict[str, dict[str, str]],
    output_dir: str | Path,
) -> dict[str, Path]:
    """Write one ``character_names.<locale>.json`` file per locale.

    Returns a mapping of locale → file path.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for locale, name_map in translations.items():
        target = out_dir / f"character_names.{locale}.json"
        try:
            target.write_text(
                json.dumps(name_map, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            written[locale] = target
        except OSError:
            pass
    return written


def merge_into_loc_data(
    translations: dict[str, dict[str, str]],
    existing_loc_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge character name translations into the game's localization data dict.

    The result is a nested dict: ``{locale: {character_name: translated, ...}}``
    that the game's runtime can look up via ``GameLoc.get('character:<name>')``
    or a similar key convention.
    """
    existing = existing_loc_data or {}
    out: dict[str, Any] = {locale: dict(mapping) for locale, mapping in existing.items()}
    for locale, name_map in translations.items():
        bucket = out.setdefault(locale, {})
        for name, translated in name_map.items():
            bucket[f"character:{name}"] = translated
    return out


def count_unfilled(template: dict[str, dict[str, str]]) -> dict[str, int]:
    """Count how many names remain unfilled per locale (for QA)."""
    return {loc: sum(1 for v in names.values() if not v) for loc, names in template.items()}

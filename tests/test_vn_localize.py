"""Tests for shared/fonts.py and agents/dev/localize/{ts_extractor,character_names}.py."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from agents.dev.localize.character_names import (
    TARGET_LOCALES,
    build_name_translation_template,
    count_unfilled,
    fill_name_translations,
    load_character_names_from_project,
    merge_into_loc_data,
    write_name_locale_files,
)
from agents.dev.localize.ts_extractor import (
    extract_from_data_json,
    extract_from_project,
    extract_from_typescript,
)
from shared.fonts import (
    CJK_LOCALES,
    FONT_FALLBACK,
    LATIN_LOCALES,
    RTL_LOCALES,
    font_assets_to_embed,
    get_font_family,
    is_cjk_locale,
    is_rtl_locale,
    text_direction,
)


# --- fonts tests ---

def test_get_font_family_for_latin_locales():
    for loc in ["en", "es", "de", "fr"]:
        assert get_font_family(loc) == "sans-serif"


def test_get_font_family_for_cjk_locales():
    for loc in ["ja", "ko", "zh", "zh-CN", "zh-TW"]:
        css = get_font_family(loc)
        assert "Noto" in css
        assert "sans-serif" in css


def test_get_font_family_for_rtl_locales():
    for loc in ["ar", "he", "fa", "ur"]:
        css = get_font_family(loc)
        assert "Noto" in css
        assert "sans-serif" in css


def test_get_font_family_for_unknown_locale_falls_back_to_sans_serif():
    assert get_font_family("xx") == "sans-serif"


def test_is_cjk_locale():
    assert is_cjk_locale("ja") is True
    assert is_cjk_locale("ko") is True
    assert is_cjk_locale("en") is False
    assert is_cjk_locale("ar") is False


def test_is_rtl_locale():
    assert is_rtl_locale("ar") is True
    assert is_rtl_locale("he") is True
    assert is_rtl_locale("ja") is False
    assert is_rtl_locale("en") is False


def test_text_direction():
    assert text_direction("en") == "ltr"
    assert text_direction("ja") == "ltr"
    assert text_direction("ar") == "rtl"
    assert text_direction("he") == "rtl"


def test_font_assets_to_embed_dedupes():
    assets = font_assets_to_embed(["ja", "ja", "ko", "en"])
    assert "NotoSansJP-Regular.otf" in assets
    assert "NotoSansKR-Regular.otf" in assets
    assert assets.count("NotoSansJP-Regular.otf") == 1


def test_font_assets_to_embed_unknown_locale_empty():
    assert font_assets_to_embed(["xx", "yy"]) == []


# --- ts_extractor tests ---

def test_extract_from_typescript_finds_phaser_text_strings(tmp_path):
    f = tmp_path / "main.ts"
    f.write_text(
        'import * as Phaser from "phaser";\n'
        'this.add.text(100, 100, "Click to start", { fontSize: "16px" });\n'
        'this.add.text(200, 200, "Game Over", {});\n'
    )
    result = extract_from_typescript(f)
    assert result != {}
    assert any("Click to start" in v for v in result.values())
    assert any("Game Over" in v for v in result.values())


def test_extract_from_typescript_finds_dialogue_speakers(tmp_path):
    f = tmp_path / "dialogue.json.ts"
    f.write_text(
        '{ lines: [\n'
        '  { id: "l01", text: "Hello there", speaker: "Alice" },\n'
        '  { id: "l02", text: "Hi Alice", speaker: "Bob" },\n'
        '} }\n'
    )
    result = extract_from_typescript(f)
    assert "Alice" in result.values()
    assert "Bob" in result.values()
    assert "Hello there" in result.values()


def test_extract_from_typescript_dedupes(tmp_path):
    f = tmp_path / "main.ts"
    f.write_text('this.add.text(0, 0, "Hello", {});\nthis.add.text(0, 0, "Hello", {});\n')
    result = extract_from_typescript(f)
    assert sum(1 for v in result.values() if v == "Hello") == 1


def test_extract_from_typescript_missing_file_returns_empty(tmp_path):
    assert extract_from_typescript(tmp_path / "nope.ts") == {}


def test_extract_from_project_walks_recursively(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.ts").write_text('this.add.text(0, 0, "Alice", {});')
    (src / "sub").mkdir()
    (src / "sub" / "b.ts").write_text('this.add.text(0, 0, "Bob", {});')
    result = extract_from_project(src)
    assert "Alice" in result.values()
    assert "Bob" in result.values()


def test_extract_from_data_json_extracts_characters_and_endings(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "characters.json").write_text(json.dumps({"characters": [
        {"name": "Alice", "role": "heroine"},
        {"name": "Bob", "role": "heroine"},
    ]}))
    (data_dir / "endings.json").write_text(json.dumps({"endings": [
        {"name": "good_end", "epilogue_key": "epilogue.good"},
    ]}))

    result = extract_from_data_json(data_dir)
    assert "Alice" in result["characters"]
    assert "Bob" in result["characters"]
    assert "good_end" in result["endings"]


# --- character_names tests ---

def test_build_name_translation_template_creates_empty_slots():
    template = build_name_translation_template(["Alice", "Bob"])
    assert template["ja"] == {"Alice": "", "Bob": ""}
    assert template["ko"] == {"Alice": "", "Bob": ""}
    assert len(template) == len(TARGET_LOCALES)


def test_fill_name_translations_merges_correctly():
    template = build_name_translation_template(["Alice", "Bob"], locales=["ja", "ko"])
    fill_name_translations(template, {"ja": {"Alice": "アリス"}, "ko": {"Bob": "밥"}})
    assert template["ja"]["Alice"] == "アリス"
    assert template["ja"]["Bob"] == ""
    assert template["ko"]["Bob"] == "밥"


def test_load_character_names_from_project(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "characters.json").write_text(json.dumps({"characters": [
        {"name": "Alice"}, {"name": "Bob"}, {"name": "Carol"},
    ]}))
    names = load_character_names_from_project(data_dir)
    assert names == ["Alice", "Bob", "Carol"]


def test_load_character_names_missing_file():
    assert load_character_names_from_project("/nonexistent") == []


def test_write_name_locale_files_creates_files(tmp_path):
    translations = {
        "ja": {"Alice": "アリス"},
        "ko": {"Alice": "앨리스"},
    }
    written = write_name_locale_files(translations, tmp_path)
    assert (tmp_path / "character_names.ja.json").exists()
    assert (tmp_path / "character_names.ko.json").exists()
    assert json.loads((tmp_path / "character_names.ja.json").read_text()) == {"Alice": "アリス"}


def test_merge_into_loc_data_preserves_existing_keys():
    result = merge_into_loc_data(
        {"ja": {"Alice": "アリス"}},
        existing_loc_data={"ja": {"menu:start": "スタート"}, "en": {"menu:start": "Start"}},
    )
    assert result["ja"]["menu:start"] == "スタート"
    assert result["ja"]["character:Alice"] == "アリス"
    assert result["en"]["menu:start"] == "Start"


def test_count_unfilled():
    template = {"ja": {"Alice": "アリス", "Bob": ""}, "ko": {"Alice": "", "Bob": ""}}
    counts = count_unfilled(template)
    assert counts == {"ja": 1, "ko": 2}

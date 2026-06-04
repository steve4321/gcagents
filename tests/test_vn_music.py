"""Tests for agents/dev/music/mood_bgm.py and sfx_generator.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.dev.music.mood_bgm import (
    MOODS,
    MOOD_BGM_CONFIG,
    _note_frequencies,
    generate_bgm_js,
    get_mood_config,
    mood_to_filename,
    write_all_bgm_tracks,
)
from agents.dev.music.sfx_generator import (
    SFX_CATEGORIES,
    SFX_DEFINITIONS,
    generate_sfx_js,
    write_sfx_js,
)


def test_moods_count_matches_plan():
    assert len(MOODS) == 7
    assert MOODS == ("neutral", "tense", "romantic", "sad", "happy", "mystery", "action")


def test_mood_bgm_config_covers_all_moods():
    for mood in MOODS:
        assert mood in MOOD_BGM_CONFIG
        cfg = MOOD_BGM_CONFIG[mood]
        assert "tempo" in cfg
        assert "scale" in cfg
        assert "octave" in cfg
        assert "waveform" in cfg
        assert "volume" in cfg
        assert 0.05 <= cfg["volume"] <= 0.20
        assert 40 <= cfg["tempo"] <= 180


def test_get_mood_config_raises_for_unknown():
    with pytest.raises(ValueError, match="unknown mood"):
        get_mood_config("euphoric")


def test_note_frequencies_returns_correct_count():
    notes = _note_frequencies("major", 4)
    assert len(notes) == 8
    assert notes[0] == pytest.approx(261.63, abs=0.1)


def test_generate_bgm_js_contains_window_global():
    for mood in MOODS:
        js = generate_bgm_js(mood)
        assert f"window.GameBGM_{mood.upper()}" in js
        assert "AudioContext" in js
        assert "start" in js
        assert "stop" in js


def test_generate_bgm_js_uses_mood_specific_tempo():
    js_neutral = generate_bgm_js("neutral")
    js_action = generate_bgm_js("action")
    assert str(MOOD_BGM_CONFIG["neutral"]["tempo"]) in js_neutral
    assert str(MOOD_BGM_CONFIG["action"]["tempo"]) in js_action
    assert MOOD_BGM_CONFIG["neutral"]["tempo"] != MOOD_BGM_CONFIG["action"]["tempo"]


def test_write_all_bgm_tracks_creates_seven_files(tmp_path):
    audio_dir = tmp_path / "audio"
    written = write_all_bgm_tracks(audio_dir)
    assert len(written) == 7
    for mood in MOODS:
        path = written[mood]
        assert path.exists()
        assert path.stat().st_size > 0
        assert path.name == f"bgm_{mood}.js"


def test_write_all_bgm_tracks_idempotent(tmp_path):
    audio_dir = tmp_path / "audio"
    write_all_bgm_tracks(audio_dir)
    first_mtime = (audio_dir / "bgm_neutral.js").stat().st_mtime
    write_all_bgm_tracks(audio_dir)
    second_mtime = (audio_dir / "bgm_neutral.js").stat().st_mtime
    assert first_mtime == second_mtime


def test_mood_to_filename_raises_for_unknown():
    with pytest.raises(ValueError):
        mood_to_filename("nervous")
    assert mood_to_filename("romantic") == "bgm_romantic.js"


def test_sfx_categories_count_matches_plan():
    assert len(SFX_CATEGORIES) == 5
    assert SFX_CATEGORIES == ("choice_select", "transition_whoosh", "heartbeat", "route_unlock", "ending_reveal")


def test_sfx_definitions_cover_all_categories():
    for cat in SFX_CATEGORIES:
        assert cat in SFX_DEFINITIONS
        assert "createOscillator" in SFX_DEFINITIONS[cat] or "createBuffer" in SFX_DEFINITIONS[cat]


def test_generate_sfx_js_includes_all_categories():
    js = generate_sfx_js()
    for cat in SFX_CATEGORIES:
        assert f"case {cat!r}" in js
    assert "window.GameSFX" in js
    assert "play" in js
    assert "AudioContext" in js


def test_write_sfx_js_creates_file(tmp_path):
    audio_dir = tmp_path / "audio"
    path = write_sfx_js(audio_dir)
    assert path is not None
    assert path.exists()
    assert path.name == "sfx.js"
    content = path.read_text()
    for cat in SFX_CATEGORIES:
        assert cat in content

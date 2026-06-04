"""Tests for code_generator — grid genre, file validation, prompt loading."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agents.dev.programmer import code_generator
from agents.dev.programmer.code_generator import (
    _PROMPT_CACHE,
    _load_prompt,
    _validate_file_path,
    is_grid_genre,
)


class TestIsGridGenre:
    @pytest.mark.parametrize(
        "genre,expected",
        [
            ("puzzle", True),
            ("match-3", True),
            ("match3", True),
            ("merge", True),
            ("sudoku", True),
            ("tetris", True),
            ("candy", True),
            ("2048", True),
            ("Puzzle", True),
            ("Match_3", True),
            ("platformer", False),
            ("shooter", False),
            ("rpg", False),
            ("", False),
        ],
    )
    def test_grid_genres(self, genre: str, expected: bool):
        assert is_grid_genre(genre) is expected


class TestValidateFilePath:
    def test_valid_relative_path(self, tmp_path):
        assert _validate_file_path(tmp_path, "src/main.ts") is True

    def test_rejects_parent_traversal(self, tmp_path):
        assert _validate_file_path(tmp_path, "../secret.txt") is False

    def test_rejects_deep_parent_traversal(self, tmp_path):
        assert _validate_file_path(tmp_path, "a/../../etc/passwd") is False

    def test_rejects_absolute_path(self, tmp_path):
        assert _validate_file_path(tmp_path, "/etc/passwd") is False


class TestPromptLoading:
    def test_load_programmer_prompt(self):
        _PROMPT_CACHE.clear()
        prompt = _load_prompt("programmer")
        assert "Phaser 4" in prompt
        assert "TypeScript" in prompt
        assert "GAME_CONFIG" in prompt

    def test_load_ceo_prompt(self):
        from dashboard.web.api_server import _load_ceo_prompt, _CEO_PROMPT_CACHE

        _CEO_PROMPT_CACHE = None
        prompt = _load_ceo_prompt()
        assert "CEO" in prompt
        assert "ACTION" in prompt

    def test_prompt_caching(self):
        _PROMPT_CACHE.clear()
        first = _load_prompt("programmer")
        second = _load_prompt("programmer")
        assert first is second
        assert "programmer" in _PROMPT_CACHE


class TestConstants:
    def test_max_self_verify_retries_is_positive(self):
        assert code_generator.MAX_SELF_VERIFY_RETRIES > 0

    def test_max_source_chars_in_prompt(self):
        assert code_generator.MAX_SOURCE_CHARS_IN_PROMPT >= 1000

    def test_grid_genres_set_not_empty(self):
        assert len(code_generator.GRID_GENRES) > 0
        assert "puzzle" in code_generator.GRID_GENRES


class TestCopyArtAssetsSafety:
    def test_rejects_path_outside_allowed_root(self, tmp_path):
        outside_dir = tmp_path / "evil_dir"
        outside_dir.mkdir()
        (outside_dir / "evil.png").write_bytes(b"\x89PNG")
        project = tmp_path / "project"
        project.mkdir()
        code_generator._copy_art_assets(str(outside_dir), project)
        assert not (project / "public" / "assets").exists()

    def test_missing_source_returns_silently(self, tmp_path, caplog):
        project = tmp_path / "project"
        project.mkdir()
        code_generator._copy_art_assets(str(tmp_path / "nonexistent"), project)
        assert not (project / "public" / "assets").exists()

"""Tests for game code generation with mocked LLM responses."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.dev.programmer.code_generator import (
    _parse_code_files,
    _scaffold_project,
)


class TestParseCodeFiles:
    def test_parse_valid_json_dict(self):
        text = json.dumps({"src/main.ts": "console.log('hello')", "src/game.ts": "// game"})
        result = _parse_code_files(text)
        assert "src/main.ts" in result
        assert "src/game.ts" in result

    def test_parse_code_block_wrapped(self):
        text = '```\n{"src/main.ts": "code"}\n```'
        result = _parse_code_files(text)
        assert "src/main.ts" in result

    def test_parse_invalid_returns_empty(self):
        result = _parse_code_files("not valid json at all")
        assert result == {}

    def test_parse_non_dict_returns_empty(self):
        result = _parse_code_files(json.dumps(["not", "a", "dict"]))
        assert result == {}


class TestScaffoldProject:
    def test_creates_project_files(self, tmp_path):
        project_dir = tmp_path / "test-game"
        project_dir.mkdir()
        _scaffold_project(project_dir)

        assert (project_dir / "package.json").exists()
        assert (project_dir / "tsconfig.json").exists()
        assert (project_dir / "vite.config.ts").exists()
        assert (project_dir / "index.html").exists()
        assert (project_dir / "public").is_dir()

    def test_package_json_is_valid(self, tmp_path):
        project_dir = tmp_path / "test-game"
        project_dir.mkdir()
        _scaffold_project(project_dir)

        pkg = json.loads((project_dir / "package.json").read_text())
        assert pkg["type"] == "module"
        assert "phaser" in pkg["dependencies"]
        assert "build" in pkg["scripts"]


class TestGenerateGameCode:
    @pytest.mark.asyncio
    async def test_generates_files_from_gdd(self, tmp_path):
        """Test that generate_game_code creates source files from a GDD."""
        mock_response = json.dumps({
            "src/main.ts": "import * as Phaser from 'phaser';",
            "src/game/scenes/GameScene.ts": "export class GameScene extends Phaser.Scene {}",
        })

        with patch("agents.dev.programmer.code_generator._install_and_build"), \
             patch("shared.llm_client.llm.chat_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = (mock_response, {"total_tokens": 1000})

            from agents.dev.programmer.code_generator import generate_game_code
            from shared.config import AppConfig

            config = AppConfig(deepseek_api_key="test-key", zhipu_api_key="")
            gdd = {"title": "Test Game", "genre": "puzzle"}

            result = await generate_game_code(gdd, tmp_path, config)

            assert (tmp_path / "src" / "main.ts").exists()
            assert "Phaser" in (tmp_path / "src" / "main.ts").read_text()

"""Tests for template-based variant generation: schema derivation, validation, file filtering."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agents.dev.programmer.code_generator import (
    _derive_template_data_schema,
    _generate_from_template,
    _is_allowed_template_data_path,
    _validate_template_data,
)


SPACE_ENEMIES = {
    "enemies": [
        {
            "key": "drone",
            "name": "Scout Drone",
            "hp": 30,
            "speed": 80,
            "goldReward": 5,
            "baseDamage": 1,
            "radius": 10,
            "color": 16241181,
        },
        {
            "key": "mech",
            "name": "War Mech",
            "hp": 60,
            "speed": 60,
            "goldReward": 10,
            "baseDamage": 2,
            "radius": 13,
            "color": 15236667,
        },
        {
            "key": "battleship",
            "name": "Battleship",
            "hp": 100,
            "speed": 40,
            "goldReward": 15,
            "baseDamage": 3,
            "radius": 16,
            "color": 10184438,
        },
    ]
}

SPACE_TOWERS = {
    "towers": [
        {
            "key": "laser",
            "name": "Laser Turret",
            "cost": 50,
            "damage": 10,
            "range": 120,
            "fireRate": 500,
            "projectileSpeed": 300,
            "projectileType": "single",
            "splashRadius": 0,
            "slowFactor": 0,
            "slowDuration": 0,
            "color": 2855648,
            "radius": 14,
            "upgrade": {"cost": 38, "damageMultiplier": 1.5, "rangeMultiplier": 1.2},
        },
    ]
}

SPACE_WAVES = {
    "waves": [
        {
            "wave": 1,
            "enemies": [{"type": "drone", "count": 5}],
            "spawnInterval": 800,
        }
    ]
}

SPACE_PATH = {"waypoints": [{"x": 0, "y": 0}, {"x": 100, "y": 0}], "startHp": 20}


class TestPathFiltering:
    def test_data_files_allowed(self):
        for path in [
            "src/game/data/towers.json",
            "src/game/data/enemies.json",
            "src/game/data/waves.json",
            "src/game/data/path.json",
            "./src/game/data/towers.json",
        ]:
            assert _is_allowed_template_data_path(path) is True, f"{path} should be allowed"

    def test_ts_files_rejected(self):
        for path in [
            "src/main.ts",
            "src/game/scenes/GameScene.ts",
            "src/game/entities/Tower.ts",
            "src/game/systems/WaveManager.ts",
        ]:
            assert _is_allowed_template_data_path(path) is False, f"{path} should be rejected"

    def test_config_files_rejected(self):
        for path in [
            "package.json",
            "tsconfig.json",
            "vite.config.ts",
            "index.html",
            "public/assets/image.png",
        ]:
            assert _is_allowed_template_data_path(path) is False, f"{path} should be rejected"


class TestSchemaDerivation:
    def test_derives_array_of_objects(self):
        data = {
            "enemies.json": json.dumps(SPACE_ENEMIES),
            "towers.json": json.dumps(SPACE_TOWERS),
        }
        schema = _derive_template_data_schema(data)
        assert "enemies" in schema["enemies.json"]
        assert schema["enemies.json"]["enemies"]["type"] == "array"
        required = schema["enemies.json"]["enemies"]["required"]
        assert "hp" in required
        assert "speed" in required
        assert "key" in required

    def test_derives_scalar_values(self):
        data = {"path.json": json.dumps(SPACE_PATH)}
        schema = _derive_template_data_schema(data)
        assert "startHp" in schema["path.json"]
        assert schema["path.json"]["startHp"]["type"] == "int"

    def test_handles_invalid_json(self):
        data = {"bad.json": "{not valid json"}
        schema = _derive_template_data_schema(data)
        assert "bad.json" not in schema

    def test_empty_array_skipped(self):
        data = {"empty.json": json.dumps({"items": []})}
        schema = _derive_template_data_schema(data)
        assert "items" not in schema.get("empty.json", {})


class TestDataValidation:
    @pytest.fixture
    def td_schema(self):
        return {
            "enemies.json": {
                "enemies": {
                    "type": "array",
                    "required": ["key", "name", "hp", "speed"],
                }
            },
            "path.json": {
                "waypoints": {"type": "array", "required": ["x", "y"]},
                "startHp": {"type": "int"},
            },
        }

    def test_valid_data_passes(self, td_schema):
        content = json.dumps({
            "enemies": [{"key": "a", "name": "A", "hp": 30, "speed": 50}]
        })
        errors = _validate_template_data("data/enemies.json", content, td_schema)
        assert errors == []

    def test_missing_field_detected(self, td_schema):
        content = json.dumps({"enemies": [{"key": "a", "name": "A", "hp": 30}]})
        errors = _validate_template_data("data/enemies.json", content, td_schema)
        assert len(errors) == 1
        assert "speed" in errors[0]

    def test_invalid_json_detected(self, td_schema):
        errors = _validate_template_data("data/enemies.json", "{bad", td_schema)
        assert len(errors) == 1
        assert "invalid JSON" in errors[0]

    def test_missing_top_level_key(self, td_schema):
        errors = _validate_template_data("data/enemies.json", json.dumps({"wrong": []}), td_schema)
        assert len(errors) == 1
        assert "enemies" in errors[0]

    def test_empty_array_detected(self, td_schema):
        errors = _validate_template_data("data/enemies.json", json.dumps({"enemies": []}), td_schema)
        assert len(errors) == 1
        assert "empty" in errors[0]

    def test_wrong_type_detected(self, td_schema):
        errors = _validate_template_data("data/enemies.json", json.dumps({"enemies": "not array"}), td_schema)
        assert len(errors) == 1
        assert "must be array" in errors[0]


class TestGenerationFlow:
    @pytest.fixture
    def copied_template(self, tmp_path):
        src = Path("game-templates/tower-defense")
        if not (src / "src" / "main.ts").exists():
            pytest.skip("Golden template not present")
        dst = tmp_path / "test-gen"
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            if item.name in ("node_modules", "dist", ".git"):
                continue
            if item.is_dir():
                shutil.copytree(item, dst / item.name, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dst / item.name)
        return dst

    @pytest.mark.asyncio
    async def test_successful_first_attempt(self, copied_template):
        llm_response = json.dumps({
            "src/game/data/towers.json": json.dumps(SPACE_TOWERS),
            "src/game/data/enemies.json": json.dumps(SPACE_ENEMIES),
            "src/game/data/waves.json": json.dumps(SPACE_WAVES),
            "src/game/data/path.json": json.dumps(SPACE_PATH),
        })

        with patch(
            "agents.dev.programmer.code_generator.llm"
        ) as mock_llm:
            mock_llm.chat_completion = AsyncMock(return_value=(llm_response,))

            from shared.config import AppConfig
            from shared.constants import DEFAULT_CODE_MODEL

            result = await _generate_from_template(
                gdd={"title": "Space TD", "genre": "tower-defense", "theme": "space"},
                project_dir=copied_template,
                config=AppConfig(),
                model=DEFAULT_CODE_MODEL,
                max_tokens=8192,
            )

            assert result == copied_template
            assert mock_llm.chat_completion.call_count == 1
            written_towers = json.loads(
                (copied_template / "src/game/data/towers.json").read_text()
            )
            assert written_towers["towers"][0]["key"] == "laser"

    @pytest.mark.asyncio
    async def test_non_data_files_filtered(self, copied_template):
        llm_response = json.dumps({
            "src/game/data/towers.json": json.dumps(SPACE_TOWERS),
            "src/main.ts": "MALICIOUS CODE",
            "src/game/systems/WaveManager.ts": "ALSO MALICIOUS",
            "package.json": "{}",
        })

        with patch("agents.dev.programmer.code_generator.llm") as mock_llm:
            mock_llm.chat_completion = AsyncMock(return_value=(llm_response,))

            from shared.config import AppConfig
            from shared.constants import DEFAULT_CODE_MODEL

            await _generate_from_template(
                gdd={"title": "Bad Gen", "genre": "tower-defense"},
                project_dir=copied_template,
                config=AppConfig(),
                model=DEFAULT_CODE_MODEL,
                max_tokens=8192,
            )

            assert mock_llm.chat_completion.call_count == 1
            original_main = (copied_template / "src/main.ts").read_text()
            assert "MALICIOUS" not in original_main

    @pytest.mark.asyncio
    async def test_retry_on_validation_failure(self, copied_template):
        bad_response = json.dumps({
            "src/game/data/towers.json": json.dumps({
                "towers": [{"key": "x"}]
            })
        })
        good_response = json.dumps({
            "src/game/data/towers.json": json.dumps(SPACE_TOWERS),
            "src/game/data/enemies.json": json.dumps(SPACE_ENEMIES),
            "src/game/data/waves.json": json.dumps(SPACE_WAVES),
            "src/game/data/path.json": json.dumps(SPACE_PATH),
        })

        with patch("agents.dev.programmer.code_generator.llm") as mock_llm:
            mock_llm.chat_completion = AsyncMock(
                side_effect=[(bad_response,), (good_response,)]
            )

            from shared.config import AppConfig
            from shared.constants import DEFAULT_CODE_MODEL

            await _generate_from_template(
                gdd={"title": "Retry TD", "genre": "tower-defense"},
                project_dir=copied_template,
                config=AppConfig(),
                model=DEFAULT_CODE_MODEL,
                max_tokens=8192,
            )

            assert mock_llm.chat_completion.call_count == 2
            second_call = mock_llm.chat_completion.call_args_list[1]
            user_msg = second_call.kwargs["messages"][1]["content"]
            assert "PREVIOUS ATTEMPT FAILED" in user_msg

    @pytest.mark.asyncio
    async def test_exhausts_retries(self, copied_template):
        bad_response = json.dumps({
            "src/game/data/towers.json": json.dumps({
                "towers": [{"key": "x"}]
            })
        })

        with patch("agents.dev.programmer.code_generator.llm") as mock_llm:
            mock_llm.chat_completion = AsyncMock(return_value=(bad_response,))

            from shared.config import AppConfig
            from shared.constants import DEFAULT_CODE_MODEL

            await _generate_from_template(
                gdd={"title": "Fail TD", "genre": "tower-defense"},
                project_dir=copied_template,
                config=AppConfig(),
                model=DEFAULT_CODE_MODEL,
                max_tokens=8192,
            )

            assert mock_llm.chat_completion.call_count == 2


class TestMemoryInjection:
    @pytest.fixture
    def copied_template(self, tmp_path):
        src = Path("game-templates/tower-defense")
        if not (src / "src" / "main.ts").exists():
            pytest.skip("Golden template not present")
        dst = tmp_path / "mem-test"
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            if item.name in ("node_modules", "dist", ".git"):
                continue
            if item.is_dir():
                shutil.copytree(item, dst / item.name, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dst / item.name)
        return dst

    @pytest.mark.asyncio
    async def test_lessons_flow_into_prompt(self, copied_template):
        llm_response = json.dumps({
            "src/game/data/towers.json": json.dumps(SPACE_TOWERS),
            "src/game/data/enemies.json": json.dumps(SPACE_ENEMIES),
            "src/game/data/waves.json": json.dumps(SPACE_WAVES),
            "src/game/data/path.json": json.dumps(SPACE_PATH),
        })

        sample_lesson = {
            "summary": "TD: always include startHp in path.json",
            "content": "TD: always include startHp in path.json",
        }

        async def fake_search(*_args, **_kwargs):
            return [sample_lesson]

        with patch(
            "agents.dev.programmer.code_generator.llm"
        ) as mock_llm, patch(
            "agents.dev.programmer.code_generator.get_memory_store"
        ) as mock_memory:
            mock_llm.chat_completion = AsyncMock(return_value=(llm_response,))
            mock_store = mock_memory.return_value
            mock_store.search_long_term = fake_search

            from shared.config import AppConfig
            from shared.constants import DEFAULT_CODE_MODEL

            await _generate_from_template(
                gdd={"title": "Memory TD", "genre": "tower-defense"},
                project_dir=copied_template,
                config=AppConfig(),
                model=DEFAULT_CODE_MODEL,
                max_tokens=8192,
            )

            assert mock_llm.chat_completion.call_count == 1
            user_msg = mock_llm.chat_completion.call_args.kwargs["messages"][1]["content"]
            assert "startHp" in user_msg
            assert "Past Experience" in user_msg

    @pytest.mark.asyncio
    async def test_empty_lessons_still_generates(self, copied_template):
        llm_response = json.dumps({
            "src/game/data/towers.json": json.dumps(SPACE_TOWERS),
            "src/game/data/enemies.json": json.dumps(SPACE_ENEMIES),
            "src/game/data/waves.json": json.dumps(SPACE_WAVES),
            "src/game/data/path.json": json.dumps(SPACE_PATH),
        })

        async def fake_search_empty(*_args, **_kwargs):
            return []

        with patch(
            "agents.dev.programmer.code_generator.llm"
        ) as mock_llm, patch(
            "agents.dev.programmer.code_generator.get_memory_store"
        ) as mock_memory:
            mock_llm.chat_completion = AsyncMock(return_value=(llm_response,))
            mock_memory.return_value.search_long_term = fake_search_empty

            from shared.config import AppConfig
            from shared.constants import DEFAULT_CODE_MODEL

            await _generate_from_template(
                gdd={"title": "No Lessons TD", "genre": "tower-defense"},
                project_dir=copied_template,
                config=AppConfig(),
                model=DEFAULT_CODE_MODEL,
                max_tokens=8192,
            )

            assert mock_llm.chat_completion.call_count == 1


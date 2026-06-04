"""Integration tests for _generate_visual_novel (2-round generation with mocked LLM)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agents.dev.programmer.code_generator import _generate_visual_novel


def _vn_gdd() -> dict:
    nodes = {f"n{i:02d}": {"scene_key": f"s{i:02d}", "dialogue": [], "choices": []} for i in range(8)}
    nodes["n00"]["choices"] = [{"label": "A", "next_node": "n01"}]
    nodes["n01"]["choices"] = []
    nodes["n02"] = {"scene_key": "s02", "dialogue": [], "choices": []}
    nodes["n03"] = {"scene_key": "s03", "dialogue": [], "choices": []}
    nodes["n04"] = {"scene_key": "s04", "dialogue": [], "choices": []}
    nodes["n05"] = {"scene_key": "s05", "dialogue": [], "choices": []}
    nodes["n06"] = {"scene_key": "s06", "dialogue": [], "choices": []}
    nodes["n07"] = {"scene_key": "s07", "dialogue": [], "choices": []}
    return {
        "title": "Test VN",
        "genre": "visual_novel",
        "narrative_premise": "A test story for integration.",
        "player_protagonist": {"name": "Yu", "pronouns": "they", "portrait_key": "yu"},
        "character_roster": [
            {"name": "Alice", "role": "heroine", "sprite_set": "c/alice",
             "expression_variants": ["neutral", "happy", "sad"], "personality": "x", "stat_affinities": []},
            {"name": "Bob", "role": "heroine", "sprite_set": "c/bob",
             "expression_variants": ["neutral", "happy", "sad"], "personality": "y", "stat_affinities": []},
        ],
        "route_structure": {"common_route_chapters": 1, "character_routes": []},
        "stat_system": {"stats": [
            {"name": f"s{i}", "range": [0, 10], "decay": 0.0, "branching_thresholds": []}
            for i in range(5)
        ]},
        "branching_tree": {"root": "n00", "nodes": nodes, "edges": []},
        "ending_conditions": [
            {"name": f"e{i}", "trigger": {"x": i}, "epilogue_key": f"e_{i}", "is_good_ending": 0}
            for i in range(3)
        ],
        "cg_milestones": [{"scene_id": "n00", "cg_key": "cg", "condition": "x"}],
        "save_points": [{"scene_id": "n00", "save_key": "s"}],
    }


def _round1_mock_response() -> str:
    return json.dumps({
        "src/game/data/characters.json": json.dumps({"characters": [{"name": "Alice"}]}),
        "src/game/data/dialogue.json": json.dumps({"lines": [{"id": "l1", "text": "hi"}]}),
        "src/main.ts": "import * as Phaser from 'phaser';\nexport {};\n",
        "src/game/scenes/BootScene.ts": "export class BootScene extends Phaser.Scene {}\n",
        "src/game/scenes/TitleScene.ts": "export class TitleScene extends Phaser.Scene {}\n",
        "src/game/scenes/MenuScene.ts": "export class MenuScene extends Phaser.Scene {}\n",
        "src/game/scenes/NovelScene.ts": "export class NovelScene extends Phaser.Scene {}\n",
        "src/game/systems/DialogueSystem.ts": "export class DialogueSystem {}\n",
    })


def _round2_mock_response() -> str:
    nodes = {f"n{i:02d}": {"scene_key": f"s{i:02d}", "choices": []} for i in range(8)}
    nodes["n00"]["choices"] = [{"label": "A", "next_node": "n01"}]
    return json.dumps({
        "src/game/data/branching.json": json.dumps({"branching_tree": {"root": "n00", "nodes": nodes, "edges": []}}),
        "src/game/data/stats.json": json.dumps({"stats": [{"name": f"s{i}", "range": [0, 10]} for i in range(5)]}),
        "src/game/data/endings.json": json.dumps({"endings": [
            {"name": f"e{i}", "trigger": {"x": i}, "epilogue_key": f"e_{i}", "is_good_ending": 0}
            for i in range(3)
        ]}),
        "src/game/systems/BranchingEngine.ts": "export class BranchingEngine {}\n",
        "src/game/systems/StatSystem.ts": "export class StatSystem {}\n",
        "src/game/systems/ChoiceSystem.ts": "export class ChoiceSystem {}\n",
        "src/game/scenes/NovelScene.ts": "export class NovelScene extends Phaser.Scene {}\n",
    })


@pytest.mark.asyncio
async def test_vn_generation_calls_2_llm_calls(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    gdd = _vn_gdd()

    call_count = {"n": 0}

    async def fake_chat(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return [_round1_mock_response(), {"prompt_tokens": 0, "completion_tokens": 0}]
        return [_round2_mock_response(), {"prompt_tokens": 0, "completion_tokens": 0}]

    with patch("agents.dev.programmer.code_generator.llm") as mock_llm:
        mock_llm.chat_completion = AsyncMock(side_effect=fake_chat)
        result = await _generate_visual_novel(
            gdd, project_dir, type("Cfg", (), {})(), "fake-model", 8192
        )

    assert call_count["n"] == 2
    assert result == project_dir


@pytest.mark.asyncio
async def test_vn_generation_writes_accumulated_files(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    gdd = _vn_gdd()

    call_count = {"n": 0}

    async def fake_chat(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return [_round1_mock_response(), {}]
        return [_round2_mock_response(), {}]

    with patch("agents.dev.programmer.code_generator.llm") as mock_llm:
        mock_llm.chat_completion = AsyncMock(side_effect=fake_chat)
        await _generate_visual_novel(
            gdd, project_dir, type("Cfg", (), {})(), "fake-model", 8192
        )

    expected_files = [
        "src/game/data/characters.json",
        "src/game/data/dialogue.json",
        "src/main.ts",
        "src/game/scenes/BootScene.ts",
        "src/game/scenes/TitleScene.ts",
        "src/game/scenes/MenuScene.ts",
        "src/game/scenes/NovelScene.ts",
        "src/game/systems/DialogueSystem.ts",
        "src/game/data/branching.json",
        "src/game/data/stats.json",
        "src/game/data/endings.json",
        "src/game/systems/BranchingEngine.ts",
        "src/game/systems/StatSystem.ts",
        "src/game/systems/ChoiceSystem.ts",
    ]
    for rel_path in expected_files:
        full = project_dir / rel_path
        assert full.exists(), f"missing: {rel_path}"
        assert full.stat().st_size > 0


@pytest.mark.asyncio
async def test_vn_generation_round2_prompt_includes_branching_summary(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    gdd = _vn_gdd()

    captured_prompts: list[str] = []

    async def fake_chat(*args, **kwargs):
        messages = kwargs.get("messages", [])
        if len(messages) >= 2:
            captured_prompts.append(messages[1]["content"])
        if len(captured_prompts) == 1:
            return [_round1_mock_response(), {}]
        return [_round2_mock_response(), {}]

    with patch("agents.dev.programmer.code_generator.llm") as mock_llm:
        mock_llm.chat_completion = AsyncMock(side_effect=fake_chat)
        await _generate_visual_novel(
            gdd, project_dir, type("Cfg", (), {})(), "fake-model", 8192
        )

    assert len(captured_prompts) == 2
    r1 = captured_prompts[0]
    r2 = captured_prompts[1]
    assert "ROUND 1" in r1
    assert "ROUND 2" in r2
    assert "characters.json" in r1
    assert "branching.json" in r2
    assert "BEFORE" not in r1 and "Already implemented" not in r1
    assert "Already implemented" in r2 or "Round 1" in r2


@pytest.mark.asyncio
async def test_vn_generation_skips_path_traversal(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    gdd = _vn_gdd()

    call_count = {"n": 0}

    async def fake_chat(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return [json.dumps({
                "src/main.ts": "valid",
                "../escape.ts": "should be skipped",
                "src/../../../etc/passwd": "should be skipped",
            }), {}]
        return [_round2_mock_response(), {}]

    with patch("agents.dev.programmer.code_generator.llm") as mock_llm:
        mock_llm.chat_completion = AsyncMock(side_effect=fake_chat)
        await _generate_visual_novel(
            gdd, project_dir, type("Cfg", (), {})(), "fake-model", 8192
        )

    assert (project_dir / "src" / "main.ts").exists()
    escape_path = project_dir.parent / "escape.ts"
    assert not escape_path.exists(), "path traversal was not blocked"

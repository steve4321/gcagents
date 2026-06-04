"""Tests for VN code generation path in agents/dev/programmer/code_generator.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agents.dev.programmer.code_generator import (
    _vn_post_gen_verify,
    generate_game_code,
)
from shared.vn_schema import (
    MIN_BRANCHING_NODES,
    MIN_ENDINGS,
    MIN_STATS,
    validate_gdd,
)


def _vn_gdd() -> dict:
    nodes = {f"n{i:02d}": {"scene_key": f"s{i:02d}", "dialogue": [], "choices": []} for i in range(MIN_BRANCHING_NODES)}
    nodes["n00"]["choices"] = [{"label": "A", "next_node": "n01"}, {"label": "B", "next_node": "n02"}]
    nodes["n01"]["choices"] = [{"label": "go", "next_node": "n03"}]
    nodes["n02"]["choices"] = [{"label": "go", "next_node": "n04"}]
    nodes["n03"]["choices"] = [{"label": "go", "next_node": "n05"}]
    nodes["n04"]["choices"] = [{"label": "go", "next_node": "n06"}]
    nodes["n05"]["choices"] = [{"label": "go", "next_node": "n07"}]
    nodes["n06"]["choices"] = [{"label": "go", "next_node": "n07"}]
    nodes["n07"]["choices"] = []
    return {
        "title": "Test VN",
        "genre": "visual_novel",
        "narrative_premise": "A test story.",
        "player_protagonist": {"name": "Yu", "pronouns": "they", "portrait_key": "yu"},
        "character_roster": [
            {"name": "Alice", "role": "heroine", "sprite_set": "characters/alice",
             "expression_variants": ["neutral", "happy", "sad", "surprised", "angry"],
             "personality": "x", "stat_affinities": ["empathy"]},
            {"name": "Bob", "role": "heroine", "sprite_set": "characters/bob",
             "expression_variants": ["neutral", "happy", "sad"],
             "personality": "y", "stat_affinities": []},
        ],
        "route_structure": {"common_route_chapters": 1, "character_routes": []},
        "stat_system": {"stats": [{"name": f"s{i}", "range": [0, 10], "decay": 0.0, "branching_thresholds": []} for i in range(MIN_STATS)]},
        "branching_tree": {"root": "n00", "nodes": nodes, "edges": []},
        "ending_conditions": [
            {"name": f"e{i}", "trigger": {"x": i}, "epilogue_key": f"e_{i}", "is_good_ending": 0}
            for i in range(MIN_ENDINGS)
        ],
        "cg_milestones": [{"scene_id": "n00", "cg_key": "cg_a", "condition": "x"}],
        "save_points": [{"scene_id": "n00", "save_key": "s_0"}],
    }


@pytest.mark.asyncio
async def test_dispatch_vn_gdd_routes_to_visual_novel_path(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    gdd = _vn_gdd()

    captured: dict = {}

    async def fake_generate_visual_novel(gdd_arg, project_dir_arg, config_arg, model_arg, max_tokens_arg, art_assets_path_arg=""):
        captured["called"] = True
        captured["gdd"] = gdd_arg
        captured["project_dir"] = project_dir_arg
        return project_dir_arg

    with patch("agents.dev.programmer.code_generator._generate_visual_novel", new=AsyncMock(side_effect=fake_generate_visual_novel)):
        with patch("agents.dev.programmer.code_generator._scaffold_project"):
            with patch("agents.dev.programmer.code_generator._install_and_build", return_value=""):
                with patch("agents.dev.programmer.code_generator._runtime_verify", return_value=""):
                    mock_config = type("Cfg", (), {"minimax_api_key": "fake"})()
                    await generate_game_code(gdd, project_dir, mock_config)

    assert captured.get("called") is True
    assert captured["gdd"]["narrative_premise"] == "A test story."


@pytest.mark.asyncio
async def test_dispatch_non_vn_gdd_skips_vn_path(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    gdd = {"title": "Generic", "mechanics": [{"name": "m1"}], "scenes": [{"name": "Game"}], "entities": []}

    with patch("agents.dev.programmer.code_generator._generate_visual_novel", new=AsyncMock()) as mock_vn:
        with patch("agents.dev.programmer.code_generator._scaffold_project"):
            with patch("agents.dev.programmer.code_generator._install_and_build", return_value=""):
                with patch("agents.dev.programmer.code_generator._runtime_verify", return_value=""):
                    with patch("agents.dev.programmer.code_generator._generate_by_mechanics", new=AsyncMock(return_value=project_dir)) as mock_bm:
                        mock_config = type("Cfg", (), {"minimax_api_key": "fake"})()
                        await generate_game_code(gdd, project_dir, mock_config)

    mock_vn.assert_not_called()
    mock_bm.assert_called()


@pytest.mark.asyncio
async def test_dispatch_invalid_vn_gdd_early_returns(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    gdd = {"title": "Broken VN", "narrative_premise": "A story.", "branching_tree": {"root": "x", "nodes": {}}}

    with patch("agents.dev.programmer.code_generator._generate_visual_novel", new=AsyncMock()) as mock_vn:
        with patch("agents.dev.programmer.code_generator._scaffold_project"):
            with patch("agents.dev.programmer.code_generator._install_and_build", return_value=""):
                mock_config = type("Cfg", (), {"minimax_api_key": "fake"})()
                result = await generate_game_code(gdd, project_dir, mock_config)

    assert result == project_dir
    mock_vn.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_missing_api_key_skips_vn_path(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    gdd = _vn_gdd()

    with patch("agents.dev.programmer.code_generator._scaffold_project"):
        mock_config = type("Cfg", (), {"minimax_api_key": ""})()
        result = await generate_game_code(gdd, project_dir, mock_config)

    assert result == project_dir


def test_post_gen_verify_valid(tmp_path):
    project_dir = tmp_path / "proj"
    data_dir = project_dir / "src" / "game" / "data"
    data_dir.mkdir(parents=True)
    nodes = {f"n{i:02d}": {"scene_key": f"s{i:02d}", "choices": []} for i in range(MIN_BRANCHING_NODES)}
    nodes["n00"]["choices"] = [{"label": "A", "next_node": "n01"}, {"label": "B", "next_node": "n02"}]
    nodes["n01"]["choices"] = [{"label": "go", "next_node": "n03"}]
    nodes["n02"]["choices"] = [{"label": "go", "next_node": "n04"}]
    nodes["n03"]["choices"] = [{"label": "go", "next_node": "n05"}]
    nodes["n04"]["choices"] = [{"label": "go", "next_node": "n06"}]
    nodes["n05"]["choices"] = [{"label": "go", "next_node": "n07"}]
    nodes["n06"]["choices"] = [{"label": "go", "next_node": "n07"}]
    nodes["n07"]["choices"] = []
    (data_dir / "branching.json").write_text(json.dumps({"branching_tree": {
        "root": "n00", "nodes": nodes, "edges": []
    }}))
    (data_dir / "endings.json").write_text(json.dumps({"endings": [
        {"name": f"e{i}", "trigger": {"x": i}, "epilogue_key": f"e_{i}", "is_good_ending": 0}
        for i in range(MIN_ENDINGS)
    ]}))

    assert _vn_post_gen_verify(project_dir) == ""


def test_post_gen_verify_invalid_branching(tmp_path):
    project_dir = tmp_path / "proj"
    data_dir = project_dir / "src" / "game" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "branching.json").write_text(json.dumps({"branching_tree": {"root": "missing", "nodes": {"a": {"scene_key": "sa"}}}}))
    (data_dir / "endings.json").write_text(json.dumps({"endings": [
        {"name": f"e{i}", "trigger": {"x": i}, "epilogue_key": f"e_{i}", "is_good_ending": 0}
        for i in range(MIN_ENDINGS)
    ]}))

    err = _vn_post_gen_verify(project_dir)
    assert "branching.json" in err
    assert "not in nodes" in err or "missing" in err


def test_post_gen_verify_invalid_endings(tmp_path):
    project_dir = tmp_path / "proj"
    data_dir = project_dir / "src" / "game" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "branching.json").write_text(json.dumps({"branching_tree": {
        "root": "n00",
        "nodes": {f"n{i:02d}": {"scene_key": f"s{i:02d}"} for i in range(MIN_BRANCHING_NODES)},
    }}))
    (data_dir / "endings.json").write_text(json.dumps({"endings": [
        {"name": "a", "trigger": {"x": 1}, "epilogue_key": "a", "is_good_ending": 0},
        {"name": "b", "trigger": {"x": 1}, "epilogue_key": "b", "is_good_ending": 0},
        {"name": "c", "trigger": {"x": 2}, "epilogue_key": "c", "is_good_ending": 0},
    ]}))

    err = _vn_post_gen_verify(project_dir)
    assert "endings.json" in err
    assert "duplicate trigger" in err


def test_post_gen_verify_missing_files_returns_empty(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    assert _vn_post_gen_verify(project_dir) == ""


def test_post_gen_verify_malformed_json(tmp_path):
    project_dir = tmp_path / "proj"
    data_dir = project_dir / "src" / "game" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "branching.json").write_text("{ invalid json")
    (data_dir / "endings.json").write_text(json.dumps({"endings": [
        {"name": f"e{i}", "trigger": {"x": i}, "epilogue_key": f"e_{i}", "is_good_ending": 0}
        for i in range(MIN_ENDINGS)
    ]}))

    err = _vn_post_gen_verify(project_dir)
    assert "branching.json" in err
    assert "parse" in err.lower() or "json" in err.lower()


def test_validate_gdd_in_dispatch_blocks_invalid(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    gdd = {"title": "broken", "narrative_premise": "x", "branching_tree": {"root": "x", "nodes": {}}}
    errors = validate_gdd(gdd)
    assert any("ending_conditions" in e for e in errors)
    assert any("character_roster" in e for e in errors)
    assert any("stat_system" in e for e in errors)

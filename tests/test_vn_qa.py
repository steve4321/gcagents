"""Tests for VN-specific QA checks in agents/dev/qa/playtest_checks.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from playwright.async_api import Page

from agents.dev.qa.playtest_checks import (
    check_branch_coverage,
    check_cg_gallery,
    check_dialogue_text_overflow,
    check_ending_reachability,
    check_localization_render,
    check_route_locked,
    check_save_load_roundtrip,
)
from shared.complexity import score_code


def _mock_page(evaluate_return=None, evaluate_side_effect=None):
    page = MagicMock(spec=Page)
    page.evaluate = AsyncMock(return_value=evaluate_return, side_effect=evaluate_side_effect)
    page.query_selector = AsyncMock()
    page.click = AsyncMock()
    page.goto = AsyncMock()
    page.reload = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    return page


def _branching_dict() -> dict:
    nodes = {f"n{i:02d}": {"scene_key": f"s{i:02d}"} for i in range(8)}
    nodes["n00"]["choices"] = [{"label": "A", "next_node": "n01"}, {"label": "B", "next_node": "n02"}]
    nodes["n01"]["choices"] = [{"label": "go", "next_node": "n03"}]
    nodes["n02"]["choices"] = [{"label": "go", "next_node": "n04"}]
    nodes["n03"]["choices"] = [{"label": "go", "next_node": "n05"}]
    nodes["n04"]["choices"] = [{"label": "go", "next_node": "n06"}]
    nodes["n05"]["choices"] = [{"label": "go", "next_node": "n07"}]
    nodes["n06"]["choices"] = [{"label": "go", "next_node": "n07"}]
    nodes["n07"]["choices"] = []
    return {"branching_tree": {"root": "n00", "nodes": nodes, "edges": []}}


def _endings_dict() -> dict:
    return {"endings": [
        {"name": f"e{i}", "trigger": {"x": i}, "epilogue_key": f"e_{i}", "is_good_ending": 0}
        for i in range(3)
    ]}


@pytest.mark.asyncio
async def test_check_branch_coverage_returns_dict_with_name_and_passed():
    page = _mock_page(evaluate_return={"currentScene": "NovelScene", "visitedScenes": ["n00"], "endingsReached": []})
    result = await check_branch_coverage(page, branching=_branching_dict(), playthroughs=1)
    assert "name" in result
    assert result["name"] == "branch_coverage"
    assert "passed" in result
    assert isinstance(result["passed"], bool)


@pytest.mark.asyncio
async def test_check_branch_coverage_passed_when_all_visited(tmp_path):
    all_nodes = [f"n{i:02d}" for i in range(8)]
    page = _mock_page(evaluate_return={"visitedScenes": all_nodes, "endingsReached": []})
    result = await check_branch_coverage(page, branching=_branching_dict(), playthroughs=1)
    assert result["passed"] is True


@pytest.mark.asyncio
async def test_check_branch_coverage_failed_when_orphans(tmp_path):
    page = _mock_page(evaluate_return={"visitedScenes": ["n00"], "endingsReached": []})
    result = await check_branch_coverage(page, branching=_branching_dict(), playthroughs=1)
    assert result["passed"] is False
    assert "unvisited" in result or "missing" in str(result).lower()


@pytest.mark.asyncio
async def test_check_branch_coverage_handles_no_test_state():
    page = _mock_page(evaluate_return=None)
    result = await check_branch_coverage(page, branching=_branching_dict(), playthroughs=1)
    assert result["passed"] is False
    assert "unvisited" in result


@pytest.mark.asyncio
async def test_check_ending_reachability_returns_dict():
    page = _mock_page(evaluate_return={"endingsReached": [], "visitedScenes": []})
    result = await check_ending_reachability(page, endings=_endings_dict(), playthroughs=1)
    assert "name" in result
    assert result["name"] == "ending_reachability"


@pytest.mark.asyncio
async def test_check_ending_reachability_passed_when_all_reached():
    page = _mock_page(evaluate_return={"endingsReached": ["e0", "e1", "e2"], "visitedScenes": []})
    result = await check_ending_reachability(page, endings=_endings_dict(), playthroughs=1)
    assert result["passed"] is True


@pytest.mark.asyncio
async def test_check_ending_reachability_failed_when_missing():
    page = _mock_page(evaluate_return={"endingsReached": ["e0"], "visitedScenes": []})
    result = await check_ending_reachability(page, endings=_endings_dict(), playthroughs=1)
    assert result["passed"] is False


@pytest.mark.asyncio
async def test_check_save_load_roundtrip_returns_dict():
    page = _mock_page(evaluate_return="hash_abc123")
    result = await check_save_load_roundtrip(page)
    assert "name" in result
    assert result["name"] == "save_load_roundtrip"


@pytest.mark.asyncio
async def test_check_save_load_roundtrip_passed_when_hashes_match():
    call_count = {"n": 0}

    async def evaluate_side_effect(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return "hash_abc"
        return "hash_abc"

    page = _mock_page(evaluate_side_effect=evaluate_side_effect)
    result = await check_save_load_roundtrip(page)
    assert result["passed"] is True
    assert result["hash_before"] == result["hash_after"]


@pytest.mark.asyncio
async def test_check_save_load_roundtrip_failed_when_hashes_differ():
    call_count = {"n": 0}

    async def evaluate_side_effect(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return "hash_before"
        return "hash_after_different"

    page = _mock_page(evaluate_side_effect=evaluate_side_effect)
    result = await check_save_load_roundtrip(page)
    assert result["passed"] is False


@pytest.mark.asyncio
async def test_check_localization_render_returns_dict():
    page = _mock_page(evaluate_return=0)
    result = await check_localization_render(page, locales=["ja", "ko"])
    assert "name" in result
    assert result["name"] == "localization_render"


@pytest.mark.asyncio
async def test_check_localization_render_passed_when_no_overflow():
    page = _mock_page(evaluate_return=0)
    result = await check_localization_render(page, locales=["ja", "ko", "en"])
    assert result["passed"] is True
    assert result["locales_tested"] == ["ja", "ko", "en"]


@pytest.mark.asyncio
async def test_check_localization_render_failed_when_overflow_detected():
    call_count = {"n": 0}

    async def evaluate_side_effect(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return 0
        return 50

    page = _mock_page(evaluate_side_effect=evaluate_side_effect)
    result = await check_localization_render(page, locales=["ja", "ar"])
    assert result["passed"] is False


@pytest.mark.asyncio
async def test_check_dialogue_text_overflow_returns_dict():
    page = _mock_page(evaluate_return={"textWidth": 100, "boxWidth": 800, "textHeight": 50, "boxHeight": 200})
    result = await check_dialogue_text_overflow(page)
    assert "name" in result
    assert result["name"] == "dialogue_overflow"


@pytest.mark.asyncio
async def test_check_dialogue_text_overflow_passed_when_fits():
    page = _mock_page(evaluate_return={"textWidth": 600, "boxWidth": 800, "textHeight": 100, "boxHeight": 200})
    result = await check_dialogue_text_overflow(page)
    assert result["passed"] is True


@pytest.mark.asyncio
async def test_check_dialogue_text_overflow_failed_when_text_exceeds():
    page = _mock_page(evaluate_return={"textWidth": 900, "boxWidth": 800, "textHeight": 100, "boxHeight": 200})
    result = await check_dialogue_text_overflow(page)
    assert result["passed"] is False


@pytest.mark.asyncio
async def test_check_cg_gallery_returns_dict():
    page = _mock_page(evaluate_return=True)
    result = await check_cg_gallery(page, cg_key="test_cg")
    assert "name" in result
    assert result["name"] == "cg_gallery"


@pytest.mark.asyncio
async def test_check_cg_gallery_passed_when_visible():
    page = _mock_page(evaluate_return=True)
    result = await check_cg_gallery(page, cg_key="test_cg")
    assert result["passed"] is True


@pytest.mark.asyncio
async def test_check_cg_gallery_failed_when_not_visible():
    page = _mock_page(evaluate_return=False)
    result = await check_cg_gallery(page, cg_key="test_cg")
    assert result["passed"] is False


@pytest.mark.asyncio
async def test_check_route_locked_returns_dict():
    page = _mock_page(evaluate_return={"currentScene": "MenuScene", "clickedScene": "MenuScene"})
    result = await check_route_locked(page, route_id="alice")
    assert "name" in result
    assert result["name"] == "route_locked"


@pytest.mark.asyncio
async def test_check_route_locked_passed_when_scene_unchanged():
    page = _mock_page(evaluate_return={"currentScene": "MenuScene", "clickedScene": "MenuScene"})
    result = await check_route_locked(page, route_id="alice")
    assert result["passed"] is True


@pytest.mark.asyncio
async def test_check_route_locked_failed_when_scene_changed():
    call_count = {"n": 0}

    async def evaluate_side_effect(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return "MenuScene"
        if call_count["n"] == 3:
            return "NovelScene"
        return None

    page = _mock_page(evaluate_side_effect=evaluate_side_effect)
    result = await check_route_locked(page, route_id="alice")
    assert result["passed"] is False
    assert result["scene_before"] == "MenuScene"
    assert result["scene_after"] == "NovelScene"


def test_complexity_score_vn_signals_present(tmp_path):
    game_dir = tmp_path / "game"
    data_dir = game_dir / "src" / "game" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "characters.json").write_text(json.dumps({"characters": [
        {"name": "A"}, {"name": "B"}, {"name": "C"}
    ]}))
    (data_dir / "stats.json").write_text(json.dumps({"stats": [{"name": f"s{i}"} for i in range(5)]}))
    (data_dir / "endings.json").write_text(json.dumps({"endings": [{"name": f"e{i}"} for i in range(3)]}))
    nodes = {f"n{i:02d}": {"scene_key": f"s{i:02d}"} for i in range(8)}
    (data_dir / "branching.json").write_text(json.dumps({"branching_tree": {"root": "n00", "nodes": nodes}}))

    src_dir = game_dir / "src"
    (src_dir / "scenes").mkdir(parents=True)
    (src_dir / "scenes" / "NovelScene.ts").write_text("export class NovelScene {}\n")

    score, metrics = score_code(game_dir)
    assert "vn_signals" in metrics or any(k.startswith("vn_") for k in metrics)
    assert score > 0


def test_complexity_score_vn_signals_missing_when_no_vn_files(tmp_path):
    game_dir = tmp_path / "game"
    src_dir = game_dir / "src"
    (src_dir / "scenes").mkdir(parents=True)
    (src_dir / "scenes" / "GameScene.ts").write_text("export class GameScene {}\n")

    score, metrics = score_code(game_dir)
    assert metrics.get("vn_signals_detected") is False or "vn_signals" not in metrics

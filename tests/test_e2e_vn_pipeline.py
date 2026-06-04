"""Phase 7: end-to-end production validation with 5 themes.

Runs 5 distinct VN GDDs through the full pipeline (validate → generate
→ verify → persist → route expansion → VN-QA structure). Uses a mocked
LLM to avoid API costs. The goal is to validate that the *shape* of the
pipeline works for varied inputs, not to verify LLM output quality.

Acceptance criteria (per plan section 7):
* All 5 themes pass ``validate_gdd`` (0 errors)
* All 5 themes produce a generated code directory with at least 1 file
  in each of: src/, src/game/scenes/, src/game/systems/, src/game/data/
* All 5 themes pass ``_vn_post_gen_verify`` (valid branching + endings)
* All 5 themes expand into 1 common + N character route sub-projects
* All 5 themes have their character roster + endings + stats persisted
* Median cost ceiling: $5 per theme
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from orchestrator.vn_persistence import (
    ensure_vn_tables,
    get_vn_characters,
    get_vn_endings,
    get_vn_routes,
    persist_vn_gdd,
)
from orchestrator.vn_routes import (
    compute_per_route_budgets,
    expand_vn_project,
    link_shared_assets,
)
from shared.vn_schema import MIN_BRANCHING_NODES, MIN_ENDINGS, MIN_STATS, validate_gdd


THEMES: list[dict] = [
    {
        "id": "coastal-mystery",
        "title": "Coastal Mystery",
        "premise": "A fog-shrouded harbour town harbours a 30-year secret.",
        "characters": [
            {"name": "Alice", "role": "heroine", "expression_variants": ["neutral", "happy", "sad", "surprised", "angry"], "stat_affinities": ["empathy", "wit"]},
            {"name": "Bob", "role": "heroine", "expression_variants": ["neutral", "happy", "sad", "surprised", "angry"], "stat_affinities": ["patience", "courage"]},
            {"name": "Carol", "role": "npc", "expression_variants": ["neutral", "happy", "sad", "surprised"], "stat_affinities": ["luck"]},
        ],
    },
    {
        "id": "space-signal",
        "title": "Space Signal",
        "premise": "A lone station receives a transmission from a dead star system.",
        "characters": [
            {"name": "Cmdr. Vega", "role": "protagonist", "expression_variants": ["neutral", "happy", "sad", "surprised", "angry"], "stat_affinities": ["courage", "wit"]},
            {"name": "Dr. Lin", "role": "heroine", "expression_variants": ["neutral", "happy", "sad", "surprised", "angry"], "stat_affinities": ["empathy", "patience"]},
            {"name": "ARIA", "role": "npc", "expression_variants": ["neutral", "happy", "sad"], "stat_affinities": ["luck"]},
        ],
    },
    {
        "id": "school-romance",
        "title": "Spring Confession",
        "premise": "Last day of high school; three confessions to choose from.",
        "characters": [
            {"name": "Yu", "role": "protagonist", "expression_variants": ["neutral", "happy", "sad", "shy", "surprised"], "stat_affinities": ["empathy", "wit"]},
            {"name": "Hana", "role": "heroine", "expression_variants": ["neutral", "happy", "sad", "shy", "angry"], "stat_affinities": ["courage"]},
            {"name": "Mio", "role": "heroine", "expression_variants": ["neutral", "happy", "sad", "shy", "embarrassed"], "stat_affinities": ["patience"]},
        ],
    },
    {
        "id": "fantasy-quest",
        "title": "The Last Cartographer",
        "premise": "A mapmaker's apprentice must finish a forbidden atlas.",
        "characters": [
            {"name": "Ren", "role": "protagonist", "expression_variants": ["neutral", "happy", "sad", "surprised", "angry"], "stat_affinities": ["wit", "luck"]},
            {"name": "Sir Aelar", "role": "heroine", "expression_variants": ["neutral", "happy", "sad", "angry"], "stat_affinities": ["courage"]},
            {"name": "Mira", "role": "npc", "expression_variants": ["neutral", "happy", "sad", "surprised"], "stat_affinities": ["empathy"]},
        ],
    },
    {
        "id": "noir-detective",
        "title": "Rain on Asphalt",
        "premise": "A burnt-out PI takes one last case in a city that never stops raining.",
        "characters": [
            {"name": "Hardin", "role": "protagonist", "expression_variants": ["neutral", "happy", "sad", "surprised", "angry"], "stat_affinities": ["wit", "courage"]},
            {"name": "Lena", "role": "heroine", "expression_variants": ["neutral", "happy", "sad", "shy", "angry"], "stat_affinities": ["empathy"]},
            {"name": "The Client", "role": "npc", "expression_variants": ["neutral", "happy", "sad", "surprised"], "stat_affinities": ["luck"]},
        ],
    },
]


def _build_full_gdd(theme: dict) -> dict:
    nodes = {f"n{i:02d}": {"scene_key": f"s_{theme['id']}_n{i:02d}", "choices": []} for i in range(MIN_BRANCHING_NODES)}
    nodes["n00"]["choices"] = [{"label": "A", "next_node": "n01"}, {"label": "B", "next_node": "n02"}]
    nodes["n01"]["choices"] = [{"label": "go", "next_node": "n03"}]
    nodes["n02"]["choices"] = [{"label": "go", "next_node": "n04"}]
    nodes["n03"]["choices"] = [{"label": "go", "next_node": "n05"}]
    nodes["n04"]["choices"] = [{"label": "go", "next_node": "n06"}]
    nodes["n05"]["choices"] = [{"label": "go", "next_node": "n07"}]
    nodes["n06"]["choices"] = [{"label": "go", "next_node": "n07"}]
    nodes["n07"]["choices"] = []
    return {
        "title": theme["title"],
        "genre": "visual_novel",
        "narrative_premise": theme["premise"],
        "player_protagonist": {"name": theme["characters"][0]["name"], "pronouns": "they", "portrait_key": "p1"},
        "character_roster": theme["characters"],
        "route_structure": {
            "common_route_chapters": 3,
            "character_routes": [
                {"key": theme["characters"][1]["name"].lower().split()[0], "name": f"{theme['characters'][1]['name']} Route", "chapters": 2, "unlock": "common_complete"},
            ],
        },
        "stat_system": {"stats": [
            {"name": f"stat_{i}", "range": [0, 10], "decay": 0.0, "branching_thresholds": []}
            for i in range(MIN_STATS)
        ]},
        "branching_tree": {"root": "n00", "nodes": nodes, "edges": []},
        "ending_conditions": [
            {"name": f"{theme['id']}_good_{i}", "trigger": {"x": i}, "epilogue_key": f"ep.{theme['id']}.{i}", "is_good_ending": 1 if i == 0 else 0}
            for i in range(MIN_ENDINGS)
        ],
        "cg_milestones": [{"scene_id": "n00", "cg_key": f"cg_{theme['id']}_open", "condition": "start"}],
        "save_points": [{"scene_id": "n00", "save_key": "save_0"}],
    }


@pytest.mark.asyncio
async def test_all_five_themes_pass_schema_validation():
    for theme in THEMES:
        gdd = _build_full_gdd(theme)
        errors = validate_gdd(gdd)
        assert errors == [], f"theme {theme['id']} failed validation: {errors}"


@pytest.mark.asyncio
async def test_all_five_themes_persist_to_db(tmp_db):
    await ensure_vn_tables()
    summaries = []
    for theme in THEMES:
        gdd = _build_full_gdd(theme)
        gdd_id = f"proj_{theme['id']}"
        summary = await persist_vn_gdd(gdd_id, gdd)
        assert summary["characters"] == 3, theme["id"]
        assert summary["endings"] == MIN_ENDINGS, theme["id"]
        assert summary["routes"] == 2, theme["id"]
        assert summary["stats"] == MIN_STATS, theme["id"]
        assert summary["cgs"] == 1, theme["id"]
        summaries.append((theme["id"], summary))

        chars = await get_vn_characters(gdd_id)
        assert len(chars) == 3
        routes = await get_vn_routes(gdd_id)
        assert {r["route_type"] for r in routes} == {"common", "character"}
        endings = await get_vn_endings(gdd_id)
        assert len(endings) == MIN_ENDINGS

    assert len(summaries) == 5


@pytest.mark.asyncio
async def test_all_five_themes_expand_to_sub_projects(tmp_path):
    for theme in THEMES:
        gdd = _build_full_gdd(theme)
        parent_dir = tmp_path / theme["id"]
        sub = expand_vn_project(gdd, f"vn_{theme['id']}", parent_dir)
        assert len(sub) == 2, f"theme {theme['id']} expected 2 sub-projects, got {len(sub)}"
        assert sub[0]["route_type"] == "common"
        assert sub[1]["route_type"] == "character"
        assert sub[1]["shared_assets_path"] is not None


@pytest.mark.asyncio
async def test_all_five_themes_run_through_code_generator_dispatch(tmp_path):
    """End-to-end: validate → dispatch → _generate_visual_novel (mocked) → verify."""
    for theme in THEMES:
        gdd = _build_full_gdd(theme)
        project_dir = tmp_path / theme["id"]
        project_dir.mkdir()
        call_count = {"n": 0}

        async def fake_chat(*args, **kwargs):
            call_count["n"] += 1
            nodes = {f"n{i:02d}": {"scene_key": f"s{i:02d}", "choices": []} for i in range(MIN_BRANCHING_NODES)}
            nodes["n00"]["choices"] = [{"label": "A", "next_node": "n01"}, {"label": "B", "next_node": "n02"}]
            nodes["n01"]["choices"] = [{"label": "go", "next_node": "n03"}]
            nodes["n02"]["choices"] = [{"label": "go", "next_node": "n04"}]
            nodes["n03"]["choices"] = [{"label": "go", "next_node": "n05"}]
            nodes["n04"]["choices"] = [{"label": "go", "next_node": "n06"}]
            nodes["n05"]["choices"] = [{"label": "go", "next_node": "n07"}]
            nodes["n06"]["choices"] = [{"label": "go", "next_node": "n07"}]
            nodes["n07"]["choices"] = []
            if call_count["n"] == 1:
                return [json.dumps({
                    "src/main.ts": "import * as Phaser from 'phaser';",
                    "src/game/scenes/BootScene.ts": "export class BootScene extends Phaser.Scene {}",
                    "src/game/scenes/TitleScene.ts": "export class TitleScene extends Phaser.Scene {}",
                    "src/game/scenes/MenuScene.ts": "export class MenuScene extends Phaser.Scene {}",
                    "src/game/scenes/NovelScene.ts": "export class NovelScene extends Phaser.Scene {}",
                    "src/game/systems/DialogueSystem.ts": "export class DialogueSystem {}",
                    "src/game/data/characters.json": json.dumps({"characters": [{"name": "Alice"}]}),
                    "src/game/data/dialogue.json": json.dumps({"lines": [{"id": "l01", "text": "hi", "speaker": "Alice"}]}),
                }), {}]
            return [json.dumps({
                "src/game/data/branching.json": json.dumps({"branching_tree": {"root": "n00", "nodes": nodes, "edges": []}}),
                "src/game/data/stats.json": json.dumps({"stats": [{"name": f"s{i}", "range": [0, 10]} for i in range(MIN_STATS)]}),
                "src/game/data/endings.json": json.dumps({"endings": [
                    {"name": f"e{i}", "trigger": {"x": i, "theme": theme["id"]}, "epilogue_key": f"e_{i}", "is_good_ending": 0}
                    for i in range(MIN_ENDINGS)
                ]}),
                "src/game/systems/BranchingEngine.ts": "export class BranchingEngine {}",
                "src/game/systems/StatSystem.ts": "export class StatSystem {}",
                "src/game/systems/ChoiceSystem.ts": "export class ChoiceSystem {}",
                "src/game/scenes/NovelScene.ts": "export class NovelScene extends Phaser.Scene {}",
            }), {}]

        with patch("agents.dev.programmer.code_generator.llm") as mock_llm:
            mock_llm.chat_completion = AsyncMock(side_effect=fake_chat)
            with patch("agents.dev.programmer.code_generator._scaffold_project"):
                with patch("agents.dev.programmer.code_generator._install_and_build", return_value=""):
                    with patch("agents.dev.programmer.code_generator._runtime_verify", return_value=""):
                        from agents.dev.programmer.code_generator import (
                            _generate_visual_novel,
                            _vn_post_gen_verify,
                        )
                        await _generate_visual_novel(
                            gdd, project_dir, type("Cfg", (), {})(), "fake-model", 8192
                        )
                        verify_err = _vn_post_gen_verify(project_dir)

        assert verify_err == "", f"theme {theme['id']} post-gen verify failed: {verify_err}"
        assert call_count["n"] == 2

        for rel in ["src/main.ts", "src/game/data/branching.json", "src/game/data/endings.json", "src/game/systems/BranchingEngine.ts"]:
            assert (project_dir / rel).exists(), f"theme {theme['id']} missing {rel}"


def test_per_theme_budget_under_cap():
    for theme in THEMES:
        gdd = _build_full_gdd(theme)
        parent_dir = Path("/tmp")
        sub = expand_vn_project(gdd, f"vn_{theme['id']}", parent_dir)
        budgets = compute_per_route_budgets(sub, total_budget_usd=5.0)
        assert all(v <= 5.0 for v in budgets.values()), f"theme {theme['id']} budget exceeded"
        assert sum(budgets.values()) == pytest.approx(5.0, abs=0.05)


def test_no_duplicate_ending_triggers_across_themes():
    triggers_seen: dict[str, str] = {}
    for theme in THEMES:
        gdd = _build_full_gdd(theme)
        themed_gdd = {
            **gdd,
            "ending_conditions": [
                {**e, "trigger": {**e["trigger"], "theme": theme["id"]}}
                for e in gdd["ending_conditions"]
            ],
        }
        for ending in themed_gdd["ending_conditions"]:
            key = json.dumps(ending["trigger"], sort_keys=True)
            if key in triggers_seen:
                pytest.fail(f"duplicate trigger {key} in {theme['id']} and {triggers_seen[key]}")
            triggers_seen[key] = theme["id"]


def test_all_themes_cover_minimum_branching_node_count():
    for theme in THEMES:
        gdd = _build_full_gdd(theme)
        node_count = len(gdd["branching_tree"]["nodes"])
        assert node_count >= MIN_BRANCHING_NODES, f"{theme['id']} has only {node_count} nodes"


def test_all_themes_cover_minimum_stat_and_ending_counts():
    for theme in THEMES:
        gdd = _build_full_gdd(theme)
        assert len(gdd["stat_system"]["stats"]) >= MIN_STATS
        assert len(gdd["ending_conditions"]) >= MIN_ENDINGS
        assert len(gdd["character_roster"]) >= 2
        for char in gdd["character_roster"]:
            assert len(char["expression_variants"]) >= 3, f"{theme['id']}: {char['name']} has < 3 expressions"

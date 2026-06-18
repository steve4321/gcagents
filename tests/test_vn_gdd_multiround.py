from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from agents.dev.designer.gdd_generator import (
    VN_CHARACTER_ROUTE_PROMPT,
    VN_COMMON_ROUTE_PROMPT,
    VN_ENDINGS_SYSTEM_PROMPT,
    VN_FOUNDATION_SYSTEM_PROMPT,
    _assemble_branching_tree,
    _default_cg_milestones,
    _default_common_route,
    _default_endings,
    _default_save_points,
    _fix_undefined_stats,
    _fix_unreachable_nodes,
    _generate_vn_foundation,
    _generate_vn_gdd_multiround,
    _merge_vn_gdd,
    _repair_vn_gdd,
)
from shared.vn_schema import is_visual_novel, validate_gdd


def _make_foundation() -> dict:
    return {
        "title": "Test VN",
        "genre": "visual-novel",
        "summary": "A test visual novel about friendship and summer.",
        "narrative_premise": "Two friends spend their last summer before graduation.",
        "player_protagonist": {
            "name": "Yuuki",
            "pronouns": "they/them",
            "portrait_key": "yuuki_neutral",
        },
        "character_roster": [
            {
                "name": "Akari",
                "role": "heroine",
                "sprite_set": "characters/akari",
                "expression_variants": ["neutral", "happy", "sad", "surprised", "angry"],
                "personality": "Cheerful and energetic",
                "stat_affinities": ["affection", "courage"],
            },
            {
                "name": "Sora",
                "role": "heroine",
                "sprite_set": "characters/sora",
                "expression_variants": ["neutral", "happy", "sad", "surprised"],
                "personality": "Quiet and thoughtful",
                "stat_affinities": ["affection", "trust"],
            },
        ],
        "stat_system": {
            "stats": [
                {"name": "affection", "range": [0, 10], "decay": 0, "branching_thresholds": []},
                {"name": "courage", "range": [0, 10], "decay": 0, "branching_thresholds": []},
                {"name": "trust", "range": [0, 10], "decay": 0, "branching_thresholds": []},
                {"name": "wisdom", "range": [0, 10], "decay": 0, "branching_thresholds": []},
                {"name": "humor", "range": [0, 10], "decay": 0, "branching_thresholds": []},
            ]
        },
        "art_style": {
            "theme": "anime",
            "color_palette": ["#ff6699", "#66ccff"],
            "reference": "Ghibli-style",
        },
        "audio": {"bgm_mood": "romantic", "sfx_list": ["page_turn"]},
    }


def _make_branching() -> dict:
    nodes = {}
    for i in range(1, 16):
        nid = f"common_{i:02d}"
        choices = []
        if i < 15:
            choices.append({"label": "Next", "next_node": f"common_{i + 1:02d}"})
        if i == 12:
            choices.append({"label": "Go to Akari", "next_node": "route_akari_01"})
            choices.append({"label": "Go to Sora", "next_node": "route_sora_01"})
        nodes[nid] = {"scene_key": f"scene_{i}", "dialogue": [f"d_{i:02d}"], "choices": choices}

    for route in ("akari", "sora"):
        for i in range(1, 11):
            nid = f"route_{route}_{i:02d}"
            choices = []
            if i < 10:
                choices.append({"label": "Next", "next_node": f"route_{route}_{i + 1:02d}"})
            nodes[nid] = {
                "scene_key": f"scene_{route}_{i}",
                "dialogue": [f"d_{route}_{i:02d}"],
                "choices": choices,
            }

    return {
        "route_structure": {
            "common_route_chapters": 3,
            "character_routes": [
                {
                    "key": "akari",
                    "name": "Akari",
                    "chapters": 2,
                    "unlock": "After common chapter 3",
                },
                {"key": "sora", "name": "Sora", "chapters": 2, "unlock": "After common chapter 3"},
            ],
        },
        "branching_tree": {"root": "common_01", "nodes": nodes},
    }


def _make_endings() -> dict:
    return {
        "ending_conditions": [
            {
                "name": "Akari Good End",
                "trigger": {"affection": 8, "courage": 5},
                "epilogue_key": "ep_akari_good",
                "is_good_ending": 1,
            },
            {
                "name": "Akari Normal End",
                "trigger": {"affection": 5},
                "epilogue_key": "ep_akari_normal",
                "is_good_ending": 0,
            },
            {
                "name": "Sora Good End",
                "trigger": {"trust": 8, "wisdom": 5},
                "epilogue_key": "ep_sora_good",
                "is_good_ending": 1,
            },
            {
                "name": "Bad End",
                "trigger": {"affection": 2, "courage": 2},
                "epilogue_key": "ep_bad",
                "is_good_ending": 0,
            },
        ],
        "cg_milestones": [
            {
                "scene_id": "common_05",
                "cg_key": "cg_summer_festival",
                "condition": "Reached festival scene",
            },
            {
                "scene_id": "common_10",
                "cg_key": "cg_school_rooftop",
                "condition": "Rooftop conversation",
            },
            {
                "scene_id": "route_akari_05",
                "cg_key": "cg_akari_confession",
                "condition": "Akari confesses",
            },
        ],
        "save_points": [
            {"scene_id": "common_01", "save_key": "save_prologue"},
            {"scene_id": "common_08", "save_key": "save_midway"},
            {"scene_id": "common_15", "save_key": "save_route_split"},
        ],
    }


class TestVNPrompts:
    def test_foundation_prompt_specifies_required_fields(self):
        for field in (
            "title",
            "genre",
            "narrative_premise",
            "player_protagonist",
            "character_roster",
            "stat_system",
        ):
            assert field in VN_FOUNDATION_SYSTEM_PROMPT, f"Foundation prompt missing: {field}"

    def test_common_route_prompt_specifies_15_nodes(self):
        assert "15" in VN_COMMON_ROUTE_PROMPT
        assert "EXACTLY" in VN_COMMON_ROUTE_PROMPT

    def test_character_route_prompt_specifies_11_nodes(self):
        assert "11" in VN_CHARACTER_ROUTE_PROMPT
        assert "EXACTLY" in VN_CHARACTER_ROUTE_PROMPT

    def test_endings_prompt_requires_unique_triggers(self):
        assert "unique" in VN_ENDINGS_SYSTEM_PROMPT.lower()
        assert "4" in VN_ENDINGS_SYSTEM_PROMPT

    def test_all_prompts_say_no_markdown(self):
        for prompt in (
            VN_FOUNDATION_SYSTEM_PROMPT,
            VN_COMMON_ROUTE_PROMPT,
            VN_CHARACTER_ROUTE_PROMPT,
            VN_ENDINGS_SYSTEM_PROMPT,
        ):
            assert "no markdown" in prompt.lower()

    def test_all_prompts_forbid_yaml(self):
        for prompt in (
            VN_FOUNDATION_SYSTEM_PROMPT,
            VN_COMMON_ROUTE_PROMPT,
            VN_CHARACTER_ROUTE_PROMPT,
            VN_ENDINGS_SYSTEM_PROMPT,
        ):
            assert "No YAML" in prompt or "no YAML" in prompt.lower() or "YAML" in prompt


class TestMergeVNGdd:
    def test_merge_includes_all_round_outputs(self):
        gdd = _merge_vn_gdd(_make_foundation(), _make_branching(), _make_endings())
        assert gdd["title"] == "Test VN"
        assert "branching_tree" in gdd
        assert "ending_conditions" in gdd
        assert "cg_milestones" in gdd
        assert "save_points" in gdd
        assert "character_roster" in gdd
        assert "stat_system" in gdd

    def test_merge_adds_schema_version(self):
        gdd = _merge_vn_gdd({}, {}, {})
        assert gdd["vn_schema_version"] == "1.0"

    def test_merge_fills_required_placeholders(self):
        gdd = _merge_vn_gdd(_make_foundation(), _make_branching(), _make_endings())
        for field in (
            "core_loop",
            "progression",
            "win_condition",
            "monetization",
            "mechanics",
            "scenes",
            "entities",
        ):
            assert field in gdd, f"Missing placeholder field: {field}"

    def test_merged_gdd_passes_validation(self):
        gdd = _merge_vn_gdd(_make_foundation(), _make_branching(), _make_endings())
        errors = validate_gdd(gdd)
        assert errors == [], f"Validation errors: {errors}"

    def test_merged_gdd_is_recognized_as_visual_novel(self):
        gdd = _merge_vn_gdd(_make_foundation(), _make_branching(), _make_endings())
        assert is_visual_novel(gdd)


class TestFixUnreachableNodes:
    def test_connects_orphan_nodes_to_root(self):
        branching = _make_branching()
        del branching["branching_tree"]["nodes"]["common_01"]["choices"][0]
        gdd = _merge_vn_gdd(_make_foundation(), branching, _make_endings())
        gdd = _fix_unreachable_nodes(gdd)

        nodes = gdd["branching_tree"]["nodes"]
        visited = set()
        queue = [gdd["branching_tree"]["root"]]
        while queue:
            cur = queue.pop(0)
            if cur in visited:
                continue
            visited.add(cur)
            for choice in nodes[cur].get("choices", []):
                if isinstance(choice, dict) and isinstance(choice.get("next_node"), str):
                    queue.append(choice["next_node"])
        assert len(visited) == len(nodes), f"Still unreachable: {set(nodes.keys()) - visited}"

    def test_handles_missing_root(self):
        branching = _make_branching()
        del branching["branching_tree"]["root"]
        gdd = _merge_vn_gdd(_make_foundation(), branching, _make_endings())
        gdd = _fix_unreachable_nodes(gdd)
        assert gdd["branching_tree"]["root"] in gdd["branching_tree"]["nodes"]


class TestFixUndefinedStats:
    def test_strips_stat_prefix_in_endings(self):
        gdd = _merge_vn_gdd(
            _make_foundation(),
            _make_branching(),
            {
                "ending_conditions": [
                    {
                        "name": "E1",
                        "trigger": {"stat:affection": 8},
                        "epilogue_key": "e1",
                        "is_good_ending": 1,
                    },
                    {
                        "name": "E2",
                        "trigger": {"stat:affection": 5},
                        "epilogue_key": "e2",
                        "is_good_ending": 0,
                    },
                    {
                        "name": "E3",
                        "trigger": {"stat:affection": 3},
                        "epilogue_key": "e3",
                        "is_good_ending": 0,
                    },
                    {
                        "name": "E4",
                        "trigger": {"stat:affection": 1},
                        "epilogue_key": "e4",
                        "is_good_ending": 0,
                    },
                ],
                "cg_milestones": _make_endings()["cg_milestones"],
                "save_points": _make_endings()["save_points"],
            },
        )
        gdd = _fix_undefined_stats(gdd, _make_foundation())
        for ending in gdd["ending_conditions"]:
            for key in ending["trigger"]:
                assert not key.startswith("stat:"), f"Prefix not stripped: {key}"

    def test_strips_stat_prefix_in_branching(self):
        branching = _make_branching()
        branching["branching_tree"]["nodes"]["common_02"]["choices"] = [
            {"label": "X", "next_node": "common_03", "stat_delta": {"stat:courage": 2}},
        ]
        gdd = _merge_vn_gdd(_make_foundation(), branching, _make_endings())
        gdd = _fix_undefined_stats(gdd, _make_foundation())
        for node in gdd["branching_tree"]["nodes"].values():
            for choice in node.get("choices", []):
                for key in choice.get("stat_delta", {}):
                    assert not key.startswith("stat:")

    def test_fixes_ending_validation_errors(self):
        gdd = _merge_vn_gdd(
            _make_foundation(),
            _make_branching(),
            {
                "ending_conditions": [
                    {
                        "name": "E1",
                        "trigger": {"stat:affection": 8, "stat:courage": 5},
                        "epilogue_key": "e1",
                        "is_good_ending": 1,
                    },
                    {
                        "name": "E2",
                        "trigger": {"stat:affection": 5},
                        "epilogue_key": "e2",
                        "is_good_ending": 0,
                    },
                    {
                        "name": "E3",
                        "trigger": {"stat:affection": 2},
                        "epilogue_key": "e3",
                        "is_good_ending": 0,
                    },
                    {
                        "name": "E4",
                        "trigger": {"stat:affection": 1},
                        "epilogue_key": "e4",
                        "is_good_ending": 0,
                    },
                ],
                "cg_milestones": _make_endings()["cg_milestones"],
                "save_points": _make_endings()["save_points"],
            },
        )
        errors_before = validate_gdd(gdd)
        gdd = _fix_undefined_stats(gdd, _make_foundation())
        errors_after = validate_gdd(gdd)
        stat_errors_before = [e for e in errors_before if "undefined stats" in e]
        stat_errors_after = [e for e in errors_after if "undefined stats" in e]
        assert len(stat_errors_before) > 0
        assert len(stat_errors_after) == 0


class TestDefaults:
    def test_default_endings_uses_first_stat(self):
        foundation = _make_foundation()
        endings = _default_endings(foundation)
        assert len(endings) >= 4
        for e in endings:
            assert "name" in e
            assert "trigger" in e
            assert "is_good_ending" in e

    def test_default_cg_milestones_from_common_nodes(self):
        branching = _make_branching()
        cgs = _default_cg_milestones(branching)
        assert len(cgs) >= 3
        for cg in cgs:
            assert "scene_id" in cg
            assert "cg_key" in cg

    def test_default_save_points_at_boundaries(self):
        branching = _make_branching()
        saves = _default_save_points(branching)
        assert len(saves) >= 3
        assert saves[0]["scene_id"] == "common_01"


class TestRepairVNGdd:
    def test_repair_passes_validation_on_valid_gdd(self):
        gdd = _merge_vn_gdd(_make_foundation(), _make_branching(), _make_endings())
        gdd = _repair_vn_gdd(gdd, _make_foundation())
        assert validate_gdd(gdd) == []

    def test_repair_fixes_stat_prefix(self):
        gdd = _merge_vn_gdd(
            _make_foundation(),
            _make_branching(),
            {
                "ending_conditions": [
                    {
                        "name": "E1",
                        "trigger": {"stat:affection": 8},
                        "epilogue_key": "e1",
                        "is_good_ending": 1,
                    },
                    {
                        "name": "E2",
                        "trigger": {"stat:affection": 5},
                        "epilogue_key": "e2",
                        "is_good_ending": 0,
                    },
                    {
                        "name": "E3",
                        "trigger": {"stat:affection": 3},
                        "epilogue_key": "e3",
                        "is_good_ending": 0,
                    },
                    {
                        "name": "E4",
                        "trigger": {"stat:affection": 1},
                        "epilogue_key": "e4",
                        "is_good_ending": 0,
                    },
                ],
                "cg_milestones": _make_endings()["cg_milestones"],
                "save_points": _make_endings()["save_points"],
            },
        )
        gdd = _repair_vn_gdd(gdd, _make_foundation())
        stat_errors = [e for e in validate_gdd(gdd) if "undefined stats" in e]
        assert stat_errors == []


class TestMultiroundOrchestrator:
    @pytest.mark.asyncio
    async def test_dispatches_to_multiround_for_visual_novel_genre(self):
        from shared.models import GameProposal

        proposal = GameProposal(
            name="Summer Romance",
            genre="visual-novel",
            description="A small-scale school romance VN",
            target_platforms=["itch.io"],
            differentiation="Multiple routes",
            reference_games=["Doki Doki"],
            market_opportunity_score=0.7,
            estimated_dev_hours=8,
        )

        foundation = _make_foundation()
        common_route = {
            "route_structure": _make_branching()["route_structure"],
            "common_route_nodes": {
                k: v
                for k, v in _make_branching()["branching_tree"]["nodes"].items()
                if k.startswith("common_")
            },
        }
        character_routes = []
        for cr in common_route["route_structure"]["character_routes"]:
            key = cr["key"]
            route_nodes = {
                k: v
                for k, v in _make_branching()["branching_tree"]["nodes"].items()
                if k.startswith(f"route_{key}_") or k.startswith(f"ending_{key}_")
            }
            character_routes.append({"route_key": key, "route_nodes": route_nodes})
        endings = _make_endings()

        with (
            patch(
                "agents.dev.designer.gdd_generator._generate_vn_foundation",
                AsyncMock(return_value=foundation),
            ) as m1,
            patch(
                "agents.dev.designer.gdd_generator._generate_vn_common_route",
                AsyncMock(return_value=common_route),
            ) as m2,
            patch(
                "agents.dev.designer.gdd_generator._generate_vn_character_routes",
                AsyncMock(return_value=character_routes),
            ) as m3,
            patch(
                "agents.dev.designer.gdd_generator._generate_vn_endings",
                AsyncMock(return_value=endings),
            ) as m4,
        ):
            from shared.config import load_config

            gdd = await _generate_vn_gdd_multiround(proposal, load_config())

        m1.assert_called_once()
        m2.assert_called_once()
        m3.assert_called_once()
        m4.assert_called_once()
        assert validate_gdd(gdd) == []

    @pytest.mark.asyncio
    async def test_falls_back_to_defaults_when_endings_round_fails(self):
        from shared.models import GameProposal

        proposal = GameProposal(
            name="Test VN",
            genre="visual-novel",
            description="Test",
            target_platforms=["itch.io"],
            differentiation="",
            reference_games=[],
            market_opportunity_score=0.5,
            estimated_dev_hours=8,
        )

        with (
            patch(
                "agents.dev.designer.gdd_generator._generate_vn_foundation",
                AsyncMock(return_value=_make_foundation()),
            ),
            patch(
                "agents.dev.designer.gdd_generator._generate_vn_common_route",
                AsyncMock(
                    return_value={
                        "route_structure": _make_branching()["route_structure"],
                        "common_route_nodes": {
                            k: v
                            for k, v in _make_branching()["branching_tree"]["nodes"].items()
                            if k.startswith("common_")
                        },
                    }
                ),
            ),
            patch(
                "agents.dev.designer.gdd_generator._generate_vn_character_routes",
                AsyncMock(return_value=[]),
            ),
            patch(
                "agents.dev.designer.gdd_generator._generate_vn_endings", AsyncMock(return_value={})
            ),
        ):
            from shared.config import load_config

            gdd = await _generate_vn_gdd_multiround(proposal, load_config())

        assert len(gdd.get("ending_conditions", [])) >= 4
        assert len(gdd.get("cg_milestones", [])) >= 3
        assert len(gdd.get("save_points", [])) >= 3

    @pytest.mark.asyncio
    async def test_dispatches_to_generic_for_non_vn_genre(self):
        from shared.config import load_config
        from shared.models import GameProposal

        proposal = GameProposal(
            name="Test Puzzle",
            genre="puzzle",
            description="A puzzle game",
            target_platforms=["itch.io"],
            differentiation="",
            reference_games=[],
            market_opportunity_score=0.5,
            estimated_dev_hours=8,
        )

        with patch(
            "agents.dev.designer.gdd_generator._generate_generic_gdd",
            AsyncMock(return_value={"title": "Test Puzzle", "genre": "puzzle"}),
        ) as mock_generic:
            from agents.dev.designer.gdd_generator import generate_gdd

            gdd = await generate_gdd(proposal, load_config())

        mock_generic.assert_called_once()
        assert gdd["title"] == "Test Puzzle"


class TestRoundParsers:
    @pytest.mark.asyncio
    async def test_foundation_round_returns_empty_on_invalid_json(self):
        from shared.config import load_config
        from shared.constants import DEFAULT_ANALYSIS_MODEL
        from shared.models import GameProposal

        proposal = GameProposal(
            name="X",
            genre="visual-novel",
            description="x",
            target_platforms=["itch.io"],
            differentiation="",
            reference_games=[],
            market_opportunity_score=0.5,
            estimated_dev_hours=8,
        )
        with patch("agents.dev.designer.gdd_generator.llm") as mock_llm:
            mock_llm.chat_completion = AsyncMock(return_value=("not json at all", None))
            result = await _generate_vn_foundation(proposal, DEFAULT_ANALYSIS_MODEL, load_config())
        assert result == {}

    @pytest.mark.asyncio
    async def test_foundation_round_returns_empty_on_missing_fields(self):
        from shared.config import load_config
        from shared.constants import DEFAULT_ANALYSIS_MODEL
        from shared.models import GameProposal

        proposal = GameProposal(
            name="X",
            genre="visual-novel",
            description="x",
            target_platforms=["itch.io"],
            differentiation="",
            reference_games=[],
            market_opportunity_score=0.5,
            estimated_dev_hours=8,
        )
        with patch("agents.dev.designer.gdd_generator.llm") as mock_llm:
            mock_llm.chat_completion = AsyncMock(return_value=(json.dumps({"title": "x"}), None))
            result = await _generate_vn_foundation(proposal, DEFAULT_ANALYSIS_MODEL, load_config())
        assert result == {}

    @pytest.mark.asyncio
    async def test_foundation_round_parses_with_meta_commentary(self):
        from shared.config import load_config
        from shared.constants import DEFAULT_ANALYSIS_MODEL
        from shared.models import GameProposal

        proposal = GameProposal(
            name="X",
            genre="visual-novel",
            description="x",
            target_platforms=["itch.io"],
            differentiation="",
            reference_games=[],
            market_opportunity_score=0.5,
            estimated_dev_hours=8,
        )
        foundation = _make_foundation()
        dirty_json = (
            f"Let me design this game.\n\n{json.dumps(foundation)}\n\nThis should work well."
        )
        with patch("agents.dev.designer.gdd_generator.llm") as mock_llm:
            mock_llm.chat_completion = AsyncMock(return_value=(dirty_json, None))
            result = await _generate_vn_foundation(proposal, DEFAULT_ANALYSIS_MODEL, load_config())
        assert result.get("title") == foundation["title"]
        assert len(result.get("character_roster", [])) == 2


class TestAssembleBranchingTree:
    def test_combines_common_and_character_routes(self):
        foundation = _make_foundation()
        common_route = {
            "route_structure": {
                "common_route_chapters": 3,
                "character_routes": [
                    {"key": "akari", "name": "Akari", "chapters": 2, "unlock": "After common 3"},
                    {"key": "sora", "name": "Sora", "chapters": 2, "unlock": "After common 3"},
                ],
            },
            "common_route_nodes": {
                f"common_{i:02d}": {"scene_key": f"sc_{i}", "dialogue": [f"d_{i}"], "choices": []}
                for i in range(1, 16)
            },
        }
        character_routes = [
            {
                "route_key": "akari",
                "route_nodes": {
                    f"route_akari_{i:02d}": {
                        "scene_key": f"sc_a_{i}",
                        "dialogue": [f"d_a_{i}"],
                        "choices": [],
                    }
                    for i in range(1, 9)
                },
            },
        ]

        branching = _assemble_branching_tree(foundation, common_route, character_routes)
        nodes = branching["branching_tree"]["nodes"]
        assert len(nodes) == 30
        assert "common_01" in nodes
        assert "common_15" in nodes
        assert "route_akari_01" in nodes
        assert "route_akari_08" in nodes
        assert "route_sora_01" not in nodes
        assert branching["branching_tree"]["root"] == "common_01"
        assert len(branching["route_structure"]["character_routes"]) == 2
        filler_nodes = [k for k, v in nodes.items() if isinstance(v, dict) and v.get("filler")]
        assert len(filler_nodes) == 7

    def test_defaults_to_first_heroine_when_no_routes(self):
        foundation = _make_foundation()
        common_route = {
            "route_structure": {"common_route_chapters": 3, "character_routes": []},
            "common_route_nodes": {
                f"common_{i:02d}": {"scene_key": f"sc_{i}", "dialogue": [f"d_{i}"], "choices": []}
                for i in range(1, 16)
            },
        }
        branching = _assemble_branching_tree(foundation, common_route, [])
        routes = branching["route_structure"]["character_routes"]
        assert len(routes) >= 1
        assert all("key" in r for r in routes)
        assert all("name" in r for r in routes)


class TestDefaultCommonRoute:
    def test_generates_15_common_nodes(self):
        foundation = _make_foundation()
        result = _default_common_route(foundation)
        assert len(result["common_route_nodes"]) == 15
        for i in range(1, 16):
            assert f"common_{i:02d}" in result["common_route_nodes"]

    def test_last_nodes_have_route_choices(self):
        foundation = _make_foundation()
        result = _default_common_route(foundation)
        char_routes = result["route_structure"]["character_routes"]
        assert len(char_routes) >= 1
        assert len(result["common_route_nodes"]["common_13"]["choices"]) >= 1
        assert any(
            "route_" in choice.get("next_node", "")
            for choice in result["common_route_nodes"]["common_13"]["choices"]
        )

"""Tests for shared/vn_schema.py — hybrid Visual Novel GDD validation."""

from __future__ import annotations

import pytest

from shared.vn_schema import (
    MIN_BRANCHING_NODES,
    MIN_CHARACTERS,
    MIN_ENDINGS,
    MIN_EXPRESSIONS_PER_CHARACTER,
    MIN_STATS,
    SCHEMA_VERSION,
    is_visual_novel,
    validate_branching_tree,
    validate_cg_milestones,
    validate_character_roster,
    validate_ending_conditions,
    validate_gdd,
    validate_stat_system,
)


def _make_character(name: str = "Alice", exprs: list[str] | None = None) -> dict:
    return {
        "name": name,
        "role": "heroine",
        "sprite_set": f"characters/{name.lower()}",
        "expression_variants": exprs or ["neutral", "happy", "sad", "surprised", "angry"],
        "personality": "cheerful",
        "stat_affinities": ["empathy", "wit"],
    }


def _make_stat(name: str = "empathy", lo: float = 0, hi: float = 10) -> dict:
    return {"name": name, "range": [lo, hi], "decay": 0.0, "branching_thresholds": []}


def _make_ending(name: str = "good_ending", trigger: dict | None = None) -> dict:
    return {
        "name": name,
        "trigger": trigger or {"stat:empathy": {">=": 5}},
        "epilogue_key": f"epilogue.{name}",
        "is_good_ending": 1,
    }


def _make_branching_node(node_id: str, scene_key: str | None = None, choices: list | None = None) -> dict:
    return {
        "scene_key": scene_key or f"scene_{node_id}",
        "dialogue": [],
        "choices": choices or [],
    }


def _valid_vn_gdd() -> dict:
    nodes = {
        f"n{i:02d}": _make_branching_node(f"n{i:02d}")
        for i in range(MIN_BRANCHING_NODES)
    }
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
        "narrative_premise": "A high school mystery in a coastal town.",
        "player_protagonist": {"name": "Yu", "pronouns": "they/them", "portrait_key": "yu_neutral"},
        "character_roster": [_make_character("Alice"), _make_character("Bob")],
        "route_structure": {
            "common_route_chapters": 3,
            "character_routes": [{"key": "alice", "name": "Alice Route", "chapters": 2, "unlock": "common_complete"}],
        },
        "stat_system": {
            "stats": [
                _make_stat("empathy", 0, 10),
                _make_stat("wit", 0, 10),
                _make_stat("courage", 0, 10),
                _make_stat("patience", 0, 10),
                _make_stat("luck", 0, 10),
            ]
        },
        "branching_tree": {"root": "n00", "nodes": nodes, "edges": []},
        "ending_conditions": [
            _make_ending("good_a", {"stat:empathy": {">=": 7}}),
            _make_ending("normal", {"stat:empathy": {">=": 3}}),
            _make_ending("bad", {"stat:empathy": {"<": 3}}),
        ],
        "cg_milestones": [{"scene_id": "n05", "cg_key": "cg_alice_smile", "condition": "choice_A"}],
        "save_points": [{"scene_id": "n00", "save_key": "save_0"}],
    }


def test_is_visual_novel_true():
    gdd = _valid_vn_gdd()
    assert is_visual_novel(gdd) is True


def test_is_visual_novel_false_no_premise():
    gdd = _valid_vn_gdd()
    gdd.pop("narrative_premise")
    assert is_visual_novel(gdd) is False


def test_is_visual_novel_false_no_tree():
    gdd = _valid_vn_gdd()
    gdd.pop("branching_tree")
    assert is_visual_novel(gdd) is False


def test_is_visual_novel_false_non_dict():
    assert is_visual_novel({}) is False
    assert is_visual_novel(None) is False  # type: ignore[arg-type]
    assert is_visual_novel("not a dict") is False  # type: ignore[arg-type]


def test_is_visual_novel_false_empty_premise():
    gdd = _valid_vn_gdd()
    gdd["narrative_premise"] = "   "
    assert is_visual_novel(gdd) is False


def test_validate_gdd_happy_path():
    gdd = _valid_vn_gdd()
    errors = validate_gdd(gdd)
    assert errors == []
    assert gdd["vn_schema_version"] == SCHEMA_VERSION


def test_validate_gdd_non_vn_is_noop():
    assert validate_gdd({}) == []
    assert validate_gdd({"title": "Generic", "mechanics": []}) == []


def test_validate_gdd_missing_required_fields():
    gdd: dict = {}
    gdd["narrative_premise"] = "test"
    gdd["branching_tree"] = {"root": "n00", "nodes": {}}
    errors = validate_gdd(gdd)
    expected_missing = {"player_protagonist", "character_roster", "route_structure",
                        "stat_system", "ending_conditions", "cg_milestones", "save_points"}
    for field in expected_missing:
        assert any(field in e for e in errors), f"Expected error mentioning missing field {field!r}, got {errors}"


def test_validate_character_roster_empty():
    errors = validate_character_roster([])
    assert any(f">= {MIN_CHARACTERS}" in e for e in errors)


def test_validate_character_roster_missing_expressions():
    char = _make_character(exprs=["happy"])
    errors = validate_character_roster([char])
    assert any("expression_variants" in e and "Alice" in e for e in errors)


def test_validate_character_roster_valid():
    chars = [_make_character("Alice"), _make_character("Bob"), _make_character("Carol")]
    assert validate_character_roster(chars) == []


def test_validate_stat_system_missing():
    errors = validate_stat_system({})
    assert any("stats" in e for e in errors)


def test_validate_stat_system_too_few():
    stats = [_make_stat(f"s{i}") for i in range(MIN_STATS - 1)]
    errors = validate_stat_system({"stats": stats})
    assert any(f">= {MIN_STATS}" in e for e in errors)


def test_validate_stat_system_invalid_range():
    stat = _make_stat("broken", 10, 0)
    errors = validate_stat_system({"stats": [stat]})
    assert any("range" in e and "min must be" in e for e in errors)


def test_validate_stat_system_valid():
    stats = [_make_stat(f"s{i}") for i in range(MIN_STATS + 2)]
    assert validate_stat_system({"stats": stats}) == []


def test_validate_branching_tree_missing_root():
    errors = validate_branching_tree({"nodes": {}})
    assert any("root" in e for e in errors)


def test_validate_branching_tree_too_few_nodes():
    nodes = {f"n{i:02d}": _make_branching_node(f"n{i:02d}") for i in range(MIN_BRANCHING_NODES - 1)}
    errors = validate_branching_tree({"root": "n00", "nodes": nodes})
    assert any(f">= {MIN_BRANCHING_NODES}" in e for e in errors)


def test_validate_branching_tree_unreachable_node():
    nodes = {f"n{i:02d}": _make_branching_node(f"n{i:02d}") for i in range(MIN_BRANCHING_NODES)}
    nodes["n00"]["choices"] = [{"label": "A", "next_node": "n01"}]
    errors = validate_branching_tree({"root": "n00", "nodes": nodes})
    assert any("unreachable" in e for e in errors)


def test_validate_branching_tree_orphan_root():
    nodes = {f"n{i:02d}": _make_branching_node(f"n{i:02d}") for i in range(MIN_BRANCHING_NODES)}
    nodes["n00"]["choices"] = [{"label": "A", "next_node": "n01"}]
    errors = validate_branching_tree({"root": "missing", "nodes": nodes})
    assert any("not in nodes" in e for e in errors)


def test_validate_branching_tree_missing_scene_key():
    nodes = {f"n{i:02d}": _make_branching_node(f"n{i:02d}") for i in range(MIN_BRANCHING_NODES)}
    nodes["n00"]["choices"] = [{"label": "A", "next_node": "n01"}]
    nodes["n01"] = {"dialogue": [], "choices": []}
    errors = validate_branching_tree({"root": "n00", "nodes": nodes})
    assert any("scene_key" in e and "n01" in e for e in errors)


def test_validate_branching_tree_valid():
    gdd = _valid_vn_gdd()
    assert validate_branching_tree(gdd["branching_tree"]) == []


def test_validate_ending_conditions_too_few():
    errors = validate_ending_conditions([_make_ending("a")])
    assert any(f">= {MIN_ENDINGS}" in e for e in errors)


def test_validate_ending_conditions_duplicate_triggers():
    a = _make_ending("a", {"stat:empathy": {">=": 5}})
    b = _make_ending("b", {"stat:empathy": {">=": 5}})
    errors = validate_ending_conditions([a, b, _make_ending("c", {"x": 1})])
    assert any("duplicate trigger" in e for e in errors)


def test_validate_ending_conditions_missing_trigger():
    bad = {"name": "x"}
    errors = validate_ending_conditions([bad, _make_ending("a"), _make_ending("b")])
    assert any("trigger" in e for e in errors)


def test_validate_ending_conditions_valid():
    gdd = _valid_vn_gdd()
    assert validate_ending_conditions(gdd["ending_conditions"]) == []


def test_validate_cg_milestones_empty():
    errors = validate_cg_milestones([])
    assert any("cg_milestones" in e for e in errors)


def test_validate_cg_milestones_missing_fields():
    bad = {"scene_id": "s1"}
    errors = validate_cg_milestones([bad])
    assert any("cg_key" in e for e in errors)


def test_validate_cg_milestones_valid():
    gdd = _valid_vn_gdd()
    assert validate_cg_milestones(gdd["cg_milestones"]) == []


def test_validate_gdd_full_integration_errors_are_sorted():
    gdd = _valid_vn_gdd()
    gdd["character_roster"] = []
    gdd["stat_system"]["stats"] = []
    gdd["ending_conditions"] = []
    errors = validate_gdd(gdd)
    assert errors == sorted(errors)
    assert len(errors) >= 3


def test_validate_gdd_stamps_schema_version():
    gdd = _valid_vn_gdd()
    gdd.pop("vn_schema_version", None)
    validate_gdd(gdd)
    assert gdd["vn_schema_version"] == SCHEMA_VERSION


@pytest.mark.parametrize(
    "mutator,error_substring",
    [
        (lambda g: g["character_roster"].clear(), "character_roster"),
        (lambda g: g["stat_system"]["stats"].clear(), "stat_system"),
        (lambda g: g["ending_conditions"].clear(), "ending_conditions"),
        (lambda g: g["branching_tree"]["nodes"].clear(), "branching_tree"),
        (lambda g: g["cg_milestones"].clear(), "cg_milestones"),
    ],
)
def test_validate_gdd_detects_each_violation(mutator, error_substring):
    gdd = _valid_vn_gdd()
    mutator(gdd)
    errors = validate_gdd(gdd)
    assert any(error_substring in e for e in errors), f"expected error containing {error_substring!r}, got {errors}"

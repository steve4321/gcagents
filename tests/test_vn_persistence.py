"""Tests for orchestrator/vn_persistence.py — VN table CRUD and GDD persistence."""

from __future__ import annotations

import json

import pytest

from orchestrator.vn_persistence import (
    ensure_vn_tables,
    get_route_assets,
    get_vn_characters,
    get_vn_endings,
    get_vn_routes,
    get_vn_stats,
    persist_vn_gdd,
    save_route_asset,
    save_vn_cg,
    save_vn_character,
    save_vn_ending,
    save_vn_route,
    save_vn_stat,
    VN_SCHEMA_VERSION,
)


@pytest.mark.asyncio
async def test_ensure_vn_tables_idempotent(tmp_db):
    await ensure_vn_tables()
    await ensure_vn_tables()
    await ensure_vn_tables()


@pytest.mark.asyncio
async def test_save_and_get_vn_route(tmp_db):
    await ensure_vn_tables()
    await save_vn_route(
        project_id="proj-1",
        route_id="proj-1_route_common",
        route_key="common",
        route_type="common",
        chapter_count=3,
    )
    routes = await get_vn_routes("proj-1")
    assert len(routes) == 1
    assert routes[0]["route_key"] == "common"
    assert routes[0]["route_type"] == "common"


@pytest.mark.asyncio
async def test_save_and_get_vn_character_round_trips_json(tmp_db):
    await ensure_vn_tables()
    await save_vn_character(
        project_id="proj-1",
        char_id="proj-1_char_alice",
        name="Alice",
        role="heroine",
        sprite_set_path="characters/alice",
        expression_variants=["neutral", "happy", "sad"],
        stat_affinities=["empathy", "wit"],
        localization_names={"ja": "アリス"},
    )
    chars = await get_vn_characters("proj-1")
    assert len(chars) == 1
    assert chars[0]["name"] == "Alice"
    assert chars[0]["expression_variants"] == ["neutral", "happy", "sad"]
    assert chars[0]["localization_names"] == {"ja": "アリス"}


@pytest.mark.asyncio
async def test_save_and_get_vn_ending_round_trips_json(tmp_db):
    await ensure_vn_tables()
    await save_vn_ending(
        project_id="proj-1",
        ending_id="proj-1_end_good",
        name="good",
        trigger_condition={"stat:empathy": {">=": 5}},
        epilogue_key="epilogue.good",
        is_good_ending=True,
    )
    endings = await get_vn_endings("proj-1")
    assert len(endings) == 1
    assert endings[0]["trigger_condition"] == {"stat:empathy": {">=": 5}}
    assert endings[0]["is_good_ending"] == 1


@pytest.mark.asyncio
async def test_save_and_get_vn_stat(tmp_db):
    await ensure_vn_tables()
    await save_vn_stat(
        project_id="proj-1",
        stat_id="proj-1_stat_empathy",
        stat_name="empathy",
        min_value=0,
        max_value=10,
        decay_per_chapter=0.5,
        branching_thresholds=[{"op": ">=", "value": 7, "route": "alice"}],
    )
    stats = await get_vn_stats("proj-1")
    assert len(stats) == 1
    assert stats[0]["stat_name"] == "empathy"
    assert stats[0]["decay_per_chapter"] == 0.5
    assert stats[0]["branching_thresholds"][0]["route"] == "alice"


@pytest.mark.asyncio
async def test_save_vn_cg(tmp_db):
    await ensure_vn_tables()
    await save_vn_cg(
        project_id="proj-1",
        cg_id="proj-1_cg_alice_smile",
        cg_key="cg_alice_smile",
        unlock_condition={"scene_id": "n05", "condition": "chose_alice"},
    )
    await ensure_vn_tables()


@pytest.mark.asyncio
async def test_save_and_get_route_asset(tmp_db):
    await ensure_vn_tables()
    await save_route_asset(
        project_id="proj-1",
        asset_id="proj-1_asset_alice_neutral",
        asset_type="character",
        asset_key="alice_neutral",
        file_path="/data/games/proj-1/public/assets/characters/alice_neutral.png",
        source_route_id="proj-1_route_common",
    )
    assets = await get_route_assets("proj-1")
    assert len(assets) == 1
    assert assets[0]["asset_key"] == "alice_neutral"


@pytest.mark.asyncio
async def test_persist_vn_gdd_populates_all_tables(tmp_db):
    await ensure_vn_tables()
    gdd = {
        "title": "Test VN",
        "narrative_premise": "A test.",
        "character_roster": [
            {"name": "Alice", "role": "heroine", "sprite_set": "alice",
             "expression_variants": ["neutral", "happy", "sad"]},
            {"name": "Bob", "role": "heroine", "sprite_set": "bob",
             "expression_variants": ["neutral", "happy", "sad"]},
        ],
        "route_structure": {
            "common_route_chapters": 3,
            "character_routes": [
                {"key": "alice", "name": "Alice Route", "chapters": 2, "unlock": "common_complete"},
                {"key": "bob", "name": "Bob Route", "chapters": 2, "unlock": "common_complete"},
            ],
        },
        "stat_system": {"stats": [
            {"name": "empathy", "range": [0, 10]},
            {"name": "wit", "range": [0, 10]},
            {"name": "courage", "range": [0, 10]},
            {"name": "patience", "range": [0, 10]},
            {"name": "luck", "range": [0, 10]},
        ]},
        "ending_conditions": [
            {"name": "good_a", "trigger": {"x": 1}, "epilogue_key": "e.good_a", "is_good_ending": 1},
            {"name": "good_b", "trigger": {"x": 2}, "epilogue_key": "e.good_b", "is_good_ending": 1},
            {"name": "normal", "trigger": {"x": 3}, "epilogue_key": "e.normal", "is_good_ending": 0},
        ],
        "cg_milestones": [
            {"scene_id": "n00", "cg_key": "cg_a", "condition": "x"},
            {"scene_id": "n01", "cg_key": "cg_b", "condition": "y"},
        ],
    }

    summary = await persist_vn_gdd("proj-1", gdd)

    assert summary["characters"] == 2
    assert summary["endings"] == 3
    assert summary["stats"] == 5
    assert summary["cgs"] == 2
    assert summary["routes"] == 3

    chars = await get_vn_characters("proj-1")
    assert {c["name"] for c in chars} == {"Alice", "Bob"}

    routes = await get_vn_routes("proj-1")
    assert len(routes) == 3
    types = {r["route_type"] for r in routes}
    assert types == {"common", "character"}


@pytest.mark.asyncio
async def test_persist_vn_gdd_handles_invalid_entries(tmp_db):
    await ensure_vn_tables()
    gdd = {
        "title": "Edge",
        "narrative_premise": "Edge cases.",
        "character_roster": [
            {"name": "OK", "expression_variants": ["a", "b", "c"]},
            {"role": "no_name"},
            "not a dict",
        ],
        "stat_system": {"stats": [{"name": "x"}, {"range": [0, 10]}, "bad"]},
        "ending_conditions": [{"name": "ok", "trigger": {}, "epilogue_key": "e"},
                              {"trigger": {}, "epilogue_key": "no_name"},
                              "string"],
        "cg_milestones": [{}, {"cg_key": "k"}, "bad"],
        "route_structure": {"common_route_chapters": 1, "character_routes": [
            {"key": "a", "name": "A"},
            {"name": "no_key"},
            "not a dict",
        ]},
    }

    summary = await persist_vn_gdd("proj-edge", gdd)

    assert summary["characters"] == 1
    assert summary["endings"] == 1
    assert summary["stats"] == 1
    assert summary["cgs"] == 1
    assert summary["routes"] == 2
    assert len(summary["skipped"]) >= 4


@pytest.mark.asyncio
async def test_vn_schema_version_constant():
    assert VN_SCHEMA_VERSION == "1.0"

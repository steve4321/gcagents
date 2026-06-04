"""Tests for orchestrator/vn_routes.py — project expansion and shared-assets linking."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from orchestrator.vn_routes import (
    compute_per_route_budgets,
    expand_vn_project,
    link_shared_assets,
)


def _sample_gdd() -> dict:
    return {
        "title": "Coastal Mystery",
        "narrative_premise": "A fog-shrouded town.",
        "route_structure": {
            "common_route_chapters": 3,
            "character_routes": [
                {"key": "alice", "name": "Alice Route", "chapters": 2, "unlock": "common_complete"},
                {"key": "bob", "name": "Bob Route", "chapters": 3, "unlock": "common_complete"},
            ],
        },
    }


def test_expand_vn_project_creates_common_plus_char_routes(tmp_path):
    gdd = _sample_gdd()
    parent_dir = tmp_path / "parent"
    parent_dir.mkdir()
    sub = expand_vn_project(gdd, "vn-1", parent_dir)

    assert len(sub) == 3
    assert sub[0]["route_key"] == "common"
    assert sub[0]["route_type"] == "common"
    assert sub[0]["shared_assets_path"] is None
    assert sub[0]["parent_id"] == "vn-1"
    assert sub[0]["sub_dir"] == parent_dir / "routes" / "common"

    char_keys = {sp["route_key"] for sp in sub[1:]}
    assert char_keys == {"alice", "bob"}
    for sp in sub[1:]:
        assert sp["route_type"] == "character"
        assert sp["shared_assets_path"] is not None
        assert sp["parent_id"] == "vn-1"


def test_expand_vn_project_with_no_character_routes(tmp_path):
    gdd = {"title": "Linear", "narrative_premise": "Story.", "route_structure": {"common_route_chapters": 5}}
    parent_dir = tmp_path / "p"
    parent_dir.mkdir()
    sub = expand_vn_project(gdd, "v", parent_dir)
    assert len(sub) == 1
    assert sub[0]["route_type"] == "common"


def test_expand_vn_project_rejects_non_vn_gdd(tmp_path):
    with pytest.raises(ValueError):
        expand_vn_project({"title": "no premise"}, "x", tmp_path)


def test_link_shared_assets_creates_symlinks(tmp_path):
    common = tmp_path / "common"
    child = tmp_path / "child"
    common_assets = common / "public" / "assets"
    (common_assets / "characters").mkdir(parents=True)
    (common_assets / "characters" / "alice.png").write_bytes(b"x")
    (common_assets / "backgrounds").mkdir(parents=True)
    (common_assets / "bgm").mkdir(parents=True)

    result = link_shared_assets(common, child, asset_subdirs=("characters", "backgrounds", "bgm", "missing_sub"))

    assert result["characters"] == "linked"
    assert result["backgrounds"] == "linked"
    assert result["bgm"] == "linked"
    assert result["missing_sub"] == "missing"
    assert (child / "public" / "assets" / "characters" / "alice.png").exists()


def test_link_shared_assets_returns_missing_when_common_empty(tmp_path):
    common = tmp_path / "common"
    child = tmp_path / "child"
    common.mkdir()

    result = link_shared_assets(common, child, asset_subdirs=("characters", "backgrounds"))
    assert result == {"characters": "missing", "backgrounds": "missing"}


def test_link_shared_assets_does_not_overwrite_existing(tmp_path):
    common = tmp_path / "common"
    child = tmp_path / "child"
    (common / "public" / "assets" / "characters").mkdir(parents=True)
    (common / "public" / "assets" / "characters" / "shared.png").write_bytes(b"common")
    (child / "public" / "assets" / "characters").mkdir(parents=True)
    (child / "public" / "assets" / "characters" / "shared.png").write_bytes(b"child-overrides")

    result = link_shared_assets(common, child)
    assert result["characters"] == "exists"
    assert (child / "public" / "assets" / "characters" / "shared.png").read_bytes() == b"child-overrides"


def test_compute_per_route_budgets_sums_to_total():
    gdd = _sample_gdd()
    parent_dir = Path("/tmp")
    sub = expand_vn_project(gdd, "v", parent_dir)
    budgets = compute_per_route_budgets(sub, total_budget_usd=5.0)
    assert sum(budgets.values()) == pytest.approx(5.0, abs=0.01)
    common_budget = next(b for sp, b in zip(sub, budgets.values()) if sp["route_type"] == "common")
    char_budgets = [b for sp, b in zip(sub, budgets.values()) if sp["route_type"] == "character"]
    assert common_budget == pytest.approx(2.0, abs=0.01)
    for b in char_budgets:
        assert b == pytest.approx(1.5, abs=0.01)


def test_compute_per_route_budgets_no_character_routes():
    sub = [{"project_id": "v__common", "route_type": "common", "route_key": "common"}]
    budgets = compute_per_route_budgets(sub, total_budget_usd=3.0)
    assert budgets == {"v__common": 3.0}


def test_expand_then_link_integration(tmp_path):
    gdd = _sample_gdd()
    parent_dir = tmp_path / "vn-game"
    parent_dir.mkdir()
    sub = expand_vn_project(gdd, "vn-coastal", parent_dir)

    common_route = sub[0]["sub_dir"]
    (common_route / "public" / "assets" / "characters").mkdir(parents=True)
    (common_route / "public" / "assets" / "characters" / "alice.png").write_bytes(b"alice-art")

    for child in sub[1:]:
        result = link_shared_assets(common_route, child["sub_dir"])
        assert result["characters"] == "linked"
        assert (child["sub_dir"] / "public" / "assets" / "characters" / "alice.png").exists()

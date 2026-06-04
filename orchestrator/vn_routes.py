"""VN project expansion: turn 1 GDD into N+1 sub-projects (common + character routes).

Also handles the shared-assets linking that lets character routes reuse
the common route's art/bgm/sfx without copying files.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from loguru import logger


def expand_vn_project(
    gdd: dict,
    parent_project_id: str,
    parent_dir: Path,
) -> list[dict]:
    """Decompose a VN project into 1 common + N character route sub-projects.

    Returns a list of dicts, each describing one sub-project:
        {
            "project_id": str,        # unique id, includes route_key
            "parent_id": str,         # parent project id
            "route_id": str,          # vn_routes row id
            "route_key": str,         # 'common' or character route key
            "route_type": str,        # 'common' or 'character'
            "display_name": str,
            "sub_dir": Path,          # where the route's code lives
            "shared_assets_path": Path | None,  # symlink target (None for common)
        }
    """
    if not gdd.get("narrative_premise"):
        raise ValueError("expand_vn_project requires a VN GDD (narrative_premise)")

    routes_struct = gdd.get("route_structure", {})
    common_chapters = routes_struct.get("common_route_chapters", 1)
    char_routes = routes_struct.get("character_routes", []) or []

    sub_projects: list[dict] = []
    base_id = parent_project_id

    common_id = f"{base_id}__common"
    common_dir = parent_dir / "routes" / "common"
    common_dir.mkdir(parents=True, exist_ok=True)
    sub_projects.append({
        "project_id": common_id,
        "parent_id": parent_project_id,
        "route_id": f"{base_id}_route_common",
        "route_key": "common",
        "route_type": "common",
        "display_name": f"{gdd.get('title', 'VN')} — Common Route",
        "sub_dir": common_dir,
        "shared_assets_path": None,
        "estimated_chapters": int(common_chapters) if isinstance(common_chapters, int) else 1,
    })

    for cr in char_routes:
        if not isinstance(cr, dict) or not cr.get("key"):
            continue
        key = cr["key"]
        child_id = f"{base_id}__{key}"
        child_dir = parent_dir / "routes" / key
        sub_projects.append({
            "project_id": child_id,
            "parent_id": parent_project_id,
            "route_id": f"{base_id}_route_{key}",
            "route_key": key,
            "route_type": "character",
            "display_name": f"{gdd.get('title', 'VN')} — {cr.get('name', key)}",
            "sub_dir": child_dir,
            "shared_assets_path": common_dir / "public" / "assets",
            "estimated_chapters": int(cr.get("chapters", 1)) if isinstance(cr.get("chapters"), int) else 1,
        })

    return sub_projects


def link_shared_assets(
    common_route_dir: Path,
    child_route_dir: Path,
    asset_subdirs: tuple[str, ...] = ("characters", "backgrounds", "cg", "audio"),
) -> dict[str, str]:
    """Symlink shared asset subdirectories from child → common (read-only).

    Returns a mapping of subdir → status ("linked" | "missing" | "failed").
    Skips silently if common dir doesn't exist (returns "missing" — caller
    can decide whether to error or proceed without shared assets).

    Existing files in child's target paths are NEVER overwritten (safety).
    """
    results: dict[str, str] = {}
    common_assets = common_route_dir / "public" / "assets"
    if not common_assets.exists():
        for sub in asset_subdirs:
            results[sub] = "missing"
        return results

    child_assets = child_route_dir / "public" / "assets"
    child_assets.mkdir(parents=True, exist_ok=True)

    for sub in asset_subdirs:
        target = child_assets / sub
        source = common_assets / sub
        if not source.exists():
            results[sub] = "missing"
            continue
        if target.exists() or target.is_symlink():
            results[sub] = "exists"
            continue
        try:
            os.symlink(source.resolve(), target, target_is_directory=True)
            results[sub] = "linked"
        except (OSError, NotImplementedError) as e:
            logger.warning(f"symlink failed for {sub}: {e}; falling back to copy")
            try:
                shutil.copytree(source, target)
                results[sub] = "copied"
            except OSError as copy_err:
                logger.error(f"copy fallback failed for {sub}: {copy_err}")
                results[sub] = "failed"
    return results


def compute_per_route_budgets(
    sub_projects: list[dict],
    total_budget_usd: float = 5.0,
) -> dict[str, float]:
    """Distribute total budget across routes.

    Common route: 40%. Each character route: 60% / N (split equally).
    """
    char_routes = [sp for sp in sub_projects if sp["route_type"] == "character"]
    n = len(char_routes)
    if n == 0:
        return {sp["project_id"]: total_budget_usd for sp in sub_projects}

    common_budget = total_budget_usd * 0.4
    per_char = (total_budget_usd * 0.6) / n
    budgets: dict[str, float] = {}
    for sp in sub_projects:
        if sp["route_type"] == "common":
            budgets[sp["project_id"]] = round(common_budget, 2)
        else:
            budgets[sp["project_id"]] = round(per_char, 2)
    return budgets

"""Persistence layer for Visual Novel multi-route data.

Provides CRUD helpers for the 6 VN tables (``vn_routes``, ``vn_characters``,
``vn_endings``, ``vn_cgs``, ``vn_stats``, ``route_assets``) plus additive
columns on the existing ``projects`` table. All operations are idempotent
and tolerate an empty database.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.persistence import _get_engine


VN_SCHEMA_VERSION = "1.0"


async def ensure_vn_tables() -> None:
    """Create the 6 VN tables and add 4 columns to ``projects`` (idempotent).

    Calls ``orchestrator.persistence.ensure_tables()`` first so the base
    schema (including ``projects``) exists before the column-augmentation
    step runs. Both calls are idempotent.
    """
    from orchestrator.persistence import ensure_tables
    await ensure_tables()
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        await _create_table(db, "vn_routes", """
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            route_key TEXT NOT NULL,
            route_type TEXT NOT NULL,
            parent_route_id TEXT,
            unlock_condition TEXT,
            chapter_count INTEGER DEFAULT 0,
            estimated_playtime_min INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        """)
        await _create_index(db, "vn_routes", "idx_vn_routes_project", "project_id")

        await _create_table(db, "vn_characters", """
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            sprite_set_path TEXT,
            expression_variants TEXT,
            stat_affinities TEXT,
            localization_names TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        """)
        await _create_index(db, "vn_characters", "idx_vn_characters_project", "project_id")

        await _create_table(db, "vn_endings", """
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            name TEXT NOT NULL,
            trigger_condition TEXT NOT NULL,
            epilogue_key TEXT NOT NULL,
            is_good_ending INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        """)
        await _create_index(db, "vn_endings", "idx_vn_endings_project", "project_id")

        await _create_table(db, "vn_cgs", """
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            cg_key TEXT NOT NULL,
            unlock_condition TEXT NOT NULL,
            image_path TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        """)
        await _create_index(db, "vn_cgs", "idx_vn_cgs_project", "project_id")

        await _create_table(db, "vn_stats", """
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            stat_name TEXT NOT NULL,
            min_value INTEGER DEFAULT 0,
            max_value INTEGER DEFAULT 10,
            decay_per_chapter REAL DEFAULT 0.0,
            branching_thresholds TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        """)
        await _create_index(db, "vn_stats", "idx_vn_stats_project", "project_id")

        await _create_table(db, "route_assets", """
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            asset_key TEXT NOT NULL,
            source_route_id TEXT,
            file_path TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        """)
        await _create_index(db, "route_assets", "idx_route_assets_project", "project_id")

        await _add_project_column_if_missing(db, "parent_id", "TEXT")
        await _add_project_column_if_missing(db, "shared_assets_path", "TEXT")
        await _add_project_column_if_missing(db, "route_id", "TEXT")
        await _add_project_column_if_missing(db, "vn_schema_version", f"TEXT DEFAULT '{VN_SCHEMA_VERSION}'")

        await db.commit()


async def _create_table(db: AsyncSession, name: str, ddl: str) -> None:
    await db.execute(text(f"CREATE TABLE IF NOT EXISTS {name} ({ddl})"))


async def _create_index(db: AsyncSession, table: str, index_name: str, column: str) -> None:
    await db.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table}({column})"))


async def _add_project_column_if_missing(db: AsyncSession, column: str, definition: str) -> None:
    result = await db.execute(text("PRAGMA table_info(projects)"))
    existing = {row[1] for row in result.fetchall()}
    if column in existing:
        return
    await db.execute(text(f"ALTER TABLE projects ADD COLUMN {column} {definition}"))


async def save_vn_route(
    project_id: str,
    route_id: str,
    route_key: str,
    route_type: str,
    parent_route_id: str | None = None,
    unlock_condition: str | None = None,
    chapter_count: int = 0,
    estimated_playtime_min: int | None = None,
) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        await db.execute(
            text("""INSERT OR REPLACE INTO vn_routes
                (id, project_id, route_key, route_type, parent_route_id, unlock_condition, chapter_count, estimated_playtime_min)
                VALUES (:id, :pid, :rkey, :rtype, :parent, :unlock, :ch, :pt)"""),
            {
                "id": route_id, "pid": project_id, "rkey": route_key, "rtype": route_type,
                "parent": parent_route_id, "unlock": unlock_condition,
                "ch": chapter_count, "pt": estimated_playtime_min,
            },
        )
        await db.commit()


async def get_vn_routes(project_id: str) -> list[dict[str, Any]]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        result = await db.execute(
            text("SELECT * FROM vn_routes WHERE project_id = :pid ORDER BY rowid"),
            {"pid": project_id},
        )
        return [dict(row._mapping) for row in result.fetchall()]


async def save_vn_character(
    project_id: str,
    char_id: str,
    name: str,
    role: str,
    sprite_set_path: str | None = None,
    expression_variants: list[str] | None = None,
    stat_affinities: list[str] | None = None,
    localization_names: dict[str, str] | None = None,
) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        await db.execute(
            text("""INSERT OR REPLACE INTO vn_characters
                (id, project_id, name, role, sprite_set_path, expression_variants, stat_affinities, localization_names)
                VALUES (:id, :pid, :name, :role, :sprite, :expr, :stats, :loc)"""),
            {
                "id": char_id, "pid": project_id, "name": name, "role": role,
                "sprite": sprite_set_path,
                "expr": json.dumps(expression_variants or []),
                "stats": json.dumps(stat_affinities or []),
                "loc": json.dumps(localization_names or {}),
            },
        )
        await db.commit()


async def get_vn_characters(project_id: str) -> list[dict[str, Any]]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        result = await db.execute(
            text("SELECT * FROM vn_characters WHERE project_id = :pid ORDER BY name"),
            {"pid": project_id},
        )
        rows = [dict(row._mapping) for row in result.fetchall()]
        for row in rows:
            if row.get("expression_variants"):
                try:
                    row["expression_variants"] = json.loads(row["expression_variants"])
                except (ValueError, TypeError):
                    row["expression_variants"] = []
            if row.get("stat_affinities"):
                try:
                    row["stat_affinities"] = json.loads(row["stat_affinities"])
                except (ValueError, TypeError):
                    row["stat_affinities"] = []
            if row.get("localization_names"):
                try:
                    row["localization_names"] = json.loads(row["localization_names"])
                except (ValueError, TypeError):
                    row["localization_names"] = {}
        return rows


async def save_vn_ending(
    project_id: str,
    ending_id: str,
    name: str,
    trigger_condition: dict,
    epilogue_key: str,
    is_good_ending: bool = False,
) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        await db.execute(
            text("""INSERT OR REPLACE INTO vn_endings
                (id, project_id, name, trigger_condition, epilogue_key, is_good_ending)
                VALUES (:id, :pid, :name, :trigger, :epilogue, :good)"""),
            {
                "id": ending_id, "pid": project_id, "name": name,
                "trigger": json.dumps(trigger_condition),
                "epilogue": epilogue_key,
                "good": 1 if is_good_ending else 0,
            },
        )
        await db.commit()


async def get_vn_endings(project_id: str) -> list[dict[str, Any]]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        result = await db.execute(
            text("SELECT * FROM vn_endings WHERE project_id = :pid ORDER BY name"),
            {"pid": project_id},
        )
        rows = [dict(row._mapping) for row in result.fetchall()]
        for row in rows:
            if row.get("trigger_condition"):
                try:
                    row["trigger_condition"] = json.loads(row["trigger_condition"])
                except (ValueError, TypeError):
                    row["trigger_condition"] = {}
        return rows


async def save_vn_stat(
    project_id: str,
    stat_id: str,
    stat_name: str,
    min_value: int = 0,
    max_value: int = 10,
    decay_per_chapter: float = 0.0,
    branching_thresholds: list[dict] | None = None,
) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        await db.execute(
            text("""INSERT OR REPLACE INTO vn_stats
                (id, project_id, stat_name, min_value, max_value, decay_per_chapter, branching_thresholds)
                VALUES (:id, :pid, :name, :min, :max, :decay, :thresh)"""),
            {
                "id": stat_id, "pid": project_id, "name": stat_name,
                "min": min_value, "max": max_value, "decay": decay_per_chapter,
                "thresh": json.dumps(branching_thresholds or []),
            },
        )
        await db.commit()


async def get_vn_stats(project_id: str) -> list[dict[str, Any]]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        result = await db.execute(
            text("SELECT * FROM vn_stats WHERE project_id = :pid ORDER BY stat_name"),
            {"pid": project_id},
        )
        rows = [dict(row._mapping) for row in result.fetchall()]
        for row in rows:
            if row.get("branching_thresholds"):
                try:
                    row["branching_thresholds"] = json.loads(row["branching_thresholds"])
                except (ValueError, TypeError):
                    row["branching_thresholds"] = []
        return rows


async def save_vn_cg(
    project_id: str,
    cg_id: str,
    cg_key: str,
    unlock_condition: dict,
    image_path: str | None = None,
) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        await db.execute(
            text("""INSERT OR REPLACE INTO vn_cgs
                (id, project_id, cg_key, unlock_condition, image_path)
                VALUES (:id, :pid, :key, :cond, :path)"""),
            {
                "id": cg_id, "pid": project_id, "key": cg_key,
                "cond": json.dumps(unlock_condition),
                "path": image_path,
            },
        )
        await db.commit()


async def save_route_asset(
    project_id: str,
    asset_id: str,
    asset_type: str,
    asset_key: str,
    file_path: str,
    source_route_id: str | None = None,
) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        await db.execute(
            text("""INSERT OR REPLACE INTO route_assets
                (id, project_id, asset_type, asset_key, source_route_id, file_path)
                VALUES (:id, :pid, :type, :key, :source, :path)"""),
            {
                "id": asset_id, "pid": project_id, "type": asset_type,
                "key": asset_key, "source": source_route_id, "path": file_path,
            },
        )
        await db.commit()


async def get_route_assets(project_id: str) -> list[dict[str, Any]]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        result = await db.execute(
            text("SELECT * FROM route_assets WHERE project_id = :pid"),
            {"pid": project_id},
        )
        return [dict(row._mapping) for row in result.fetchall()]


async def persist_vn_gdd(project_id: str, gdd: dict) -> dict:
    """Insert all VN records from a validated GDD into the persistence layer.

    Returns a summary dict with counts and any records that were skipped.
    """
    summary: dict = {"characters": 0, "endings": 0, "stats": 0, "cgs": 0, "routes": 0, "skipped": []}

    for i, char in enumerate(gdd.get("character_roster", []) or []):
        if not isinstance(char, dict) or not char.get("name"):
            summary["skipped"].append(f"character[{i}]: missing name")
            continue
        char_id = f"{project_id}_char_{char['name'].lower().replace(' ', '_')}"
        await save_vn_character(
            project_id=project_id,
            char_id=char_id,
            name=char["name"],
            role=char.get("role", "npc"),
            sprite_set_path=char.get("sprite_set"),
            expression_variants=char.get("expression_variants"),
            stat_affinities=char.get("stat_affinities"),
        )
        summary["characters"] += 1

    for i, ending in enumerate(gdd.get("ending_conditions", []) or []):
        if not isinstance(ending, dict) or not ending.get("name"):
            summary["skipped"].append(f"ending[{i}]: missing name")
            continue
        ending_id = f"{project_id}_end_{ending['name']}"
        await save_vn_ending(
            project_id=project_id,
            ending_id=ending_id,
            name=ending["name"],
            trigger_condition=ending.get("trigger", {}),
            epilogue_key=ending.get("epilogue_key", ending["name"]),
            is_good_ending=bool(ending.get("is_good_ending", 0)),
        )
        summary["endings"] += 1

    for i, stat in enumerate(gdd.get("stat_system", {}).get("stats", []) or []):
        if not isinstance(stat, dict) or not stat.get("name"):
            summary["skipped"].append(f"stat[{i}]: missing name")
            continue
        rng = stat.get("range", [0, 10])
        stat_id = f"{project_id}_stat_{stat['name']}"
        await save_vn_stat(
            project_id=project_id,
            stat_id=stat_id,
            stat_name=stat["name"],
            min_value=int(rng[0]) if len(rng) > 0 else 0,
            max_value=int(rng[1]) if len(rng) > 1 else 10,
            decay_per_chapter=float(stat.get("decay", 0.0)),
            branching_thresholds=stat.get("branching_thresholds"),
        )
        summary["stats"] += 1

    for i, cg in enumerate(gdd.get("cg_milestones", []) or []):
        if not isinstance(cg, dict) or not cg.get("cg_key"):
            summary["skipped"].append(f"cg[{i}]: missing cg_key")
            continue
        cg_id = f"{project_id}_cg_{cg['cg_key']}"
        await save_vn_cg(
            project_id=project_id,
            cg_id=cg_id,
            cg_key=cg["cg_key"],
            unlock_condition={"scene_id": cg.get("scene_id"), "raw": cg.get("condition")},
        )
        summary["cgs"] += 1

    routes_struct = gdd.get("route_structure", {})
    common_chapters = routes_struct.get("common_route_chapters", 0)
    common_route_id = f"{project_id}_route_common"
    await save_vn_route(
        project_id=project_id,
        route_id=common_route_id,
        route_key="common",
        route_type="common",
        parent_route_id=None,
        unlock_condition=None,
        chapter_count=int(common_chapters) if isinstance(common_chapters, int) else 0,
    )
    summary["routes"] += 1
    for i, cr in enumerate(routes_struct.get("character_routes", []) or []):
        if not isinstance(cr, dict) or not cr.get("key"):
            continue
        cr_id = f"{project_id}_route_{cr['key']}"
        await save_vn_route(
            project_id=project_id,
            route_id=cr_id,
            route_key=cr["key"],
            route_type="character",
            parent_route_id=common_route_id,
            unlock_condition=cr.get("unlock"),
            chapter_count=int(cr.get("chapters", 0)) if isinstance(cr.get("chapters"), int) else 0,
        )
        summary["routes"] += 1

    logger.info(
        f"persisted VN GDD {project_id}: chars={summary['characters']} "
        f"endings={summary['endings']} stats={summary['stats']} "
        f"cgs={summary['cgs']} routes={summary['routes']} "
        f"skipped={len(summary['skipped'])}"
    )
    return summary

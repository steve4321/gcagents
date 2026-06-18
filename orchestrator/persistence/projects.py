"""Projects table CRUD, targeted update helpers, and game-version snapshots."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.persistence.engine import _get_engine, _parse_datetime
from shared.constants import TRUNC_CHANGELOG
from shared.models import ProjectPhase, ProjectState


async def save_project(project: ProjectState) -> str:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(UTC).isoformat()
        existing = await db.execute(
            text("SELECT id FROM projects WHERE id = :id"),
            {"id": project.id},
        )
        if existing.fetchone():
            await db.execute(
                text("""
                    UPDATE projects SET name=:name, genre=:genre, phase=:phase,
                        progress=:progress, proposal=:proposal, gdd=:gdd,
                        code_path=:code_path, art_assets_path=:art_assets_path,
                        art_status=:art_status,
                        music_status=:music_status,
                        qa_result=:qa_result, itch_url=:itch_url,
                        platform_urls=:platform_urls,
                        version=:version, awaiting_decision=:awaiting_decision,
                        updated_at=:updated_at
                    WHERE id=:id
                """),
                {
                    "id": project.id,
                    "name": project.name,
                    "genre": project.genre,
                    "phase": project.phase.value
                    if hasattr(project.phase, "value")
                    else project.phase,
                    "progress": project.progress,
                    "proposal": json.dumps(project.proposal) if project.proposal else None,
                    "gdd": json.dumps(project.gdd) if project.gdd else None,
                    "code_path": project.code_path,
                    "art_assets_path": project.art_assets_path,
                    "art_status": project.art_status,
                    "music_status": project.music_status,
                    "qa_result": json.dumps(project.qa_result) if project.qa_result else None,
                    "itch_url": project.itch_url,
                    "platform_urls": json.dumps(project.platform_urls),
                    "version": project.version,
                    "awaiting_decision": project.awaiting_decision,
                    "updated_at": now,
                },
            )
        else:
            await db.execute(
                text("""
                    INSERT INTO projects (id, name, genre, phase, progress, proposal, gdd,
                        code_path, art_assets_path, art_status, music_status, qa_result, itch_url,
                        platform_urls, version,
                        awaiting_decision, created_at, updated_at)
                    VALUES (:id, :name, :genre, :phase, :progress, :proposal, :gdd,
                        :code_path, :art_assets_path, :art_status, :music_status, :qa_result, :itch_url,
                        :platform_urls, :version,
                        :awaiting_decision, :created_at, :updated_at)
                """),
                {
                    "id": project.id,
                    "name": project.name,
                    "genre": project.genre,
                    "phase": project.phase.value
                    if hasattr(project.phase, "value")
                    else project.phase,
                    "progress": project.progress,
                    "proposal": json.dumps(project.proposal) if project.proposal else None,
                    "gdd": json.dumps(project.gdd) if project.gdd else None,
                    "code_path": project.code_path,
                    "art_assets_path": project.art_assets_path,
                    "art_status": project.art_status,
                    "music_status": project.music_status,
                    "qa_result": json.dumps(project.qa_result) if project.qa_result else None,
                    "itch_url": project.itch_url,
                    "platform_urls": json.dumps(project.platform_urls),
                    "version": project.version,
                    "awaiting_decision": project.awaiting_decision,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        await db.commit()
        await _mirror_to_game_projects(db, project)
        await db.commit()
        return project.id


async def _mirror_to_game_projects(db: AsyncSession, project: ProjectState) -> None:
    """Mirror the current projects state into game_projects for analytics.

    The two tables have overlapping but distinct schemas:
      - projects: rich lifecycle state (phase, gdd, code_path, art_assets_path)
      - game_projects: published/feedback view (status, itch_url, current_version)
    Mirror only the subset the analytics dashboard reads.
    """
    phase = project.phase.value if hasattr(project.phase, "value") else str(project.phase)
    status = "live" if phase == "live" else phase
    proposal_json = json.dumps(project.proposal) if project.proposal else None
    gdd_json = json.dumps(project.gdd) if project.gdd else None
    try:
        existing = (
            await db.execute(
                text("SELECT id FROM game_projects WHERE name = :name"),
                {"name": project.name},
            )
        ).fetchone()
        if existing:
            await db.execute(
                text("""
                    UPDATE game_projects SET genre=:genre, status=:status,
                        gdd=:gdd, proposal=:proposal, itch_url=:itch_url,
                        current_version=:current_version, updated_at=:updated_at
                    WHERE name = :name
                """),
                {
                    "name": project.name,
                    "genre": project.genre or "unknown",
                    "status": status,
                    "gdd": gdd_json,
                    "proposal": proposal_json,
                    "itch_url": project.itch_url or "",
                    "current_version": project.version or "0.0.0",
                    "updated_at": datetime.now(UTC).isoformat(),
                },
            )
        else:
            await db.execute(
                text("""
                    INSERT INTO game_projects
                        (name, genre, status, gdd, proposal, itch_url,
                         current_version, created_at, updated_at)
                    VALUES (:name, :genre, :status, :gdd, :proposal, :itch_url,
                            :current_version, :created_at, :updated_at)
                """),
                {
                    "name": project.name,
                    "genre": project.genre or "unknown",
                    "status": status,
                    "gdd": gdd_json,
                    "proposal": proposal_json,
                    "itch_url": project.itch_url or "",
                    "current_version": project.version or "0.0.0",
                    "created_at": project.created_at or datetime.now(UTC).isoformat(),
                    "updated_at": datetime.now(UTC).isoformat(),
                },
            )
    except Exception as e:
        logger.warning(f"Failed to upsert game project '{project.name}': {e}")


async def get_project(project_id: str) -> ProjectState | None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        row = await db.execute(
            text("SELECT * FROM projects WHERE id = :id"),
            {"id": project_id},
        )
        result = row.fetchone()
        if not result:
            return None
        return _row_to_project(dict(result._mapping))


async def get_all_projects() -> list[ProjectState]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = await db.execute(text("SELECT * FROM projects ORDER BY updated_at DESC"))
        return [_row_to_project(dict(r._mapping)) for r in rows.fetchall()]


async def get_projects_by_phase(phase: str) -> list[ProjectState]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = await db.execute(
            text("SELECT * FROM projects WHERE phase = :phase ORDER BY updated_at DESC"),
            {"phase": phase},
        )
        return [_row_to_project(dict(r._mapping)) for r in rows.fetchall()]


async def update_project_phase(project_id: str, phase: str, progress: float | None = None) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(UTC).isoformat()
        if progress is not None:
            await db.execute(
                text(
                    "UPDATE projects SET phase=:phase, progress=:progress, updated_at=:now WHERE id=:id"
                ),
                {"phase": phase, "progress": progress, "now": now, "id": project_id},
            )
        else:
            await db.execute(
                text("UPDATE projects SET phase=:phase, updated_at=:now WHERE id=:id"),
                {"phase": phase, "now": now, "id": project_id},
            )
        await db.commit()


def _row_to_project(d: dict) -> ProjectState:
    return ProjectState(
        id=d["id"],
        name=d["name"],
        genre=d.get("genre", ""),
        phase=ProjectPhase(d.get("phase", "backlog")),
        progress=d.get("progress", 0.0),
        proposal=json.loads(d["proposal"]) if d.get("proposal") else None,
        gdd=json.loads(d["gdd"]) if d.get("gdd") else None,
        code_path=d.get("code_path"),
        art_assets_path=d.get("art_assets_path", ""),
        art_status=d.get("art_status", "pending"),
        music_status=d.get("music_status", "pending"),
        qa_result=json.loads(d["qa_result"]) if d.get("qa_result") else None,
        itch_url=d.get("itch_url"),
        platform_urls=json.loads(d.get("platform_urls", "{}")) if d.get("platform_urls") else {},
        version=d.get("version", "0.0.0"),
        awaiting_decision=d.get("awaiting_decision"),
        created_at=_parse_datetime(d.get("created_at")),
        updated_at=_parse_datetime(d.get("updated_at")),
    )


async def save_game_version(
    project_id: str,
    version: str,
    gdd_snapshot: dict | None = None,
    changelog: str = "",
    feedback_ids: list[int] | None = None,
    build_size: int = 0,
) -> int:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        result = await db.execute(
            text("""
                INSERT INTO game_versions
                    (project_id, version, gdd_snapshot, changelog, feedback_ids, build_size)
                VALUES (:project_id, :version, :gdd_snapshot, :changelog, :feedback_ids, :build_size)
            """),
            {
                "project_id": project_id,
                "version": version,
                "gdd_snapshot": json.dumps(gdd_snapshot or {}),
                "changelog": changelog[:TRUNC_CHANGELOG],
                "feedback_ids": json.dumps(feedback_ids or []),
                "build_size": build_size,
            },
        )
        await db.execute(
            text("UPDATE projects SET version = :ver, updated_at = :now WHERE id = :pid"),
            {"ver": version, "now": datetime.now(UTC).isoformat(), "pid": project_id},
        )
        await db.commit()
        return result.lastrowid or 0


async def get_latest_version(project_id: str) -> str:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        row = await db.execute(
            text("SELECT version FROM projects WHERE id = :pid"),
            {"pid": project_id},
        )
        result = row.fetchone()
        return result[0] if result else "0.0.0"


async def update_project_awaiting_decision(project_id: str, decision_id: str | None) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(UTC).isoformat()
        await db.execute(
            text("UPDATE projects SET awaiting_decision=:d, updated_at=:now WHERE id=:id"),
            {"d": decision_id, "now": now, "id": project_id},
        )
        await db.commit()


async def update_project_proposal_and_phase(
    project_id: str, proposal: dict, phase: str = "designing"
) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(UTC).isoformat()
        await db.execute(
            text(
                "UPDATE projects SET phase=:phase, proposal=:proposal, updated_at=:now WHERE id=:id"
            ),
            {"phase": phase, "proposal": json.dumps(proposal), "now": now, "id": project_id},
        )
        await db.commit()


async def update_project_gdd(project_id: str, gdd: dict) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(UTC).isoformat()
        await db.execute(
            text("UPDATE projects SET gdd=:gdd, updated_at=:now WHERE id=:id"),
            {"gdd": json.dumps(gdd), "now": now, "id": project_id},
        )
        await db.commit()


async def update_project_art_status(project_id: str, status: str = "done") -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(UTC).isoformat()
        await db.execute(
            text("UPDATE projects SET art_status=:s, updated_at=:now WHERE id=:id"),
            {"s": status, "now": now, "id": project_id},
        )
        await db.commit()


async def update_project_music_status(project_id: str, status: str = "done") -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(UTC).isoformat()
        await db.execute(
            text("UPDATE projects SET music_status=:s, updated_at=:now WHERE id=:id"),
            {"s": status, "now": now, "id": project_id},
        )
        await db.commit()


async def update_project_code_path(project_id: str, code_path: str) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(UTC).isoformat()
        await db.execute(
            text("UPDATE projects SET code_path=:cp, updated_at=:now WHERE id=:id"),
            {"cp": code_path, "now": now, "id": project_id},
        )
        await db.commit()


async def update_project_qa_result(project_id: str, qa_result: dict) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(UTC).isoformat()
        await db.execute(
            text("UPDATE projects SET qa_result=:qr, updated_at=:now WHERE id=:id"),
            {"qr": json.dumps(qa_result), "now": now, "id": project_id},
        )
        await db.commit()


async def update_project_build_path(project_id: str, build_path: str) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(UTC).isoformat()
        await db.execute(
            text("UPDATE projects SET build_path=:bp, updated_at=:now WHERE id=:id"),
            {"bp": build_path, "now": now, "id": project_id},
        )
        await db.commit()


async def update_project_art_assets_path(project_id: str, art_assets_path: str) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(UTC).isoformat()
        await db.execute(
            text("UPDATE projects SET art_assets_path=:aap, updated_at=:now WHERE id=:id"),
            {"aap": art_assets_path, "now": now, "id": project_id},
        )
        await db.commit()


async def update_project_platform_urls(project_id: str, platform_urls: dict[str, str]) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(UTC).isoformat()
        await db.execute(
            text("UPDATE projects SET platform_urls=:pu, updated_at=:now WHERE id=:id"),
            {"pu": json.dumps(platform_urls), "now": now, "id": project_id},
        )
        await db.commit()


async def set_project_live(project_id: str, itch_url: str, version: str = "0.0.0") -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(UTC).isoformat()
        await db.execute(
            text(
                "UPDATE projects SET itch_url=:url, version=:ver, phase='live', "
                "awaiting_decision=NULL, updated_at=:now WHERE id=:id"
            ),
            {"url": itch_url, "ver": version, "now": now, "id": project_id},
        )
        await db.commit()

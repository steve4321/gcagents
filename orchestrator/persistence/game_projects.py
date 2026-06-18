"""Game projects, itch.io stats, and project-discovery helpers."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.persistence.engine import _get_engine


async def get_live_projects() -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = await db.execute(
            text("""
                SELECT id, name, genre, status, itch_url, current_version, feedback_count
                FROM game_projects
                WHERE status IN ('live', 'updating')
                ORDER BY updated_at DESC
            """)
        )
        return [dict(r._mapping) for r in rows.fetchall()]


async def get_latest_project() -> dict | None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        row = (
            await db.execute(
                text("SELECT name, status FROM game_projects ORDER BY updated_at DESC LIMIT 1")
            )
        ).fetchone()
    if row:
        return {"name": row.name, "status": row.status}
    return None


async def find_project_by_name(name: str) -> str | None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        row = (
            await db.execute(
                text("SELECT id FROM game_projects WHERE name = :name"),
                {"name": name},
            )
        ).fetchone()
    return row.id if row else None


async def get_project_gdd(project_id: str) -> dict | None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        row = (
            await db.execute(
                text("SELECT name, gdd, proposal FROM game_projects WHERE id = :pid"),
                {"pid": project_id},
            )
        ).fetchone()
    if row:
        return {"name": row.name, "gdd": row.gdd, "proposal": row.proposal}
    return None


async def get_completed_genres() -> set[str]:
    engine = _get_engine()
    genres: set[str] = set()
    async with AsyncSession(engine) as db:
        rows = await db.execute(text("SELECT DISTINCT genre FROM game_projects"))
        for row in rows.fetchall():
            if row.genre:
                genres.add(row.genre.lower())
    return genres


async def find_project_to_update() -> dict | None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = await db.execute(
            text("""
                SELECT p.id, p.name, p.itch_url,
                       COUNT(f.id) AS unprocessed_count
                FROM game_projects p
                JOIN game_feedback f ON f.project_id = p.id AND f.processed = 0
                WHERE p.status IN ('live', 'updating')
                AND f.category IN ('bug', 'feature')
                GROUP BY p.id
                HAVING unprocessed_count >= 2
                ORDER BY unprocessed_count DESC
                LIMIT 1
            """)
        )
        row = rows.fetchone()
    if row:
        return {
            "id": row.id,
            "name": row.name,
            "itch_url": row.itch_url,
            "unprocessed_count": row.unprocessed_count,
        }
    return None


async def save_itch_stat(
    project_id: str,
    itch_game_id: int,
    title: str,
    itch_url: str,
    downloads_count: int,
    views_count: int,
    purchases_count: int,
) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        await db.execute(
            text("""
                INSERT INTO itch_stats (
                    project_id, itch_game_id, title, itch_url,
                    downloads_count, views_count, purchases_count
                )
                VALUES (
                    :project_id, :itch_game_id, :title, :itch_url,
                    :downloads_count, :views_count, :purchases_count
                )
            """),
            {
                "project_id": project_id,
                "itch_game_id": itch_game_id,
                "title": title,
                "itch_url": itch_url,
                "downloads_count": downloads_count,
                "views_count": views_count,
                "purchases_count": purchases_count,
            },
        )
        await db.commit()


async def get_latest_itch_stats() -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = (
            await db.execute(
                text("""
                SELECT s.project_id, s.itch_game_id, s.title, s.itch_url,
                       s.downloads_count, s.views_count, s.purchases_count, s.fetched_at
                FROM itch_stats s
                INNER JOIN (
                    SELECT project_id, MAX(fetched_at) AS max_fetched
                    FROM itch_stats
                    GROUP BY project_id
                ) latest
                  ON s.project_id = latest.project_id
                 AND s.fetched_at = latest.max_fetched
                ORDER BY s.downloads_count DESC, s.title ASC
            """)
            )
        ).fetchall()
        return [
            {
                "project_id": r[0],
                "itch_game_id": r[1],
                "title": r[2],
                "itch_url": r[3],
                "downloads_count": r[4],
                "views_count": r[5],
                "purchases_count": r[6],
                "fetched_at": r[7],
            }
            for r in rows
        ]

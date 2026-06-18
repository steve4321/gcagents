"""Game feedback persistence (game_feedback table)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.persistence.engine import _get_engine
from shared.constants import TRUNC_AI_ANALYSIS, TRUNC_FEEDBACK_TEXT


async def save_feedback(
    project_id: int,
    post_id: str,
    body: str,
    author: str = "",
    posted_at: str | None = None,
    vote_count: int = 0,
    category: str = "other",
    ai_analysis: str = "",
) -> int:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        existing = await db.execute(
            text("SELECT id FROM game_feedback WHERE project_id = :pid AND post_id = :post_id"),
            {"pid": project_id, "post_id": post_id},
        )
        if existing.fetchone():
            return 0  # dedup
        result = await db.execute(
            text("""
                INSERT INTO game_feedback
                    (project_id, post_id, author, text, posted_at, vote_count, category, ai_analysis)
                VALUES (:project_id, :post_id, :author, :text, :posted_at, :vote_count, :category, :ai_analysis)
            """),
            {
                "project_id": project_id,
                "post_id": post_id,
                "author": author[:100],
                "text": body[:TRUNC_FEEDBACK_TEXT],
                "posted_at": posted_at or datetime.now(UTC).isoformat(),
                "vote_count": vote_count,
                "category": category,
                "ai_analysis": ai_analysis[:TRUNC_AI_ANALYSIS],
            },
        )
        await db.execute(
            text("UPDATE game_projects SET feedback_count = feedback_count + 1 WHERE id = :pid"),
            {"pid": project_id},
        )
        await db.commit()
        return result.lastrowid or 0


async def get_unprocessed_feedback(project_id: int) -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = await db.execute(
            text(
                "SELECT * FROM game_feedback WHERE project_id = :pid AND processed = 0 ORDER BY posted_at DESC"
            ),
            {"pid": project_id},
        )
        return [dict(r._mapping) for r in rows.fetchall()]


async def mark_feedback_processed(feedback_ids: list[int]) -> None:
    if not feedback_ids:
        return
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        placeholders = ", ".join(f":fid{i}" for i in range(len(feedback_ids)))
        params = {f"fid{i}": fid for i, fid in enumerate(feedback_ids)}
        await db.execute(
            text(f"UPDATE game_feedback SET processed = 1 WHERE id IN ({placeholders})"),
            params,
        )
        await db.commit()


async def get_pending_feedback(project_id: str) -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = (
            await db.execute(
                text(
                    "SELECT * FROM game_feedback WHERE project_id = :pid AND processed = 0 ORDER BY posted_at DESC"
                ),
                {"pid": project_id},
            )
        ).fetchall()
    return [dict(r._mapping) for r in rows]


async def get_all_feedback(project_id: str) -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = (
            await db.execute(
                text(
                    "SELECT * FROM game_feedback WHERE project_id = :pid ORDER BY posted_at DESC LIMIT 50"
                ),
                {"pid": project_id},
            )
        ).fetchall()
    return [dict(r._mapping) for r in rows]

"""Agent execution log persistence (agent_logs table)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.persistence.engine import _get_engine
from shared.constants import TRUNC_ERROR


async def save_agent_log(
    node_name: str,
    status: str = "running",
    phase: str | None = None,
    error: str | None = None,
    duration_ms: int | None = None,
    project_name: str | None = None,
    run_id: str | None = None,
    started_at: str | None = None,
) -> int:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(UTC).isoformat()
        result = await db.execute(
            text("""
                INSERT INTO agent_logs
                    (node_name, phase, status, started_at, completed_at, duration_ms, error, project_name, run_id)
                VALUES (:node_name, :phase, :status, :started_at, :completed_at, :duration_ms, :error, :project_name, :run_id)
            """),
            {
                "node_name": node_name,
                "phase": phase or "",
                "status": status,
                "started_at": started_at or now,
                "completed_at": now if status in ("completed", "failed") else None,
                "duration_ms": duration_ms,
                "error": (error or "")[:TRUNC_ERROR],
                "project_name": project_name or "",
                "run_id": run_id or "",
            },
        )
        await db.commit()
        return result.lastrowid or 0


async def get_agent_logs(limit: int = 50) -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = (
            await db.execute(
                text(
                    "SELECT node_name, status, phase, started_at, completed_at, duration_ms, error, project_name FROM agent_logs ORDER BY id DESC LIMIT :lim"
                ),
                {"lim": limit},
            )
        ).fetchall()
    return [dict(r._mapping) for r in rows]


async def get_agent_stats() -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = (
            await db.execute(
                text("""
                SELECT node_name, COUNT(*) as runs,
                    SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as successes,
                    SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failures,
                    ROUND(AVG(CASE WHEN duration_ms IS NOT NULL THEN duration_ms ELSE 0 END)) as avg_duration_ms
                FROM agent_logs GROUP BY node_name ORDER BY node_name
            """)
            )
        ).fetchall()
    return [dict(r._mapping) for r in rows]

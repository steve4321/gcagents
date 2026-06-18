"""Game metrics persistence and analytics aggregation."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.persistence.engine import _get_engine


async def save_game_metric(project_id: int, metric_name: str, metric_value: float) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        await db.execute(
            text("""
                INSERT INTO game_metrics (project_id, metric_name, metric_value)
                VALUES (:project_id, :metric_name, :metric_value)
            """),
            {
                "project_id": project_id,
                "metric_name": metric_name[:50],
                "metric_value": metric_value,
            },
        )
        await db.commit()


async def get_project_metrics(project_id: int, limit: int = 100) -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = await db.execute(
            text("""
                SELECT * FROM game_metrics
                WHERE project_id = :pid
                ORDER BY recorded_at DESC
                LIMIT :lim
            """),
            {"pid": project_id, "lim": limit},
        )
        return [dict(r._mapping) for r in rows.fetchall()]


async def get_analytics_summary() -> dict:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        projects = (
            await db.execute(
                text("""
                SELECT id, name, genre, status, feedback_count, current_version
                FROM game_projects
                WHERE status IN ('live', 'updating')
                ORDER BY updated_at DESC
            """)
            )
        ).fetchall()

        metrics_rows = (
            await db.execute(
                text("""
                SELECT project_id, metric_name,
                       SUM(metric_value) as total_value,
                       COUNT(*) as sample_count
                FROM game_metrics
                GROUP BY project_id, metric_name
            """)
            )
        ).fetchall()

        metrics_by_project: dict[int, dict] = {}
        for row in metrics_rows:
            pid = row._mapping["project_id"]
            if pid not in metrics_by_project:
                metrics_by_project[pid] = {}
            metrics_by_project[pid][row._mapping["metric_name"]] = {
                "value": float(row._mapping["total_value"]),
                "samples": int(row._mapping["sample_count"]),
            }

        result = []
        for p in projects:
            pd = dict(p._mapping)
            pd["metrics"] = metrics_by_project.get(pd["id"], {})
            result.append(pd)

        return {"projects": result}


async def get_game_analytics_summary() -> dict:
    """Aggregated play/retention metrics across all games."""
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        # Play counts (sum of event_game_start values)
        plays = await db.execute(
            text("""
                SELECT project_id,
                       COALESCE(SUM(metric_value), 0) as play_count,
                       (SELECT AVG(m2.metric_value)
                        FROM game_metrics m2
                        WHERE m2.project_id = game_metrics.project_id
                          AND m2.metric_name = 'last_score') as avg_score
                FROM game_metrics
                WHERE metric_name = 'event_game_start'
                GROUP BY project_id
            """)
        )
        plays_data: dict[int, dict] = {
            r[0]: {"plays": int(r[1]), "avg_score": round(r[2], 2) if r[2] else None}
            for r in plays.fetchall()
        }

        # Average session duration
        sessions = await db.execute(
            text("""
                SELECT project_id, AVG(metric_value) as avg_session_seconds
                FROM game_metrics
                WHERE metric_name = 'avg_session_s'
                GROUP BY project_id
            """)
        )
        for r in sessions.fetchall():
            if r[0] in plays_data:
                plays_data[r[0]]["avg_session_seconds"] = round(r[1], 1)

        # Recent 24h activity
        recent = await db.execute(
            text("""
                SELECT project_id, metric_name, COUNT(*) as count
                FROM game_metrics
                WHERE recorded_at > datetime('now', '-1 day')
                GROUP BY project_id, metric_name
            """)
        )
        recent_data: dict[int, dict[str, int]] = {}
        for r in recent.fetchall():
            if r[0] not in recent_data:
                recent_data[r[0]] = {}
            recent_data[r[0]][r[1]] = r[2]

        return {"by_game": plays_data, "recent_24h": recent_data}


async def get_game_metrics_detail(project_id: int, days: int = 7) -> list[dict]:
    """Detailed metrics for a specific game over the given time range."""
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = await db.execute(
            text("""
                SELECT metric_name, metric_value, recorded_at
                FROM game_metrics
                WHERE project_id = :pid
                  AND recorded_at > datetime('now', '-' || :days || ' days')
                ORDER BY recorded_at DESC
            """),
            {"pid": project_id, "days": days},
        )
        return [dict(r._mapping) for r in rows.fetchall()]

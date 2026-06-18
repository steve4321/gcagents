"""Event log persistence (event_logs table)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.persistence.engine import _get_engine


async def log_event(
    event_type: str,
    severity: str,
    title: str,
    detail: str = "",
    source_agent: str = "",
    project_name: str = "",
    metadata: dict = None,
) -> int:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        result = await db.execute(
            text("""
                INSERT INTO event_logs
                    (event_type, severity, title, detail, source_agent, project_name, metadata_json, created_at)
                VALUES (:event_type, :severity, :title, :detail, :source_agent, :project_name, :metadata_json, :created_at)
            """),
            {
                "event_type": event_type,
                "severity": severity,
                "title": title,
                "detail": detail,
                "source_agent": source_agent,
                "project_name": project_name,
                "metadata_json": json.dumps(metadata or {}),
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
        await db.commit()
        return result.lastrowid or 0


async def get_recent_events(limit: int = 200, event_type: str = "") -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        if event_type:
            rows = await db.execute(
                text(
                    "SELECT * FROM event_logs WHERE event_type = :event_type ORDER BY created_at DESC LIMIT :lim"
                ),
                {"event_type": event_type, "lim": limit},
            )
        else:
            rows = await db.execute(
                text("SELECT * FROM event_logs ORDER BY created_at DESC LIMIT :lim"),
                {"lim": limit},
            )
        return [dict(r._mapping) for r in rows.fetchall()]

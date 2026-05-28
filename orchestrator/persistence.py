from __future__ import annotations

import json
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from shared.config import load_config

_engine_cache = None


def _get_engine():
    global _engine_cache
    if _engine_cache is None:
        config = load_config()
        _engine_cache = create_async_engine(config.db_url, echo=False)
    return _engine_cache


async def ensure_tables():
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_name TEXT NOT NULL,
                phase TEXT,
                status TEXT NOT NULL DEFAULT 'running',
                started_at TEXT NOT NULL,
                completed_at TEXT,
                duration_ms INTEGER,
                error TEXT,
                project_name TEXT,
                run_id TEXT
            )
        """))
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS market_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signals_count INTEGER DEFAULT 0,
                opportunities_json TEXT,
                raw_analysis TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """))
        await db.commit()


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
        now = datetime.now(timezone.utc).isoformat()
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
                "error": (error or "")[:500],
                "project_name": project_name or "",
                "run_id": run_id or "",
            },
        )
        await db.commit()
        return result.lastrowid or 0


async def save_market_report(
    signals_count: int,
    opportunities: list[dict],
    raw_analysis: str | None = None,
) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        await db.execute(
            text("""
                INSERT INTO market_reports (signals_count, opportunities_json, raw_analysis, created_at)
                VALUES (:signals_count, :opportunities_json, :raw_analysis, :created_at)
            """),
            {
                "signals_count": signals_count,
                "opportunities_json": json.dumps(opportunities, ensure_ascii=False),
                "raw_analysis": (raw_analysis or "")[:50000],
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        await db.commit()


async def save_pipeline_state(
    phase: str,
    project_name: str | None = None,
    project_genre: str | None = None,
    errors: list[str] | None = None,
) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        try:
            await db.execute(
                text("""
                    INSERT INTO orchestrator_state (phase, current_project_id, errors, updated_at)
                    VALUES (:phase, :project_id, :errors, :updated_at)
                """),
                {
                    "phase": phase,
                    "project_id": 0,
                    "errors": json.dumps(errors or []),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            if project_name:
                result = await db.execute(
                    text("SELECT id FROM game_projects WHERE name = :name"),
                    {"name": project_name},
                )
                row = result.fetchone()
                if not row:
                    await db.execute(
                        text("""
                            INSERT INTO game_projects (name, genre, status, proposal, created_at, updated_at)
                            VALUES (:name, :genre, :status, :proposal, :created_at, :updated_at)
                        """),
                        {
                            "name": project_name,
                            "genre": project_genre or "unknown",
                            "status": phase,
                            "proposal": json.dumps({"name": project_name, "genre": project_genre}),
                            "created_at": datetime.now(timezone.utc).isoformat(),
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def save_market_signals(signals: list[dict]) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        for sig in signals[:20]:
            try:
                await db.execute(
                    text("""
                        INSERT INTO market_signals (source, signal_type, genre, title, data, score, captured_at)
                        VALUES (:source, :signal_type, :genre, :title, :data, :score, :captured_at)
                    """),
                    {
                        "source": sig.get("source", "unknown"),
                        "signal_type": "market",
                        "genre": sig.get("genre", "unknown"),
                        "title": sig.get("title", "")[:200],
                        "data": json.dumps(sig.get("data", {})),
                        "score": float(sig.get("score", 0)),
                        "captured_at": sig.get("captured_at", datetime.now(timezone.utc).isoformat()),
                    },
                )
            except Exception:
                pass
        await db.commit()

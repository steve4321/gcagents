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
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS game_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                post_id TEXT NOT NULL,
                author TEXT DEFAULT '',
                text TEXT NOT NULL,
                posted_at TEXT,
                vote_count INTEGER DEFAULT 0,
                category TEXT DEFAULT 'other',
                ai_analysis TEXT DEFAULT '',
                processed INTEGER DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """))
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS game_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                version TEXT NOT NULL,
                gdd_snapshot TEXT,
                changelog TEXT DEFAULT '',
                feedback_ids TEXT DEFAULT '[]',
                build_size INTEGER DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """))
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS game_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                metric_name TEXT NOT NULL,
                metric_value REAL NOT NULL,
                recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """))
        # Add columns to game_projects if missing (idempotent migration)
        for col_sql in [
            "ALTER TABLE game_projects ADD COLUMN current_version TEXT DEFAULT '0.0.0'",
            "ALTER TABLE game_projects ADD COLUMN feedback_count INTEGER DEFAULT 0",
        ]:
            try:
                await db.execute(text(col_sql))
            except Exception:
                pass  # column already exists
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


# ── Feedback ────────────────────────────────────────────────────────────────

async def save_feedback(
    project_id: int,
    post_id: str,
    text: str,
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
                "text": text[:5000],
                "posted_at": posted_at or datetime.now(timezone.utc).isoformat(),
                "vote_count": vote_count,
                "category": category,
                "ai_analysis": ai_analysis[:2000],
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
            text("SELECT * FROM game_feedback WHERE project_id = :pid AND processed = 0 ORDER BY posted_at DESC"),
            {"pid": project_id},
        )
        return [dict(r._mapping) for r in rows.fetchall()]


async def mark_feedback_processed(feedback_ids: list[int]) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        for fid in feedback_ids:
            await db.execute(
                text("UPDATE game_feedback SET processed = 1 WHERE id = :fid"),
                {"fid": fid},
            )
        await db.commit()


# ── Game Versions ───────────────────────────────────────────────────────────

async def save_game_version(
    project_id: int,
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
                "changelog": changelog[:2000],
                "feedback_ids": json.dumps(feedback_ids or []),
                "build_size": build_size,
            },
        )
        await db.execute(
            text("UPDATE game_projects SET current_version = :ver, updated_at = :now WHERE id = :pid"),
            {"ver": version, "now": datetime.now(timezone.utc).isoformat(), "pid": project_id},
        )
        await db.commit()
        return result.lastrowid or 0


async def get_latest_version(project_id: int) -> str:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        row = await db.execute(
            text("SELECT current_version FROM game_projects WHERE id = :pid"),
            {"pid": project_id},
        )
        result = row.fetchone()
        return result[0] if result else "0.0.0"


# ── Game Metrics ────────────────────────────────────────────────────────────

async def save_game_metric(project_id: int, metric_name: str, metric_value: float) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        await db.execute(
            text("""
                INSERT INTO game_metrics (project_id, metric_name, metric_value)
                VALUES (:project_id, :metric_name, :metric_value)
            """),
            {"project_id": project_id, "metric_name": metric_name[:50], "metric_value": metric_value},
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


# ── Queries ─────────────────────────────────────────────────────────────────

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

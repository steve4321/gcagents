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
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS api_usage_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                project_name TEXT DEFAULT '',
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                estimated_cost_usd REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS finance_budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                budget_type TEXT NOT NULL DEFAULT 'monthly',
                budget_limit_usd REAL NOT NULL,
                spent_usd REAL DEFAULT 0.0,
                period_start TEXT,
                period_end TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """))
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                agent_name TEXT DEFAULT '',
                metadata_json TEXT DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """))
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS event_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'info',
                title TEXT NOT NULL,
                detail TEXT DEFAULT '',
                source_agent TEXT DEFAULT '',
                project_name TEXT DEFAULT '',
                metadata_json TEXT DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
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


# ── API Usage ────────────────────────────────────────────────────────────────

async def log_api_usage(
    model: str,
    agent_name: str,
    project_name: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    estimated_cost_usd: float = 0.0,
) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        await db.execute(
            text("""
                INSERT INTO api_usage_logs
                    (model, agent_name, project_name, prompt_tokens, completion_tokens,
                     total_tokens, estimated_cost_usd)
                VALUES (:model, :agent_name, :project_name, :prompt_tokens,
                        :completion_tokens, :total_tokens, :estimated_cost_usd)
            """),
            {
                "model": model,
                "agent_name": agent_name,
                "project_name": project_name,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "estimated_cost_usd": estimated_cost_usd,
            },
        )
        await db.commit()


async def get_usage_summary(days: int = 30) -> dict:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        days_arg = f"-{days} days"

        row = await db.execute(
            text("""
                SELECT COALESCE(SUM(estimated_cost_usd), 0),
                       COALESCE(SUM(total_tokens), 0)
                FROM api_usage_logs
                WHERE created_at >= datetime('now', :days_arg)
            """),
            {"days_arg": days_arg},
        )
        totals = row.fetchone()

        rows = await db.execute(
            text("""
                SELECT model, SUM(total_tokens), SUM(estimated_cost_usd)
                FROM api_usage_logs
                WHERE created_at >= datetime('now', :days_arg)
                GROUP BY model
            """),
            {"days_arg": days_arg},
        )
        by_model = {r[0]: {"tokens": r[1], "cost": r[2]} for r in rows.fetchall()}

        rows = await db.execute(
            text("""
                SELECT agent_name, SUM(total_tokens), SUM(estimated_cost_usd)
                FROM api_usage_logs
                WHERE created_at >= datetime('now', :days_arg)
                GROUP BY agent_name
            """),
            {"days_arg": days_arg},
        )
        by_agent = {r[0]: {"tokens": r[1], "cost": r[2]} for r in rows.fetchall()}

        rows = await db.execute(
            text("""
                SELECT DATE(created_at), SUM(total_tokens), SUM(estimated_cost_usd)
                FROM api_usage_logs
                WHERE created_at >= datetime('now', :days_arg)
                GROUP BY DATE(created_at)
                ORDER BY DATE(created_at)
            """),
            {"days_arg": days_arg},
        )
        daily_trend = [{"day": r[0], "tokens": r[1], "cost": r[2]} for r in rows.fetchall()]

        return {
            "total_cost": totals[0] if totals else 0,
            "total_tokens": totals[1] if totals else 0,
            "by_model": by_model,
            "by_agent": by_agent,
            "daily_trend": daily_trend,
        }


async def get_project_cost(project_name: str) -> dict:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        row = await db.execute(
            text("""
                SELECT COALESCE(SUM(estimated_cost_usd), 0),
                       COALESCE(SUM(total_tokens), 0),
                       COUNT(*)
                FROM api_usage_logs
                WHERE project_name = :project_name
            """),
            {"project_name": project_name},
        )
        result = row.fetchone()
        return {
            "project_name": project_name,
            "total_cost": result[0] if result else 0,
            "total_tokens": result[1] if result else 0,
            "call_count": result[2] if result else 0,
        }


# ── Finance Budgets ──────────────────────────────────────────────────────────

async def set_budget(
    category: str,
    budget_type: str,
    budget_limit_usd: float,
    period_start: str = "",
    period_end: str = "",
) -> int:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        existing = await db.execute(
            text(
                "SELECT id FROM finance_budgets WHERE category = :category AND budget_type = :budget_type AND is_active = 1"
            ),
            {"category": category, "budget_type": budget_type},
        )
        row = existing.fetchone()
        now = datetime.now(timezone.utc).isoformat()
        if row:
            await db.execute(
                text(
                    "UPDATE finance_budgets SET budget_limit_usd = :limit, period_start = :period_start, period_end = :period_end, updated_at = :now WHERE id = :id"
                ),
                {
                    "limit": budget_limit_usd,
                    "period_start": period_start,
                    "period_end": period_end,
                    "now": now,
                    "id": row[0],
                },
            )
            await db.commit()
            return row[0]
        else:
            result = await db.execute(
                text("""
                    INSERT INTO finance_budgets
                        (category, budget_type, budget_limit_usd, spent_usd, period_start, period_end, is_active, created_at, updated_at)
                    VALUES (:category, :budget_type, :budget_limit_usd, :spent_usd, :period_start, :period_end, 1, :now, :now)
                """),
                {
                    "category": category,
                    "budget_type": budget_type,
                    "budget_limit_usd": budget_limit_usd,
                    "spent_usd": 0.0,
                    "period_start": period_start,
                    "period_end": period_end,
                    "now": now,
                },
            )
            await db.commit()
            return result.lastrowid or 0


async def get_active_budgets() -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = await db.execute(
            text("SELECT * FROM finance_budgets WHERE is_active = 1 ORDER BY category")
        )
        return [dict(r._mapping) for r in rows.fetchall()]


async def check_budget_available(category: str, estimated_cost_usd: float) -> bool:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        row = await db.execute(
            text(
                "SELECT budget_limit_usd, spent_usd FROM finance_budgets WHERE category = :category AND is_active = 1"
            ),
            {"category": category},
        )
        result = row.fetchone()
        if not result:
            return True  # no budget set means no limit
        return (result[1] + estimated_cost_usd) <= result[0]


async def record_spend(category: str, amount_usd: float) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            text(
                "UPDATE finance_budgets SET spent_usd = spent_usd + :amount, updated_at = :now WHERE category = :category AND is_active = 1"
            ),
            {"amount": amount_usd, "now": now, "category": category},
        )
        await db.commit()


# ── Chat Messages ────────────────────────────────────────────────────────────

async def save_chat_message(
    role: str,
    content: str,
    agent_name: str = "",
    metadata: dict = None,
) -> int:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        result = await db.execute(
            text("""
                INSERT INTO chat_messages (role, content, agent_name, metadata_json, created_at)
                VALUES (:role, :content, :agent_name, :metadata_json, :created_at)
            """),
            {
                "role": role,
                "content": content,
                "agent_name": agent_name,
                "metadata_json": json.dumps(metadata or {}),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        await db.commit()
        return result.lastrowid or 0


async def get_chat_history(limit: int = 100) -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = await db.execute(
            text("SELECT * FROM chat_messages ORDER BY created_at DESC LIMIT :lim"),
            {"lim": limit},
        )
        return [dict(r._mapping) for r in rows.fetchall()]


async def get_pending_instructions(agent_name: str) -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = await db.execute(
            text("SELECT * FROM chat_messages WHERE role = 'user' ORDER BY created_at ASC"),
        )
        results = []
        for r in rows.fetchall():
            d = dict(r._mapping)
            meta = json.loads(d.get("metadata_json", "{}"))
            if meta.get("target_agent") == agent_name and not meta.get("processed", False):
                results.append(d)
        return results


# ── Event Logs ───────────────────────────────────────────────────────────────

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
                "created_at": datetime.now(timezone.utc).isoformat(),
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

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from shared.config import load_config
from shared.constants import (
    MAX_SIGNALS_PER_BATCH,
    TRUNC_AI_ANALYSIS,
    TRUNC_CHANGELOG,
    TRUNC_ERROR,
    TRUNC_FEEDBACK_TEXT,
    TRUNC_RAW_ANALYSIS,
)
from shared.models import DecisionPoint, ProjectState, TaskRecord

_engine_cache = None


def _get_engine() -> AsyncEngine:
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
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                genre TEXT DEFAULT '',
                phase TEXT NOT NULL DEFAULT 'backlog',
                progress REAL DEFAULT 0.0,
                proposal TEXT,
                gdd TEXT,
                code_path TEXT,
                art_status TEXT DEFAULT 'pending',
                music_status TEXT DEFAULT 'pending',
                qa_result TEXT,
                itch_url TEXT,
                version TEXT DEFAULT '0.0.0',
                awaiting_decision TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """))
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS decisions (
                id TEXT PRIMARY KEY,
                project_id TEXT,
                decision_type TEXT NOT NULL,
                question TEXT NOT NULL,
                options TEXT NOT NULL DEFAULT '[]',
                context TEXT DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'pending',
                human_response TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                resolved_at TEXT
            )
        """))
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                project_id TEXT,
                task_type TEXT NOT NULL,
                params TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                progress REAL DEFAULT 0.0,
                result TEXT,
                error TEXT,
                retry_count INTEGER DEFAULT 0,
                retry_strategy TEXT DEFAULT '',
                layer INTEGER DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                started_at TEXT,
                completed_at TEXT
            )
        """))
        # Referenced by save_pipeline_state() and dashboard /api/status endpoints.
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS orchestrator_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phase TEXT,
                current_project_id TEXT,
                errors TEXT,
                updated_at TEXT
            )
        """))
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS market_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                genre TEXT,
                title TEXT,
                data TEXT NOT NULL DEFAULT '{}',
                score REAL DEFAULT 0.0,
                captured_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """))
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS game_projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                genre TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'proposed',
                gdd TEXT,
                proposal TEXT,
                itch_url TEXT,
                current_version TEXT DEFAULT '0.0.0',
                feedback_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                published_at TEXT
            )
        """))
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS company_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT,
                importance REAL DEFAULT 0.5,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """))

        # Schema migrations for existing tables
        existing_cols = {row[1] for row in (await db.execute(text("PRAGMA table_info(projects)"))).fetchall()}
        if "music_status" not in existing_cols:
            await db.execute(text("ALTER TABLE projects ADD COLUMN music_status TEXT DEFAULT 'pending'"))
        if "feedback_count" not in existing_cols:
            await db.execute(text("ALTER TABLE projects ADD COLUMN feedback_count INTEGER DEFAULT 0"))

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
                "error": (error or "")[:TRUNC_ERROR],
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
                "raw_analysis": (raw_analysis or "")[:TRUNC_RAW_ANALYSIS],
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
            current_project_id = None
            if project_name:
                result = await db.execute(
                    text("SELECT id FROM game_projects WHERE name = :name"),
                    {"name": project_name},
                )
                row = result.fetchone()
                if row:
                    current_project_id = row[0]
                else:
                    insert_result = await db.execute(
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
                    current_project_id = insert_result.lastrowid

            await db.execute(
                text("""
                    INSERT INTO orchestrator_state (phase, current_project_id, errors, updated_at)
                    VALUES (:phase, :project_id, :errors, :updated_at)
                """),
                {
                    "phase": phase,
                    "project_id": current_project_id,
                    "errors": json.dumps(errors or []),
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
                "text": text[:TRUNC_FEEDBACK_TEXT],
                "posted_at": posted_at or datetime.now(timezone.utc).isoformat(),
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
                "changelog": changelog[:TRUNC_CHANGELOG],
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
        for sig in signals[:MAX_SIGNALS_PER_BATCH]:
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
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Failed to insert market signal: {e}")
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
            text("SELECT * FROM chat_messages ORDER BY created_at ASC LIMIT :lim"),
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
                meta["processed"] = True
                await db.execute(
                    text("UPDATE chat_messages SET metadata_json=:meta WHERE id=:id"),
                    {"meta": json.dumps(meta), "id": d["id"]},
                )
        await db.commit()
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


# ── Projects (multi-project) ──────────────────────────────────────────────────

async def save_project(project) -> str:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(timezone.utc).isoformat()
        existing = await db.execute(
            text("SELECT id FROM projects WHERE id = :id"),
            {"id": project.id},
        )
        if existing.fetchone():
            await db.execute(
                text("""
                    UPDATE projects SET name=:name, genre=:genre, phase=:phase,
                        progress=:progress, proposal=:proposal, gdd=:gdd,
                        code_path=:code_path, art_status=:art_status,
                        music_status=:music_status,
                        qa_result=:qa_result, itch_url=:itch_url,
                        version=:version, awaiting_decision=:awaiting_decision,
                        updated_at=:updated_at
                    WHERE id=:id
                """),
                {
                    "id": project.id,
                    "name": project.name,
                    "genre": project.genre,
                    "phase": project.phase.value if hasattr(project.phase, "value") else project.phase,
                    "progress": project.progress,
                    "proposal": json.dumps(project.proposal) if project.proposal else None,
                    "gdd": json.dumps(project.gdd) if project.gdd else None,
                    "code_path": project.code_path,
                    "art_status": project.art_status,
                    "music_status": project.music_status,
                    "qa_result": json.dumps(project.qa_result) if project.qa_result else None,
                    "itch_url": project.itch_url,
                    "version": project.version,
                    "awaiting_decision": project.awaiting_decision,
                    "updated_at": now,
                },
            )
        else:
            await db.execute(
                text("""
                    INSERT INTO projects (id, name, genre, phase, progress, proposal, gdd,
                        code_path, art_status, music_status, qa_result, itch_url, version,
                        awaiting_decision, created_at, updated_at)
                    VALUES (:id, :name, :genre, :phase, :progress, :proposal, :gdd,
                        :code_path, :art_status, :music_status, :qa_result, :itch_url, :version,
                        :awaiting_decision, :created_at, :updated_at)
                """),
                {
                    "id": project.id,
                    "name": project.name,
                    "genre": project.genre,
                    "phase": project.phase.value if hasattr(project.phase, "value") else project.phase,
                    "progress": project.progress,
                    "proposal": json.dumps(project.proposal) if project.proposal else None,
                    "gdd": json.dumps(project.gdd) if project.gdd else None,
                    "code_path": project.code_path,
                    "art_status": project.art_status,
                    "music_status": project.music_status,
                    "qa_result": json.dumps(project.qa_result) if project.qa_result else None,
                    "itch_url": project.itch_url,
                    "version": project.version,
                    "awaiting_decision": project.awaiting_decision,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        await db.commit()
        return project.id


async def get_project(project_id: str):
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
        rows = await db.execute(
            text("SELECT * FROM projects ORDER BY updated_at DESC")
        )
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
        now = datetime.now(timezone.utc).isoformat()
        if progress is not None:
            await db.execute(
                text("UPDATE projects SET phase=:phase, progress=:progress, updated_at=:now WHERE id=:id"),
                {"phase": phase, "progress": progress, "now": now, "id": project_id},
            )
        else:
            await db.execute(
                text("UPDATE projects SET phase=:phase, updated_at=:now WHERE id=:id"),
                {"phase": phase, "now": now, "id": project_id},
            )
        await db.commit()


def _parse_datetime(val: str | None) -> datetime:
    if not val:
        return datetime.now(timezone.utc)
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(val)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def _row_to_project(d: dict) -> ProjectState:
    from shared.models import ProjectState, ProjectPhase
    return ProjectState(
        id=d["id"],
        name=d["name"],
        genre=d.get("genre", ""),
        phase=ProjectPhase(d.get("phase", "backlog")),
        progress=d.get("progress", 0.0),
        proposal=json.loads(d["proposal"]) if d.get("proposal") else None,
        gdd=json.loads(d["gdd"]) if d.get("gdd") else None,
        code_path=d.get("code_path"),
        art_status=d.get("art_status", "pending"),
        music_status=d.get("music_status", "pending"),
        qa_result=json.loads(d["qa_result"]) if d.get("qa_result") else None,
        itch_url=d.get("itch_url"),
        version=d.get("version", "0.0.0"),
        awaiting_decision=d.get("awaiting_decision"),
        created_at=_parse_datetime(d.get("created_at")),
        updated_at=_parse_datetime(d.get("updated_at")),
    )


# ── Decisions ────────────────────────────────────────────────────────────────

async def save_decision(decision) -> str:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            text("""
                INSERT INTO decisions (id, project_id, decision_type, question,
                    options, context, status, human_response, created_at, resolved_at)
                VALUES (:id, :project_id, :decision_type, :question,
                    :options, :context, :status, :human_response, :created_at, :resolved_at)
            """),
            {
                "id": decision.id,
                "project_id": decision.project_id,
                "decision_type": decision.decision_type.value if hasattr(decision.decision_type, "value") else decision.decision_type,
                "question": decision.question,
                "options": json.dumps(decision.options),
                "context": json.dumps(decision.context),
                "status": decision.status.value if hasattr(decision.status, "value") else decision.status,
                "human_response": decision.human_response,
                "created_at": now,
                "resolved_at": decision.resolved_at.isoformat() if decision.resolved_at else None,
            },
        )
        await db.commit()
        return decision.id


async def get_pending_decisions() -> list[DecisionPoint]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = await db.execute(
            text("SELECT * FROM decisions WHERE status = 'pending' ORDER BY created_at DESC")
        )
        return [_row_to_decision(dict(r._mapping)) for r in rows.fetchall()]


async def get_decision_by_id(decision_id: str) -> DecisionPoint | None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        row = await db.execute(
            text("SELECT * FROM decisions WHERE id = :id"),
            {"id": decision_id},
        )
        result = row.fetchone()
        if not result:
            return None
        return _row_to_decision(dict(result._mapping))


async def get_project_decisions(project_id: str) -> list[DecisionPoint]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = await db.execute(
            text("SELECT * FROM decisions WHERE project_id = :pid ORDER BY created_at DESC"),
            {"pid": project_id},
        )
        return [_row_to_decision(dict(r._mapping)) for r in rows.fetchall()]


async def resolve_decision(decision_id: str, response: str) -> None:
    """Mark a decision as resolved.  Status is derived from *response*:
    ``approve`` → ``approved``, anything else (``reject``, etc.) → ``rejected``.
    """
    status = "approved" if response == "approve" else "rejected"
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            text("UPDATE decisions SET status=:status, human_response=:response, resolved_at=:now WHERE id=:id"),
            {"status": status, "response": response, "now": now, "id": decision_id},
        )
        await db.commit()


def _row_to_decision(d: dict) -> DecisionPoint:
    from shared.models import DecisionPoint, DecisionType, DecisionStatus
    return DecisionPoint(
        id=d["id"],
        project_id=d.get("project_id"),
        decision_type=DecisionType(d.get("decision_type", "new_project")),
        question=d["question"],
        options=json.loads(d.get("options", "[]")),
        context=json.loads(d.get("context", "{}")),
        status=DecisionStatus(d.get("status", "pending")),
        human_response=d.get("human_response"),
        created_at=_parse_datetime(d.get("created_at")),
        resolved_at=_parse_datetime(d.get("resolved_at")) if d.get("resolved_at") else None,
    )


# ── Tasks ──────────────────────────────────────────────────────────────────────

async def save_task(task) -> str:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            text("""
                INSERT INTO tasks (id, project_id, task_type, status, progress,
                    params, result, error, started_at, completed_at, created_at)
                VALUES (:id, :project_id, :task_type, :status, :progress,
                    :params, :result, :error, :started_at, :completed_at, :created_at)
            """),
            {
                "id": task.id,
                "project_id": task.project_id,
                "task_type": task.task_type,
                "status": task.status.value if hasattr(task.status, "value") else task.status,
                "progress": task.progress,
                "params": json.dumps(task.params),
                "result": json.dumps(task.result) if task.result else None,
                "error": task.error,
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                "created_at": now,
            },
        )
        await db.commit()
        return task.id


async def get_task(task_id: str):
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        row = await db.execute(
            text("SELECT * FROM tasks WHERE id = :id"),
            {"id": task_id},
        )
        result = row.fetchone()
        if not result:
            return None
        return _row_to_task(dict(result._mapping))


async def get_project_tasks(project_id: str) -> list[TaskRecord]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = await db.execute(
            text("SELECT * FROM tasks WHERE project_id = :pid ORDER BY created_at DESC"),
            {"pid": project_id},
        )
        return [_row_to_task(dict(r._mapping)) for r in rows.fetchall()]


async def get_pending_tasks() -> list[TaskRecord]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = await db.execute(
            text("SELECT * FROM tasks WHERE status IN ('pending', 'running') ORDER BY created_at ASC")
        )
        return [_row_to_task(dict(r._mapping)) for r in rows.fetchall()]


async def update_task_status(
    task_id: str,
    status: str,
    progress: float | None = None,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(timezone.utc).isoformat()
        sets = ["status=:status"]
        params: dict = {"id": task_id, "status": status}
        if progress is not None:
            sets.append("progress=:progress")
            params["progress"] = progress
        if result is not None:
            sets.append("result=:result")
            params["result"] = json.dumps(result)
        if error is not None:
            sets.append("error=:error")
            params["error"] = error
        if status in ("completed", "failed", "cancelled"):
            sets.append("completed_at=:completed_at")
            params["completed_at"] = now
        elif status == "running":
            sets.append("started_at=:started_at")
            params["started_at"] = now
        await db.execute(
            text(f"UPDATE tasks SET {', '.join(sets)} WHERE id=:id"),
            params,
        )
        await db.commit()


def _row_to_task(d: dict) -> TaskRecord:
    from shared.models import TaskRecord, TaskStatus
    return TaskRecord(
        id=d["id"],
        project_id=d["project_id"],
        task_type=d["task_type"],
        status=TaskStatus(d.get("status", "pending")),
        progress=d.get("progress", 0.0),
        params=json.loads(d.get("params", "{}")),
        result=json.loads(d["result"]) if d.get("result") else None,
        error=d.get("error"),
        started_at=d.get("started_at"),
        completed_at=d.get("completed_at"),
        created_at=_parse_datetime(d.get("created_at")),
    )


# ── Targeted update helpers (replaces raw SQL in scheduler/decision_gate) ────

async def update_project_awaiting_decision(project_id: str, decision_id: str | None) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(timezone.utc).isoformat()
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
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            text("UPDATE projects SET phase=:phase, proposal=:proposal, updated_at=:now WHERE id=:id"),
            {"phase": phase, "proposal": json.dumps(proposal), "now": now, "id": project_id},
        )
        await db.commit()


async def update_project_gdd(project_id: str, gdd: dict) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            text("UPDATE projects SET gdd=:gdd, updated_at=:now WHERE id=:id"),
            {"gdd": json.dumps(gdd), "now": now, "id": project_id},
        )
        await db.commit()


async def update_project_art_status(project_id: str, status: str = "done") -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            text("UPDATE projects SET art_status=:s, updated_at=:now WHERE id=:id"),
            {"s": status, "now": now, "id": project_id},
        )
        await db.commit()


async def update_project_music_status(project_id: str, status: str = "done") -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            text("UPDATE projects SET music_status=:s, updated_at=:now WHERE id=:id"),
            {"s": status, "now": now, "id": project_id},
        )
        await db.commit()


async def update_project_code_path(project_id: str, code_path: str) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            text("UPDATE projects SET code_path=:cp, updated_at=:now WHERE id=:id"),
            {"cp": code_path, "now": now, "id": project_id},
        )
        await db.commit()


async def update_project_qa_result(project_id: str, qa_result: dict) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            text("UPDATE projects SET qa_result=:qr, updated_at=:now WHERE id=:id"),
            {"qr": json.dumps(qa_result), "now": now, "id": project_id},
        )
        await db.commit()


async def update_project_build_path(project_id: str, build_path: str) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            text("UPDATE projects SET code_path=:bp, updated_at=:now WHERE id=:id"),
            {"bp": build_path, "now": now, "id": project_id},
        )
        await db.commit()


async def set_project_live(
    project_id: str, itch_url: str, version: str = "0.0.0"
) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            text(
                "UPDATE projects SET itch_url=:url, version=:ver, phase='live', "
                "awaiting_decision=NULL, updated_at=:now WHERE id=:id"
            ),
            {"url": itch_url, "ver": version, "now": now, "id": project_id},
        )
        await db.commit()


# ── CEO Helpers ───────────────────────────────────────────────────────────────


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
        return {"id": row.id, "name": row.name, "itch_url": row.itch_url,
                "unprocessed_count": row.unprocessed_count}
    return None


async def mark_instruction_processed(instruction_id: str, metadata: dict) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        await db.execute(
            text("UPDATE chat_messages SET metadata_json = :meta WHERE id = :mid"),
            {"meta": json.dumps(metadata), "mid": instruction_id},
        )
        await db.commit()


# ── Scheduler Helpers ─────────────────────────────────────────────────────────


async def get_latest_market_report() -> dict | None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = await db.execute(
            text("SELECT id, opportunities_json FROM market_reports ORDER BY id DESC LIMIT 1")
        )
        row = rows.fetchone()
    if row:
        return {"id": row.id, "opportunities_json": row.opportunities_json}
    return None


async def count_completed_tasks(project_id: str) -> int:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = await db.execute(
            text("SELECT COUNT(*) FROM tasks WHERE project_id=:pid AND status='completed'"),
            {"pid": project_id},
        )
        return rows.scalar() or 0


async def get_api_usage_summary() -> dict:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        row = (await db.execute(
            text("SELECT COUNT(*) as calls, COALESCE(SUM(estimated_cost_usd), 0) as total_cost FROM api_usage_logs")
        )).fetchone()
    return {"calls": row[0] if row else 0, "total_cost": float(row[1]) if row else 0.0}


async def get_recent_completed_tasks(limit: int = 5) -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = (await db.execute(
            text("SELECT task_type, project_id, completed_at FROM tasks WHERE status='completed' ORDER BY completed_at DESC LIMIT :lim"),
            {"lim": limit},
        )).fetchall()
    return [{"task_type": r.task_type, "project_id": r.project_id, "completed_at": r.completed_at} for r in rows]


# ── API Server Helpers ────────────────────────────────────────────────────────


async def get_orchestrator_state() -> dict | None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        row = (await db.execute(
            text("SELECT phase, errors FROM orchestrator_state ORDER BY id DESC LIMIT 1")
        )).fetchone()
    if row:
        return {"phase": row.phase, "errors": row.errors}
    return None


async def get_last_scan_time() -> str | None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        row = (await db.execute(
            text("SELECT MAX(captured_at) as last_scan FROM market_signals")
        )).fetchone()
    return row.last_scan if row and row.last_scan else None


async def get_latest_project() -> dict | None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        row = (await db.execute(
            text("SELECT name, status FROM game_projects ORDER BY updated_at DESC LIMIT 1")
        )).fetchone()
    if row:
        return {"name": row.name, "status": row.status}
    return None


async def get_orchestrator_history(limit: int = 20) -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = (await db.execute(
            text("SELECT phase, updated_at, errors FROM orchestrator_state ORDER BY id DESC LIMIT :lim"),
            {"lim": limit},
        )).fetchall()
    return [{"phase": r.phase, "updated_at": r.updated_at, "errors": r.errors} for r in rows]


async def get_market_report_detail() -> dict | None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        row = (await db.execute(
            text("SELECT * FROM market_reports ORDER BY id DESC LIMIT 1")
        )).fetchone()
    if row:
        return dict(row._mapping)
    return None


async def get_project_gdd(project_id: str) -> dict | None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        row = (await db.execute(
            text("SELECT name, gdd, proposal FROM game_projects WHERE id = :pid"),
            {"pid": project_id},
        )).fetchone()
    if row:
        return {"name": row.name, "gdd": row.gdd, "proposal": row.proposal}
    return None


async def find_project_by_name(name: str) -> str | None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        row = (await db.execute(
            text("SELECT id FROM game_projects WHERE name = :name"),
            {"name": name},
        )).fetchone()
    return row.id if row else None


async def get_pending_feedback(project_id: str) -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = (await db.execute(
            text("SELECT * FROM game_feedback WHERE project_id = :pid AND processed = 0 ORDER BY posted_at DESC"),
            {"pid": project_id},
        )).fetchall()
    return [dict(r._mapping) for r in rows]


async def get_all_feedback(project_id: str) -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = (await db.execute(
            text("SELECT * FROM game_feedback WHERE project_id = :pid ORDER BY posted_at DESC LIMIT 50"),
            {"pid": project_id},
        )).fetchall()
    return [dict(r._mapping) for r in rows]


async def save_user_genre_directive(genre: str, instruction: str, now: str) -> None:
    import json as _json
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        await db.execute(
            text("""
                INSERT INTO company_memory (category, title, content, importance, created_at)
                VALUES ('directive', 'user_genre_directive', :content, 0.9, :now)
            """),
            {
                "content": _json.dumps({"genre": genre, "instruction": instruction, "source": "user_chat"}),
                "now": now,
            },
        )
        await db.commit()


async def get_agent_logs(limit: int = 50) -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = (await db.execute(
            text("SELECT node_name, status, phase, started_at, completed_at, duration_ms, error, project_name FROM agent_logs ORDER BY id DESC LIMIT :lim"),
            {"lim": limit},
        )).fetchall()
    return [dict(r._mapping) for r in rows]


async def get_agent_stats() -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = (await db.execute(
            text("""
                SELECT node_name, COUNT(*) as runs,
                    SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as successes,
                    SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failures,
                    ROUND(AVG(CASE WHEN duration_ms IS NOT NULL THEN duration_ms ELSE 0 END)) as avg_duration_ms
                FROM agent_logs GROUP BY node_name ORDER BY node_name
            """)
        )).fetchall()
    return [dict(r._mapping) for r in rows]


async def get_latest_market_signals(limit: int = 50) -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = (await db.execute(
            text("SELECT id, source, signal_type, genre, title, data, score, captured_at FROM market_signals ORDER BY captured_at DESC LIMIT :lim"),
            {"lim": limit},
        )).fetchall()
    signals = []
    for row in rows:
        d = dict(row._mapping)
        if isinstance(d.get("data"), str):
            d["data"] = json.loads(d["data"])
        signals.append(d)
    return signals


async def get_company_memory(limit: int = 50) -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = (await db.execute(
            text("SELECT id, category, title, content, importance, created_at FROM company_memory ORDER BY importance DESC, created_at DESC LIMIT :lim"),
            {"lim": limit},
        )).fetchall()
    memories = []
    for row in rows:
        d = dict(row._mapping)
        if isinstance(d.get("content"), str):
            try:
                d["content"] = json.loads(d["content"])
            except (json.JSONDecodeError, TypeError):
                pass
        memories.append(d)
    return memories

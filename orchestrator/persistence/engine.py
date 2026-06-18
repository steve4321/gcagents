"""Shared database engine, schema bootstrap, and common helpers.

All domain submodules import :func:`_get_engine` from here.  The
``orchestrator_state`` table helpers also live here because they are
tightly coupled to the engine bootstrap.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from shared.config import load_config

_engine_cache = None


def _get_engine() -> AsyncEngine:
    global _engine_cache
    if _engine_cache is None:
        config = load_config()
        _engine_cache = create_async_engine(
            config.db_url,
            echo=False,
            connect_args={"timeout": 30},
        )

        @event.listens_for(_engine_cache.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return _engine_cache


async def ensure_tables():
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        await db.execute(
            text("""
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
        """)
        )
        await db.execute(
            text("""
            CREATE TABLE IF NOT EXISTS market_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signals_count INTEGER DEFAULT 0,
                opportunities_json TEXT,
                raw_analysis TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        )
        await db.execute(
            text("""
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
        """)
        )
        await db.execute(
            text("""
            CREATE TABLE IF NOT EXISTS game_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                version TEXT NOT NULL,
                gdd_snapshot TEXT,
                changelog TEXT DEFAULT '',
                feedback_ids TEXT DEFAULT '[]',
                build_size INTEGER DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        )
        await db.execute(
            text("""
            CREATE TABLE IF NOT EXISTS game_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                metric_name TEXT NOT NULL,
                metric_value REAL NOT NULL,
                recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        )
        await db.execute(
            text("""
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
        """)
        )
        await db.execute(
            text("""
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
        """)
        )
        await db.execute(
            text("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                agent_name TEXT DEFAULT '',
                metadata_json TEXT DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        )
        await db.execute(
            text("""
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
        """)
        )
        await db.execute(
            text("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                genre TEXT DEFAULT '',
                phase TEXT NOT NULL DEFAULT 'backlog',
                progress REAL DEFAULT 0.0,
                proposal TEXT,
                gdd TEXT,
                code_path TEXT,
                art_assets_path TEXT DEFAULT '',
                art_status TEXT DEFAULT 'pending',
                music_status TEXT DEFAULT 'pending',
                qa_result TEXT,
                itch_url TEXT,
                version TEXT DEFAULT '0.0.0',
                awaiting_decision TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        )
        await db.execute(
            text("""
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
        """)
        )
        await db.execute(
            text("""
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
        """)
        )
        # Referenced by save_pipeline_state() and dashboard /api/status endpoints.
        await db.execute(
            text("""
            CREATE TABLE IF NOT EXISTS orchestrator_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phase TEXT,
                current_project_id TEXT,
                errors TEXT,
                updated_at TEXT
            )
        """)
        )
        await db.execute(
            text("""
            CREATE TABLE IF NOT EXISTS company_policy (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                budget_limit_usd REAL DEFAULT 5.0,
                preferred_genres TEXT DEFAULT '[]',
                auto_publish INTEGER DEFAULT 1,
                auto_cancel INTEGER DEFAULT 1,
                require_new_project_approval INTEGER DEFAULT 1,
                working_hours_start INTEGER DEFAULT 9,
                working_hours_end INTEGER DEFAULT 23,
                max_active_projects INTEGER DEFAULT 3,
                decision_timeout_hours INTEGER DEFAULT 24,
                timeout_action TEXT DEFAULT 'reject',
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        )
        await db.execute(
            text("""
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
        """)
        )
        await db.execute(
            text("""
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
        """)
        )
        await db.execute(
            text("""
            CREATE TABLE IF NOT EXISTS company_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT,
                importance REAL DEFAULT 0.5,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        )
        await db.execute(
            text("""
            CREATE TABLE IF NOT EXISTS itch_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                itch_game_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                itch_url TEXT,
                downloads_count INTEGER DEFAULT 0,
                views_count INTEGER DEFAULT 0,
                purchases_count INTEGER DEFAULT 0,
                fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        )

        # Schema migrations for existing tables
        existing_cols = {
            row[1] for row in (await db.execute(text("PRAGMA table_info(projects)"))).fetchall()
        }
        if "music_status" not in existing_cols:
            await db.execute(
                text("ALTER TABLE projects ADD COLUMN music_status TEXT DEFAULT 'pending'")
            )
        if "feedback_count" not in existing_cols:
            await db.execute(
                text("ALTER TABLE projects ADD COLUMN feedback_count INTEGER DEFAULT 0")
            )
        if "art_assets_path" not in existing_cols:
            await db.execute(
                text("ALTER TABLE projects ADD COLUMN art_assets_path TEXT DEFAULT ''")
            )
        if "platform_urls" not in existing_cols:
            await db.execute(
                text("ALTER TABLE projects ADD COLUMN platform_urls TEXT DEFAULT '{}'")
            )

        policy_cols = {
            row[1]
            for row in (await db.execute(text("PRAGMA table_info(company_policy)"))).fetchall()
        }
        if "max_dev_projects" not in policy_cols:
            await db.execute(
                text("ALTER TABLE company_policy ADD COLUMN max_dev_projects INTEGER DEFAULT 3")
            )
        if "max_live_projects" not in policy_cols:
            await db.execute(
                text("ALTER TABLE company_policy ADD COLUMN max_live_projects INTEGER DEFAULT 5")
            )

        await db.execute(text("CREATE INDEX IF NOT EXISTS idx_projects_phase ON projects(phase)"))
        await db.execute(
            text("CREATE INDEX IF NOT EXISTS idx_projects_updated_at ON projects(updated_at)")
        )
        await db.execute(
            text("CREATE INDEX IF NOT EXISTS idx_tasks_project_id ON tasks(project_id)")
        )
        await db.execute(text("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)"))
        await db.execute(
            text("CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at)")
        )
        await db.execute(
            text("CREATE INDEX IF NOT EXISTS idx_decisions_project_id ON decisions(project_id)")
        )
        await db.execute(
            text("CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions(status)")
        )
        await db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_game_feedback_project_id ON game_feedback(project_id)"
            )
        )
        await db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_game_feedback_processed ON game_feedback(processed)"
            )
        )
        await db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_game_versions_project_id ON game_versions(project_id)"
            )
        )
        await db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_game_metrics_project_id ON game_metrics(project_id)"
            )
        )
        await db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_api_usage_logs_project_name ON api_usage_logs(project_name)"
            )
        )
        await db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_api_usage_logs_created_at ON api_usage_logs(created_at)"
            )
        )
        await db.execute(
            text("CREATE INDEX IF NOT EXISTS idx_chat_messages_role ON chat_messages(role)")
        )
        await db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_market_signals_captured_at ON market_signals(captured_at)"
            )
        )
        await db.execute(
            text("CREATE INDEX IF NOT EXISTS idx_event_logs_event_type ON event_logs(event_type)")
        )
        await db.execute(
            text("CREATE INDEX IF NOT EXISTS idx_event_logs_created_at ON event_logs(created_at)")
        )
        await db.execute(
            text("CREATE INDEX IF NOT EXISTS idx_itch_stats_project_id ON itch_stats(project_id)")
        )
        await db.execute(
            text("CREATE INDEX IF NOT EXISTS idx_itch_stats_fetched_at ON itch_stats(fetched_at)")
        )

        await db.commit()


def _parse_datetime(val: str | None) -> datetime:
    if not val:
        return datetime.now(UTC)
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(val)
    except (ValueError, TypeError):
        return datetime.now(UTC)


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
                            "created_at": datetime.now(UTC).isoformat(),
                            "updated_at": datetime.now(UTC).isoformat(),
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
                    "updated_at": datetime.now(UTC).isoformat(),
                },
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def get_orchestrator_state() -> dict | None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        row = (
            await db.execute(
                text("SELECT phase, errors FROM orchestrator_state ORDER BY id DESC LIMIT 1")
            )
        ).fetchone()
    if row:
        return {"phase": row.phase, "errors": row.errors}
    return None


async def get_orchestrator_history(limit: int = 20) -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = (
            await db.execute(
                text(
                    "SELECT phase, updated_at, errors FROM orchestrator_state ORDER BY id DESC LIMIT :lim"
                ),
                {"lim": limit},
            )
        ).fetchall()
    return [{"phase": r.phase, "updated_at": r.updated_at, "errors": r.errors} for r in rows]

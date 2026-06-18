"""Company policy singleton (company_policy table)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.persistence.engine import _get_engine


async def get_company_policy() -> dict:
    """Get the company policy (singleton row). Returns default policy if none exists."""
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        row = await db.execute(text("SELECT * FROM company_policy WHERE id = 1"))
        result = row.fetchone()
        if not result:
            return {
                "budget_limit_usd": 5.0,
                "preferred_genres": [],
                "auto_publish": True,
                "auto_cancel": True,
                "require_new_project_approval": True,
                "working_hours_start": 9,
                "working_hours_end": 23,
                "max_active_projects": 3,
                "max_dev_projects": 3,
                "max_live_projects": 5,
                "decision_timeout_hours": 24,
                "timeout_action": "reject",
            }
        d = dict(result._mapping)
        d["preferred_genres"] = json.loads(d.get("preferred_genres", "[]"))
        d["auto_publish"] = bool(d.get("auto_publish", 1))
        d["auto_cancel"] = bool(d.get("auto_cancel", 1))
        d["require_new_project_approval"] = bool(d.get("require_new_project_approval", 1))
        return d


async def set_company_policy(policy: dict) -> None:
    """Upsert the company policy (singleton row)."""
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(UTC).isoformat()
        existing = await db.execute(text("SELECT id FROM company_policy WHERE id = 1"))
        if existing.fetchone():
            await db.execute(
                text("""
                    UPDATE company_policy SET
                        budget_limit_usd=:budget_limit_usd,
                        preferred_genres=:preferred_genres,
                        auto_publish=:auto_publish,
                        auto_cancel=:auto_cancel,
                        require_new_project_approval=:require_new_project_approval,
                        working_hours_start=:working_hours_start,
                        working_hours_end=:working_hours_end,
                        max_active_projects=:max_active_projects,
                        max_dev_projects=:max_dev_projects,
                        max_live_projects=:max_live_projects,
                        decision_timeout_hours=:decision_timeout_hours,
                        timeout_action=:timeout_action,
                        updated_at=:updated_at
                    WHERE id = 1
                """),
                {
                    "budget_limit_usd": policy.get("budget_limit_usd", 5.0),
                    "preferred_genres": json.dumps(policy.get("preferred_genres", [])),
                    "auto_publish": 1 if policy.get("auto_publish", True) else 0,
                    "auto_cancel": 1 if policy.get("auto_cancel", True) else 0,
                    "require_new_project_approval": 1
                    if policy.get("require_new_project_approval", True)
                    else 0,
                    "working_hours_start": policy.get("working_hours_start", 9),
                    "working_hours_end": policy.get("working_hours_end", 23),
                    "max_active_projects": policy.get("max_active_projects", 3),
                    "max_dev_projects": policy.get("max_dev_projects", 3),
                    "max_live_projects": policy.get("max_live_projects", 5),
                    "decision_timeout_hours": policy.get("decision_timeout_hours", 24),
                    "timeout_action": policy.get("timeout_action", "reject"),
                    "updated_at": now,
                },
            )
        else:
            await db.execute(
                text("""
                    INSERT INTO company_policy
                        (id, budget_limit_usd, preferred_genres, auto_publish, auto_cancel,
                         require_new_project_approval, working_hours_start, working_hours_end,
                         max_active_projects, max_dev_projects, max_live_projects,
                         decision_timeout_hours, timeout_action, updated_at)
                    VALUES (1, :budget_limit_usd, :preferred_genres, :auto_publish, :auto_cancel,
                            :require_new_project_approval, :working_hours_start, :working_hours_end,
                            :max_active_projects, :max_dev_projects, :max_live_projects,
                            :decision_timeout_hours, :timeout_action, :updated_at)
                """),
                {
                    "budget_limit_usd": policy.get("budget_limit_usd", 5.0),
                    "preferred_genres": json.dumps(policy.get("preferred_genres", [])),
                    "auto_publish": 1 if policy.get("auto_publish", True) else 0,
                    "auto_cancel": 1 if policy.get("auto_cancel", True) else 0,
                    "require_new_project_approval": 1
                    if policy.get("require_new_project_approval", True)
                    else 0,
                    "working_hours_start": policy.get("working_hours_start", 9),
                    "working_hours_end": policy.get("working_hours_end", 23),
                    "max_active_projects": policy.get("max_active_projects", 3),
                    "max_dev_projects": policy.get("max_dev_projects", 3),
                    "max_live_projects": policy.get("max_live_projects", 5),
                    "decision_timeout_hours": policy.get("decision_timeout_hours", 24),
                    "timeout_action": policy.get("timeout_action", "reject"),
                    "updated_at": now,
                },
            )
        await db.commit()

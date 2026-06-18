"""Finance budgets and API usage cost tracking."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.persistence.engine import _get_engine


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
        now = datetime.now(UTC).isoformat()
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
        now = datetime.now(UTC).isoformat()
        await db.execute(
            text(
                "UPDATE finance_budgets SET spent_usd = spent_usd + :amount, updated_at = :now WHERE category = :category AND is_active = 1"
            ),
            {"amount": amount_usd, "now": now, "category": category},
        )
        await db.commit()


async def get_api_usage_summary() -> dict:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        row = (
            await db.execute(
                text(
                    "SELECT COUNT(*) as calls, COALESCE(SUM(estimated_cost_usd), 0) as total_cost FROM api_usage_logs"
                )
            )
        ).fetchone()
    return {"calls": row[0] if row else 0, "total_cost": float(row[1]) if row else 0.0}

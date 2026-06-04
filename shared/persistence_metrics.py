"""Prometheus metrics for GCAgents (text format, no external deps).

Exposes:
- gcagents_projects_total{phase="..."}
- gcagents_tasks_total{type="...",status="..."}
- gcagents_decisions_pending
- gcagents_api_cost_usd_total
- gcagents_scheduler_tick_seconds (gauge of last tick duration)
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from orchestrator.persistence import _get_engine
from shared.constants import (
    DEFAULT_ANALYSIS_MODEL,
    TRUNC_ERROR,
)


async def collect_metrics_text() -> str:
    lines: list[str] = []
    engine = _get_engine()
    from sqlalchemy.ext.asyncio import AsyncSession

    try:
        async with AsyncSession(engine) as db:
            proj_rows = (
                await db.execute(
                    text("SELECT phase, COUNT(*) FROM projects GROUP BY phase")
                )
            ).fetchall()
            lines.append("# HELP gcagents_projects_total Number of projects by phase")
            lines.append("# TYPE gcagents_projects_total gauge")
            for r in proj_rows:
                phase = (r[0] or "unknown").replace('"', '\\"')
                lines.append(f'gcagents_projects_total{{phase="{phase}"}} {r[1]}')

            task_rows = (
                await db.execute(
                    text("SELECT task_type, status, COUNT(*) FROM tasks GROUP BY task_type, status")
                )
            ).fetchall()
            lines.append("# HELP gcagents_tasks_total Number of tasks by type and status")
            lines.append("# TYPE gcagents_tasks_total gauge")
            for r in task_rows:
                ttype = (r[0] or "unknown").replace('"', '\\"')
                status = (r[1] or "unknown").replace('"', '\\"')
                lines.append(f'gcagents_tasks_total{{type="{ttype}",status="{status}"}} {r[2]}')

            try:
                dec_count = (
                    await db.execute(
                        text("SELECT COUNT(*) FROM decisions WHERE status='pending'")
                    )
                ).scalar() or 0
            except Exception:
                dec_count = 0
            lines.append("# HELP gcagents_decisions_pending Pending human approval decisions")
            lines.append("# TYPE gcagents_decisions_pending gauge")
            lines.append(f"gcagents_decisions_pending {dec_count}")

            try:
                cost_row = (
                    await db.execute(
                        text("SELECT COALESCE(SUM(estimated_cost_usd), 0) FROM api_usage_logs")
                    )
                ).fetchone()
                total_cost = float(cost_row[0] if cost_row else 0)
            except Exception:
                total_cost = 0.0
            lines.append("# HELP gcagents_api_cost_usd_total Cumulative API cost (USD)")
            lines.append("# TYPE gcagents_api_cost_usd_total counter")
            lines.append(f"gcagents_api_cost_usd_total {total_cost:.4f}")
    except Exception as e:
        lines.append(f"# scrape_error: {str(e)[:200]}")
    return "\n".join(lines) + "\n"

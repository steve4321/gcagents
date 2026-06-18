from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from dashboard.web import api_server

router = APIRouter()


# ── Finance API ────────────────────────────────────────────────────────────────


@router.post("/api/finance/budget", dependencies=[Depends(api_server.get_api_key)])
async def set_budget(budget: dict):
    from orchestrator.persistence import log_event
    from orchestrator.persistence import set_budget as db_set_budget

    category = budget.get("category", "monthly")
    budget_type = budget.get("budget_type", "monthly")
    limit_usd = budget.get("budget_limit_usd", 0)
    if not isinstance(limit_usd, (int, float)) or limit_usd < 0:
        raise HTTPException(
            status_code=400, detail="budget_limit_usd must be a non-negative number"
        )

    await db_set_budget(category, budget_type, limit_usd)
    await log_event(
        "finance", "info", f"Budget set: {category} ${limit_usd}", source_agent="dashboard"
    )
    return {"status": "ok"}


@router.get("/api/finance/summary")
async def get_finance_summary(days: int = 30):
    from orchestrator.persistence import get_active_budgets, get_usage_summary

    summary = await get_usage_summary(days)
    budgets = await get_active_budgets()
    return {"usage": summary, "budgets": budgets}


@router.get("/api/policy")
async def get_policy():
    from orchestrator.persistence import get_company_policy

    return await get_company_policy()


@router.post("/api/policy", dependencies=[Depends(api_server.get_api_key)])
async def set_policy(policy: dict):
    from orchestrator.persistence import log_event, set_company_policy

    await set_company_policy(policy)
    await log_event("policy", "info", "Company policy updated", source_agent="dashboard")
    return {"status": "ok"}

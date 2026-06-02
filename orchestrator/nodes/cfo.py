"""CFO Agent — Financial oversight and budget control."""
from __future__ import annotations

from loguru import logger

from orchestrator.state import CompanyState, PipelinePhase
from shared.llm_client import llm


async def cfo_budget_check(state: CompanyState) -> dict:
    """Check if the pipeline can proceed based on budget constraints.

    Called before expensive operations (develop, art generation).
    If budget is exceeded, route to IDLE with a financial alert.
    """
    from orchestrator.persistence import (
        check_budget_available,
        log_event,
    )

    project_name = state.current_proposal.name if state.current_proposal else "general"

    # develop step: ~50K tokens deepseek-coder ≈ $0.10
    estimated_cost = 0.10

    monthly_ok = await check_budget_available("monthly", estimated_cost)

    project_ok = True
    if state.current_project_id:
        project_ok = await check_budget_available(project_name, estimated_cost)

    if not monthly_ok:
        await log_event(
            event_type="finance",
            severity="error",
            title="Monthly budget exceeded",
            detail=f"Estimated cost ${estimated_cost:.4f} would exceed monthly budget",
            source_agent="cfo",
            project_name=project_name,
        )
        logger.warning("CFO: Monthly budget exceeded, halting pipeline")
        return {"phase": PipelinePhase.IDLE, "errors": ["Monthly budget exceeded"]}

    if not project_ok:
        await log_event(
            event_type="finance",
            severity="warning",
            title=f"Project budget exceeded: {project_name}",
            detail=f"Estimated cost ${estimated_cost:.4f} would exceed project budget",
            source_agent="cfo",
            project_name=project_name,
        )
        logger.warning(f"CFO: Project budget exceeded for {project_name}")
        return {
            "phase": PipelinePhase.IDLE,
            "errors": [f"Project budget exceeded: {project_name}"],
        }

    await log_event(
        event_type="finance",
        severity="info",
        title="Budget check passed",
        detail=f"Estimated ${estimated_cost:.4f} within budget for {project_name}",
        source_agent="cfo",
        project_name=project_name,
    )
    return {}


async def cfo_financial_report(state: CompanyState) -> dict:
    """Generate a financial summary report using LLM analysis.

    Called periodically or on demand.
    """
    from orchestrator.persistence import get_active_budgets, get_usage_summary, log_event

    summary = await get_usage_summary(days=30)
    budgets = await get_active_budgets()

    report_text = (
        f"Financial Report (Last 30 days):\n"
        f"Total Cost: ${summary.get('total_cost', 0):.4f}\n"
        f"Total Tokens: {summary.get('total_tokens', 0):,}\n"
        f"By Model: {summary.get('by_model', {})}\n"
        f"By Agent: {summary.get('by_agent', {})}\n"
        f"Active Budgets: {len(budgets)}"
    )

    # deepseek-chat model for cost analysis
    try:
        llm_response, _usage = await llm.chat_completion(
            model="deepseek-v4-flash",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a CFO analyzing game company finances. "
                        "Provide brief, actionable insights in 2-3 sentences."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Analyze this financial data and provide "
                        f"recommendations:\n{report_text}"
                    ),
                },
            ],
            max_tokens=500,
            temperature=0.3,
            agent_name="cfo",
        )
        insight = llm_response
    except Exception as e:
        logger.warning(f"CFO: LLM analysis failed: {e}")
        insight = "Financial analysis unavailable (LLM error)."

    await log_event(
        event_type="finance",
        severity="info",
        title="Financial report generated",
        detail=insight[:500],
        source_agent="cfo",
    )

    return {"messages": [{"role": "assistant", "content": insight}]}

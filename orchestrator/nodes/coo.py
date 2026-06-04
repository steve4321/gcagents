"""COO Agent — Operations oversight and pipeline health."""

from __future__ import annotations

from loguru import logger

from orchestrator.state import CompanyState, PipelinePhase


async def coo_health_check(state: CompanyState) -> dict:
    """Check pipeline health and log operational status.

    Runs at pipeline entry to assess readiness.
    """
    from orchestrator.persistence import log_event

    phase = state.phase
    errors = state.errors or []

    await log_event(
        event_type="pipeline",
        severity="info",
        title=f"Pipeline health check: {phase.value}",
        detail=f"Errors: {len(errors)}, Project: {state.current_project_id}",
        source_agent="coo",
        project_name=state.current_proposal.name if state.current_proposal else "",
    )

    if len(errors) >= 3:
        await log_event(
            event_type="pipeline",
            severity="error",
            title="Pipeline has excessive errors",
            detail=f"Error count: {len(errors)}. Last errors: {'; '.join(errors[-3:])}",
            source_agent="coo",
        )
        logger.error(f"COO: Pipeline has {len(errors)} errors, recommending halt")
        return {"phase": PipelinePhase.IDLE}

    if state.retry_count >= 3:
        await log_event(
            event_type="pipeline",
            severity="warning",
            title="Max retries reached",
            detail=f"Retry count: {state.retry_count}",
            source_agent="coo",
        )
        return {"phase": PipelinePhase.IDLE}

    return {}

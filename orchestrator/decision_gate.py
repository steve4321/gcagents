"""Five-type human approval gate system.

Decision types: new_project, publish, cancel, budget_overrun, direction_change.
Each decision is persisted to DB and resolved by human response.
"""

from __future__ import annotations

import uuid

from loguru import logger

from orchestrator.persistence import (
    get_decision_by_id,
    get_pending_decisions,
    save_decision,
)
from orchestrator.persistence import (
    resolve_decision as db_resolve_decision,
)
from shared.events import ActionType, Event
from shared.models import DecisionPoint, DecisionType

DECISION_TYPES = {
    "new_project": {
        "default_options": [
            {"label": "Approve", "value": "approve"},
            {"label": "Reject", "value": "reject"},
            {"label": "Discuss", "value": "discuss"},
        ],
    },
    "publish": {
        "default_options": [
            {"label": "Publish", "value": "approve"},
            {"label": "Reject", "value": "reject"},
            {"label": "Discuss", "value": "discuss"},
        ],
    },
    "cancel": {
        "default_options": [
            {"label": "Cancel project", "value": "approve"},
            {"label": "Keep going", "value": "reject"},
            {"label": "Discuss", "value": "discuss"},
        ],
    },
    "budget_overrun": {
        "default_options": [
            {"label": "Continue", "value": "approve"},
            {"label": "Pause", "value": "reject"},
            {"label": "Discuss", "value": "discuss"},
        ],
    },
    "direction_change": {
        "default_options": [
            {"label": "Change direction", "value": "approve"},
            {"label": "Keep current", "value": "reject"},
            {"label": "Discuss", "value": "discuss"},
        ],
    },
}


async def create_decision(
    decision_type: str,
    question: str,
    project_id: str | None = None,
    context: dict | None = None,
    options: list[dict] | None = None,
    tick_id: int = 0,
) -> DecisionPoint:
    """Create and persist a new decision for human approval."""
    if options is None:
        options = DECISION_TYPES.get(decision_type, {}).get(
            "default_options",
            [
                {"label": "Approve", "value": "approve"},
                {"label": "Reject", "value": "reject"},
            ],
        )
    decision = DecisionPoint(
        id=str(uuid.uuid4()),
        project_id=project_id,
        decision_type=DecisionType(decision_type),
        question=question,
        options=options,
        context=context or {},
    )
    await save_decision(decision)
    try:
        from orchestrator.event_store import get_event_store

        await get_event_store().append(
            Event.new(
                event_type=ActionType.DECISION_CREATED,
                tick_id=tick_id,
                project_id=project_id,
                payload={
                    "decision_id": decision.id,
                    "decision_type": decision_type,
                    "question": question[:200],
                },
            )
        )
    except Exception as e:
        logger.debug(f"Event emission skipped for create_decision: {e}")
    return decision


async def get_pending() -> list[DecisionPoint]:
    return await get_pending_decisions()


async def resolve(decision_id: str, response: str, tick_id: int = 0) -> DecisionPoint | None:
    """Mark a decision as resolved with the given human response."""
    await db_resolve_decision(decision_id, response)
    decision = await get_decision_by_id(decision_id)
    if decision:
        try:
            from orchestrator.event_store import get_event_store

            await get_event_store().append(
                Event.new(
                    event_type=ActionType.DECISION_RESOLVED,
                    tick_id=tick_id,
                    project_id=decision.project_id,
                    payload={"decision_id": decision_id, "response": response},
                )
            )
        except Exception as e:
            logger.debug(f"Event emission skipped for resolve: {e}")
    return decision

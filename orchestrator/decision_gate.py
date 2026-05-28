from __future__ import annotations

import uuid
from datetime import datetime, timezone

from shared.models import DecisionPoint, DecisionType, DecisionStatus
from orchestrator.persistence import save_decision, get_pending_decisions, resolve_decision as db_resolve_decision

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
) -> DecisionPoint:
    if options is None:
        options = DECISION_TYPES.get(decision_type, {})["default_options"]
    decision = DecisionPoint(
        id=str(uuid.uuid4()),
        project_id=project_id,
        decision_type=DecisionType(decision_type),
        question=question,
        options=options,
        context=context or {},
    )
    await save_decision(decision)
    return decision


async def get_pending() -> list[DecisionPoint]:
    return await get_pending_decisions()


async def resolve(decision_id: str, response: str) -> DecisionPoint | None:
    await db_resolve_decision(decision_id, response)
    from orchestrator.persistence import get_decision_by_id
    return await get_decision_by_id(decision_id)

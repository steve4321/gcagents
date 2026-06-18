from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException

from dashboard.web import api_server

router = APIRouter()


@router.get("/api/decisions")
async def list_decisions():
    from orchestrator.decision_gate import get_pending

    decisions = await get_pending()
    return [d.model_dump() for d in decisions]


@router.get("/api/decisions/history")
async def get_decision_history(limit: int = 50):
    from orchestrator.persistence import get_decision_history

    return await get_decision_history(limit)


@router.post("/api/decisions/{decision_id}/respond", dependencies=[Depends(api_server.get_api_key)])
async def respond_decision(decision_id: str, response: str = "", conditions: str = ""):
    from orchestrator.decision_gate import resolve
    from orchestrator.persistence import update_project_awaiting_decision

    result = await resolve(decision_id, response)
    if not result:
        raise HTTPException(404, "Decision not found")

    if conditions:
        result.context["conditions"] = conditions
        from sqlalchemy import text

        from orchestrator.persistence import _get_engine

        engine = _get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE decisions SET context=:ctx WHERE id=:id"),
                {"ctx": json.dumps(result.context), "id": decision_id},
            )

    resp = response.lower()
    pid = result.project_id
    if resp in ("approve", "approved") and pid:
        await _apply_approved_decision(result)
    elif resp in ("reject", "rejected") and pid:
        await _apply_rejected_decision(result)

    if pid:
        await update_project_awaiting_decision(pid, None)

    return result.model_dump()


async def _apply_approved_decision(decision) -> None:
    from orchestrator.persistence import get_project, update_project_phase
    from orchestrator.task_queue import enqueue

    dtype = decision.decision_type.value
    pid = decision.project_id

    if dtype == "new_project" and pid:
        await update_project_phase(pid, "scanning")

    elif dtype == "publish" and pid:
        await update_project_phase(pid, "publishing")
        project = await get_project(pid)
        if project:
            await enqueue(pid, "deploy", {"project_name": project.name})

    elif dtype == "budget_overrun" and pid:
        await update_project_phase(pid, "developing")

    elif dtype == "direction_change" and pid:
        await update_project_phase(pid, "designing")


async def _apply_rejected_decision(decision) -> None:
    from orchestrator.persistence import update_project_phase

    dtype = decision.decision_type.value
    pid = decision.project_id

    if dtype == "new_project" and pid:
        await update_project_phase(pid, "cancelled")

    elif dtype == "cancel" and pid:
        pass

    elif dtype == "publish" and pid:
        await update_project_phase(pid, "testing")

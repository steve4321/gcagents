"""Decisions table CRUD and resolution helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.persistence.engine import _get_engine, _parse_datetime
from shared.models import DecisionPoint, DecisionStatus, DecisionType


async def save_decision(decision: DecisionPoint) -> str:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(UTC).isoformat()
        await db.execute(
            text("""
                INSERT INTO decisions (id, project_id, decision_type, question,
                    options, context, status, human_response, created_at, resolved_at)
                VALUES (:id, :project_id, :decision_type, :question,
                    :options, :context, :status, :human_response, :created_at, :resolved_at)
            """),
            {
                "id": decision.id,
                "project_id": decision.project_id,
                "decision_type": decision.decision_type.value
                if hasattr(decision.decision_type, "value")
                else decision.decision_type,
                "question": decision.question,
                "options": json.dumps(decision.options),
                "context": json.dumps(decision.context),
                "status": decision.status.value
                if hasattr(decision.status, "value")
                else decision.status,
                "human_response": decision.human_response,
                "created_at": now,
                "resolved_at": decision.resolved_at.isoformat() if decision.resolved_at else None,
            },
        )
        await db.commit()
        return decision.id


async def get_pending_decisions() -> list[DecisionPoint]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = await db.execute(
            text("SELECT * FROM decisions WHERE status = 'pending' ORDER BY created_at DESC")
        )
        return [_row_to_decision(dict(r._mapping)) for r in rows.fetchall()]


async def get_decision_by_id(decision_id: str) -> DecisionPoint | None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        row = await db.execute(
            text("SELECT * FROM decisions WHERE id = :id"),
            {"id": decision_id},
        )
        result = row.fetchone()
        if not result:
            return None
        return _row_to_decision(dict(result._mapping))


async def get_project_decisions(project_id: str) -> list[DecisionPoint]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = await db.execute(
            text("SELECT * FROM decisions WHERE project_id = :pid ORDER BY created_at DESC"),
            {"pid": project_id},
        )
        return [_row_to_decision(dict(r._mapping)) for r in rows.fetchall()]


async def resolve_decision(decision_id: str, response: str) -> None:
    """Mark a decision as resolved.  Status is derived from *response*:
    ``approve`` → ``approved``, anything else (``reject``, etc.) → ``rejected``.
    """
    status = "approved" if response == "approve" else "rejected"
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(UTC).isoformat()
        await db.execute(
            text(
                "UPDATE decisions SET status=:status, human_response=:response, resolved_at=:now WHERE id=:id"
            ),
            {"status": status, "response": response, "now": now, "id": decision_id},
        )
        await db.commit()


async def get_decision_history(limit: int = 50) -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = (
            await db.execute(
                text("""
                SELECT id, project_id, decision_type, question, options, context,
                       status, human_response, created_at, resolved_at
                FROM decisions
                WHERE status IN ('approved', 'rejected')
                ORDER BY resolved_at DESC
                LIMIT :lim
            """),
                {"lim": limit},
            )
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def _row_to_decision(d: dict) -> DecisionPoint:
    return DecisionPoint(
        id=d["id"],
        project_id=d.get("project_id"),
        decision_type=DecisionType(d.get("decision_type", "new_project")),
        question=d["question"],
        options=json.loads(d.get("options", "[]")),
        context=json.loads(d.get("context", "{}")),
        status=DecisionStatus(d.get("status", "pending")),
        human_response=d.get("human_response"),
        created_at=_parse_datetime(d.get("created_at")),
        resolved_at=_parse_datetime(d.get("resolved_at")) if d.get("resolved_at") else None,
    )

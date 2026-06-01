"""Tests for orchestrator/decision_gate.py — human-in-the-loop decision workflow."""

from __future__ import annotations

import pytest

import orchestrator.persistence as persist
from orchestrator.decision_gate import create_decision, resolve
from shared.models import DecisionStatus


@pytest.mark.asyncio
async def test_create_decision_returns_id(tmp_db):
    """create_decision should persist and return a DecisionPoint with a UUID id."""
    await persist.ensure_tables()

    decision = await create_decision("new_project", "Should we start project X?")
    assert decision.id is not None
    assert len(decision.id) > 0
    assert decision.status == DecisionStatus.PENDING

    fetched = await persist.get_decision_by_id(decision.id)
    assert fetched is not None
    assert fetched.id == decision.id


@pytest.mark.asyncio
async def test_resolve_decision_updates_status(tmp_db):
    """Resolving a decision should change its status and record the response."""
    await persist.ensure_tables()

    decision = await create_decision("publish", "Publish game?")
    assert decision.status == DecisionStatus.PENDING

    resolved = await resolve(decision.id, "approve")
    assert resolved is not None
    assert resolved.human_response == "approve"
    assert resolved.status.value == "approved"

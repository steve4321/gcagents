"""Tests for orchestrator/decision_gate.py — human-in-the-loop decision workflow."""

from __future__ import annotations

import pytest

import orchestrator.persistence as persist
from orchestrator.decision_gate import DECISION_TYPES, create_decision, get_pending, resolve
from shared.models import DecisionStatus


@pytest.mark.asyncio
async def test_create_decision_returns_id(tmp_db):
    await persist.ensure_tables()

    decision = await create_decision("new_project", "Should we start project X?")
    assert decision.id is not None
    assert len(decision.id) > 0
    assert decision.status == DecisionStatus.PENDING

    fetched = await persist.get_decision_by_id(decision.id)
    assert fetched is not None


@pytest.mark.asyncio
async def test_resolve_decision_updates_status(tmp_db):
    await persist.ensure_tables()

    decision = await create_decision("publish", "Publish game?")

    resolved = await resolve(decision.id, "approve")
    assert resolved is not None
    assert resolved.status.value == "approved"


@pytest.mark.asyncio
async def test_create_decision_with_custom_options(tmp_db):
    await persist.ensure_tables()

    custom = [{"label": "Yes", "value": "yes"}, {"label": "No", "value": "no"}]
    decision = await create_decision("new_project", "Start?", options=custom)
    assert decision.options == custom


@pytest.mark.asyncio
async def test_create_decision_with_project_id(tmp_db):
    await persist.ensure_tables()

    decision = await create_decision("new_project", "Start?", project_id="proj-001")
    assert decision.project_id == "proj-001"


@pytest.mark.asyncio
async def test_get_pending_returns_only_pending(tmp_db):
    await persist.ensure_tables()

    d1 = await create_decision("new_project", "Q1?")
    d2 = await create_decision("publish", "Q2?")
    await resolve(d1.id, "approve")

    pending = await get_pending()
    assert len(pending) == 1
    assert pending[0].id == d2.id


@pytest.mark.asyncio
async def test_resolve_nonexistent_returns_none(tmp_db):
    await persist.ensure_tables()

    result = await resolve("nonexistent-id", "approve")
    assert result is None


@pytest.mark.asyncio
async def test_decision_types_all_have_options():
    for dtype, config in DECISION_TYPES.items():
        assert "default_options" in config
        assert len(config["default_options"]) >= 2

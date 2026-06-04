"""Tests for orchestrator/nodes/ — COO, CFO, CEO agents."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from orchestrator.state import CompanyState, PipelinePhase


def _make_state(**kwargs) -> CompanyState:
    defaults = {
        "phase": PipelinePhase.DEVELOPING,
        "current_project_id": "proj-001",
        "retry_count": 0,
        "errors": [],
    }
    defaults.update(kwargs)
    return CompanyState(**defaults)


@pytest.mark.asyncio
async def test_coo_health_check_ok(tmp_db):
    from orchestrator.nodes.coo import coo_health_check
    from orchestrator.persistence import ensure_tables

    await ensure_tables()

    state = _make_state()
    result = await coo_health_check(state)
    assert result == {}


@pytest.mark.asyncio
async def test_coo_health_check_excessive_errors(tmp_db):
    from orchestrator.nodes.coo import coo_health_check
    from orchestrator.persistence import ensure_tables

    await ensure_tables()

    state = _make_state(errors=["e1", "e2", "e3"])
    result = await coo_health_check(state)
    assert result["phase"] == PipelinePhase.IDLE


@pytest.mark.asyncio
async def test_coo_health_check_max_retries(tmp_db):
    from orchestrator.nodes.coo import coo_health_check
    from orchestrator.persistence import ensure_tables

    await ensure_tables()

    state = _make_state(retry_count=5)
    result = await coo_health_check(state)
    assert result["phase"] == PipelinePhase.IDLE


@pytest.mark.asyncio
async def test_cfo_budget_check_passes(tmp_db):
    from orchestrator.nodes.cfo import cfo_budget_check
    from orchestrator.persistence import ensure_tables

    await ensure_tables()

    with patch(
        "orchestrator.persistence.check_budget_available", new_callable=AsyncMock, return_value=True
    ):
        state = _make_state()
        result = await cfo_budget_check(state)
        assert result == {}


@pytest.mark.asyncio
async def test_cfo_budget_check_monthly_exceeded(tmp_db):
    from orchestrator.nodes.cfo import cfo_budget_check
    from orchestrator.persistence import ensure_tables

    await ensure_tables()

    async def fake_check(scope, cost):
        return scope != "monthly"

    with patch("orchestrator.persistence.check_budget_available", side_effect=fake_check):
        state = _make_state()
        result = await cfo_budget_check(state)
        assert result["phase"] == PipelinePhase.IDLE
        assert "Monthly budget exceeded" in result["errors"][0]


@pytest.mark.asyncio
async def test_cfo_budget_check_project_exceeded(tmp_db):
    from orchestrator.nodes.cfo import cfo_budget_check
    from orchestrator.persistence import ensure_tables

    await ensure_tables()

    async def fake_check(scope, cost):
        return scope == "monthly"

    with patch("orchestrator.persistence.check_budget_available", side_effect=fake_check):
        state = _make_state()
        result = await cfo_budget_check(state)
        assert result["phase"] == PipelinePhase.IDLE
        assert "Project budget exceeded" in result["errors"][0]

"""Tests for orchestrator/scheduler.py — retry/fallback logic.

Covers the three-layer error recovery strategy and task-type fallback mapping.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from orchestrator.scheduler import (
    _escalate_layer3,
    _fallback_task_type,
    _retry_layer1,
)


def test_fallback_task_type_develop_has_real_fallback():
    assert _fallback_task_type("develop") == "develop_simple"


def test_fallback_task_type_qa_is_identity():
    """REGRESSION: 'qa' currently maps to itself (no real fallback).

    This is intentional — the TODO in the source acknowledges the gap.
    We track it so it doesn't silently regress further.
    """
    assert _fallback_task_type("qa") == "qa"


def test_fallback_task_type_unknown_returns_input():
    assert _fallback_task_type("nonexistent_task") == "nonexistent_task"


@pytest.mark.asyncio
async def test_layer1_retry_increments_retry_count(tmp_db):
    """Mock enqueue_retry and verify it gets called with retry_count+1."""
    await __import__("orchestrator.persistence", fromlist=["ensure_tables"]).ensure_tables()

    task = __import__("shared.models", fromlist=["TaskRecord"]).TaskRecord(
        id="t1",
        project_id="p1",
        task_type="develop",
        params={"retry_count": 0, "layer": 1},
    )

    with patch("orchestrator.scheduler.enqueue_retry", new_callable=AsyncMock) as mock_enqueue:
        mock_enqueue.return_value = task
        await _retry_layer1(task, "something broke", retry_count=0)

        mock_enqueue.assert_awaited_once()
        call_kwargs = mock_enqueue.call_args
        assert call_kwargs.kwargs["retry_count"] == 1


@pytest.mark.asyncio
async def test_layer3_creates_decision(tmp_db):
    """Verify Layer 3 escalation calls the decision gate (create_decision)."""
    await __import__("orchestrator.persistence", fromlist=["ensure_tables"]).ensure_tables()

    from shared.models import ProjectPhase, ProjectState

    project = ProjectState(id="p1", name="test-game", phase=ProjectPhase.DEVELOPING)
    await __import__("orchestrator.persistence", fromlist=["save_project"]).save_project(project)

    task = __import__("shared.models", fromlist=["TaskRecord"]).TaskRecord(
        id="t1",
        project_id="p1",
        task_type="develop_simple",
        params={
            "original_task_type": "develop",
            "retry_count": 2,
            "retry_strategy": "strategy_change",
            "layer": 2,
        },
    )

    with patch(
        "orchestrator.scheduler.create_decision", new_callable=AsyncMock
    ) as mock_decision, patch(
        "orchestrator.scheduler.emit", new_callable=AsyncMock
    ):
        from shared.models import DecisionPoint, DecisionType, DecisionStatus
        mock_decision.return_value = DecisionPoint(
            id="d1",
            project_id="p1",
            decision_type=DecisionType.DIRECTION_CHANGE,
            question="test",
            status=DecisionStatus.PENDING,
        )
        await _escalate_layer3(task, "fatal error")

        mock_decision.assert_awaited_once()
        assert mock_decision.call_args.args[0] == "direction_change"

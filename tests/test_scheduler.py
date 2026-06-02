"""Tests for orchestrator/scheduler.py — retry/fallback logic and core scheduler functions."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from orchestrator.scheduler import (
    _escalate_layer3,
    _fallback_task_type,
    _get_phase_ticks,
    _load_scheduler_config,
    _retry_layer1,
    is_paused,
    set_paused,
)
from shared.models import DecisionPoint, DecisionStatus, DecisionType, ProjectPhase, ProjectState, TaskRecord


def test_fallback_task_type_develop_has_real_fallback():
    assert _fallback_task_type("develop") == "develop_simple"


def test_fallback_task_type_qa_returns_none():
    assert _fallback_task_type("qa") is None


def test_fallback_task_type_unknown_returns_none():
    assert _fallback_task_type("nonexistent_task") is None


def test_fallback_task_type_art_returns_none():
    assert _fallback_task_type("art_gen") is None


def test_fallback_task_type_music_returns_none():
    assert _fallback_task_type("generate_music") is None


def test_fallback_task_type_localize_returns_none():
    assert _fallback_task_type("localize") is None


def test_fallback_task_type_scan_returns_none():
    assert _fallback_task_type("market_scan") is None


def test_fallback_task_type_design_returns_none():
    assert _fallback_task_type("design_game") is None


def test_fallback_task_type_build_returns_none():
    assert _fallback_task_type("build") is None


@pytest.mark.asyncio
async def test_layer1_retry_increments_retry_count(tmp_db):
    from orchestrator.persistence import ensure_tables

    await ensure_tables()

    task = TaskRecord(
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
    from orchestrator.persistence import ensure_tables, save_project

    await ensure_tables()

    project = ProjectState(id="p1", name="test-game", phase=ProjectPhase.DEVELOPING)
    await save_project(project)

    task = TaskRecord(
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


@pytest.mark.asyncio
async def test_get_phase_ticks(tmp_db):
    from orchestrator.persistence import ensure_tables, save_project, save_task, update_task_status

    await ensure_tables()

    project = ProjectState(id="proj-001", name="Test", genre="puzzle", phase=ProjectPhase.DEVELOPING)
    await save_project(project)

    t1 = TaskRecord(id="t1", project_id="proj-001", task_type="develop", description="t1")
    t2 = TaskRecord(id="t2", project_id="proj-001", task_type="qa", description="t2")
    await save_task(t1)
    await save_task(t2)
    await update_task_status("t1", "completed")

    ticks = await _get_phase_ticks("proj-001")
    assert ticks == 1


@pytest.mark.asyncio
async def test_get_phase_ticks_empty_project(tmp_db):
    from orchestrator.persistence import ensure_tables

    await ensure_tables()

    ticks = await _get_phase_ticks("nonexistent")
    assert ticks == 0


def test_is_paused_and_set_paused(tmp_path, monkeypatch):
    pause_path = str(tmp_path / "test_paused")
    monkeypatch.setattr("orchestrator.scheduler._PAUSE_FLAG_PATH", pause_path)

    assert is_paused() is False

    set_paused(True)
    assert is_paused() is True

    set_paused(False)
    assert is_paused() is False


def test_is_paused_remove_nonexistent(tmp_path, monkeypatch):
    pause_path = str(tmp_path / "nonexistent")
    monkeypatch.setattr("orchestrator.scheduler._PAUSE_FLAG_PATH", pause_path)

    set_paused(False)
    assert is_paused() is False


def test_load_scheduler_config_returns_dict():
    result = _load_scheduler_config()
    assert isinstance(result, dict)


def test_scheduler_constants_are_positive():
    from orchestrator.scheduler import (
        CEO_EVALUATE_INTERVAL,
        MARKET_SCAN_INTERVAL,
        MAX_ACTIVE_PROJECTS,
        REPORT_INTERVAL,
    )

    assert MARKET_SCAN_INTERVAL > 0
    assert CEO_EVALUATE_INTERVAL > 0
    assert MAX_ACTIVE_PROJECTS > 0
    assert REPORT_INTERVAL > 0

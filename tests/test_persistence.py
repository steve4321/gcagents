"""Tests for orchestrator/persistence.py — database layer."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import orchestrator.persistence as persist
from shared.models import (
    DecisionPoint,
    DecisionStatus,
    DecisionType,
    ProjectPhase,
    ProjectState,
    TaskRecord,
)


@pytest.mark.asyncio
async def test_ensure_tables_creates_orchestrator_state(tmp_db):
    await persist.ensure_tables()

    async with AsyncSession(tmp_db) as db:
        result = await db.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='orchestrator_state'")
        )
        assert result.fetchone() is not None


@pytest.mark.asyncio
async def test_save_pipeline_state_inserts_row(tmp_db):
    await persist.ensure_tables()

    await persist.save_pipeline_state(phase="developing", errors=["err1"])

    async with AsyncSession(tmp_db) as db:
        result = await db.execute(text("SELECT phase, errors FROM orchestrator_state"))
        row = result.fetchone()
        assert row is not None
        assert row[0] == "developing"
        assert json.loads(row[1]) == ["err1"]


@pytest.mark.asyncio
async def test_ensure_tables_idempotent(tmp_db):
    await persist.ensure_tables()
    await persist.ensure_tables()

    async with AsyncSession(tmp_db) as db:
        result = await db.execute(text("SELECT COUNT(*) FROM sqlite_master WHERE type='table'"))
        assert result.scalar() > 0


@pytest.mark.asyncio
async def test_get_project_returns_none_for_missing(tmp_db):
    await persist.ensure_tables()

    result = await persist.get_project("nonexistent-id")
    assert result is None


@pytest.mark.asyncio
async def test_save_project_and_get(tmp_db):
    await persist.ensure_tables()

    project = ProjectState(
        id="proj-001", name="Test Game", genre="puzzle", phase=ProjectPhase.SCANNING
    )
    await persist.save_project(project)

    fetched = await persist.get_project("proj-001")
    assert fetched is not None
    assert fetched.name == "Test Game"
    assert fetched.genre == "puzzle"


@pytest.mark.asyncio
async def test_get_all_projects(tmp_db):
    await persist.ensure_tables()

    p1 = ProjectState(id="p1", name="Game A", genre="action", phase=ProjectPhase.SCANNING)
    p2 = ProjectState(id="p2", name="Game B", genre="rpg", phase=ProjectPhase.DEVELOPING)
    await persist.save_project(p1)
    await persist.save_project(p2)

    projects = await persist.get_all_projects()
    assert len(projects) >= 2
    names = {p.name for p in projects}
    assert "Game A" in names
    assert "Game B" in names


@pytest.mark.asyncio
async def test_save_decision_and_get(tmp_db):
    await persist.ensure_tables()

    decision = DecisionPoint(
        id="dec-001",
        project_id="proj-001",
        decision_type=DecisionType.NEW_PROJECT,
        question="Should we start?",
        status=DecisionStatus.PENDING,
    )
    await persist.save_decision(decision)

    fetched = await persist.get_decision_by_id("dec-001")
    assert fetched is not None
    assert fetched.id == "dec-001"


@pytest.mark.asyncio
async def test_resolve_decision(tmp_db):
    await persist.ensure_tables()

    decision = DecisionPoint(
        id="dec-002",
        project_id="proj-001",
        decision_type=DecisionType.PUBLISH,
        question="Publish?",
        status=DecisionStatus.PENDING,
    )
    await persist.save_decision(decision)

    await persist.resolve_decision("dec-002", "approve")

    fetched = await persist.get_decision_by_id("dec-002")
    assert fetched is not None
    assert fetched.status.value == "approved"


@pytest.mark.asyncio
async def test_get_pending_decisions(tmp_db):
    await persist.ensure_tables()

    d1 = DecisionPoint(
        id="d1",
        project_id="p1",
        decision_type=DecisionType.NEW_PROJECT,
        question="Q1?",
        status=DecisionStatus.PENDING,
    )
    d2 = DecisionPoint(
        id="d2",
        project_id="p2",
        decision_type=DecisionType.PUBLISH,
        question="Q2?",
        status=DecisionStatus.APPROVED,
    )
    await persist.save_decision(d1)
    await persist.save_decision(d2)

    pending = await persist.get_pending_decisions()
    assert len(pending) == 1
    assert pending[0].id == "d1"


@pytest.mark.asyncio
async def test_save_task_and_get(tmp_db):
    await persist.ensure_tables()

    project = ProjectState(
        id="proj-001", name="Test", genre="puzzle", phase=ProjectPhase.DEVELOPING
    )
    await persist.save_project(project)

    task = TaskRecord(id="task-001", project_id="proj-001", task_type="code")
    await persist.save_task(task)

    fetched = await persist.get_task("task-001")
    assert fetched is not None
    assert fetched.task_type == "code"


@pytest.mark.asyncio
async def test_update_task_status(tmp_db):
    await persist.ensure_tables()

    project = ProjectState(
        id="proj-001", name="Test", genre="puzzle", phase=ProjectPhase.DEVELOPING
    )
    await persist.save_project(project)

    task = TaskRecord(id="task-002", project_id="proj-001", task_type="qa")
    await persist.save_task(task)

    await persist.update_task_status("task-002", "completed")

    fetched = await persist.get_task("task-002")
    assert fetched.status.value == "completed"


@pytest.mark.asyncio
async def test_log_event(tmp_db):
    await persist.ensure_tables()

    event_id = await persist.log_event("pipeline", "info", "Test event", detail="extra info")
    assert event_id > 0

    async with AsyncSession(tmp_db) as db:
        result = await db.execute(
            text("SELECT event_type, severity, title FROM event_logs LIMIT 1")
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == "pipeline"
        assert row[1] == "info"
        assert row[2] == "Test event"


@pytest.mark.asyncio
async def test_save_chat_message(tmp_db):
    await persist.ensure_tables()

    await persist.save_chat_message("user", "Hello CEO", agent_name="ceo")

    async with AsyncSession(tmp_db) as db:
        result = await db.execute(text("SELECT role, content FROM chat_messages LIMIT 1"))
        row = result.fetchone()
        assert row is not None
        assert row[0] == "user"
        assert row[1] == "Hello CEO"


@pytest.mark.asyncio
async def test_log_api_usage(tmp_db):
    await persist.ensure_tables()

    await persist.log_api_usage(
        model="deepseek",
        agent_name="coder",
        project_name="test-project",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        estimated_cost_usd=0.001,
    )

    async with AsyncSession(tmp_db) as db:
        result = await db.execute(
            text("SELECT model, agent_name, prompt_tokens FROM api_usage_logs LIMIT 1")
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == "deepseek"
        assert row[1] == "coder"
        assert row[2] == 100


@pytest.mark.asyncio
async def test_get_pending_instructions_empty(tmp_db):
    await persist.ensure_tables()

    instructions = await persist.get_pending_instructions("ceo")
    assert instructions == []


@pytest.mark.asyncio
async def test_get_api_usage_summary(tmp_db):
    await persist.ensure_tables()

    await persist.log_api_usage(
        model="deepseek", agent_name="c1", total_tokens=100, estimated_cost_usd=0.001
    )
    await persist.log_api_usage(
        model="zhipu", agent_name="c2", total_tokens=200, estimated_cost_usd=0.002
    )

    summary = await persist.get_api_usage_summary()
    assert summary["calls"] == 2
    assert summary["total_cost"] == pytest.approx(0.003)


@pytest.mark.asyncio
async def test_count_completed_tasks(tmp_db):
    await persist.ensure_tables()

    project = ProjectState(
        id="proj-001", name="Test", genre="puzzle", phase=ProjectPhase.DEVELOPING
    )
    await persist.save_project(project)

    t1 = TaskRecord(id="t1", project_id="proj-001", task_type="code")
    t2 = TaskRecord(id="t2", project_id="proj-001", task_type="qa")
    await persist.save_task(t1)
    await persist.save_task(t2)
    await persist.update_task_status("t1", "completed")

    count = await persist.count_completed_tasks("proj-001")
    assert count == 1


@pytest.mark.asyncio
async def test_get_orchestrator_state_empty(tmp_db):
    await persist.ensure_tables()

    state = await persist.get_orchestrator_state()
    assert state is None


@pytest.mark.asyncio
async def test_save_and_get_market_report(tmp_db):
    await persist.ensure_tables()

    await persist.save_market_report(
        signals_count=5,
        opportunities=[{"genre": "puzzle", "score": 0.9}],
        raw_analysis="Market looks good",
    )

    report = await persist.get_latest_market_report()
    assert report is not None


@pytest.mark.asyncio
async def test_update_project_phase(tmp_db):
    await persist.ensure_tables()

    project = ProjectState(id="proj-001", name="Test", genre="puzzle", phase=ProjectPhase.SCANNING)
    await persist.save_project(project)
    await persist.update_project_phase("proj-001", ProjectPhase.DEVELOPING)

    fetched = await persist.get_project("proj-001")
    assert fetched.phase == ProjectPhase.DEVELOPING


@pytest.mark.asyncio
async def test_update_project_gdd(tmp_db):
    await persist.ensure_tables()

    project = ProjectState(
        id="proj-001", name="Test", genre="puzzle", phase=ProjectPhase.DEVELOPING
    )
    await persist.save_project(project)
    gdd = {"title": "Test Game", "mechanics": ["tap", "swipe"]}
    await persist.update_project_gdd("proj-001", gdd)

    fetched = await persist.get_project("proj-001")
    assert fetched.gdd is not None
    assert fetched.gdd["title"] == "Test Game"


@pytest.mark.asyncio
async def test_get_last_scan_time_empty(tmp_db):
    await persist.ensure_tables()

    result = await persist.get_last_scan_time()
    assert result is None


@pytest.mark.asyncio
async def test_get_latest_project_empty(tmp_db):
    await persist.ensure_tables()

    result = await persist.get_latest_project()
    assert result is None


@pytest.mark.asyncio
async def test_get_orchestrator_history_empty(tmp_db):
    await persist.ensure_tables()

    history = await persist.get_orchestrator_history()
    assert history == []


@pytest.mark.asyncio
async def test_get_pending_feedback_empty(tmp_db):
    await persist.ensure_tables()

    result = await persist.get_pending_feedback("proj-001")
    assert result == []


@pytest.mark.asyncio
async def test_get_all_feedback_empty(tmp_db):
    await persist.ensure_tables()

    result = await persist.get_all_feedback("proj-001")
    assert result == []


@pytest.mark.asyncio
async def test_get_agent_logs_empty(tmp_db):
    await persist.ensure_tables()

    result = await persist.get_agent_logs()
    assert result == []


@pytest.mark.asyncio
async def test_get_agent_stats_empty(tmp_db):
    await persist.ensure_tables()

    result = await persist.get_agent_stats()
    assert result == []


@pytest.mark.asyncio
async def test_get_latest_market_signals_empty(tmp_db):
    await persist.ensure_tables()

    result = await persist.get_latest_market_signals()
    assert result == []


@pytest.mark.asyncio
async def test_get_company_memory_empty(tmp_db):
    await persist.ensure_tables()

    result = await persist.get_company_memory()
    assert result == []


@pytest.mark.asyncio
async def test_save_project_updates_existing(tmp_db):
    await persist.ensure_tables()

    project = ProjectState(id="proj-001", name="Test", genre="puzzle", phase=ProjectPhase.SCANNING)
    await persist.save_project(project)

    project.name = "Updated Test"
    await persist.save_project(project)

    fetched = await persist.get_project("proj-001")
    assert fetched.name == "Updated Test"


@pytest.mark.asyncio
async def test_update_project_code_path(tmp_db):
    await persist.ensure_tables()

    project = ProjectState(
        id="proj-001", name="Test", genre="puzzle", phase=ProjectPhase.DEVELOPING
    )
    await persist.save_project(project)
    await persist.update_project_code_path("proj-001", "/path/to/code")

    fetched = await persist.get_project("proj-001")
    assert fetched.code_path == "/path/to/code"


@pytest.mark.asyncio
async def test_update_project_art_status(tmp_db):
    await persist.ensure_tables()

    project = ProjectState(
        id="proj-001", name="Test", genre="puzzle", phase=ProjectPhase.DEVELOPING
    )
    await persist.save_project(project)
    await persist.update_project_art_status("proj-001", "completed")

    fetched = await persist.get_project("proj-001")
    assert fetched.art_status == "completed"


@pytest.mark.asyncio
async def test_update_project_music_status(tmp_db):
    await persist.ensure_tables()

    project = ProjectState(
        id="proj-001", name="Test", genre="puzzle", phase=ProjectPhase.DEVELOPING
    )
    await persist.save_project(project)
    await persist.update_project_music_status("proj-001", "completed")

    fetched = await persist.get_project("proj-001")
    assert fetched.music_status == "completed"


@pytest.mark.asyncio
async def test_update_project_qa_result(tmp_db):
    await persist.ensure_tables()

    project = ProjectState(
        id="proj-001", name="Test", genre="puzzle", phase=ProjectPhase.DEVELOPING
    )
    await persist.save_project(project)
    qa = {"score": 85, "checks_passed": 7}
    await persist.update_project_qa_result("proj-001", qa)

    fetched = await persist.get_project("proj-001")
    assert fetched.qa_result is not None
    assert fetched.qa_result["score"] == 85


@pytest.mark.asyncio
async def test_set_project_live(tmp_db):
    await persist.ensure_tables()

    project = ProjectState(id="proj-001", name="Test", genre="puzzle", phase=ProjectPhase.BUILDING)
    await persist.save_project(project)
    await persist.set_project_live("proj-001", "https://itch.io/game")

    fetched = await persist.get_project("proj-001")
    assert fetched.phase == ProjectPhase.LIVE
    assert fetched.itch_url == "https://itch.io/game"


@pytest.mark.asyncio
async def test_update_project_awaiting_decision(tmp_db):
    await persist.ensure_tables()

    project = ProjectState(
        id="proj-001", name="Test", genre="puzzle", phase=ProjectPhase.DEVELOPING
    )
    await persist.save_project(project)
    await persist.update_project_awaiting_decision("proj-001", "publish")

    fetched = await persist.get_project("proj-001")
    assert fetched.awaiting_decision == "publish"


@pytest.mark.asyncio
async def test_get_project_tasks_empty(tmp_db):
    await persist.ensure_tables()

    tasks = await persist.get_project_tasks("proj-001")
    assert tasks == []


@pytest.mark.asyncio
async def test_get_pending_tasks_empty(tmp_db):
    await persist.ensure_tables()

    tasks = await persist.get_pending_tasks()
    assert tasks == []


@pytest.mark.asyncio
async def test_update_project_proposal_and_phase(tmp_db):
    await persist.ensure_tables()

    project = ProjectState(id="proj-001", name="Test", genre="puzzle", phase=ProjectPhase.SCANNING)
    await persist.save_project(project)

    proposal = {"title": "Test Game", "genre": "puzzle"}
    await persist.update_project_proposal_and_phase("proj-001", proposal, ProjectPhase.DESIGNING)

    fetched = await persist.get_project("proj-001")
    assert fetched.phase == ProjectPhase.DESIGNING
    assert fetched.proposal is not None
    assert fetched.proposal["title"] == "Test Game"


@pytest.mark.asyncio
async def test_save_and_get_decision_detail(tmp_db):
    await persist.ensure_tables()

    decision = DecisionPoint(
        id="dec-detail-001",
        project_id="proj-001",
        decision_type=DecisionType.NEW_PROJECT,
        question="Start this game?",
        context={"genre": "puzzle"},
        status=DecisionStatus.PENDING,
    )
    await persist.save_decision(decision)

    detail = await persist.get_decision_by_id("dec-detail-001")
    assert detail is not None
    assert detail.id == "dec-detail-001"
    assert detail.question == "Start this game?"


@pytest.mark.asyncio
async def test_resolve_decision_rejected(tmp_db):
    await persist.ensure_tables()

    decision = DecisionPoint(
        id="dec-reject-001",
        project_id="proj-001",
        decision_type=DecisionType.CANCEL,
        question="Cancel project?",
        status=DecisionStatus.PENDING,
    )
    await persist.save_decision(decision)

    await persist.resolve_decision("dec-reject-001", "reject")

    fetched = await persist.get_decision_by_id("dec-reject-001")
    assert fetched.status.value == "rejected"


@pytest.mark.asyncio
async def test_update_task_status_running(tmp_db):
    await persist.ensure_tables()

    project = ProjectState(
        id="proj-001", name="Test", genre="puzzle", phase=ProjectPhase.DEVELOPING
    )
    await persist.save_project(project)

    task = TaskRecord(id="task-run-001", project_id="proj-001", task_type="code")
    await persist.save_task(task)

    await persist.update_task_status("task-run-001", "running")

    fetched = await persist.get_task("task-run-001")
    assert fetched.status.value == "running"
    assert fetched.started_at is not None


@pytest.mark.asyncio
async def test_update_task_status_failed(tmp_db):
    await persist.ensure_tables()

    project = ProjectState(
        id="proj-001", name="Test", genre="puzzle", phase=ProjectPhase.DEVELOPING
    )
    await persist.save_project(project)

    task = TaskRecord(id="task-fail-001", project_id="proj-001", task_type="qa")
    await persist.save_task(task)

    await persist.update_task_status("task-fail-001", "failed", error="Test error")

    fetched = await persist.get_task("task-fail-001")
    assert fetched.status.value == "failed"
    assert fetched.error == "Test error"


@pytest.mark.asyncio
async def test_update_task_status_with_result(tmp_db):
    await persist.ensure_tables()

    project = ProjectState(
        id="proj-001", name="Test", genre="puzzle", phase=ProjectPhase.DEVELOPING
    )
    await persist.save_project(project)

    task = TaskRecord(id="task-res-001", project_id="proj-001", task_type="code")
    await persist.save_task(task)

    await persist.update_task_status("task-res-001", "completed", result={"path": "/dist"})

    fetched = await persist.get_task("task-res-001")
    assert fetched.status.value == "completed"
    assert fetched.result is not None
    assert fetched.result["path"] == "/dist"


@pytest.mark.asyncio
async def test_get_completed_genres_empty(tmp_db):
    await persist.ensure_tables()

    genres = await persist.get_completed_genres()
    assert genres == set()


@pytest.mark.asyncio
async def test_find_project_to_update_none(tmp_db):
    await persist.ensure_tables()

    result = await persist.find_project_to_update()
    assert result is None


@pytest.mark.asyncio
async def test_save_chat_message_with_metadata(tmp_db):
    await persist.ensure_tables()

    await persist.save_chat_message(
        "user", "Hello", agent_name="ceo", metadata={"type": "instruction"}
    )

    async with AsyncSession(tmp_db) as db:
        result = await db.execute(text("SELECT metadata_json FROM chat_messages LIMIT 1"))
        row = result.fetchone()
        assert row is not None
        meta = json.loads(row[0])
        assert meta["type"] == "instruction"


@pytest.mark.asyncio
async def test_log_event_with_metadata(tmp_db):
    await persist.ensure_tables()

    await persist.log_event("pipeline", "info", "Test", metadata={"key": "value"})

    async with AsyncSession(tmp_db) as db:
        result = await db.execute(text("SELECT metadata_json FROM event_logs LIMIT 1"))
        row = result.fetchone()
        assert row is not None
        meta = json.loads(row[0])
        assert meta["key"] == "value"


@pytest.mark.asyncio
async def test_get_chat_history_empty(tmp_db):
    await persist.ensure_tables()

    history = await persist.get_chat_history()
    assert history == []


@pytest.mark.asyncio
async def test_set_budget(tmp_db):
    await persist.ensure_tables()

    await persist.set_budget("monthly", "recurring", 100.0)
    budgets = await persist.get_active_budgets()
    assert len(budgets) > 0


@pytest.mark.asyncio
async def test_check_budget_available(tmp_db):
    await persist.ensure_tables()

    await persist.set_budget("monthly", "recurring", 100.0)
    result = await persist.check_budget_available("monthly", 50.0)
    assert result is True


@pytest.mark.asyncio
async def test_check_budget_exceeded(tmp_db):
    await persist.ensure_tables()

    await persist.set_budget("monthly", "recurring", 10.0)
    result = await persist.check_budget_available("monthly", 50.0)
    assert result is False


@pytest.mark.asyncio
async def test_record_spend(tmp_db):
    await persist.ensure_tables()

    await persist.set_budget("monthly", "recurring", 100.0)
    await persist.record_spend("monthly", 25.0)
    budgets = await persist.get_active_budgets()
    assert budgets[0]["spent_usd"] == pytest.approx(25.0)


@pytest.mark.asyncio
async def test_get_usage_summary(tmp_db):
    await persist.ensure_tables()

    await persist.log_api_usage(
        model="deepseek", agent_name="c1", total_tokens=100, estimated_cost_usd=0.001
    )
    summary = await persist.get_usage_summary(days=30)
    assert "total_cost" in summary
    assert "total_tokens" in summary
    assert summary["total_tokens"] >= 100


@pytest.mark.asyncio
async def test_get_project_cost(tmp_db):
    await persist.ensure_tables()

    await persist.log_api_usage(
        model="deepseek", agent_name="c1", project_name="proj-001", estimated_cost_usd=0.05
    )
    cost = await persist.get_project_cost("proj-001")
    assert "total_cost" in cost
    assert cost["total_cost"] >= 0.05


@pytest.mark.asyncio
async def test_save_agent_log(tmp_db):
    await persist.ensure_tables()

    await persist.save_agent_log(
        "coder", "completed", "developing", project_name="Test", duration_ms=1500
    )

    async with AsyncSession(tmp_db) as db:
        result = await db.execute(
            text("SELECT node_name, status, duration_ms FROM agent_logs LIMIT 1")
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == "coder"
        assert row[1] == "completed"
        assert row[2] == 1500


@pytest.mark.asyncio
async def test_save_market_signals(tmp_db):
    await persist.ensure_tables()

    signals = [
        {
            "source": "itch",
            "signal_type": "trending",
            "genre": "puzzle",
            "title": "Test",
            "score": 0.9,
        },
    ]
    await persist.save_market_signals(signals)

    async with AsyncSession(tmp_db) as db:
        result = await db.execute(text("SELECT COUNT(*) FROM market_signals"))
        count = result.fetchone()[0]
        assert count >= 1


@pytest.mark.asyncio
async def test_get_live_projects(tmp_db):
    await persist.ensure_tables()

    projects = await persist.get_live_projects()
    assert isinstance(projects, list)


@pytest.mark.asyncio
async def test_save_game_version(tmp_db):
    await persist.ensure_tables()

    project = ProjectState(id="vproj-1", name="VersionTest", genre="puzzle")
    await persist.save_project(project)

    await persist.save_game_version("vproj-1", "1.0.0", gdd_snapshot={"title": "test"})
    version = await persist.get_latest_version("vproj-1")
    assert version == "1.0.0"


@pytest.mark.asyncio
async def test_save_game_metric(tmp_db):
    await persist.ensure_tables()

    async with AsyncSession(tmp_db) as db:
        await db.execute(
            text(
                "INSERT INTO game_projects (name, genre, status) VALUES ('Test', 'puzzle', 'live')"
            )
        )
        await db.commit()
        result = await db.execute(text("SELECT id FROM game_projects LIMIT 1"))
        project_id = result.fetchone()[0]

    await persist.save_game_metric(project_id, "session_count", 42)
    metrics = await persist.get_project_metrics(project_id)
    assert len(metrics) > 0
    assert metrics[0]["metric_name"] == "session_count"


@pytest.mark.asyncio
async def test_get_recent_events(tmp_db):
    await persist.ensure_tables()

    await persist.log_event("pipeline", "info", "Test event 1")
    await persist.log_event("finance", "info", "Test event 2")

    events = await persist.get_recent_events(limit=10)
    assert len(events) >= 2


@pytest.mark.asyncio
async def test_get_recent_events_by_type(tmp_db):
    await persist.ensure_tables()

    await persist.log_event("pipeline", "info", "Pipeline event")
    await persist.log_event("finance", "info", "Finance event")

    events = await persist.get_recent_events(limit=10, event_type="pipeline")
    assert all(e["event_type"] == "pipeline" for e in events)


@pytest.mark.asyncio
async def test_get_projects_by_phase(tmp_db):
    await persist.ensure_tables()

    p1 = ProjectState(id="p1", name="Game A", genre="action", phase=ProjectPhase.DEVELOPING)
    p2 = ProjectState(id="p2", name="Game B", genre="rpg", phase=ProjectPhase.DEVELOPING)
    p3 = ProjectState(id="p3", name="Game C", genre="puzzle", phase=ProjectPhase.SCANNING)
    await persist.save_project(p1)
    await persist.save_project(p2)
    await persist.save_project(p3)

    dev_projects = await persist.get_projects_by_phase(ProjectPhase.DEVELOPING)
    assert len(dev_projects) >= 2


@pytest.mark.asyncio
async def test_save_feedback(tmp_db):
    await persist.ensure_tables()

    async with AsyncSession(tmp_db) as db:
        await db.execute(
            text(
                "INSERT INTO game_projects (name, genre, status) VALUES ('Test', 'puzzle', 'live')"
            )
        )
        await db.commit()
        result = await db.execute(text("SELECT id FROM game_projects LIMIT 1"))
        project_id = result.fetchone()[0]

    await persist.save_feedback(project_id, "post-001", "Great game!", author="user1")
    feedback = await persist.get_unprocessed_feedback(project_id)
    assert len(feedback) > 0


@pytest.mark.asyncio
async def test_get_project_decisions(tmp_db):
    await persist.ensure_tables()

    project = ProjectState(
        id="proj-001", name="Test", genre="puzzle", phase=ProjectPhase.DEVELOPING
    )
    await persist.save_project(project)

    d1 = DecisionPoint(
        id="d-proj-001",
        project_id="proj-001",
        decision_type=DecisionType.NEW_PROJECT,
        question="Q1?",
        status=DecisionStatus.PENDING,
    )
    await persist.save_decision(d1)

    decisions = await persist.get_project_decisions("proj-001")
    assert len(decisions) >= 1


# ── H1: platform_urls persistence ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_project_platform_urls(tmp_db):
    await persist.ensure_tables()

    project = ProjectState(id="proj-001", name="Test", genre="puzzle", phase=ProjectPhase.LIVE)
    await persist.save_project(project)

    urls = {"itch.io": "https://test.itch.io/game", "github": "https://pages.github.io/game"}
    await persist.update_project_platform_urls("proj-001", urls)

    fetched = await persist.get_project("proj-001")
    assert fetched.platform_urls == urls


@pytest.mark.asyncio
async def test_platform_urls_saved_with_project(tmp_db):
    await persist.ensure_tables()

    urls = {"itch.io": "https://test.itch.io/game"}
    project = ProjectState(
        id="proj-002",
        name="PlatformTest",
        genre="puzzle",
        phase=ProjectPhase.LIVE,
        platform_urls=urls,
    )
    await persist.save_project(project)

    fetched = await persist.get_project("proj-002")
    assert fetched.platform_urls == urls


# ── H9: Project ID uniqueness ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_two_projects_same_name_different_ids(tmp_db):
    await persist.ensure_tables()

    p1 = ProjectState(id="abc123def456", name="My Game", genre="puzzle")
    p2 = ProjectState(id="789ghi012jkl", name="My Game", genre="puzzle")
    await persist.save_project(p1)
    await persist.save_project(p2)

    all_projects = await persist.get_all_projects()
    same_name = [p for p in all_projects if p.name == "My Game"]
    assert len(same_name) == 2
    assert same_name[0].id != same_name[1].id


@pytest.mark.asyncio
async def test_new_id_generates_unique_ids():
    from orchestrator.scheduler import _new_id

    ids = {_new_id() for _ in range(100)}
    assert len(ids) == 100
    for project_id in ids:
        assert len(project_id) == 12


# ── H8: Budget check in LLM client ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_budget_exceeded_in_usage_info(tmp_db):
    from unittest.mock import AsyncMock, MagicMock, patch

    await persist.ensure_tables()
    await persist.set_budget("monthly", "recurring", 0.0000001)
    await persist.record_spend("monthly", 0.0000001)

    from shared.llm_client import LLMClient

    client = LLMClient()

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 500
    mock_usage.completion_tokens = 100
    mock_usage.total_tokens = 600

    mock_response = MagicMock()
    mock_response.usage = mock_usage
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "test response"

    mock_openai = AsyncMock()
    mock_openai.chat.completions.create.return_value = mock_response

    with patch.object(client, "_get_client", return_value=mock_openai):
        _, usage_info = await client._call_single(
            model="deepseek-v4-flash",
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=100,
            temperature=0.7,
            agent_name="test",
            project_name="test",
        )

    assert "budget_exceeded" in usage_info
    assert usage_info["budget_exceeded"] is True

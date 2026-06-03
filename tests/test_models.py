"""Tests for shared/data models."""
from __future__ import annotations

from shared.models import (
    ProjectPhase, ProjectState, DecisionType, DecisionStatus, DecisionPoint,
    TaskStatus, TaskRecord,
)


class TestEnums:
    def test_project_phase_values(self):
        assert ProjectPhase.BACKLOG == "backlog"
        assert ProjectPhase.LIVE == "live"
        assert ProjectPhase.CANCELLED == "cancelled"
        assert len(ProjectPhase) == 10

    def test_decision_type_values(self):
        assert DecisionType.NEW_PROJECT == "new_project"
        assert len(DecisionType) == 5

    def test_task_status_values(self):
        assert TaskStatus.PENDING == "pending"
        assert len(TaskStatus) == 5


class TestProjectState:
    def test_defaults(self):
        p = ProjectState(id="test", name="Test Game")
        assert p.phase == ProjectPhase.BACKLOG
        assert p.progress == 0.0
        assert p.gdd is None
        assert p.awaiting_decision is None

    def test_with_gdd(self):
        p = ProjectState(id="1", name="Game", gdd={"title": "Test"})
        assert p.gdd == {"title": "Test"}


class TestDecisionPoint:
    def test_defaults(self):
        d = DecisionPoint(id="d1", decision_type=DecisionType.NEW_PROJECT, question="Start?")
        assert d.status == DecisionStatus.PENDING
        assert d.human_response is None
        assert d.context == {}


class TestTaskRecord:
    def test_defaults(self):
        t = TaskRecord(id="t1", project_id="p1", task_type="develop")
        assert t.status == TaskStatus.PENDING
        assert t.progress == 0.0
        assert t.result is None
        assert t.error is None

"""Tests for domain-specific exceptions."""
from __future__ import annotations

import pytest
from shared.exceptions import (
    GCAgentsError, SchedulerError, TaskExecutionError, GameBuildError,
    MarketScanError, LLMApiError, DecisionError, PersistenceError,
)


class TestExceptionHierarchy:
    def test_all_inherit_from_base(self):
        for exc_cls in [SchedulerError, TaskExecutionError, GameBuildError,
                        MarketScanError, LLMApiError, DecisionError, PersistenceError]:
            assert issubclass(exc_cls, GCAgentsError)

    def test_task_execution_error_attributes(self):
        e = TaskExecutionError("develop", "p1", "build failed")
        assert e.task_type == "develop"
        assert e.project_id == "p1"
        assert "develop" in str(e)
        assert "p1" in str(e)

    def test_game_build_error_attributes(self):
        e = GameBuildError("/tmp/game", "npm error")
        assert e.project_dir == "/tmp/game"
        assert "npm error" in str(e)

    def test_llm_api_error_attributes(self):
        e = LLMApiError("deepseek", 429, "rate limited")
        assert e.model == "deepseek"
        assert e.status_code == 429
        assert "429" in str(e)

    def test_base_exception_is_catchable(self):
        with pytest.raises(GCAgentsError):
            raise SchedulerError("tick failed")

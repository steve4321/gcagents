"""Domain-specific exceptions for GCAgents."""
from __future__ import annotations


class GCAgentsError(Exception):
    """Base exception for all GCAgents errors."""


class SchedulerError(GCAgentsError):
    """Error in the scheduler tick loop."""


class TaskExecutionError(GCAgentsError):
    """Error during task execution."""

    def __init__(self, task_type: str, project_id: str, detail: str = "") -> None:
        self.task_type = task_type
        self.project_id = project_id
        super().__init__(f"Task '{task_type}' failed for project {project_id}: {detail}")


class GameBuildError(GCAgentsError):
    """Error during game build (npm install / vite build)."""

    def __init__(self, project_dir: str, detail: str = "") -> None:
        self.project_dir = project_dir
        super().__init__(f"Build failed in {project_dir}: {detail}")


class MarketScanError(GCAgentsError):
    """Error during market data collection."""


class LLMApiError(GCAgentsError):
    """Error communicating with an LLM API."""

    def __init__(self, model: str, status_code: int | None = None, detail: str = "") -> None:
        self.model = model
        self.status_code = status_code
        super().__init__(f"LLM API error (model={model}, status={status_code}): {detail}")


class DecisionError(GCAgentsError):
    """Error in the decision gate system."""


class PersistenceError(GCAgentsError):
    """Error in database operations."""

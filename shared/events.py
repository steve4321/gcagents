"""Event sourcing core — immutable events as single source of truth."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol


class ActionType(str, Enum):
    """All system actions that produce events."""

    # Scheduler lifecycle
    SCHEDULER_TICK_START = "scheduler.tick_start"
    SCHEDULER_TICK_END = "scheduler.tick_end"

    # Task lifecycle
    TASK_ENQUEUED = "task.enqueued"
    TASK_DEQUEUED = "task.dequeued"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_RETRIED = "task.retried"

    # Decision gate
    DECISION_CREATED = "decision.created"
    DECISION_RESOLVED = "decision.resolved"
    DECISION_TIMEOUT = "decision.timeout"

    # Project lifecycle
    PROJECT_CREATED = "project.created"
    PROJECT_PHASE_CHANGED = "project.phase_changed"
    PROJECT_CANCELLED = "project.cancelled"
    PROJECT_PUBLISHED = "project.published"

    # Agent actions
    AGENT_CALLED = "agent.called"
    AGENT_TOOL_USED = "agent.tool_used"
    AGENT_MESSAGE = "agent.message"

    # CEO actions
    CEO_SUGGESTION = "ceo.suggestion"
    CEO_INSTRUCTION = "ceo.instruction"
    CEO_PROJECT_INITIATED = "ceo.project_initiated"

    # Market
    MARKET_SCAN_STARTED = "market.scan_started"
    MARKET_SCAN_COMPLETED = "market.scan_completed"

    # Memory
    MEMORY_STORED = "memory.stored"
    MEMORY_CONSOLIDATED = "memory.consolidated"

    # Verification
    VERIFICATION_PLAN_CREATED = "verification.plan_created"
    VERIFICATION_PASSED = "verification.passed"
    VERIFICATION_FAILED = "verification.failed"


@dataclass(frozen=True)
class Event:
    """Immutable event — the system's single source of truth."""

    event_id: str
    event_type: ActionType
    timestamp: str  # ISO 8601
    tick_id: int
    project_id: str | None
    agent_name: str | None
    payload: dict[str, object] = field(default_factory=dict)
    parent_event_id: str | None = None  # causal chain
    metadata: dict[str, object] = field(default_factory=dict)

    @staticmethod
    def new(
        event_type: ActionType,
        tick_id: int = 0,
        project_id: str | None = None,
        agent_name: str | None = None,
        payload: dict | None = None,
        parent_event_id: str | None = None,
        metadata: dict | None = None,
    ) -> Event:
        """Factory method — auto-generates ID and timestamp."""
        return Event(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            timestamp=datetime.now(UTC).isoformat(),
            tick_id=tick_id,
            project_id=project_id,
            agent_name=agent_name,
            payload=payload or {},
            parent_event_id=parent_event_id,
            metadata=metadata or {},
        )


class EventStoreProtocol(Protocol):
    """Interface for event storage backends."""

    async def append(self, event: Event) -> None: ...
    async def append_batch(self, events: list[Event]) -> None: ...
    async def get_events(
        self,
        project_id: str | None = None,
        event_type: ActionType | None = None,
        from_tick: int | None = None,
        to_tick: int | None = None,
        limit: int = 100,
    ) -> list[Event]: ...
    async def get_event(self, event_id: str) -> Event | None: ...
    async def get_project_timeline(self, project_id: str, from_tick: int = 0) -> list[Event]: ...
    async def replay(self, project_id: str, from_tick: int = 0) -> list[Event]: ...
    async def count_events(
        self,
        project_id: str | None = None,
        event_type: ActionType | None = None,
    ) -> int: ...

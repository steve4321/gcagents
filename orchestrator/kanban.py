"""Kanban-style persistent task board for parallel agent execution.

SQLite-backed with atomic CAS claiming to prevent double-spend.
Replaces FIFO queue with structured task states and dependency tracking.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from loguru import logger

from shared.events import ActionType, Event

DB_PATH = Path("data/gcagents.db")


class KanbanStatus(str, Enum):
    """Task states on the Kanban board."""

    TRIAGED = "triaged"  # Analyzed, waiting to be claimed
    CLAIMED = "claimed"  # Agent has claimed, not yet running
    RUNNING = "running"  # Currently executing
    REVIEW = "review"  # Completed, awaiting verification
    COMPLETED = "completed"  # Done and verified
    FAILED = "failed"  # Failed
    BLOCKED = "blocked"  # Waiting on dependency
    CANCELLED = "cancelled"  # Manually cancelled


class KanbanPriority(str, Enum):
    """Task priority levels."""

    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


@dataclass
class KanbanTask:
    """A task on the Kanban board."""

    id: str
    project_id: str
    task_type: str
    status: KanbanStatus = KanbanStatus.TRIAGED
    priority: KanbanPriority = KanbanPriority.NORMAL
    params: dict = field(default_factory=dict)
    result: dict | None = None
    error: str | None = None
    claimed_by: str | None = None
    depends_on: list[str] = field(default_factory=list)  # task IDs this depends on
    parent_task_id: str | None = None  # for decomposed tasks
    plan_id: str | None = None  # which execution plan this belongs to
    retry_count: int = 0
    max_retries: int = 3
    created_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None

    @staticmethod
    def new(
        project_id: str,
        task_type: str,
        params: dict | None = None,
        priority: KanbanPriority = KanbanPriority.NORMAL,
        depends_on: list[str] | None = None,
        parent_task_id: str | None = None,
        plan_id: str | None = None,
    ) -> KanbanTask:
        return KanbanTask(
            id=str(uuid.uuid4()),
            project_id=project_id,
            task_type=task_type,
            params=params or {},
            priority=priority,
            depends_on=depends_on or [],
            parent_task_id=parent_task_id,
            plan_id=plan_id,
            created_at=datetime.now(UTC).isoformat(),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "task_type": self.task_type,
            "status": self.status.value,
            "priority": self.priority.value,
            "params": self.params,
            "claimed_by": self.claimed_by,
            "depends_on": self.depends_on,
            "parent_task_id": self.parent_task_id,
            "plan_id": self.plan_id,
            "retry_count": self.retry_count,
        }


class KanbanBoard:
    """SQLite-backed Kanban board with atomic task claiming.

    Key design: Uses CAS (Compare-And-Swap) for atomic claiming.
    Only one agent can claim a task at a time, even with concurrent access.
    """

    def __init__(self, db_path: str | Path = DB_PATH) -> None:
        self.db_path = str(db_path)
        self._init_table()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_table(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS kanban_tasks (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'triaged',
                    priority TEXT NOT NULL DEFAULT 'normal',
                    params TEXT NOT NULL DEFAULT '{}',
                    result TEXT,
                    error TEXT,
                    claimed_by TEXT,
                    depends_on TEXT NOT NULL DEFAULT '[]',
                    parent_task_id TEXT,
                    plan_id TEXT,
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kanban_status ON kanban_tasks(status)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_kanban_project ON kanban_tasks(project_id)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kanban_type ON kanban_tasks(task_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kanban_priority ON kanban_tasks(priority)")

    # ── Core Operations ──────────────────────────────────────────────────

    async def add_task(self, task: KanbanTask, tick_id: int = 0) -> KanbanTask:
        """Add a new task to the board."""
        await asyncio.to_thread(self._add_task_sync, task)
        try:
            from orchestrator.event_store import get_event_store

            await get_event_store().append(
                Event.new(
                    event_type=ActionType.TASK_ENQUEUED,
                    tick_id=tick_id,
                    project_id=task.project_id if task.project_id != "__system__" else None,
                    payload={
                        "task_id": task.id,
                        "task_type": task.task_type,
                        "priority": task.priority.value,
                    },
                )
            )
        except (OSError, RuntimeError, ValueError) as e:
            logger.debug(f"Event store emit skipped: {e}")
        return task

    def _add_task_sync(self, task: KanbanTask) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO kanban_tasks "
                "(id, project_id, task_type, status, priority, params, depends_on, "
                "parent_task_id, plan_id, retry_count, max_retries, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task.id,
                    task.project_id,
                    task.task_type,
                    task.status.value,
                    task.priority.value,
                    json.dumps(task.params),
                    json.dumps(task.depends_on),
                    task.parent_task_id,
                    task.plan_id,
                    task.retry_count,
                    task.max_retries,
                    task.created_at,
                ),
            )

    async def claim_task(self, task_id: str, agent_name: str, tick_id: int = 0) -> bool:
        """Atomically claim a task (CAS). Returns True if claim succeeded.

        Only succeeds if task is in 'triaged' status — prevents double-claiming.
        """
        return await asyncio.to_thread(self._claim_task_sync, task_id, agent_name)

    def _claim_task_sync(self, task_id: str, agent_name: str) -> bool:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE kanban_tasks SET status='running', claimed_by=?, started_at=? "
                "WHERE id=? AND status='triaged'",
                (agent_name, now, task_id),
            )
            return cursor.rowcount == 1

    async def complete_task(
        self, task_id: str, result: dict | None = None, tick_id: int = 0
    ) -> None:
        """Mark a task as completed."""
        now = datetime.now(UTC).isoformat()
        await asyncio.to_thread(self._complete_task_sync, task_id, result, now)
        try:
            from orchestrator.event_store import get_event_store

            await get_event_store().append(
                Event.new(
                    event_type=ActionType.TASK_COMPLETED,
                    tick_id=tick_id,
                    payload={"task_id": task_id},
                )
            )
        except (OSError, RuntimeError, ValueError) as e:
            logger.debug(f"Event store emit skipped: {e}")

    def _complete_task_sync(self, task_id: str, result: dict | None, now: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE kanban_tasks SET status='completed', result=?, completed_at=? WHERE id=?",
                (json.dumps(result) if result else None, now, task_id),
            )

    async def fail_task(self, task_id: str, error: str, tick_id: int = 0) -> None:
        """Mark a task as failed."""
        await asyncio.to_thread(self._fail_task_sync, task_id, error)
        try:
            from orchestrator.event_store import get_event_store

            await get_event_store().append(
                Event.new(
                    event_type=ActionType.TASK_FAILED,
                    tick_id=tick_id,
                    payload={"task_id": task_id, "error": error[:200]},
                )
            )
        except (OSError, RuntimeError, ValueError) as e:
            logger.debug(f"Event store emit skipped: {e}")

    def _fail_task_sync(self, task_id: str, error: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE kanban_tasks SET status='failed', error=? WHERE id=?",
                (error[:500], task_id),
            )

    async def block_task(self, task_id: str, reason: str) -> None:
        """Block a task with a reason."""
        await asyncio.to_thread(self._block_task_sync, task_id, reason)

    def _block_task_sync(self, task_id: str, reason: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE kanban_tasks SET status='blocked', error=? WHERE id=?",
                (reason, task_id),
            )

    async def unblock_task(self, task_id: str) -> None:
        """Unblock a task back to triaged."""
        await asyncio.to_thread(
            lambda: self._connect().execute(
                "UPDATE kanban_tasks SET status='triaged', error=NULL WHERE id=?", (task_id,)
            )
        )

    async def retry_task(self, task_id: str, tick_id: int = 0) -> bool:
        """Reset a failed task to triaged for retry (increments retry_count)."""
        return await asyncio.to_thread(self._retry_task_sync, task_id)

    def _retry_task_sync(self, task_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT retry_count, max_retries FROM kanban_tasks WHERE id=?", (task_id,)
            ).fetchone()
            if not row:
                return False
            if row["retry_count"] >= row["max_retries"]:
                return False
            conn.execute(
                "UPDATE kanban_tasks SET status='triaged', retry_count=retry_count+1, "
                "claimed_by=NULL, error=NULL, started_at=NULL WHERE id=?",
                (task_id,),
            )
            return True

    # ── Query Operations ─────────────────────────────────────────────────

    async def get_available_tasks(
        self,
        agent_role: str | None = None,
        max_concurrent: int = 5,
        project_id: str | None = None,
    ) -> list[KanbanTask]:
        """Get triaged tasks ready to be claimed, ordered by priority.

        Filters out tasks whose dependencies are not yet completed.
        """
        return await asyncio.to_thread(
            self._get_available_sync, agent_role, max_concurrent, project_id
        )

    def _get_available_sync(self, agent_role, max_concurrent, project_id) -> list[KanbanTask]:
        with self._connect() as conn:
            query = """
                SELECT * FROM kanban_tasks 
                WHERE status='triaged'
            """
            params: list[Any] = []

            if project_id:
                query += " AND project_id=?"
                params.append(project_id)

            query += " ORDER BY "
            query += " CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 WHEN 'low' THEN 3 END"
            query += ", created_at ASC LIMIT ?"
            params.append(max_concurrent)

            rows = conn.execute(query, params).fetchall()
            tasks = [self._row_to_task(r) for r in rows]

            # Filter out tasks with unmet dependencies
            completed_ids = {
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM kanban_tasks WHERE status='completed'"
                ).fetchall()
            }
            return [t for t in tasks if all(dep in completed_ids for dep in t.depends_on)]

    async def get_running_tasks(self, project_id: str | None = None) -> list[KanbanTask]:
        """Get all currently running tasks."""
        return await asyncio.to_thread(self._get_running_sync, project_id)

    def _get_running_sync(self, project_id) -> list[KanbanTask]:
        with self._connect() as conn:
            query = "SELECT * FROM kanban_tasks WHERE status='running'"
            params: list[Any] = []
            if project_id:
                query += " AND project_id=?"
                params.append(project_id)
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_task(r) for r in rows]

    async def get_task(self, task_id: str) -> KanbanTask | None:
        """Get a single task by ID."""
        return await asyncio.to_thread(self._get_task_sync, task_id)

    def _get_task_sync(self, task_id: str) -> KanbanTask | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM kanban_tasks WHERE id=?", (task_id,)).fetchone()
            return self._row_to_task(row) if row else None

    async def get_tasks_by_project(self, project_id: str) -> list[KanbanTask]:
        """Get all tasks for a project."""
        return await asyncio.to_thread(
            lambda: [
                self._row_to_task(r)
                for r in self._connect()
                .execute(
                    "SELECT * FROM kanban_tasks WHERE project_id=? ORDER BY created_at",
                    (project_id,),
                )
                .fetchall()
            ]
        )

    async def count_by_status(self, project_id: str | None = None) -> dict[str, int]:
        """Count tasks grouped by status."""
        return await asyncio.to_thread(self._count_by_status_sync, project_id)

    def _count_by_status_sync(self, project_id) -> dict[str, int]:
        with self._connect() as conn:
            query = "SELECT status, COUNT(*) as cnt FROM kanban_tasks"
            params: list[Any] = []
            if project_id:
                query += " WHERE project_id=?"
                params.append(project_id)
            query += " GROUP BY status"
            rows = conn.execute(query, params).fetchall()
            return {row["status"]: row["cnt"] for row in rows}

    async def get_board_summary(self) -> dict[str, int]:
        """Get counts for each column on the board."""
        counts = await self.count_by_status()
        return {
            "triaged": counts.get("triaged", 0),
            "running": counts.get("running", 0),
            "completed": counts.get("completed", 0),
            "failed": counts.get("failed", 0),
            "blocked": counts.get("blocked", 0),
        }

    # ── Batch Operations ─────────────────────────────────────────────────

    async def add_tasks_batch(self, tasks: list[KanbanTask], tick_id: int = 0) -> list[KanbanTask]:
        """Add multiple tasks atomically."""
        await asyncio.to_thread(self._add_tasks_batch_sync, tasks)
        if tasks:
            try:
                from orchestrator.event_store import get_event_store

                events = [
                    Event.new(
                        event_type=ActionType.TASK_ENQUEUED,
                        tick_id=tick_id,
                        project_id=t.project_id if t.project_id != "__system__" else None,
                        payload={"task_id": t.id, "task_type": t.task_type},
                    )
                    for t in tasks
                ]
                await get_event_store().append_batch(events)
            except (OSError, RuntimeError, ValueError) as e:
                logger.debug(f"Event store batch emit skipped: {e}")
        return tasks

    def _add_tasks_batch_sync(self, tasks: list[KanbanTask]) -> None:
        with self._connect() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO kanban_tasks "
                "(id, project_id, task_type, status, priority, params, depends_on, "
                "parent_task_id, plan_id, retry_count, max_retries, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        t.id,
                        t.project_id,
                        t.task_type,
                        t.status.value,
                        t.priority.value,
                        json.dumps(t.params),
                        json.dumps(t.depends_on),
                        t.parent_task_id,
                        t.plan_id,
                        t.retry_count,
                        t.max_retries,
                        t.created_at,
                    )
                    for t in tasks
                ],
            )

    # ── Auto-Decomposition ───────────────────────────────────────────────

    async def auto_decompose(
        self, parent_task: KanbanTask, sub_tasks: list[KanbanTask]
    ) -> list[KanbanTask]:
        """Decompose a task into sub-tasks. Sub-tasks depend on each other as specified.

        The parent task is automatically blocked until all sub-tasks complete.
        """
        for st in sub_tasks:
            st.parent_task_id = parent_task.id
        await self.add_tasks_batch(sub_tasks)
        await self.block_task(parent_task.id, f"Decomposed into {len(sub_tasks)} sub-tasks")
        logger.info(f"Kanban: decomposed task {parent_task.id} into {len(sub_tasks)} sub-tasks")
        return sub_tasks

    # ── Conversion Helpers ───────────────────────────────────────────────

    def _row_to_task(self, row: sqlite3.Row) -> KanbanTask:
        return KanbanTask(
            id=row["id"],
            project_id=row["project_id"],
            task_type=row["task_type"],
            status=KanbanStatus(row["status"]),
            priority=KanbanPriority(row["priority"]),
            params=json.loads(row["params"]) if row["params"] else {},
            result=json.loads(row["result"]) if row["result"] else None,
            error=row["error"],
            claimed_by=row["claimed_by"],
            depends_on=json.loads(row["depends_on"]) if row["depends_on"] else [],
            parent_task_id=row["parent_task_id"],
            plan_id=row["plan_id"],
            retry_count=row["retry_count"] or 0,
            max_retries=row["max_retries"] or 3,
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )


# Singleton
_board: KanbanBoard | None = None


def get_kanban_board() -> KanbanBoard:
    global _board
    if _board is None:
        _board = KanbanBoard()
    return _board

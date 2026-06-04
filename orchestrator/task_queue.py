"""SQLite-backed async task queue for the scheduler.

Tasks are enqueued per project, dequeued FIFO, and tracked
with status/progress/result/error fields.
"""

from __future__ import annotations

import uuid

from loguru import logger

from orchestrator.persistence import claim_next_task, save_task, update_task_status
from shared.events import ActionType, Event
from shared.models import TaskParams, TaskRecord


async def enqueue(
    project_id: str,
    task_type: str,
    params: TaskParams | dict | None = None,
    tick_id: int = 0,
) -> TaskRecord:
    """Create and persist a new task record."""
    task = TaskRecord(
        id=str(uuid.uuid4()),
        project_id=project_id,
        task_type=task_type,
        params=params or {},
    )
    await save_task(task)
    try:
        from orchestrator.event_store import get_event_store

        await get_event_store().append(
            Event.new(
                event_type=ActionType.TASK_ENQUEUED,
                tick_id=tick_id,
                project_id=project_id if project_id != "__system__" else None,
                agent_name=task_type,
                payload={"task_id": task.id, "task_type": task_type},
            )
        )
    except Exception as e:
        logger.debug(f"Event emission skipped for enqueue: {e}")
    return task


async def dequeue(tick_id: int = 0) -> TaskRecord | None:
    """Atomically claim and return the oldest pending task, or None if queue is empty."""
    task = await claim_next_task()
    if task:
        try:
            from orchestrator.event_store import get_event_store

            await get_event_store().append(
                Event.new(
                    event_type=ActionType.TASK_DEQUEUED,
                    tick_id=tick_id,
                    project_id=task.project_id if task.project_id != "__system__" else None,
                    agent_name=task.task_type,
                    payload={"task_id": task.id, "task_type": task.task_type},
                )
            )
        except Exception as e:
            logger.debug(f"Event emission skipped for dequeue: {e}")
    return task


async def complete_task(task_id: str, result: dict | None = None, tick_id: int = 0) -> None:
    await update_task_status(
        task_id,
        status="completed",
        progress=1.0,
        result=result,
    )
    try:
        from orchestrator.event_store import get_event_store

        await get_event_store().append(
            Event.new(
                event_type=ActionType.TASK_COMPLETED,
                tick_id=tick_id,
                payload={"task_id": task_id},
            )
        )
    except Exception as e:
        logger.debug(f"Event emission skipped for complete: {e}")


async def fail_task(task_id: str, error: str, tick_id: int = 0) -> None:
    await update_task_status(task_id, status="failed", error=error)
    try:
        from orchestrator.event_store import get_event_store

        await get_event_store().append(
            Event.new(
                event_type=ActionType.TASK_FAILED,
                tick_id=tick_id,
                payload={"task_id": task_id, "error": error[:200]},
            )
        )
    except Exception as e:
        logger.debug(f"Event emission skipped for fail: {e}")


async def update_progress(task_id: str, progress: float) -> None:
    await update_task_status(task_id, status="running", progress=progress)


async def enqueue_retry(
    project_id: str,
    task_type: str,
    params: TaskParams | dict | None = None,
    *,
    retry_count: int = 0,
    retry_strategy: str = "retry_with_feedback",
    layer: int = 1,
    last_error: str | None = None,
) -> TaskRecord:
    """Enqueue a retry with recovery metadata (layer, strategy, error)."""
    base_params = dict(params or {})
    base_params["retry_count"] = retry_count
    base_params["retry_strategy"] = retry_strategy
    base_params["layer"] = layer
    if last_error:
        base_params["last_error"] = last_error
    return await enqueue(project_id, task_type, base_params)

from __future__ import annotations

import uuid

from orchestrator.persistence import save_task, get_pending_tasks, update_task_status
from shared.models import TaskRecord


async def enqueue(project_id: str, task_type: str, params: dict | None = None) -> TaskRecord:
    task = TaskRecord(
        id=str(uuid.uuid4()),
        project_id=project_id,
        task_type=task_type,
        params=params or {},
    )
    await save_task(task)
    return task


async def dequeue() -> TaskRecord | None:
    tasks = await get_pending_tasks()
    return tasks[0] if tasks else None


async def complete_task(task_id: str, result: dict | None = None) -> None:
    await update_task_status(
        task_id,
        status="completed",
        progress=1.0,
        result=result,
    )


async def fail_task(task_id: str, error: str) -> None:
    await update_task_status(task_id, status="failed", error=error)


async def update_progress(task_id: str, progress: float) -> None:
    await update_task_status(task_id, status="running", progress=progress)


async def enqueue_retry(
    project_id: str,
    task_type: str,
    params: dict | None = None,
    *,
    retry_count: int = 0,
    retry_strategy: str = "retry_with_feedback",
    layer: int = 1,
    last_error: str | None = None,
) -> TaskRecord:
    base_params = dict(params or {})
    base_params["retry_count"] = retry_count
    base_params["retry_strategy"] = retry_strategy
    base_params["layer"] = layer
    if last_error:
        base_params["last_error"] = last_error
    return await enqueue(project_id, task_type, base_params)

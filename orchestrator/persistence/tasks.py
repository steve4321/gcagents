"""Tasks table CRUD, atomic claiming, and completion counting."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.persistence.engine import _get_engine, _parse_datetime
from shared.models import TaskRecord, TaskStatus


async def save_task(task) -> str:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(UTC).isoformat()
        await db.execute(
            text("""
                INSERT INTO tasks (id, project_id, task_type, status, progress,
                    params, result, error, started_at, completed_at, created_at)
                VALUES (:id, :project_id, :task_type, :status, :progress,
                    :params, :result, :error, :started_at, :completed_at, :created_at)
            """),
            {
                "id": task.id,
                "project_id": task.project_id,
                "task_type": task.task_type,
                "status": task.status.value if hasattr(task.status, "value") else task.status,
                "progress": task.progress,
                "params": json.dumps(task.params),
                "result": json.dumps(task.result) if task.result else None,
                "error": task.error,
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                "created_at": now,
            },
        )
        await db.commit()
        return task.id


async def get_task(task_id: str) -> TaskRecord | None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        row = await db.execute(
            text("SELECT * FROM tasks WHERE id = :id"),
            {"id": task_id},
        )
        result = row.fetchone()
        if not result:
            return None
        return _row_to_task(dict(result._mapping))


async def get_project_tasks(project_id: str) -> list[TaskRecord]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = await db.execute(
            text("SELECT * FROM tasks WHERE project_id = :pid ORDER BY created_at DESC"),
            {"pid": project_id},
        )
        return [_row_to_task(dict(r._mapping)) for r in rows.fetchall()]


async def get_pending_tasks() -> list[TaskRecord]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = await db.execute(
            text(
                "SELECT * FROM tasks WHERE status IN ('pending', 'running') ORDER BY created_at ASC"
            )
        )
        return [_row_to_task(dict(r._mapping)) for r in rows.fetchall()]


async def has_active_task(project_id: str, task_type: str) -> bool:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        row = await db.execute(
            text(
                "SELECT 1 FROM tasks WHERE project_id=:pid AND task_type=:type AND status IN ('pending','running') LIMIT 1"
            ),
            {"pid": project_id, "type": task_type},
        )
        return row.fetchone() is not None


async def get_active_task_project_ids() -> set[str]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        result = await db.execute(
            text("SELECT DISTINCT project_id FROM tasks WHERE status IN ('pending', 'running')")
        )
        return {row[0] for row in result.fetchall()}


async def claim_next_task() -> TaskRecord | None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(UTC).isoformat()
        row = await db.execute(
            text(
                "UPDATE tasks SET status='running', started_at=:now "
                "WHERE id = ("
                "  SELECT id FROM tasks WHERE status='pending' ORDER BY created_at ASC LIMIT 1"
                ") "
                "RETURNING *"
            ),
            {"now": now},
        )
        claimed = row.fetchone()
        await db.commit()
        if claimed:
            return _row_to_task(dict(claimed._mapping))
        return None


async def update_task_status(
    task_id: str,
    status: str,
    progress: float | None = None,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        now = datetime.now(UTC).isoformat()
        sets = ["status=:status"]
        params: dict = {"id": task_id, "status": status}
        if progress is not None:
            sets.append("progress=:progress")
            params["progress"] = progress
        if result is not None:
            sets.append("result=:result")
            params["result"] = json.dumps(result)
        if error is not None:
            sets.append("error=:error")
            params["error"] = error
        if status in ("completed", "failed", "cancelled"):
            sets.append("completed_at=:completed_at")
            params["completed_at"] = now
        elif status == "running":
            sets.append("started_at=:started_at")
            params["started_at"] = now
        await db.execute(
            text(f"UPDATE tasks SET {', '.join(sets)} WHERE id=:id"),
            params,
        )
        await db.commit()


def _row_to_task(d: dict) -> TaskRecord:
    return TaskRecord(
        id=d["id"],
        project_id=d["project_id"],
        task_type=d["task_type"],
        status=TaskStatus(d.get("status", "pending")),
        progress=d.get("progress", 0.0),
        params=json.loads(d.get("params", "{}")),
        result=json.loads(d["result"]) if d.get("result") else None,
        error=d.get("error"),
        started_at=d.get("started_at"),
        completed_at=d.get("completed_at"),
        created_at=_parse_datetime(d.get("created_at")),
    )


async def count_completed_tasks(project_id: str) -> int:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = await db.execute(
            text("SELECT COUNT(*) FROM tasks WHERE project_id=:pid AND status='completed'"),
            {"pid": project_id},
        )
        return rows.scalar() or 0


async def count_completed_tasks_by_type(project_id: str, task_type: str) -> int:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = await db.execute(
            text(
                "SELECT COUNT(*) FROM tasks WHERE project_id=:pid AND task_type=:task_type AND status='completed'"
            ),
            {"pid": project_id, "task_type": task_type},
        )
        return rows.scalar() or 0


async def count_completed_tasks_batch(
    project_ids: list[str],
    task_types: list[str] | None = None,
) -> dict[tuple[str, str], int]:
    """Batch count of completed tasks: (project_id, task_type) -> count.

    Single SQL with GROUP BY; replaces per-project per-type N+1 calls.
    """
    if not project_ids:
        return {}
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        if task_types:
            rows = await db.execute(
                text(
                    "SELECT project_id, task_type, COUNT(*) FROM tasks "
                    "WHERE project_id IN :pids AND task_type IN :ttypes "
                    "AND status='completed' GROUP BY project_id, task_type"
                ).bindparams(
                    bindparam("pids", expanding=True),
                    bindparam("ttypes", expanding=True),
                ),
                {"pids": project_ids, "ttypes": task_types},
            )
        else:
            rows = await db.execute(
                text(
                    "SELECT project_id, task_type, COUNT(*) FROM tasks "
                    "WHERE project_id IN :pids AND status='completed' "
                    "GROUP BY project_id, task_type"
                ).bindparams(bindparam("pids", expanding=True)),
                {"pids": project_ids},
            )
    return {(r[0], r[1]): int(r[2]) for r in rows.fetchall()}


async def get_recent_completed_tasks(limit: int = 5) -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = (
            await db.execute(
                text(
                    "SELECT task_type, project_id, completed_at FROM tasks WHERE status='completed' ORDER BY completed_at DESC LIMIT :lim"
                ),
                {"lim": limit},
            )
        ).fetchall()
    return [
        {"task_type": r.task_type, "project_id": r.project_id, "completed_at": r.completed_at}
        for r in rows
    ]

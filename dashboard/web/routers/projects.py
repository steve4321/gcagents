from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from dashboard.web import api_server

router = APIRouter()


@router.post("/api/projects/{project_id}/advance")
async def advance_project(project_id: str):
    from orchestrator.persistence import get_project, update_project_phase

    project = await get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    phase_order = [
        "backlog",
        "scanning",
        "designing",
        "developing",
        "testing",
        "building",
        "publishing",
        "live",
    ]
    current_idx = (
        phase_order.index(project.phase.value) if project.phase.value in phase_order else -1
    )

    if current_idx < 0 or current_idx >= len(phase_order) - 1:
        return {"status": "error", "message": "Project is already at final phase"}

    next_phase = phase_order[current_idx + 1]
    await update_project_phase(project_id, next_phase)
    return {"status": "ok", "from": project.phase.value, "to": next_phase}


@router.post("/api/projects/{project_id}/cancel", dependencies=[Depends(api_server.get_api_key)])
async def cancel_project(project_id: str):
    from orchestrator.persistence import get_project, update_project_phase

    project = await get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    await update_project_phase(project_id, "cancelled")
    return {"status": "cancelled", "project": project.name}


@router.get("/api/orchestrator/projects")
async def list_orchestrator_projects():
    from orchestrator.persistence import get_all_projects

    projects = await get_all_projects()
    return [p.model_dump() for p in projects]


@router.get("/api/orchestrator/projects/{project_id}")
async def get_orchestrator_project(project_id: str):
    from orchestrator.persistence import get_project

    project = await get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project.model_dump()


@router.get("/api/orchestrator/tasks")
async def list_tasks(project_id: str = ""):
    from orchestrator.persistence import get_pending_tasks, get_project, get_project_tasks

    if project_id:
        tasks = await get_project_tasks(project_id)
    else:
        tasks = await get_pending_tasks()

    project_names: dict[str, str] = {}
    result = []
    for t in tasks:
        d = t.model_dump()
        if t.project_id not in project_names:
            proj = await get_project(t.project_id)
            project_names[t.project_id] = proj.name if proj else "Unknown"
        d["project_name"] = project_names[t.project_id]
        result.append(d)
    return result


@router.post("/api/projects/{project_id}/pause", dependencies=[Depends(api_server.get_api_key)])
async def pause_project(project_id: str):
    from orchestrator.persistence import update_project_phase

    await update_project_phase(project_id, "paused")
    return {"status": "paused"}


@router.post("/api/projects/{project_id}/resume", dependencies=[Depends(api_server.get_api_key)])
async def resume_project(project_id: str):
    from orchestrator.persistence import get_project, update_project_phase

    project = await get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    await update_project_phase(project_id, "backlog")
    return {"status": "resumed"}

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from dashboard.web import api_server

router = APIRouter()


@router.get("/api/status")
async def get_status():
    from orchestrator.persistence import (
        get_last_scan_time,
        get_latest_project,
        get_orchestrator_state,
    )

    state = await get_orchestrator_state()
    scan_time = await get_last_scan_time()
    project = await get_latest_project()

    phase = state["phase"] if state else "idle"

    if (
        api_server._scheduler_process is not None
        and api_server._scheduler_process.poll() is None
    ):
        phase = "scheduler"

    return {
        "phase": phase,
        "active_project": project,
        "last_scan_time": scan_time,
        "errors": json.loads(state["errors"]) if state and state["errors"] else [],
        "games": api_server.games_dir(),
    }


@router.get("/api/agents")
async def get_agents():
    from orchestrator.persistence import get_agent_logs, get_agent_stats

    agents = await get_agent_logs()
    stats = await get_agent_stats()
    return {"logs": agents, "stats": stats}


@router.get("/api/market/report")
async def get_market_report():
    from orchestrator.persistence import get_market_report_detail

    d = await get_market_report_detail()
    if not d:
        return None
    if isinstance(d.get("opportunities_json"), str):
        d["opportunities"] = json.loads(d["opportunities_json"])
    return d


@router.get("/api/market/latest")
async def get_market_latest():
    from orchestrator.persistence import get_latest_market_signals

    return await get_latest_market_signals()


@router.get("/api/projects")
async def list_projects():
    from orchestrator.persistence import get_all_projects

    projects = await get_all_projects()
    out = []
    for p in projects:
        d = p.model_dump()
        d["status"] = d.get("phase", "unknown")
        out.append(d)
    return out


@router.get("/api/pipeline/history")
async def get_pipeline_history():
    from orchestrator.persistence import get_orchestrator_history

    return await get_orchestrator_history()


@router.get("/api/memory")
async def get_memory():
    from orchestrator.persistence import get_company_memory

    return await get_company_memory()


@router.get("/api/gdd/{project_id}")
async def get_gdd(project_id: int):
    from orchestrator.persistence import get_project_gdd

    d = await get_project_gdd(str(project_id))
    if not d:
        raise HTTPException(404, "Project not found")
    if isinstance(d.get("gdd"), str):
        try:
            d["gdd"] = json.loads(d["gdd"])
        except (json.JSONDecodeError, TypeError):
            pass
    if isinstance(d.get("proposal"), str):
        try:
            d["proposal"] = json.loads(d["proposal"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

router = APIRouter()


# ── Feedback API ──────────────────────────────────────────────────────────────


@router.get("/api/feedback/summary")
async def feedback_summary():
    from orchestrator.persistence import get_live_projects, get_pending_feedback

    projects = await get_live_projects()
    result = []
    for proj in projects:
        feedback = await get_pending_feedback(str(proj["id"]))
        entry = {
            "project_id": proj["id"],
            "project_name": proj["name"],
            "total_pending": len(feedback),
            "by_category": {},
        }
        for f in feedback:
            cat = f.get("category", "other")
            entry["by_category"][cat] = entry["by_category"].get(cat, 0) + 1
        result.append(entry)
    return {"games": result, "total_pending": sum(g["total_pending"] for g in result)}


@router.get("/api/feedback/{project_id}")
async def list_feedback(project_id: int, unprocessed_only: bool = False):
    from orchestrator.persistence import get_all_feedback, get_pending_feedback

    if unprocessed_only:
        return await get_pending_feedback(str(project_id))
    return await get_all_feedback(str(project_id))


@router.get("/api/projects/{project_id}/documents")
async def get_project_documents(project_id: str):
    from orchestrator.persistence import get_project, get_project_tasks

    project = await get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    tasks = await get_project_tasks(project_id)

    # Parse task results by type — pick latest completed for each
    task_by_type: dict[str, dict] = {}
    for t in tasks:
        if t.status.value == "completed" and t.task_type not in task_by_type:
            task_by_type[t.task_type] = {
                "result": t.result,
                "completed_at": t.completed_at,
            }

    def _parse(raw):
        if raw is None:
            return None
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return raw
        return raw

    proposal_raw = getattr(project, "proposal", None)
    gdd_raw = getattr(project, "gdd", None)
    qa_raw = getattr(project, "qa_result", None)

    documents = [
        {
            "type": "proposal",
            "title": "项目提案",
            "content": _parse(proposal_raw) if proposal_raw else None,
            "available": proposal_raw is not None,
            "created_at": project.created_at,
        },
        {
            "type": "gdd",
            "title": "游戏设计文档",
            "content": _parse(gdd_raw) if gdd_raw else None,
            "available": gdd_raw is not None,
            "created_at": project.created_at,
        },
        {
            "type": "market_scan",
            "title": "市场调研报告",
            "content": (task_by_type.get("market_scan", {}).get("result")),
            "available": "market_scan" in task_by_type,
            "created_at": task_by_type.get("market_scan", {}).get("completed_at"),
        },
        {
            "type": "art_report",
            "title": "美术资源报告",
            "content": (task_by_type.get("art_gen", {}).get("result")),
            "available": "art_gen" in task_by_type,
            "created_at": task_by_type.get("art_gen", {}).get("completed_at"),
        },
        {
            "type": "music_report",
            "title": "音乐报告",
            "content": (task_by_type.get("generate_music", {}).get("result")),
            "available": "generate_music" in task_by_type,
            "created_at": task_by_type.get("generate_music", {}).get("completed_at"),
        },
        {
            "type": "qa_report",
            "title": "QA测试报告",
            "content": _parse(qa_raw) if qa_raw else None,
            "available": qa_raw is not None,
            "created_at": project.updated_at,
        },
        {
            "type": "build_report",
            "title": "构建报告",
            "content": (task_by_type.get("build", {}).get("result")),
            "available": "build" in task_by_type,
            "created_at": task_by_type.get("build", {}).get("completed_at"),
        },
    ]

    return documents


@router.get("/api/projects/live")
async def list_live_projects():
    from orchestrator.persistence import get_live_projects

    return await get_live_projects()

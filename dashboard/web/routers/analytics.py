from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from loguru import logger

router = APIRouter()


# ── Analytics ─────────────────────────────────────────────────────────────────


@router.post("/api/analytics/event")
async def receive_analytics(game: str = "", event: str = "", score: float = 0, play_time: int = 0):
    from orchestrator.persistence import find_project_by_name, save_game_metric

    try:
        pid = await find_project_by_name(game)
        if pid:
            await save_game_metric(pid, f"event_{event}", 1)
            if score > 0:
                await save_game_metric(pid, "last_score", score)
            if play_time > 0:
                await save_game_metric(pid, "avg_session_s", play_time)
    except Exception as e:
        logger.warning(f"Analytics event error: {e}")
    return {"ok": True}


@router.get("/api/analytics/summary")
async def get_analytics_summary():
    from orchestrator.persistence import get_analytics_summary

    return await get_analytics_summary()


@router.get("/api/analytics/games")
async def game_analytics():
    from orchestrator.persistence import get_game_analytics_summary

    return await get_game_analytics_summary()


@router.get("/api/analytics/games/{project_id}")
async def game_analytics_detail(project_id: int, days: int = Query(default=7, ge=1, le=90)):
    from orchestrator.persistence import get_game_metrics_detail

    metrics = await get_game_metrics_detail(project_id, days)
    if not metrics:
        from orchestrator.persistence import find_project_by_name

        found = await find_project_by_name(str(project_id))
        if not found:
            raise HTTPException(404, "Project not found")
    return {"project_id": project_id, "days": days, "metrics": metrics}


@router.get("/api/analytics/top")
async def top_games(limit: int = Query(default=10, ge=1, le=50)):
    from orchestrator.persistence import get_game_analytics_summary, get_live_projects

    summary = await get_game_analytics_summary()
    live = await get_live_projects()
    name_map = {g["id"]: g["name"] for g in live}

    ranked = []
    for pid, data in summary.get("by_game", {}).items():
        ranked.append(
            {
                "project_id": pid,
                "project_name": name_map.get(pid, str(pid)),
                "plays": data.get("plays", 0),
                "avg_score": data.get("avg_score"),
                "avg_session_seconds": data.get("avg_session_seconds"),
            }
        )
    ranked.sort(key=lambda x: x["plays"], reverse=True)
    return {"top_games": ranked[:limit]}


@router.get("/api/itch/stats")
async def get_itch_stats():
    from orchestrator.persistence import get_latest_itch_stats

    stats = await get_latest_itch_stats()
    return {"stats": stats, "total_downloads": sum(s["downloads_count"] for s in stats)}


@router.post("/api/itch/refresh")
async def refresh_itch_stats():
    from agents.ops.deployer.itch_stats import fetch_itch_stats

    results = await fetch_itch_stats()
    return {"refreshed": len(results), "games": results}

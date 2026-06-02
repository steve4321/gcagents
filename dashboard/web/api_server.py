from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from shared.config import load_config, ROOT_DIR

config = load_config()

# ── API-Key Authentication ────────────────────────────────────────────────────

_DASHBOARD_API_KEY: str = os.environ.get("DASHBOARD_API_KEY", "")


async def get_api_key(request: Request) -> None:
    """Validate ``X-API-Key`` header on control-plane endpoints.

    Security model
    ~~~~~~~~~~~~~~
    * If ``DASHBOARD_API_KEY`` is set in the environment, every mutating /
      control-plane endpoint (listed below) must carry an ``X-API-Key`` header
      whose value matches the configured key.
    * If the variable is **not** set the dependency is a no-op; the server
      should bind to ``127.0.0.1`` only (enforced in the ``__main__`` block).

    Protected endpoints (POST + WebSocket):
        ``/api/pipeline/{run,run-forever,stop}``,
        ``/api/projects/{id}/{pause,resume,cancel}``,
        ``/api/decisions/{id}/respond``,
        ``/api/chat/send``,
        ``/api/finance/budget``,
        ``/api/orchestrator/prototype``,
        ``/ws/events``.

    Always-open (no key required):
        All ``GET`` endpoints and ``POST /api/analytics/event``
        (browser telemetry).

    Returns ``401 Unauthorized`` when the key is required but missing or
    incorrect.
    """
    if not _DASHBOARD_API_KEY:
        return
    api_key = request.headers.get("X-API-Key", "")
    if api_key != _DASHBOARD_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")

# Track running pipeline process
_pipeline_process: subprocess.Popen | None = None
_forever_process: subprocess.Popen | None = None
_scheduler_process: subprocess.Popen | None = None

# Track connected WebSocket clients for event broadcasting
_event_clients: set[WebSocket] = set()


async def broadcast_event(event_data: dict):
    """Send event to all connected WebSocket clients."""
    disconnected: set[WebSocket] = set()
    for ws in _event_clients:
        try:
            await ws.send_json({"type": "event", "data": event_data})
        except Exception:
            disconnected.add(ws)
    _event_clients.difference_update(disconnected)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine
    from orchestrator.persistence import _get_engine, ensure_tables
    engine = _get_engine()
    await ensure_tables()
    yield
    await engine.dispose()


_cors_origins = (
    [o.strip() for o in _cors_raw.split(",") if o.strip()]
    if (_cors_raw := os.environ.get("DASHBOARD_CORS_ORIGINS", ""))
    else ["http://localhost:8080"]
)

app = FastAPI(title="GCAgents Dashboard", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def games_dir() -> list[dict]:
    results = []
    games_path = config.games_output_dir
    if not games_path.exists():
        return results
    for d in sorted(games_path.iterdir()):
        if d.is_dir() and (d / "dist").exists():
            dist_files = list((d / "dist").rglob("*"))
            results.append({
                "name": d.name,
                "dist_size": sum(f.stat().st_size for f in dist_files if f.is_file()),
                "file_count": len(dist_files),
                "updated": max(f.stat().st_mtime for f in dist_files) if dist_files else 0,
            })
    return results


@app.get("/api/status")
async def get_status():
    from orchestrator.persistence import (
        get_orchestrator_state, get_last_scan_time, get_latest_project,
    )
    state = await get_orchestrator_state()
    scan_time = await get_last_scan_time()
    project = await get_latest_project()

    phase = state["phase"] if state else "idle"

    if _scheduler_process is not None and _scheduler_process.poll() is None:
        phase = "scheduler"

    return {
        "phase": phase,
        "active_project": project,
        "last_scan_time": scan_time,
        "errors": json.loads(state["errors"]) if state and state["errors"] else [],
        "games": games_dir(),
    }


@app.get("/api/agents")
async def get_agents():
    from orchestrator.persistence import get_agent_logs, get_agent_stats
    agents = await get_agent_logs()
    stats = await get_agent_stats()
    return {"logs": agents, "stats": stats}


@app.get("/api/market/report")
async def get_market_report():
    from orchestrator.persistence import get_market_report_detail
    d = await get_market_report_detail()
    if not d:
        return None
    if isinstance(d.get("opportunities_json"), str):
        d["opportunities"] = json.loads(d["opportunities_json"])
    return d


@app.get("/api/market/latest")
async def get_market_latest():
    from orchestrator.persistence import get_latest_market_signals
    return await get_latest_market_signals()


@app.get("/api/projects")
async def list_projects():
    from orchestrator.persistence import get_all_projects
    projects = await get_all_projects()
    out = []
    for p in projects:
        d = p.model_dump()
        d["status"] = d.get("phase", "unknown")
        out.append(d)
    return out


@app.get("/api/pipeline/history")
async def get_pipeline_history():
    from orchestrator.persistence import get_orchestrator_history
    return await get_orchestrator_history()


@app.get("/api/memory")
async def get_memory():
    from orchestrator.persistence import get_company_memory
    return await get_company_memory()


@app.get("/api/gdd/{project_id}")
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


# ── Pipeline Control ──────────────────────────────────────────────────────────

@app.post("/api/pipeline/run", dependencies=[Depends(get_api_key)])
async def trigger_pipeline():
    global _pipeline_process
    if _pipeline_process is not None and _pipeline_process.poll() is None:
        return {"status": "already_running", "message": "Pipeline is already running"}

    try:
        _pipeline_process = subprocess.Popen(
            [sys.executable, "-m", "orchestrator.main", "run"],
            cwd=ROOT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (FileNotFoundError, PermissionError, OSError) as e:
        logger.error(f"Failed to start pipeline: {e}")
        return {"status": "error", "message": f"Failed to start pipeline: {e}"}
    logger.info(f"Pipeline started (pid={_pipeline_process.pid})")
    return {"status": "started", "message": "Pipeline started"}


@app.post("/api/pipeline/run-forever", dependencies=[Depends(get_api_key)])
async def trigger_forever(interval: int = 3600):
    global _forever_process
    if _forever_process is not None and _forever_process.poll() is None:
        return {"status": "already_running", "message": "24/7 mode is already running"}

    try:
        _forever_process = subprocess.Popen(
            [sys.executable, "-m", "orchestrator.main", "run-forever",
             "--interval", str(interval)],
            cwd=ROOT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (FileNotFoundError, PermissionError, OSError) as e:
        logger.error(f"Failed to start 24/7 mode: {e}")
        return {"status": "error", "message": f"Failed to start 24/7 mode: {e}"}
    logger.info(f"24/7 mode started (pid={_forever_process.pid}, interval={interval}s)")
    return {"status": "started", "mode": "forever", "message": "24/7 mode started"}


@app.post("/api/pipeline/run-scheduler", dependencies=[Depends(get_api_key)])
async def trigger_scheduler(interval: int = 60):
    global _scheduler_process
    if _scheduler_process is not None and _scheduler_process.poll() is None:
        return {"status": "already_running", "message": "Scheduler is already running"}

    try:
        _scheduler_process = subprocess.Popen(
            [sys.executable, "-m", "orchestrator.main", "run-scheduler",
             "--interval", str(interval)],
            cwd=ROOT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (FileNotFoundError, PermissionError, OSError) as e:
        logger.error(f"Failed to start scheduler: {e}")
        return {"status": "error", "message": f"Failed to start scheduler: {e}"}
    logger.info(f"Scheduler started (pid={_scheduler_process.pid}, interval={interval}s)")
    return {"status": "started", "mode": "scheduler", "message": f"Scheduler started (interval={interval}s)"}


@app.post("/api/scheduler/pause", dependencies=[Depends(get_api_key)])
async def pause_scheduler():
    from orchestrator.scheduler import set_paused
    set_paused(True)
    return {"paused": True}


@app.post("/api/scheduler/resume", dependencies=[Depends(get_api_key)])
async def resume_scheduler():
    from orchestrator.scheduler import set_paused
    set_paused(False)
    return {"paused": False}


@app.get("/api/scheduler/paused")
async def get_scheduler_paused():
    from orchestrator.scheduler import is_paused
    return {"paused": is_paused()}


@app.post("/api/pipeline/stop", dependencies=[Depends(get_api_key)])
async def stop_pipeline():
    global _pipeline_process, _forever_process, _scheduler_process
    stopped = []

    if _pipeline_process is not None and _pipeline_process.poll() is None:
        _pipeline_process.terminate()
        try:
            _pipeline_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _pipeline_process.kill()
        stopped.append("pipeline")
        _pipeline_process = None

    if _forever_process is not None and _forever_process.poll() is None:
        _forever_process.terminate()
        try:
            _forever_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _forever_process.kill()
        stopped.append("24/7 mode")
        _forever_process = None

    if _scheduler_process is not None and _scheduler_process.poll() is None:
        _scheduler_process.terminate()
        try:
            _scheduler_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _scheduler_process.kill()
        stopped.append("scheduler")
        _scheduler_process = None

    if stopped:
        logger.info(f"Stopped: {', '.join(stopped)}")
        return {"status": "stopped", "stopped": stopped}
    return {"status": "idle", "message": "Nothing was running"}


@app.get("/api/pipeline/status")
async def check_pipeline_status():
    global _pipeline_process, _forever_process, _scheduler_process

    scheduler_running = (
        _scheduler_process is not None and _scheduler_process.poll() is None
    )
    if not scheduler_running:
        import subprocess
        result = subprocess.run(
            ["pgrep", "-f", "orchestrator.main run-scheduler"],
            capture_output=True, text=True,
        )
        scheduler_running = bool(result.stdout.strip())

    forever_running = (
        _forever_process is not None and _forever_process.poll() is None
    )
    single_running = (
        _pipeline_process is not None and _pipeline_process.poll() is None
    )

    if scheduler_running:
        return {"running": True, "mode": "scheduler", "scheduler_running": True,
                "forever_running": forever_running, "status": "running"}
    if forever_running:
        return {"running": True, "mode": "forever", "forever_running": True,
                "scheduler_running": False, "status": "running"}
    if single_running:
        return {"running": True, "mode": "single", "forever_running": False,
                "scheduler_running": False, "status": "running"}

    # Single pipeline may have just finished — check exit code
    if _pipeline_process is not None:
        ret = _pipeline_process.poll()
        status = "completed" if ret == 0 else "failed"
        _pipeline_process = None
        return {"running": False, "mode": "idle", "forever_running": False,
                "status": status, "exit_code": ret}

    return {"running": False, "mode": "idle", "forever_running": False,
            "status": "idle"}


# ── Analytics ─────────────────────────────────────────────────────────────────

@app.post("/api/analytics/event")
async def receive_analytics(game: str = "", event: str = "", score: float = 0, play_time: int = 0):
    from orchestrator.persistence import save_game_metric, find_project_by_name
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


@app.get("/api/analytics/summary")
async def get_analytics_summary():
    from orchestrator.persistence import get_analytics_summary
    return await get_analytics_summary()


# ── Feedback API ──────────────────────────────────────────────────────────────

@app.get("/api/feedback/{project_id}")
async def list_feedback(project_id: int, unprocessed_only: bool = False):
    from orchestrator.persistence import get_pending_feedback, get_all_feedback
    if unprocessed_only:
        return await get_pending_feedback(str(project_id))
    return await get_all_feedback(str(project_id))


@app.get("/api/projects/{project_id}/documents")
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


@app.get("/api/projects/live")
async def list_live_projects():
    from orchestrator.persistence import get_live_projects
    return await get_live_projects()


# ── WebSocket Event Stream ─────────────────────────────────────────────────────

@app.websocket("/ws/events")
async def events_websocket(websocket: WebSocket):
    if _DASHBOARD_API_KEY:
        ws_key = websocket.headers.get("X-API-Key", "") or websocket.query_params.get("api_key", "")
        if ws_key != _DASHBOARD_API_KEY:
            await websocket.close(code=4001, reason="Invalid or missing X-API-Key")
            return
    await websocket.accept()
    _event_clients.add(websocket)
    try:
        from orchestrator.persistence import get_recent_events
        events = await get_recent_events(limit=50)
        for event in reversed(events):
            await websocket.send_json({"type": "event", "data": event})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _event_clients.discard(websocket)


# ── Chat API ───────────────────────────────────────────────────────────────────

@app.post("/api/chat/send", dependencies=[Depends(get_api_key)])
async def send_chat_message(message: dict):
    content = message.get("content", "").strip()
    target_agent = message.get("target_agent", "ceo").strip().lower()

    if not content:
        raise HTTPException(400, "Message content is required")

    if target_agent != "ceo":
        raise HTTPException(400, "Only CEO is available")

    from orchestrator.persistence import save_chat_message, log_event, get_all_projects
    from shared.models import ProjectPhase

    await save_chat_message(
        role="user",
        content=content,
        agent_name=target_agent,
        metadata={"target_agent": target_agent, "processed": True},
    )

    await log_event(
        event_type="system",
        severity="info",
        title=f"User message to {target_agent.upper()}",
        detail=content[:200],
        source_agent="dashboard",
    )

    reply = await _generate_ceo_reply(content)

    await save_chat_message(
        role="assistant",
        content=reply,
        agent_name="ceo",
    )

    return {"status": "sent", "target": target_agent}


async def _generate_ceo_reply(content: str) -> str:
    from orchestrator.persistence import get_all_projects, update_project_phase
    from shared.llm_client import llm
    from shared.models import ProjectPhase

    content_lower = content.lower().strip()

    # 指令式命令处理
    if any(kw in content_lower for kw in ("推进", "advance", "下一个", "next")):
        projects = await get_all_projects()
        active = [p for p in projects if p.phase not in (ProjectPhase.BACKLOG, ProjectPhase.CANCELLED, ProjectPhase.LIVE)]
        if not active:
            backlog = [p for p in projects if p.phase == ProjectPhase.BACKLOG]
            if backlog:
                await update_project_phase(backlog[0].id, "scanning")
                return f"已将 {backlog[0].name} 从 backlog 推进到 scanning 阶段。"
            return "没有可推进的项目。"
        p = active[0]
        phase_order = ["scanning", "designing", "developing", "testing", "building", "publishing", "live"]
        current_idx = phase_order.index(p.phase.value) if p.phase.value in phase_order else -1
        if current_idx < len(phase_order) - 1:
            next_phase = phase_order[current_idx + 1]
            await update_project_phase(p.id, next_phase)
            return f"已将 {p.name} 从 {p.phase.value} 推进到 {next_phase}。"
        return f"{p.name} 已经是最终阶段了。"

    if any(kw in content_lower for kw in ("取消", "cancel")):
        projects = await get_all_projects()
        for p in projects:
            if p.name.lower() in content_lower and p.phase != ProjectPhase.CANCELLED:
                await update_project_phase(p.id, "cancelled")
                return f"已取消项目 {p.name}。"
        active = [p for p in projects if p.phase not in (ProjectPhase.BACKLOG, ProjectPhase.CANCELLED)]
        if active:
            await update_project_phase(active[0].id, "cancelled")
            return f"已取消项目 {active[0].name}。"
        return "没有可取消的项目。"

    projects = await get_all_projects()
    if projects:
        lines = [f"- {p.name} ({p.phase.value}): {p.progress:.0%}" for p in projects]
        project_summary = "\n".join(lines)
    else:
        project_summary = "暂无项目"

    system_prompt = (
        "你是 GCAgents 的 CEO，一家 AI 驱动的游戏公司。你负责管理游戏项目的全生命周期。"
        "根据公司当前状态回答用户问题。简洁专业，用中文回复。\n"
        "可用指令：「推进」推进项目到下一阶段，「取消 项目名」取消项目，「状态」查看所有项目。\n\n"
        f"当前项目列表:\n{project_summary}"
    )

    try:
        reply, _ = await llm.chat_completion(
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            max_tokens=500,
            temperature=0.7,
            agent_name="ceo-chat",
        )
        return reply.strip()
    except Exception:
        if not projects:
            return "目前还没有项目。系统会自动扫描市场并创建新项目。"
        active = [p for p in projects if p.phase not in (ProjectPhase.BACKLOG, ProjectPhase.CANCELLED)]
        return f"当前 {len(projects)} 个项目，{len(active)} 个活跃中。"


@app.get("/api/chat/history")
async def get_chat_history_api(limit: int = 100):
    from orchestrator.persistence import get_chat_history
    return await get_chat_history(limit)


# ── Events API ─────────────────────────────────────────────────────────────────

@app.get("/api/events")
async def get_events(limit: int = 200, event_type: str = ""):
    from orchestrator.persistence import get_recent_events
    return await get_recent_events(limit, event_type)


# ── Finance API ────────────────────────────────────────────────────────────────

@app.post("/api/finance/budget", dependencies=[Depends(get_api_key)])
async def set_budget(budget: dict):
    from orchestrator.persistence import set_budget as db_set_budget, log_event

    category = budget.get("category", "monthly")
    budget_type = budget.get("budget_type", "monthly")
    limit_usd = budget.get("budget_limit_usd", 0)

    await db_set_budget(category, budget_type, limit_usd)
    await log_event("finance", "info", f"Budget set: {category} ${limit_usd}", source_agent="dashboard")
    return {"status": "ok"}


@app.get("/api/finance/summary")
async def get_finance_summary(days: int = 30):
    from orchestrator.persistence import get_usage_summary, get_active_budgets
    summary = await get_usage_summary(days)
    budgets = await get_active_budgets()
    return {"usage": summary, "budgets": budgets}


@app.get("/api/policy")
async def get_policy():
    from orchestrator.persistence import get_company_policy
    return await get_company_policy()


@app.post("/api/policy", dependencies=[Depends(get_api_key)])
async def set_policy(policy: dict):
    from orchestrator.persistence import set_company_policy, log_event
    await set_company_policy(policy)
    await log_event("policy", "info", "Company policy updated", source_agent="dashboard")
    return {"status": "ok"}


@app.get("/api/decisions")
async def list_decisions():
    from orchestrator.decision_gate import get_pending
    decisions = await get_pending()
    return [d.model_dump() for d in decisions]


@app.get("/api/decisions/history")
async def get_decision_history(limit: int = 50):
    from orchestrator.persistence import get_decision_history
    return await get_decision_history(limit)


@app.post("/api/decisions/{decision_id}/respond", dependencies=[Depends(get_api_key)])
async def respond_decision(decision_id: str, response: str = "", conditions: str = ""):
    from orchestrator.decision_gate import resolve
    from orchestrator.persistence import update_project_awaiting_decision
    result = await resolve(decision_id, response)
    if not result:
        raise HTTPException(404, "Decision not found")

    if conditions:
        result.context["conditions"] = conditions
        from orchestrator.persistence import _get_engine
        from sqlalchemy import text
        engine = _get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE decisions SET context=:ctx WHERE id=:id"),
                {"ctx": json.dumps(result.context), "id": decision_id},
            )

    resp = response.lower()
    pid = result.project_id
    if resp in ("approve", "approved") and pid:
        await _apply_approved_decision(result)
    elif resp in ("reject", "rejected") and pid:
        await _apply_rejected_decision(result)

    if pid:
        await update_project_awaiting_decision(pid, None)

    return result.model_dump()


@app.post("/api/projects/{project_id}/advance")
async def advance_project(project_id: str):
    from orchestrator.persistence import get_project, update_project_phase
    from shared.models import ProjectPhase

    project = await get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    phase_order = ["backlog", "scanning", "designing", "developing", "testing", "building", "publishing", "live"]
    current_idx = phase_order.index(project.phase.value) if project.phase.value in phase_order else -1

    if current_idx < 0 or current_idx >= len(phase_order) - 1:
        return {"status": "error", "message": "Project is already at final phase"}

    next_phase = phase_order[current_idx + 1]
    await update_project_phase(project_id, next_phase)
    return {"status": "ok", "from": project.phase.value, "to": next_phase}


@app.post("/api/projects/{project_id}/cancel", dependencies=[Depends(get_api_key)])
async def cancel_project(project_id: str):
    from orchestrator.persistence import get_project, update_project_phase

    project = await get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    await update_project_phase(project_id, "cancelled")
    return {"status": "cancelled", "project": project.name}


async def _apply_approved_decision(decision) -> None:
    from orchestrator.persistence import get_project, update_project_phase
    from orchestrator.task_queue import enqueue
    from shared.models import ProjectPhase

    dtype = decision.decision_type.value
    pid = decision.project_id

    if dtype == "new_project" and pid:
        await update_project_phase(pid, "scanning")

    elif dtype == "publish" and pid:
        await update_project_phase(pid, "publishing")
        project = await get_project(pid)
        if project:
            await enqueue(pid, "deploy", {"project_name": project.name})

    elif dtype == "budget_overrun" and pid:
        await update_project_phase(pid, "developing")

    elif dtype == "direction_change" and pid:
        await update_project_phase(pid, "designing")


async def _apply_rejected_decision(decision) -> None:
    from orchestrator.persistence import get_project, update_project_phase

    dtype = decision.decision_type.value
    pid = decision.project_id

    if dtype == "new_project" and pid:
        await update_project_phase(pid, "cancelled")

    elif dtype == "cancel" and pid:
        pass

    elif dtype == "publish" and pid:
        await update_project_phase(pid, "testing")


@app.get("/api/orchestrator/projects")
async def list_orchestrator_projects():
    from orchestrator.persistence import get_all_projects
    projects = await get_all_projects()
    return [p.model_dump() for p in projects]


@app.get("/api/orchestrator/projects/{project_id}")
async def get_orchestrator_project(project_id: str):
    from orchestrator.persistence import get_project
    project = await get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project.model_dump()


@app.get("/api/orchestrator/tasks")
async def list_tasks(project_id: str = ""):
    from orchestrator.persistence import get_pending_tasks, get_project_tasks, get_project
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


@app.post("/api/projects/{project_id}/pause", dependencies=[Depends(get_api_key)])
async def pause_project(project_id: str):
    from orchestrator.persistence import update_project_phase
    await update_project_phase(project_id, "paused")
    return {"status": "paused"}


@app.post("/api/projects/{project_id}/resume", dependencies=[Depends(get_api_key)])
async def resume_project(project_id: str):
    from orchestrator.persistence import get_project, update_project_phase
    project = await get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    await update_project_phase(project_id, "backlog")
    return {"status": "resumed"}


# ── Layered Memory API ────────────────────────────────────────────────────────

@app.get("/api/memory/{project_id}/recent")
async def get_recent_memories(project_id: str, category: str = "", limit: int = 20):
    from shared.memory import get_memory_store
    store = get_memory_store()
    return store.get_recent(project_id, category=category or None, limit=limit)


@app.get("/api/memory/search")
async def search_memories(q: str = "", category: str = "", limit: int = 10):
    if not q:
        raise HTTPException(400, "Query parameter 'q' is required")
    from shared.memory import get_memory_store
    store = get_memory_store()
    return store.search_long_term(q, category=category or None, limit=limit)


@app.get("/api/memory/lessons")
async def get_all_lessons():
    from shared.memory import get_memory_store
    store = get_memory_store()
    return store.get_all_lessons()


@app.post("/api/orchestrator/prototype", dependencies=[Depends(get_api_key)])
async def run_prototype(request: dict):
    concept = request.get("concept", "").strip()
    if not concept:
        raise HTTPException(400, "concept is required")
    from orchestrator.prototype_mode import run_prototype
    result = await run_prototype(concept)
    return result


# ── Game Preview Static Files ─────────────────────────────────────────────────

games_output = config.games_output_dir
if games_output.exists():
    app.mount(
        "/games-preview",
        StaticFiles(directory=str(games_output)),
        name="games-preview",
    )

app.mount("/", StaticFiles(directory=str(ROOT_DIR / "dashboard" / "web"), html=True), name="dashboard")

if __name__ == "__main__":
    import uvicorn
    _host = "127.0.0.1" if not _DASHBOARD_API_KEY else "0.0.0.0"
    if _DASHBOARD_API_KEY:
        logger.info("DASHBOARD_API_KEY configured — requiring X-API-Key on control-plane endpoints")
    else:
        logger.warning("DASHBOARD_API_KEY not set — running in permissive localhost-only mode")
    uvicorn.run("dashboard.web.api_server:app", host=_host, port=config.dashboard_port, reload=True)

from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from shared.config import ROOT_DIR, load_config

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
_scheduler_process: subprocess.Popen | None = None

# Track connected WebSocket clients for event broadcasting
_event_clients: set[WebSocket] = set()


async def broadcast_event(event_data: dict):
    """Send event to all connected WebSocket clients."""
    disconnected: set[WebSocket] = set()
    for ws in _event_clients:
        try:
            await ws.send_json({"type": "event", "data": event_data})
        except (RuntimeError, OSError, ValueError) as e:
            logger.debug(f"WebSocket send failed, disconnecting: {e}")
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
            results.append(
                {
                    "name": d.name,
                    "dist_size": sum(f.stat().st_size for f in dist_files if f.is_file()),
                    "file_count": len(dist_files),
                    "updated": max(f.stat().st_mtime for f in dist_files) if dist_files else 0,
                }
            )
    return results


@app.get("/api/status")
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


@app.post("/api/pipeline/run-scheduler", dependencies=[Depends(get_api_key)])
async def trigger_scheduler(interval: int = Query(default=60, ge=1, le=3600)):
    global _scheduler_process
    if _scheduler_process is not None and _scheduler_process.poll() is None:
        return {"status": "already_running", "message": "Scheduler is already running"}

    result = subprocess.run(
        ["pgrep", "-f", "orchestrator.main run-scheduler"],
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        return {"status": "already_running", "message": "Scheduler is already running (external)"}

    try:
        _scheduler_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "orchestrator.main",
                "run-scheduler",
                "--interval",
                str(interval),
            ],
            cwd=ROOT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (FileNotFoundError, PermissionError, OSError) as e:
        logger.error(f"Failed to start scheduler: {e}")
        return {"status": "error", "message": f"Failed to start scheduler: {e}"}
    logger.info(f"Scheduler started (pid={_scheduler_process.pid}, interval={interval}s)")
    return {
        "status": "started",
        "mode": "scheduler",
        "message": f"Scheduler started (interval={interval}s)",
    }


@app.post("/api/pipeline/stop", dependencies=[Depends(get_api_key)])
async def stop_scheduler():
    global _scheduler_process
    stopped = []

    if _scheduler_process is not None and _scheduler_process.poll() is None:
        _scheduler_process.terminate()
        try:
            _scheduler_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _scheduler_process.kill()
        stopped.append("scheduler")
        _scheduler_process = None

    result = subprocess.run(
        ["pgrep", "-f", "orchestrator.main run-scheduler"],
        capture_output=True,
        text=True,
    )
    for pid_str in result.stdout.strip().splitlines():
        try:
            os.kill(int(pid_str), 15)
            stopped.append(f"scheduler-{pid_str}")
        except (ValueError, ProcessLookupError):
            pass

    if stopped:
        logger.info(f"Stopped: {', '.join(stopped)}")
        return {"status": "stopped", "stopped": stopped}
    return {"status": "idle", "message": "Nothing was running"}


@app.get("/api/pipeline/status")
async def check_pipeline_status():
    global _scheduler_process

    scheduler_running = _scheduler_process is not None and _scheduler_process.poll() is None
    if not scheduler_running:
        result = subprocess.run(
            ["pgrep", "-f", "orchestrator.main run-scheduler"],
            capture_output=True,
            text=True,
        )
        scheduler_running = bool(result.stdout.strip())

    if scheduler_running:
        return {
            "running": True,
            "mode": "scheduler",
            "scheduler_running": True,
            "status": "running",
        }

    return {"running": False, "mode": "idle", "scheduler_running": False, "status": "idle"}


# ── Analytics ─────────────────────────────────────────────────────────────────


@app.post("/api/analytics/event")
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


@app.get("/api/analytics/summary")
async def get_analytics_summary():
    from orchestrator.persistence import get_analytics_summary

    return await get_analytics_summary()


@app.get("/api/itch/stats")
async def get_itch_stats():
    from orchestrator.persistence import get_latest_itch_stats

    stats = await get_latest_itch_stats()
    return {"stats": stats, "total_downloads": sum(s["downloads_count"] for s in stats)}


@app.post("/api/itch/refresh")
async def refresh_itch_stats():
    from agents.ops.deployer.itch_stats import fetch_itch_stats

    results = await fetch_itch_stats()
    return {"refreshed": len(results), "games": results}


# ── Feedback API ──────────────────────────────────────────────────────────────


@app.get("/api/feedback/{project_id}")
async def list_feedback(project_id: int, unprocessed_only: bool = False):
    from orchestrator.persistence import get_all_feedback, get_pending_feedback

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

    from orchestrator.persistence import log_event, save_chat_message

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


async def _build_ceo_context() -> tuple[str, list[dict]]:
    """Gather comprehensive company data for the CEO system prompt."""

    from orchestrator.persistence import (
        get_all_projects,
        get_api_usage_summary,
        get_chat_history,
        get_company_memory,
        get_company_policy,
        get_latest_market_report,
        get_pending_decisions,
        get_recent_events,
    )

    # Projects
    projects = await get_all_projects()
    if projects:
        proj_lines = []
        for p in projects:
            proj_lines.append(
                f"  - {p.name} | 类型: {p.genre or '未定'} "
                f"| 阶段: {p.phase.value} | 进度: {p.progress:.0%}"
            )
        project_summary = "\n".join(proj_lines)
    else:
        project_summary = "  （暂无项目）"

    # Market report
    market = await get_latest_market_report()
    market_summary = "  （暂无市场报告）"
    if market and market.get("opportunities_json"):
        try:
            opps = (
                json.loads(market["opportunities_json"])
                if isinstance(market["opportunities_json"], str)
                else market["opportunities_json"]
            )
            if isinstance(opps, list):
                top = opps[:3]
                opp_lines = []
                for o in top:
                    if isinstance(o, dict):
                        opp_lines.append(
                            f"  - {o.get('genre', '?')}: "
                            f"{o.get('reason', o.get('description', '无详情'))}"
                        )
                    else:
                        opp_lines.append(f"  - {o}")
                if opp_lines:
                    market_summary = "\n".join(opp_lines)
        except (json.JSONDecodeError, TypeError):
            pass

    # Financials
    usage = await get_api_usage_summary()
    total_cost = usage.get("total_cost", 0.0)
    calls = usage.get("calls", 0)

    # Pending decisions
    decisions = await get_pending_decisions()

    # Recent events
    events = await get_recent_events(limit=8)
    event_lines = []
    for ev in events[:8]:
        title = ev.get("title", "")
        if title:
            event_lines.append(f"  - {title}")
    events_summary = "\n".join(event_lines) if event_lines else "  （无近期事件）"

    # Company memory / lessons
    memories = await get_company_memory(limit=5)
    mem_lines = []
    for m in memories[:5]:
        mem_lines.append(f"  - {m.get('title', m.get('content', ''))}")
    mem_summary = "\n".join(mem_lines) if mem_lines else "  （暂无）"

    # Policy
    policy = await get_company_policy()

    # Chat history (last 6 messages)
    chat_history = await get_chat_history(limit=6)

    context = (
        f"### 项目列表\n{project_summary}\n\n"
        f"### 市场机会（最新报告前3）\n{market_summary}\n\n"
        f"### 财务状况\n"
        f"  - 总API花费: ${total_cost:.2f}\n"
        f"  - API调用次数: {calls}\n"
        f"  - 预算上限: ${policy.get('budget_limit_usd', '?')}/月\n\n"
        f"### 待处理决策: {len(decisions)} 个\n\n"
        f"### 近期事件\n{events_summary}\n\n"
        f"### 公司记忆/经验教训\n{mem_summary}\n\n"
        f"### 公司策略\n"
        f"  - 最大活跃项目数: {policy.get('max_active_projects', '?')}\n"
        f"  - 自动发布: {'是' if policy.get('auto_publish') else '否'}\n"
        f"  - 偏好类型: {', '.join(policy.get('preferred_genres', [])) or '不限'}"
    )
    return context, chat_history


async def _generate_ceo_reply(content: str) -> str:
    from shared.llm_client import llm

    context, chat_history = await _build_ceo_context()

    system_prompt = (
        "你是 GCAgents 的 CEO，一家 AI 驱动的游戏公司的首席执行官。你全权负责公司运营。\n\n"
        "## 你的职责\n"
        "- 管理所有游戏项目的全生命周期\n"
        "- 与人类讨论项目创意和方向\n"
        "- 根据市场数据和公司状况做出决策\n"
        "- 提出改善方案和新的创意\n"
        "- 回答关于公司运营的任何问题\n\n"
        "## 行动能力\n"
        "你可以通过在回复中嵌入隐藏的 JSON 动作块来执行操作。格式：\n"
        '[ACTION]{"action":"create_project","data":{...}}[/ACTION]\n'
        '[ACTION]{"action":"cancel_project","data":{"project_id":"..."}}[/ACTION]\n'
        '[ACTION]{"action":"publish_project","data":{"project_id":"..."}}[/ACTION]\n\n'
        "### create_project: 当人类明确同意创建新项目时使用\n"
        "data 需要: name (str), genre (str), description (str)\n\n"
        "### cancel_project: 当人类明确同意取消项目时使用\n"
        "data 需要: project_id (str) 或 project_name (str)\n\n"
        "### publish_project: 当项目完成测试且人类同意发布时使用\n"
        "data 需要: project_id (str) 或 project_name (str)\n\n"
        "注意：这些动作块不会显示给用户。你必须在回复中用自然语言说明你做了什么。\n\n"
        "## 沟通风格\n"
        "- 简洁专业，用中文回复\n"
        "- 主动提供建议和分析\n"
        "- 基于数据做判断，不要泛泛而谈\n"
        "- 对于人类提出的项目创意，先讨论可行性和市场情况，再决定是否创建\n"
        "- 市场分析数据仅供参考，项目立项基于与人类的讨论结果\n\n"
        f"## 当前公司状况\n{context}"
    )

    import re

    messages = [{"role": "system", "content": system_prompt}]
    for msg in chat_history[-6:]:
        role = msg.get("role", "user")
        msg_content = msg.get("content", "")
        if msg_content and role in ("user", "assistant"):
            clean = re.sub(r"\[ACTION\].*?\[/ACTION\]", "", msg_content).strip()
            if clean:
                messages.append({"role": role, "content": clean})
    messages.append({"role": "user", "content": content})

    try:
        reply, _ = await llm.chat_completion(
            model="MiniMax-M3",
            messages=messages,
            max_tokens=800,
            temperature=0.7,
            agent_name="ceo-chat",
        )
        cleaned_reply = await _execute_ceo_actions(reply.strip())
        return cleaned_reply
    except Exception as e:
        logger.error(f"CEO chat error: {e}")
        return "抱歉，我暂时无法回复。请稍后再试。"


async def _execute_ceo_actions(reply: str) -> str:
    """Parse and execute hidden [ACTION] blocks from the CEO reply."""
    import re

    actions = re.findall(r"\[ACTION\](.*?)\[/ACTION\]", reply)
    cleaned = re.sub(r"\[ACTION\].*?\[/ACTION\]", "", reply).strip()

    for action_str in actions:
        try:
            action = json.loads(action_str)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse CEO action: {action_str[:100]}")
            continue

        action_type = action.get("action")
        data = action.get("data", {})

        ALLOWED_ACTIONS = {
            "create_project",
            "cancel_project",
            "publish_project",
            "update_project",
            "pause_project",
        }
        if action_type not in ALLOWED_ACTIONS:
            logger.warning(f"Unknown CEO action type: {action_type}")
            continue

        if action_type == "create_project":
            await _action_create_project(data)
        elif action_type == "cancel_project":
            await _action_cancel_project(data)
        elif action_type == "publish_project":
            await _action_publish_project(data)
        else:
            logger.warning(f"Unknown CEO action: {action_type}")

    return cleaned


async def _action_create_project(data: dict) -> None:
    """Create a new project from CEO action data."""
    import uuid

    from orchestrator.persistence import save_project
    from shared.models import ProjectPhase, ProjectState

    name = data.get("name", "").strip()
    genre = data.get("genre", "").strip()
    description = data.get("description", "").strip()

    if not name:
        logger.warning("create_project action missing name")
        return

    project = ProjectState(
        id=str(uuid.uuid4()),
        name=name,
        genre=genre,
        phase=ProjectPhase.BACKLOG,
        proposal={"description": description} if description else None,
    )
    await save_project(project)
    logger.info(f"CEO created project: {name} (genre={genre})")


async def _action_cancel_project(data: dict) -> None:
    """Cancel a project by name or id."""
    from orchestrator.persistence import get_all_projects, update_project_phase

    project_id = data.get("project_id", "").strip()
    project_name = data.get("project_name", "").strip()

    if project_id:
        await update_project_phase(project_id, "cancelled")
        logger.info(f"CEO cancelled project: {project_id}")
        return

    if project_name:
        projects = await get_all_projects()
        for p in projects:
            if p.name.lower() == project_name.lower():
                await update_project_phase(p.id, "cancelled")
                logger.info(f"CEO cancelled project: {p.name} ({p.id})")
                return
        logger.warning(f"cancel_project: project not found: {project_name}")


async def _action_publish_project(data: dict) -> None:
    """Publish a project by name or id."""
    from orchestrator.persistence import get_all_projects, update_project_phase

    project_id = data.get("project_id", "").strip()
    project_name = data.get("project_name", "").strip()

    if project_id:
        await update_project_phase(project_id, "publishing")
        logger.info(f"CEO publishing project: {project_id}")
        return

    if project_name:
        projects = await get_all_projects()
        for p in projects:
            if p.name.lower() == project_name.lower():
                await update_project_phase(p.id, "publishing")
                logger.info(f"CEO publishing project: {p.name} ({p.id})")
                return
        logger.warning(f"publish_project: project not found: {project_name}")


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
    from orchestrator.persistence import log_event
    from orchestrator.persistence import set_budget as db_set_budget

    category = budget.get("category", "monthly")
    budget_type = budget.get("budget_type", "monthly")
    limit_usd = budget.get("budget_limit_usd", 0)
    if not isinstance(limit_usd, (int, float)) or limit_usd < 0:
        raise HTTPException(
            status_code=400, detail="budget_limit_usd must be a non-negative number"
        )

    await db_set_budget(category, budget_type, limit_usd)
    await log_event(
        "finance", "info", f"Budget set: {category} ${limit_usd}", source_agent="dashboard"
    )
    return {"status": "ok"}


@app.get("/api/finance/summary")
async def get_finance_summary(days: int = 30):
    from orchestrator.persistence import get_active_budgets, get_usage_summary

    summary = await get_usage_summary(days)
    budgets = await get_active_budgets()
    return {"usage": summary, "budgets": budgets}


@app.get("/api/policy")
async def get_policy():
    from orchestrator.persistence import get_company_policy

    return await get_company_policy()


@app.post("/api/policy", dependencies=[Depends(get_api_key)])
async def set_policy(policy: dict):
    from orchestrator.persistence import log_event, set_company_policy

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
        from sqlalchemy import text

        from orchestrator.persistence import _get_engine

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
    from orchestrator.persistence import update_project_phase

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


# ── Game Preview Static Files ─────────────────────────────────────────────────

games_output = config.games_output_dir
if games_output.exists():
    app.mount(
        "/games-preview",
        StaticFiles(directory=str(games_output)),
        name="games-preview",
    )

app.mount(
    "/", StaticFiles(directory=str(ROOT_DIR / "dashboard" / "web"), html=True), name="dashboard"
)

if __name__ == "__main__":
    import uvicorn

    _host = "127.0.0.1" if not _DASHBOARD_API_KEY else "0.0.0.0"
    if _DASHBOARD_API_KEY:
        logger.info("DASHBOARD_API_KEY configured — requiring X-API-Key on control-plane endpoints")
    else:
        logger.warning("DASHBOARD_API_KEY not set — running in permissive localhost-only mode")
    uvicorn.run("dashboard.web.api_server:app", host=_host, port=config.dashboard_port, reload=True)

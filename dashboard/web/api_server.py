from __future__ import annotations

import json
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from shared.config import load_config, ROOT_DIR

config = load_config()
engine = create_async_engine(config.db_url, echo=False)

# Track running pipeline process
_pipeline_process: subprocess.Popen | None = None

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
    yield
    await engine.dispose()


app = FastAPI(title="GCAgents Dashboard", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    async with AsyncSession(engine) as db:
        state_row = (await db.execute(
            text("SELECT phase, errors FROM orchestrator_state ORDER BY id DESC LIMIT 1")
        )).fetchone()

        scan_row = (await db.execute(
            text("SELECT MAX(captured_at) as last_scan FROM market_signals")
        )).fetchone()

        proj_row = (await db.execute(
            text("SELECT name, status FROM game_projects ORDER BY updated_at DESC LIMIT 1")
        )).fetchone()

        return {
            "phase": state_row.phase if state_row else "idle",
            "active_project": {"name": proj_row.name, "status": proj_row.status} if proj_row else None,
            "last_scan_time": scan_row.last_scan if scan_row and scan_row.last_scan else None,
            "errors": json.loads(state_row.errors) if state_row and state_row.errors else [],
            "games": games_dir(),
        }


@app.get("/api/agents")
async def get_agents():
    async with AsyncSession(engine) as db:
        rows = (await db.execute(text("""
            SELECT node_name, status, phase, started_at, completed_at, duration_ms, error, project_name
            FROM agent_logs
            ORDER BY id DESC
            LIMIT 50
        """))).fetchall()

        agents = [dict(r._mapping) for r in rows]

        stats = (await db.execute(text("""
            SELECT
                node_name,
                COUNT(*) as runs,
                SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as successes,
                SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failures,
                ROUND(AVG(CASE WHEN duration_ms IS NOT NULL THEN duration_ms ELSE 0 END)) as avg_duration_ms
            FROM agent_logs
            GROUP BY node_name
            ORDER BY node_name
        """))).fetchall()

        return {"logs": agents, "stats": [dict(r._mapping) for r in stats]}


@app.get("/api/market/report")
async def get_market_report():
    async with AsyncSession(engine) as db:
        report = (await db.execute(
            text("SELECT * FROM market_reports ORDER BY id DESC LIMIT 1")
        )).fetchone()

        if not report:
            return None

        d = dict(report._mapping)
        if isinstance(d.get("opportunities_json"), str):
            d["opportunities"] = json.loads(d["opportunities_json"])
        return d


@app.get("/api/market/latest")
async def get_market_latest():
    async with AsyncSession(engine) as db:
        rows = (await db.execute(
            text("""
                SELECT id, source, signal_type, genre, title, data, score, captured_at
                FROM market_signals
                ORDER BY captured_at DESC
                LIMIT 50
            """)
        )).fetchall()
        signals = []
        for row in rows:
            d = dict(row._mapping)
            if isinstance(d.get("data"), str):
                d["data"] = json.loads(d["data"])
            signals.append(d)
        return signals


@app.get("/api/projects")
async def list_projects():
    async with AsyncSession(engine) as db:
        rows = (await db.execute(
            text("""
                SELECT id, name, genre, status, gdd, itch_url,
                       created_at, updated_at, published_at
                FROM game_projects
                ORDER BY updated_at DESC
            """)
        )).fetchall()
        projects = []
        for row in rows:
            d = dict(row._mapping)
            if isinstance(d.get("gdd"), str):
                try:
                    d["gdd"] = json.loads(d["gdd"])
                except (json.JSONDecodeError, TypeError):
                    pass
            projects.append(d)
        return projects


@app.get("/api/pipeline/history")
async def get_pipeline_history():
    async with AsyncSession(engine) as db:
        rows = (await db.execute(
            text("SELECT phase, updated_at, errors FROM orchestrator_state ORDER BY id DESC LIMIT 20")
        )).fetchall()
        return [dict(r._mapping) for r in rows]


@app.get("/api/memory")
async def get_memory():
    async with AsyncSession(engine) as db:
        rows = (await db.execute(
            text("""
                SELECT id, category, title, content, importance, created_at
                FROM company_memory
                ORDER BY importance DESC, created_at DESC
                LIMIT 50
            """)
        )).fetchall()
        memories = []
        for row in rows:
            d = dict(row._mapping)
            if isinstance(d.get("content"), str):
                try:
                    d["content"] = json.loads(d["content"])
                except (json.JSONDecodeError, TypeError):
                    pass
            memories.append(d)
        return memories


@app.get("/api/gdd/{project_id}")
async def get_gdd(project_id: int):
    async with AsyncSession(engine) as db:
        row = (await db.execute(
            text("SELECT name, gdd, proposal FROM game_projects WHERE id = :pid"),
            {"pid": project_id},
        )).fetchone()
        if not row:
            raise HTTPException(404, "Project not found")
        d = dict(row._mapping)
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

@app.post("/api/pipeline/run")
async def trigger_pipeline():
    global _pipeline_process
    if _pipeline_process is not None and _pipeline_process.poll() is None:
        return {"status": "already_running", "message": "Pipeline is already running"}

    _pipeline_process = subprocess.Popen(
        [sys.executable, "-m", "orchestrator.main", "run"],
        cwd=ROOT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    logger.info(f"Pipeline started (pid={_pipeline_process.pid})")
    return {"status": "started", "message": "Pipeline started"}


@app.get("/api/pipeline/status")
async def check_pipeline_status():
    global _pipeline_process
    if _pipeline_process is None:
        return {"running": False, "status": "idle"}
    ret = _pipeline_process.poll()
    if ret is None:
        return {"running": True, "status": "running"}
    status = "completed" if ret == 0 else "failed"
    _pipeline_process = None
    return {"running": False, "status": status, "exit_code": ret}


# ── Analytics ─────────────────────────────────────────────────────────────────

@app.post("/api/analytics/event")
async def receive_analytics(game: str = "", event: str = "", score: float = 0, play_time: int = 0):
    from orchestrator.persistence import save_game_metric, _get_engine
    from sqlalchemy import text
    try:
        engine = _get_engine()
        async with AsyncSession(engine) as db:
            row = await db.execute(
                text("SELECT id FROM game_projects WHERE name = :name"),
                {"name": game},
            )
            row = row.fetchone()
            if row:
                pid = row[0]
                await save_game_metric(pid, f"event_{event}", 1)
                if score > 0:
                    await save_game_metric(pid, "last_score", score)
                if play_time > 0:
                    await save_game_metric(pid, "avg_session_s", play_time)
    except Exception:
        pass
    return {"ok": True}


# ── Feedback API ──────────────────────────────────────────────────────────────

@app.get("/api/feedback/{project_id}")
async def list_feedback(project_id: int, unprocessed_only: bool = False):
    from orchestrator.persistence import _get_engine
    from sqlalchemy import text
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        if unprocessed_only:
            rows = await db.execute(
                text("SELECT * FROM game_feedback WHERE project_id = :pid AND processed = 0 ORDER BY posted_at DESC"),
                {"pid": project_id},
            )
        else:
            rows = await db.execute(
                text("SELECT * FROM game_feedback WHERE project_id = :pid ORDER BY posted_at DESC LIMIT 50"),
                {"pid": project_id},
            )
        return [dict(r._mapping) for r in rows.fetchall()]


@app.get("/api/projects/live")
async def list_live_projects():
    from orchestrator.persistence import get_live_projects
    return await get_live_projects()


# ── WebSocket Event Stream ─────────────────────────────────────────────────────

@app.websocket("/ws/events")
async def events_websocket(websocket: WebSocket):
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

@app.post("/api/chat/send")
async def send_chat_message(message: dict):
    content = message.get("content", "").strip()
    target_agent = message.get("target_agent", "ceo").strip().lower()

    if not content:
        raise HTTPException(400, "Message content is required")

    if target_agent not in ("ceo", "cfo", "coo"):
        raise HTTPException(400, "Target must be ceo, cfo, or coo")

    from orchestrator.persistence import save_chat_message, log_event

    await save_chat_message(
        role="user",
        content=content,
        agent_name=target_agent,
        metadata={"target_agent": target_agent, "processed": False},
    )

    await log_event(
        event_type="system",
        severity="info",
        title=f"User message to {target_agent.upper()}",
        detail=content[:200],
        source_agent="dashboard",
    )

    return {"status": "sent", "target": target_agent}


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

@app.post("/api/finance/budget")
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
    uvicorn.run("dashboard.web.api_server:app", host="0.0.0.0", port=config.dashboard_port, reload=True)

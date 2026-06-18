from __future__ import annotations

import os
import subprocess
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
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


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error on {request.method} {request.url.path}: {exc}")
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "path": request.url.path},
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


# ── API Routers ───────────────────────────────────────────────────────────────
# Imported after shared state is defined so routers can resolve
# ``api_server.get_api_key`` / ``api_server._scheduler_process`` etc.
from dashboard.web.routers import (  # noqa: E402
    analytics,
    chat,
    decisions,
    feedback,
    finance,
    memory,
    metrics,
    pipeline,
    projects,
    status,
)

# Re-export chat helpers for backward compatibility (tests import these by name)
from dashboard.web.routers.chat import _CEO_PROMPT_CACHE, _load_ceo_prompt  # noqa: E402, F401

app.include_router(status.router)
app.include_router(pipeline.router)
app.include_router(analytics.router)
app.include_router(feedback.router)
app.include_router(chat.router)
app.include_router(finance.router)
app.include_router(decisions.router)
app.include_router(projects.router)
app.include_router(memory.router)
app.include_router(metrics.router)


# ── WebSocket Event Stream ─────────────────────────────────────────────────────


@app.websocket("/ws/events")
async def events_websocket(websocket: WebSocket):
    if _DASHBOARD_API_KEY:
        ws_key = websocket.headers.get("X-API-Key", "") or websocket.query_params.get(
            "api_key", ""
        )
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


# ── Events API ─────────────────────────────────────────────────────────────────


@app.get("/api/events")
async def get_events(limit: int = 200, event_type: str = ""):
    from orchestrator.persistence import get_recent_events

    return await get_recent_events(limit, event_type)


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

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from shared.config import AppConfig, load_config, ROOT_DIR

config: AppConfig = load_config()
engine = create_async_engine(config.db_url, echo=False)


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


async def get_db() -> AsyncSession:
    async with AsyncSession(engine) as session:
        yield session


async def row_to_dict(row) -> dict:
    return dict(row._mapping)


@app.get("/api/status")
async def get_status():
    async with AsyncSession(engine) as db:
        result = await db.execute(
            text("""
                SELECT phase::text, current_project_id, errors
                FROM orchestrator_state
                ORDER BY id DESC
                LIMIT 1
            """)
        )
        state_row = result.fetchone()

        result = await db.execute(
            text("SELECT MAX(captured_at) as last_scan FROM market_signals")
        )
        scan_row = result.fetchone()

        active_project = None
        if state_row and state_row.current_project_id:
            result = await db.execute(
                text("SELECT name, status FROM game_projects WHERE id = :pid"),
                {"pid": state_row.current_project_id},
            )
            proj = result.fetchone()
            if proj:
                active_project = {"name": proj.name, "status": proj.status}

        return {
            "phase": state_row.phase if state_row else "idle",
            "active_project": active_project,
            "last_scan_time": scan_row.last_scan.isoformat() if scan_row and scan_row.last_scan else None,
            "errors": state_row.errors if state_row and state_row.errors else [],
        }


@app.get("/api/projects")
async def list_projects():
    async with AsyncSession(engine) as db:
        result = await db.execute(
            text("""
                SELECT id, name, genre, status, itch_url,
                       created_at, updated_at, published_at
                FROM game_projects
                ORDER BY updated_at DESC
            """)
        )
        rows = result.fetchall()
        projects = []
        for row in rows:
            d = dict(row._mapping)
            for col in ("created_at", "updated_at", "published_at"):
                if d.get(col):
                    d[col] = d[col].isoformat()
            projects.append(d)
        return projects


@app.get("/api/projects/{project_id}")
async def get_project(project_id: int):
    async with AsyncSession(engine) as db:
        result = await db.execute(
            text("SELECT * FROM game_projects WHERE id = :pid"),
            {"pid": project_id},
        )
        row = result.fetchone()
        if not row:
            raise HTTPException(404, "Project not found")
        d = dict(row._mapping)
        for col in ("created_at", "updated_at", "published_at"):
            if d.get(col):
                d[col] = d[col].isoformat()
        return d


@app.get("/api/market/latest")
async def get_market_latest():
    async with AsyncSession(engine) as db:
        result = await db.execute(
            text("""
                SELECT id, source, signal_type, genre, title, data, score, captured_at
                FROM market_signals
                ORDER BY captured_at DESC
                LIMIT 50
            """)
        )
        rows = result.fetchall()
        signals = []
        for row in rows:
            d = dict(row._mapping)
            d["captured_at"] = d["captured_at"].isoformat()
            if isinstance(d.get("data"), str):
                d["data"] = json.loads(d["data"])
            signals.append(d)
        return signals


@app.get("/api/metrics/{project_id}")
async def get_metrics(project_id: int):
    async with AsyncSession(engine) as db:
        result = await db.execute(
            text("""
                SELECT metric_type, value, captured_at
                FROM game_metrics
                WHERE project_id = :pid
                ORDER BY captured_at DESC
                LIMIT 100
            """),
            {"pid": project_id},
        )
        rows = result.fetchall()
        metrics = []
        for row in rows:
            d = dict(row._mapping)
            d["captured_at"] = d["captured_at"].isoformat()
            metrics.append(d)
        return metrics


@app.get("/api/memory")
async def get_memory():
    async with AsyncSession(engine) as db:
        result = await db.execute(
            text("""
                SELECT id, category, title, content, importance, created_at
                FROM company_memory
                ORDER BY importance DESC, created_at DESC
                LIMIT 50
            """)
        )
        rows = result.fetchall()
        memories = []
        for row in rows:
            d = dict(row._mapping)
            d["created_at"] = d["created_at"].isoformat()
            if isinstance(d.get("content"), str):
                d["content"] = json.loads(d["content"])
            memories.append(d)
        return memories


app.mount("/", StaticFiles(directory="dashboard/web", html=True), name="dashboard")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api_server:app", host="0.0.0.0", port=config.dashboard_port, reload=True)

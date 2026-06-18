from __future__ import annotations

import os
import subprocess
import sys

from fastapi import APIRouter, Depends, Query
from loguru import logger

from dashboard.web import api_server
from shared.config import ROOT_DIR

router = APIRouter()


# ── Pipeline Control ──────────────────────────────────────────────────────────


@router.post("/api/pipeline/run-scheduler", dependencies=[Depends(api_server.get_api_key)])
async def trigger_scheduler(interval: int = Query(default=60, ge=1, le=3600)):
    if (
        api_server._scheduler_process is not None
        and api_server._scheduler_process.poll() is None
    ):
        return {"status": "already_running", "message": "Scheduler is already running"}

    result = subprocess.run(
        ["pgrep", "-f", "orchestrator.main run-scheduler"],
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        return {"status": "already_running", "message": "Scheduler is already running (external)"}

    try:
        api_server._scheduler_process = subprocess.Popen(
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
    logger.info(
        f"Scheduler started (pid={api_server._scheduler_process.pid}, interval={interval}s)"
    )
    return {
        "status": "started",
        "mode": "scheduler",
        "message": f"Scheduler started (interval={interval}s)",
    }


@router.post("/api/pipeline/stop", dependencies=[Depends(api_server.get_api_key)])
async def stop_scheduler():
    stopped = []

    if (
        api_server._scheduler_process is not None
        and api_server._scheduler_process.poll() is None
    ):
        api_server._scheduler_process.terminate()
        try:
            api_server._scheduler_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            api_server._scheduler_process.kill()
        stopped.append("scheduler")
        api_server._scheduler_process = None

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


@router.get("/api/pipeline/status")
async def check_pipeline_status():
    scheduler_running = (
        api_server._scheduler_process is not None
        and api_server._scheduler_process.poll() is None
    )
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

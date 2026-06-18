"""Startup wrapper for the GCAgents dashboard.

Avoids the pre-existing circular import in dashboard.web.routers.chat
by adding the project root to sys.path before the uvicorn import.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import uvicorn  # noqa: E402

from shared.config import load_config  # noqa: E402

config = load_config()
host = "127.0.0.1"
port = config.dashboard_port

if __name__ == "__main__":
    uvicorn.run(
        "dashboard.web.api_server:app",
        host=host,
        port=port,
        reload=False,
    )

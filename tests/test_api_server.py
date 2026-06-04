"""Basic tests for the FastAPI dashboard API."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine


@pytest_asyncio.fixture
async def client():
    """Create an async test client for the FastAPI app with in-memory SQLite."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    with (
        patch("orchestrator.persistence._get_engine", return_value=test_engine),
        patch("orchestrator.persistence._engine_cache", None),
    ):
        from dashboard.web.api_server import app
        from orchestrator.persistence import ensure_tables

        await ensure_tables()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.mark.asyncio
async def test_get_status(client):
    """GET /api/status returns 200."""
    response = await client.get("/api/status")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_projects(client):
    """GET /api/orchestrator/projects returns a list."""
    response = await client.get("/api/orchestrator/projects")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_get_decisions(client):
    """GET /api/decisions returns a list."""
    response = await client.get("/api/decisions")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_get_tasks(client):
    """GET /api/orchestrator/tasks returns a list."""
    response = await client.get("/api/orchestrator/tasks")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_market_report(client):
    """GET /api/market/report returns 200 (may be empty)."""
    response = await client.get("/api/market/report")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_events(client):
    """GET /api/events returns a list."""
    response = await client.get("/api/events")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_post_analytics_event(client):
    """POST /api/analytics/event accepts telemetry without auth."""
    response = await client.post(
        "/api/analytics/event",
        params={
            "game": "test-game",
            "event": "game_start",
        },
    )
    assert response.status_code == 200

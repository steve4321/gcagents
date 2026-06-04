"""Tests for game analytics dashboard: persistence functions and API endpoints."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine


@pytest_asyncio.fixture
async def client():
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
async def test_get_game_analytics_summary_empty(client):
    response = await client.get("/api/analytics/games")
    assert response.status_code == 200
    data = response.json()
    assert "by_game" in data
    assert "recent_24h" in data
    assert data["by_game"] == {}
    assert data["recent_24h"] == {}


@pytest.mark.asyncio
async def test_get_game_analytics_summary_with_data(client):
    from orchestrator.persistence import save_game_metric

    with patch("orchestrator.persistence._engine_cache", None):
        await save_game_metric(1, "event_game_start", 1)
        await save_game_metric(1, "event_game_start", 1)
        await save_game_metric(1, "last_score", 42.0)
        await save_game_metric(1, "avg_session_s", 120)

    response = await client.get("/api/analytics/games")
    assert response.status_code == 200
    data = response.json()
    assert "1" in data["by_game"] or 1 in data["by_game"]

    key = 1 if 1 in data["by_game"] else "1"
    game = data["by_game"][key]
    assert game["plays"] == 2
    assert game["avg_score"] == 42.0
    assert game["avg_session_seconds"] == 120.0


@pytest.mark.asyncio
async def test_get_game_metrics_detail(client):
    from orchestrator.persistence import save_game_metric

    with patch("orchestrator.persistence._engine_cache", None):
        await save_game_metric(5, "event_game_start", 1)
        await save_game_metric(5, "last_score", 99.5)

    response = await client.get("/api/analytics/games/5")
    assert response.status_code == 200
    data = response.json()
    assert data["project_id"] == 5
    assert len(data["metrics"]) == 2


@pytest.mark.asyncio
async def test_get_game_metrics_detail_not_found(client):
    response = await client.get("/api/analytics/games/999?days=30")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_top_games_empty(client):
    response = await client.get("/api/analytics/top")
    assert response.status_code == 200
    data = response.json()
    assert "top_games" in data
    assert data["top_games"] == []


@pytest.mark.asyncio
async def test_top_games_ranked(client):
    from orchestrator.persistence import save_game_metric

    with patch("orchestrator.persistence._engine_cache", None):
        for _ in range(10):
            await save_game_metric(1, "event_game_start", 1)
        for _ in range(5):
            await save_game_metric(2, "event_game_start", 1)

    response = await client.get("/api/analytics/top")
    assert response.status_code == 200
    data = response.json()
    assert len(data["top_games"]) == 2
    assert data["top_games"][0]["plays"] >= data["top_games"][1]["plays"]


@pytest.mark.asyncio
async def test_top_games_limit(client):
    response = await client.get("/api/analytics/top?limit=3")
    assert response.status_code == 200
    data = response.json()
    assert len(data["top_games"]) <= 3


@pytest.mark.asyncio
async def test_persistence_get_game_analytics_summary(tmp_db):
    from sqlalchemy import text

    from orchestrator.persistence import ensure_tables, get_game_analytics_summary

    await ensure_tables()

    async with tmp_db.begin() as conn:
        await conn.execute(
            text("INSERT INTO game_metrics (project_id, metric_name, metric_value) VALUES (1, 'event_game_start', 1)")
        )
        await conn.execute(
            text("INSERT INTO game_metrics (project_id, metric_name, metric_value) VALUES (1, 'event_game_start', 1)")
        )
        await conn.execute(
            text("INSERT INTO game_metrics (project_id, metric_name, metric_value) VALUES (1, 'last_score', 50.0)")
        )

    result = await get_game_analytics_summary()
    assert "by_game" in result
    assert 1 in result["by_game"]
    assert result["by_game"][1]["plays"] == 2
    assert result["by_game"][1]["avg_score"] == 50.0


@pytest.mark.asyncio
async def test_persistence_get_game_metrics_detail(tmp_db):
    from sqlalchemy import text

    from orchestrator.persistence import ensure_tables, get_game_metrics_detail

    await ensure_tables()

    async with tmp_db.begin() as conn:
        await conn.execute(
            text("INSERT INTO game_metrics (project_id, metric_name, metric_value) VALUES (1, 'event_game_start', 1)")
        )
        await conn.execute(
            text("INSERT INTO game_metrics (project_id, metric_name, metric_value) VALUES (1, 'last_score', 100)")
        )
        await conn.execute(
            text("INSERT INTO game_metrics (project_id, metric_name, metric_value) VALUES (2, 'event_game_start', 1)")
        )

    result = await get_game_metrics_detail(1, days=7)
    assert len(result) == 2

    result_empty = await get_game_metrics_detail(999, days=7)
    assert result_empty == []

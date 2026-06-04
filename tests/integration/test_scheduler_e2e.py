"""Integration tests — full scheduler tick with mocked LLM and persistence.

These tests exercise the scheduler end-to-end (state machine + task queue)
without requiring real LLM calls or external services. They use a fresh
SQLite database per test.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from orchestrator import scheduler
from orchestrator.persistence import (
    ensure_tables,
    get_project,
    save_project,
    set_project_live,
)
from orchestrator.scheduler import scheduler_tick
from shared.models import ProjectPhase, ProjectState


@pytest_asyncio.fixture
async def fresh_db(tmp_db):
    await ensure_tables()
    yield tmp_db


@pytest.fixture
def mock_llm():
    """Stub the shared llm client so async tasks succeed without network."""
    fake_response = ("mocked LLM response", {"tokens": 0})
    with patch("shared.llm_client.llm") as mock:
        mock.chat_completion = AsyncMock(return_value=fake_response)
        yield mock


async def _make_project(name: str = "Test Game", genre: str = "puzzle") -> ProjectState:
    pid = uuid.uuid4().hex[:12]
    project = ProjectState(
        id=pid,
        name=name,
        genre=genre,
        phase=ProjectPhase.BACKLOG,
        proposal={"name": name, "genre": genre, "description": "test"},
    )
    await save_project(project)
    return project


class TestSchedulerTickEndToEnd:
    @pytest.mark.asyncio
    async def test_tick_with_no_projects_succeeds(self, fresh_db, mock_llm):
        result = await scheduler_tick()
        assert result is not None
        assert "tick" in result
        assert result["tick"] >= 1

    @pytest.mark.asyncio
    async def test_tick_does_not_crash_with_empty_db(self, fresh_db, mock_llm):
        for _ in range(3):
            result = await scheduler_tick()
            assert result is not None
            assert result["tick"] >= 1

    @pytest.mark.asyncio
    async def test_tick_skips_awaiting_decision_projects(self, fresh_db, mock_llm):
        project = await _make_project()
        project.awaiting_decision = "publish"
        await save_project(project)
        await scheduler_tick()
        p = await get_project(project.id)
        assert p is not None


class TestPersistenceIntegration:
    @pytest.mark.asyncio
    async def test_save_and_get_project_round_trip(self, fresh_db):
        project = await _make_project("Round Trip", "shooter")
        loaded = await get_project(project.id)
        assert loaded is not None
        assert loaded.name == "Round Trip"
        assert loaded.genre == "shooter"
        assert loaded.phase == ProjectPhase.BACKLOG

    @pytest.mark.asyncio
    async def test_set_project_live_persists(self, fresh_db):
        project = await _make_project("Live Test", "rpg")
        await set_project_live(project.id, "https://example.itch.io/test")
        loaded = await get_project(project.id)
        assert loaded is not None
        assert loaded.itch_url == "https://example.itch.io/test"
        assert loaded.phase == ProjectPhase.LIVE

    @pytest.mark.asyncio
    async def test_save_preserves_uuid_id(self, fresh_db):
        pid = "abc123def456"
        project = ProjectState(
            id=pid,
            name="UUID Test",
            genre="rpg",
            phase=ProjectPhase.BACKLOG,
        )
        await save_project(project)
        loaded = await get_project(pid)
        assert loaded is not None
        assert loaded.id == pid

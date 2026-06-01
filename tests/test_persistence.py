"""Tests for orchestrator/persistence.py — database layer.

Key regression test: ``orchestrator_state`` table was once referenced but never
created by ``ensure_tables()``, causing silent pipeline tracking failures.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import orchestrator.persistence as persist


@pytest.mark.asyncio
async def test_ensure_tables_creates_orchestrator_state(tmp_db):
    """REGRESSION: ensure_tables must create the orchestrator_state table.

    Historical bug: ``save_pipeline_state()`` referenced ``orchestrator_state``
    but ``ensure_tables()`` never created it, causing OperationalError at runtime.
    """
    await persist.ensure_tables()

    async with AsyncSession(tmp_db) as db:
        result = await db.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='orchestrator_state'")
        )
        assert result.fetchone() is not None


@pytest.mark.asyncio
async def test_save_pipeline_state_inserts_row(tmp_db):
    """Verify INSERT into orchestrator_state actually persists a row."""
    await persist.ensure_tables()

    await persist.save_pipeline_state(phase="developing", errors=["err1"])

    async with AsyncSession(tmp_db) as db:
        result = await db.execute(text("SELECT phase, errors FROM orchestrator_state"))
        row = result.fetchone()
        assert row is not None
        assert row[0] == "developing"
        assert json.loads(row[1]) == ["err1"]


@pytest.mark.asyncio
async def test_ensure_tables_idempotent(tmp_db):
    """Running ensure_tables twice must not raise."""
    await persist.ensure_tables()
    await persist.ensure_tables()

    async with AsyncSession(tmp_db) as db:
        result = await db.execute(
            text("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
        )
        assert result.scalar() > 0


@pytest.mark.asyncio
async def test_get_project_returns_none_for_missing(tmp_db):
    """get_project with an unknown id returns None."""
    await persist.ensure_tables()

    result = await persist.get_project("nonexistent-id")
    assert result is None

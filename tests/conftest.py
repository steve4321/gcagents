"""Shared pytest fixtures for GCAgents test suite.

Provides a fresh in-memory SQLite database per test, an async event loop,
and autouse cleanup to prevent state leakage between tests.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped event loop for async tests (pytest-asyncio)."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture()
def tmp_db(tmp_path):
    """Create a fresh SQLite database on tmp_path and monkeypatch persistence.

    Returns the aiosqlite URL so tests can also create their own sessions.
    The real ``data/gcagents.db`` is never touched.
    """
    db_file = tmp_path / "test.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    test_engine = create_async_engine(db_url, echo=False)

    # Monkeypatch the module-level engine cache so every persistence function
    # uses our test engine instead of the production one.
    with patch("orchestrator.persistence._get_engine", return_value=test_engine):
        yield test_engine


@pytest.fixture(autouse=True)
def cleanup_db():
    """Reset the global engine cache before and after every test.

    Ensures no test accidentally reuses a stale engine from a sibling test.
    """
    import orchestrator.persistence as _persist

    original = _persist._engine_cache
    _persist._engine_cache = None
    yield
    _persist._engine_cache = original

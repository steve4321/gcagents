"""Tests for shared/memory.py — layered memory system."""

from __future__ import annotations

import pytest

from shared.memory import MemoryStore, get_memory_store


@pytest.fixture
def memory_store(tmp_path):
    db_path = tmp_path / "test_memory.db"
    return MemoryStore(db_path=db_path)


def test_memory_store_init(memory_store):
    assert memory_store is not None


@pytest.mark.asyncio
async def test_store_short_term(memory_store):
    await memory_store.store_short_term("test_event", "Test content", "proj-001")
    results = await memory_store.get_recent("proj-001")
    assert len(results) > 0


@pytest.mark.asyncio
async def test_store_short_term_with_metadata(memory_store):
    await memory_store.store_short_term("tick_result", "Phase: develop", "proj-001", tick_id="5", importance=0.8)
    results = await memory_store.get_recent("proj-001")
    assert len(results) > 0


@pytest.mark.asyncio
async def test_store_long_term(memory_store):
    await memory_store.store_long_term("lesson", "Always test code", summary="test lesson", importance=0.9)
    results = await memory_store.search_long_term("test")
    assert len(results) > 0


@pytest.mark.asyncio
async def test_search_long_term_empty(memory_store):
    results = await memory_store.search_long_term("nonexistent")
    assert results == []


@pytest.mark.asyncio
async def test_consolidate(memory_store):
    await memory_store.store_short_term("event1", "Content 1", "proj-001")
    await memory_store.store_short_term("event2", "Content 2", "proj-001")
    lessons = await memory_store.consolidate("proj-001")
    assert len(lessons) > 0
    assert any("event1" in lesson or "event2" in lesson for lesson in lessons)


@pytest.mark.asyncio
async def test_get_recent_empty(memory_store):
    results = await memory_store.get_recent("proj-empty")
    assert results == []


@pytest.mark.asyncio
async def test_search_by_project(memory_store):
    await memory_store.store_short_term("e1", "c1", "proj-A")
    await memory_store.store_short_term("e2", "c2", "proj-B")
    results = await memory_store.get_recent("proj-A")
    assert all(r["project_id"] == "proj-A" for r in results)


@pytest.mark.asyncio
async def test_search_long_term_by_category(memory_store):
    await memory_store.store_long_term("dev", "code stuff", summary="coding", importance=0.9)
    await memory_store.store_long_term("art", "visual stuff", summary="artwork", importance=0.8)
    results = await memory_store.search_long_term("stuff", category="dev")
    assert len(results) > 0
    assert all(r["category"] == "dev" for r in results)


def test_get_memory_store_singleton():
    store1 = get_memory_store()
    store2 = get_memory_store()
    assert store1 is store2


@pytest.mark.asyncio
async def test_get_all_lessons(memory_store):
    await memory_store.store_long_term("lesson", "lesson content", summary="summary", importance=0.9)
    lessons = await memory_store.get_all_lessons()
    assert len(lessons) > 0


@pytest.mark.asyncio
async def test_delete_project_memories(memory_store):
    await memory_store.store_short_term("e1", "c1", "proj-del")
    count = await memory_store.delete_project_memories("proj-del")
    assert count >= 1


@pytest.mark.asyncio
async def test_memory_store_persistence(tmp_path):
    db_path = tmp_path / "persist_test.db"
    store1 = MemoryStore(db_path=db_path)
    await store1.store_short_term("e1", "c1", "proj-001")

    store2 = MemoryStore(db_path=db_path)
    results = await store2.get_recent("proj-001")
    assert len(results) > 0


@pytest.mark.asyncio
async def test_consolidate_empty(memory_store):
    lessons = await memory_store.consolidate("proj-empty")
    assert lessons == []


@pytest.mark.asyncio
async def test_get_project_context(memory_store):
    await memory_store.store_short_term("e1", "developing puzzle game", "proj-001")
    context = await memory_store.get_project_context("proj-001", "puzzle")
    assert isinstance(context, str)


@pytest.mark.asyncio
async def test_get_recent_with_category(memory_store):
    await memory_store.store_short_term("development", "code done", "proj-001")
    await memory_store.store_short_term("art", "sprite done", "proj-001")
    results = await memory_store.get_recent("proj-001", category="development")
    assert all(r["category"] == "development" for r in results)

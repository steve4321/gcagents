from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


# ── Layered Memory API ────────────────────────────────────────────────────────


@router.get("/api/memory/{project_id}/recent")
async def get_recent_memories(project_id: str, category: str = "", limit: int = 20):
    from shared.memory import get_memory_store

    store = get_memory_store()
    return store.get_recent(project_id, category=category or None, limit=limit)


@router.get("/api/memory/search")
async def search_memories(q: str = "", category: str = "", limit: int = 10):
    if not q:
        raise HTTPException(400, "Query parameter 'q' is required")
    from shared.memory import get_memory_store

    store = get_memory_store()
    return store.search_long_term(q, category=category or None, limit=limit)


@router.get("/api/memory/lessons")
async def get_all_lessons():
    from shared.memory import get_memory_store

    store = get_memory_store()
    return store.get_all_lessons()

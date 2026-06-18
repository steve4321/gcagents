"""Company memory persistence (company_memory table)."""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.persistence.engine import _get_engine


async def save_user_genre_directive(genre: str, instruction: str, now: str) -> None:
    import json as _json

    engine = _get_engine()
    async with AsyncSession(engine) as db:
        await db.execute(
            text("""
                INSERT INTO company_memory (category, title, content, importance, created_at)
                VALUES ('directive', 'user_genre_directive', :content, 0.9, :now)
            """),
            {
                "content": _json.dumps(
                    {"genre": genre, "instruction": instruction, "source": "user_chat"}
                ),
                "now": now,
            },
        )
        await db.commit()


async def get_company_memory(limit: int = 50) -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = (
            await db.execute(
                text(
                    "SELECT id, category, title, content, importance, created_at FROM company_memory ORDER BY importance DESC, created_at DESC LIMIT :lim"
                ),
                {"lim": limit},
            )
        ).fetchall()
    memories = []
    for row in rows:
        d = dict(row._mapping)
        if isinstance(d.get("content"), str):
            try:
                d["content"] = json.loads(d["content"])
            except (json.JSONDecodeError, TypeError):
                pass
        memories.append(d)
    return memories

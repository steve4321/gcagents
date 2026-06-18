"""Chat messages persistence (chat_messages table)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.persistence.engine import _get_engine


async def save_chat_message(
    role: str,
    content: str,
    agent_name: str = "",
    metadata: dict = None,
) -> int:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        result = await db.execute(
            text("""
                INSERT INTO chat_messages (role, content, agent_name, metadata_json, created_at)
                VALUES (:role, :content, :agent_name, :metadata_json, :created_at)
            """),
            {
                "role": role,
                "content": content,
                "agent_name": agent_name,
                "metadata_json": json.dumps(metadata or {}),
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
        await db.commit()
        return result.lastrowid or 0


async def get_chat_history(limit: int = 100) -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = await db.execute(
            text("SELECT * FROM chat_messages ORDER BY created_at ASC LIMIT :lim"),
            {"lim": limit},
        )
        return [dict(r._mapping) for r in rows.fetchall()]


async def get_pending_instructions(agent_name: str) -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = await db.execute(
            text("SELECT * FROM chat_messages WHERE role = 'user' ORDER BY created_at ASC"),
        )
        results = []
        to_mark: list[tuple[str, str]] = []
        for r in rows.fetchall():
            d = dict(r._mapping)
            meta = json.loads(d.get("metadata_json", "{}"))
            if meta.get("target_agent") == agent_name and not meta.get("processed", False):
                results.append(d)
                meta["processed"] = True
                to_mark.append((json.dumps(meta), d["id"]))

        for meta_json, msg_id in to_mark:
            await db.execute(
                text("UPDATE chat_messages SET metadata_json=:meta WHERE id=:id"),
                {"meta": meta_json, "id": msg_id},
            )
        await db.commit()
        return results


async def mark_instruction_processed(instruction_id: str, metadata: dict) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        await db.execute(
            text("UPDATE chat_messages SET metadata_json = :meta WHERE id = :mid"),
            {"meta": json.dumps(metadata), "mid": instruction_id},
        )
        await db.commit()

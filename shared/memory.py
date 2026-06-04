"""Layered memory system for persistent learning across game projects."""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "gcagents.db"


class MemoryStore:
    """Two-layer memory: short-term (per-project events) and long-term (cross-project lessons)."""

    def __init__(self, db_path: str | Path = DB_PATH):
        self.db_path = str(db_path)
        self._init_tables()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_tables(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    summary TEXT,
                    embedding_hash TEXT,
                    project_id TEXT NOT NULL DEFAULT '',
                    tick_id TEXT DEFAULT '',
                    importance REAL DEFAULT 0.5,
                    created_at TEXT NOT NULL,
                    accessed_at TEXT NOT NULL,
                    access_count INTEGER DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project_id)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance)"
            )

    # ── Short-term memory ────────────────────────────────────────────────────

    def _store_short_term_sync(
        self,
        category: str,
        content: str,
        project_id: str,
        tick_id: str = "",
        importance: float = 0.5,
    ) -> str:
        mem_id = hashlib.md5(
            f"{category}:{content}:{datetime.now(UTC).isoformat()}".encode()
        ).hexdigest()[:12]
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO memories "
                "(id, category, content, project_id, "
                "tick_id, importance, created_at, accessed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (mem_id, category, content, project_id, tick_id, importance, now, now),
            )
        return mem_id

    async def store_short_term(
        self,
        category: str,
        content: str,
        project_id: str,
        tick_id: str = "",
        importance: float = 0.5,
    ) -> str:
        return await asyncio.to_thread(
            self._store_short_term_sync, category, content, project_id, tick_id, importance
        )

    def _get_recent_sync(
        self,
        project_id: str,
        category: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        with self._connect() as conn:
            if category:
                rows = conn.execute(
                    "SELECT * FROM memories WHERE project_id = ? AND category = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (project_id, category, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM memories WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
                    (project_id, limit),
                ).fetchall()
            return [dict(r) for r in rows]

    async def get_recent(
        self,
        project_id: str,
        category: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        return await asyncio.to_thread(self._get_recent_sync, project_id, category, limit)

    # ── Long-term memory ─────────────────────────────────────────────────────

    def _store_long_term_sync(
        self,
        category: str,
        content: str,
        summary: str,
        importance: float = 0.7,
    ) -> str:
        mem_id = hashlib.md5(f"lt:{category}:{summary}".encode()).hexdigest()[:12]
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO memories "
                "(id, category, content, summary, project_id, importance, created_at, accessed_at) "
                "VALUES (?, ?, ?, ?, '', ?, ?, ?)",
                (mem_id, category, content, summary, importance, now, now),
            )
        return mem_id

    async def store_long_term(
        self,
        category: str,
        content: str,
        summary: str,
        importance: float = 0.7,
    ) -> str:
        return await asyncio.to_thread(
            self._store_long_term_sync, category, content, summary, importance
        )

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [t for t in text.lower().split() if len(t) >= 2]

    def _build_match_sql(self, tokens: list[str], category: str | None) -> tuple[str, list]:
        conditions: list[str] = []
        params: list = []
        for tok in tokens:
            conditions.append("(LOWER(content) LIKE ? OR LOWER(summary) LIKE ?)")
            params.extend([f"%{tok}%", f"%{tok}%"])
        where = " AND ".join(conditions)
        if category:
            where = f"category = ? AND ({where})"
            params.insert(0, category)
        else:
            where = f"project_id = '' AND ({where})"
        return where, params

    def _score_result(self, row: dict, tokens: list[str]) -> float:
        score = float(row.get("importance", 0.5))
        text = (row.get("content", "") + " " + row.get("summary", "")).lower()
        for tok in tokens:
            count = text.count(tok)
            if count > 0:
                score += min(count * 0.1, 0.3)
        if row.get("access_count", 0) > 2:
            score += 0.1
        return score

    def _search_long_term_sync(
        self,
        query: str,
        category: str | None = None,
        limit: int = 5,
    ) -> list[dict]:
        tokens = self._tokenize(query)
        if not tokens:
            tokens = [query.lower()]
        where, params = self._build_match_sql(tokens, category)
        sql = (
            f"SELECT * FROM memories WHERE {where} "
            "ORDER BY importance DESC, created_at DESC LIMIT ?"
        )
        params.append(limit * 3)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            results = [dict(r) for r in rows]
        scored = [(r, self._score_result(r, tokens)) for r in results]
        scored.sort(key=lambda x: -x[1])
        results = [r for r, _ in scored[:limit]]
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            for r in results:
                conn.execute(
                    "UPDATE memories SET access_count = access_count + 1, accessed_at = ? WHERE id = ?",
                    (now, r["id"]),
                )
        return results

    async def search_long_term(
        self,
        query: str,
        category: str | None = None,
        limit: int = 5,
    ) -> list[dict]:
        return await asyncio.to_thread(self._search_long_term_sync, query, category, limit)

    # ── Consolidation ────────────────────────────────────────────────────────

    def _consolidate_sync(self, project_id: str) -> list[str]:
        """Consolidate short-term project memories into long-term lessons.

        Groups recent events by category, extracts agent-specific patterns
        (success/failure modes for programmer, designer, QA), and stores
        actionable lessons as long-term memories.
        """
        recent = self._get_recent_sync(project_id, limit=100)
        if not recent:
            return []

        by_category: dict[str, list[str]] = {}
        for m in recent:
            by_category.setdefault(m["category"], []).append(m["content"])

        lessons: list[str] = []

        agent_categories = {
            "tick_result": "agent_performance",
            "error": "failure_pattern",
            "success": "success_pattern",
        }

        agent_role_map = {
            "develop": "programmer",
            "develop_simple": "programmer",
            "code": "programmer",
            "build": "programmer",
            "design_game": "designer",
            "design": "designer",
            "qa": "qa",
            "test": "qa",
            "art_gen": "artist",
            "art": "artist",
            "generate_music": "music",
            "music": "music",
            "deploy": "deployer",
            "market_scan": "scanner",
            "scan": "scanner",
        }

        def _infer_agent_role(category: str, items: list[str]) -> str | None:
            """Infer agent role from event category and content for role-based lesson indexing."""
            if category in agent_role_map:
                return agent_role_map[category]
            for item in items[:5]:
                lower = item.lower()
                for key, role in agent_role_map.items():
                    if key in lower:
                        return role
            return None

        for cat, items in by_category.items():
            effective_cat = agent_categories.get(cat, cat)
            content_text = "\n".join(items[:10])

            agent_role = _infer_agent_role(cat, items)

            if len(items) <= 2:
                summary = f"[{effective_cat}] From {len(items)} events: " + "; ".join(items[:2])
            else:
                patterns: dict[str, int] = {}
                for item in items:
                    key = item[:80]
                    patterns[key] = patterns.get(key, 0) + 1
                frequent = [k for k, v in sorted(patterns.items(), key=lambda x: -x[1]) if v > 1]
                if frequent:
                    summary = (
                        f"[{effective_cat}] {len(items)} events, {len(frequent)} recurring: "
                        + "; ".join(frequent[:3])
                    )
                else:
                    summary = (
                        f"[{effective_cat}] {len(items)} events: " + "; ".join(items[:3])
                    )

            importance = 0.7 if "fail" in effective_cat else 0.6

            self._store_long_term_sync(
                category=f"lesson:{effective_cat}",
                content=content_text,
                summary=summary,
                importance=importance,
            )

            if agent_role:
                self._store_long_term_sync(
                    category=f"lesson:{agent_role}",
                    content=content_text,
                    summary=summary,
                    importance=importance,
                )

            lessons.append(summary)

        logger.info(
            f"Consolidated {len(recent)} memories into {len(lessons)} lessons for project {project_id}"
        )
        return lessons

    async def consolidate(self, project_id: str) -> list[str]:
        return await asyncio.to_thread(self._consolidate_sync, project_id)

    # ── Context builder ──────────────────────────────────────────────────────

    def _get_project_context_sync(self, project_id: str, query: str = "") -> str:
        parts: list[str] = []

        recent = self._get_recent_sync(project_id, limit=5)
        if recent:
            parts.append("## Recent Project Events")
            for m in recent:
                parts.append(f"- [{m['category']}] {m['content']}")

        if query:
            lessons = self._search_long_term_sync(query, limit=3)
            if lessons:
                parts.append("\n## Relevant Past Lessons")
            for lesson in lessons:
                parts.append(f"- {lesson.get('summary', lesson.get('content', ''))}")

        return "\n".join(parts) if parts else ""

    async def get_project_context(self, project_id: str, query: str = "") -> str:
        return await asyncio.to_thread(self._get_project_context_sync, project_id, query)

    # ── Utilities ────────────────────────────────────────────────────────────

    def _get_all_lessons_sync(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE project_id = '' ORDER BY importance DESC, created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    async def get_all_lessons(self) -> list[dict]:
        return await asyncio.to_thread(self._get_all_lessons_sync)

    def _delete_project_memories_sync(self, project_id: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM memories WHERE project_id = ?", (project_id,))
            return cursor.rowcount

    async def delete_project_memories(self, project_id: str) -> int:
        return await asyncio.to_thread(self._delete_project_memories_sync, project_id)


_memory_store: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    global _memory_store
    if _memory_store is None:
        _memory_store = MemoryStore()
    return _memory_store

"""SQLite-backed event store for GCAgents event sourcing."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

from shared.events import ActionType, Event

DB_PATH = Path("data/gcagents.db")


class SqliteEventStore:
    """SQLite-backed append-only event store."""

    def __init__(self, db_path: str | Path = DB_PATH) -> None:
        self.db_path = str(db_path)
        self._init_table()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_table(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS domain_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    tick_id INTEGER DEFAULT 0,
                    project_id TEXT,
                    agent_name TEXT,
                    payload TEXT NOT NULL DEFAULT '{}',
                    parent_event_id TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}'
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_project ON domain_events(project_id)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON domain_events(event_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_tick ON domain_events(tick_id)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON domain_events(timestamp)"
            )

    async def append(self, event: Event) -> None:
        await asyncio.to_thread(self._append_sync, event)

    def _append_sync(self, event: Event) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO domain_events "
                "(event_id, event_type, timestamp, tick_id, project_id, agent_name, "
                "payload, parent_event_id, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.event_id,
                    event.event_type.value,
                    event.timestamp,
                    event.tick_id,
                    event.project_id,
                    event.agent_name,
                    json.dumps(event.payload),
                    event.parent_event_id,
                    json.dumps(event.metadata),
                ),
            )
            self._mirror_to_event_logs(conn, event)

    def _mirror_to_event_logs(self, conn, event: "Event") -> None:
        """Mirror a domain event into the event_logs table for dashboard reads.

        event_logs has fewer columns than domain_events; we map a summary.
        Schema:
          event_logs(id, event_type, severity, title, detail, source_agent,
                     project_name, metadata_json, created_at)
        """
        payload = event.payload or {}
        title = (
            payload.get("title")
            or f"{event.event_type.value} by {event.agent_name or 'system'}"
        )
        try:
            conn.execute(
                "INSERT INTO event_logs "
                "(event_type, severity, title, detail, source_agent, "
                " project_name, metadata_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.event_type.value,
                    payload.get("severity", "info"),
                    title[:200],
                    json.dumps(payload, ensure_ascii=False)[:2000],
                    event.agent_name or "",
                    payload.get("project_name", "") or event.project_id or "",
                    json.dumps(event.metadata, ensure_ascii=False)[:2000],
                    event.timestamp,
                ),
            )
        except Exception as e:
            logger.debug(f"domain_events append failed: {e}")

    async def append_batch(self, events: list[Event]) -> None:
        await asyncio.to_thread(self._append_batch_sync, events)

    def _append_batch_sync(self, events: list[Event]) -> None:
        with self._connect() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO domain_events "
                "(event_id, event_type, timestamp, tick_id, project_id, agent_name, "
                "payload, parent_event_id, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        e.event_id,
                        e.event_type.value,
                        e.timestamp,
                        e.tick_id,
                        e.project_id,
                        e.agent_name,
                        json.dumps(e.payload),
                        e.parent_event_id,
                        json.dumps(e.metadata),
                    )
                    for e in events
                ],
            )

    async def get_events(
        self,
        project_id: str | None = None,
        event_type: ActionType | None = None,
        from_tick: int | None = None,
        to_tick: int | None = None,
        limit: int = 100,
    ) -> list[Event]:
        return await asyncio.to_thread(
            self._get_events_sync, project_id, event_type, from_tick, to_tick, limit
        )

    def _get_events_sync(
        self,
        project_id: str | None,
        event_type: ActionType | None,
        from_tick: int | None,
        to_tick: int | None,
        limit: int,
    ) -> list[Event]:
        conditions: list[str] = []
        params: list[Any] = []
        if project_id is not None:
            conditions.append("project_id = ?")
            params.append(project_id)
        if event_type is not None:
            conditions.append("event_type = ?")
            params.append(event_type.value)
        if from_tick is not None:
            conditions.append("tick_id >= ?")
            params.append(from_tick)
        if to_tick is not None:
            conditions.append("tick_id <= ?")
            params.append(to_tick)

        where = " AND ".join(conditions) if conditions else "1=1"
        query = f"SELECT * FROM domain_events WHERE {where} ORDER BY timestamp ASC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_event(row) for row in rows]

    async def get_event(self, event_id: str) -> Event | None:
        return await asyncio.to_thread(self._get_event_sync, event_id)

    def _get_event_sync(self, event_id: str) -> Event | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM domain_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            return self._row_to_event(row) if row else None

    async def get_project_timeline(self, project_id: str, from_tick: int = 0) -> list[Event]:
        return await self.get_events(project_id=project_id, from_tick=from_tick, limit=1000)

    async def replay(self, project_id: str, from_tick: int = 0) -> list[Event]:
        return await self.get_events(project_id=project_id, from_tick=from_tick, limit=10000)

    async def count_events(
        self,
        project_id: str | None = None,
        event_type: ActionType | None = None,
    ) -> int:
        return await asyncio.to_thread(self._count_events_sync, project_id, event_type)

    def _count_events_sync(
        self,
        project_id: str | None,
        event_type: ActionType | None,
    ) -> int:
        conditions: list[str] = []
        params: list[str] = []
        if project_id is not None:
            conditions.append("project_id = ?")
            params.append(project_id)
        if event_type is not None:
            conditions.append("event_type = ?")
            params.append(event_type.value)
        where = " AND ".join(conditions) if conditions else "1=1"
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) as cnt FROM domain_events WHERE {where}", params
            ).fetchone()
            return row["cnt"]

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> Event:
        return Event(
            event_id=row["event_id"],
            event_type=ActionType(row["event_type"]),
            timestamp=row["timestamp"],
            tick_id=row["tick_id"],
            project_id=row["project_id"],
            agent_name=row["agent_name"],
            payload=json.loads(row["payload"]),
            parent_event_id=row["parent_event_id"],
            metadata=json.loads(row["metadata"]),
        )


_event_store: SqliteEventStore | None = None


def get_event_store() -> SqliteEventStore:
    global _event_store
    if _event_store is None:
        _event_store = SqliteEventStore()
    return _event_store

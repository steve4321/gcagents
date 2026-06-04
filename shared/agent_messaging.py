"""SQLite-backed inter-agent mailbox for direct message passing."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from loguru import logger

DB_PATH = Path("data/gcagents.db")

MessagePriority = Literal["low", "normal", "high", "critical"]
MessageType = Literal[
    "gdd_update",
    "bug_report",
    "feedback_insight",
    "task_request",
    "task_complete",
    "status_update",
    "question",
    "directive",
]


@dataclass
class Message:
    """A single inter-agent message."""

    id: str = ""
    from_agent: str = ""
    to_agent: str = ""
    message_type: str = ""
    payload: dict | str = field(default_factory=dict)
    priority: MessagePriority = "normal"
    read: bool = False
    timestamp: str = ""

    def __post_init__(self) -> None:
        now_iso = datetime.now(UTC).isoformat()
        if not self.id:
            raw = f"{self.from_agent}:{self.to_agent}:{self.message_type}:{now_iso}"
            self.id = hashlib.md5(raw.encode()).hexdigest()[:12]
        if not self.timestamp:
            self.timestamp = now_iso


class AgentMailbox:
    """SQLite-backed mailbox for inter-agent communication."""

    def __init__(self, db_path: str | Path = DB_PATH) -> None:
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
                CREATE TABLE IF NOT EXISTS agent_mailbox (
                    id TEXT PRIMARY KEY,
                    from_agent TEXT NOT NULL,
                    to_agent TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}',
                    priority TEXT NOT NULL DEFAULT 'normal',
                    read INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_mailbox_to_agent ON agent_mailbox(to_agent)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_mailbox_msg_type ON agent_mailbox(message_type)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_mailbox_to_read ON agent_mailbox(to_agent, read)"
            )

    # ── Send ──────────────────────────────────────────────────────────────────
    def _send_sync(
        self,
        from_agent: str,
        to_agent: str,
        msg_type: str,
        payload: str = "{}",
        priority: MessagePriority = "normal",
    ) -> str:
        msg = Message(
            from_agent=from_agent,
            to_agent=to_agent,
            message_type=msg_type,
            payload=payload,
            priority=priority,
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO agent_mailbox "
                "(id, from_agent, to_agent, message_type, payload, priority, read, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
                (
                    msg.id,
                    msg.from_agent,
                    msg.to_agent,
                    msg.message_type,
                    msg.payload,
                    msg.priority,
                    msg.timestamp,
                ),
            )
        logger.debug(f"Mailbox: {from_agent} → {to_agent} [{msg_type}] ({msg.id})")
        return msg.id

    async def send(
        self,
        from_agent: str,
        to_agent: str,
        msg_type: str,
        payload: dict | str | None = None,
        priority: MessagePriority = "normal",
    ) -> str:
        """Send a message from one agent to another."""
        payload_str = json.dumps(payload) if isinstance(payload, dict) else (payload or "{}")
        return await asyncio.to_thread(
            self._send_sync, from_agent, to_agent, msg_type, payload_str, priority
        )

    # ── Receive ───────────────────────────────────────────────────────────────
    def _receive_sync(
        self,
        agent_name: str,
        msg_type: str | None = None,
        timeout: float = 0,
    ) -> Message | None:
        import time

        deadline = time.monotonic() + timeout
        while True:
            with self._connect() as conn:
                if msg_type:
                    row = conn.execute(
                        "SELECT * FROM agent_mailbox "
                        "WHERE to_agent = ? AND message_type = ? AND read = 0 "
                        "ORDER BY CASE priority "
                        "  WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
                        "  WHEN 'normal' THEN 2 ELSE 3 END, created_at ASC LIMIT 1",
                        (agent_name, msg_type),
                    ).fetchone()
                else:
                    row = conn.execute(
                        "SELECT * FROM agent_mailbox "
                        "WHERE to_agent = ? AND read = 0 "
                        "ORDER BY CASE priority "
                        "  WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
                        "  WHEN 'normal' THEN 2 ELSE 3 END, created_at ASC LIMIT 1",
                        (agent_name,),
                    ).fetchone()
                if row:
                    conn.execute("UPDATE agent_mailbox SET read = 1 WHERE id = ?", (row["id"],))
                    raw_payload = row["payload"]
                    payload_data = (
                        json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
                    )
                    return Message(
                        id=row["id"],
                        from_agent=row["from_agent"],
                        to_agent=row["to_agent"],
                        message_type=row["message_type"],
                        payload=payload_data,
                        priority=row["priority"],
                        read=True,
                        timestamp=row["created_at"],
                    )
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.05)

    async def receive(
        self,
        agent_name: str,
        msg_type: str | None = None,
        timeout: float = 0,
    ) -> Message | None:
        """Receive the next unread message for an agent. Non-blocking by default."""
        return await asyncio.to_thread(self._receive_sync, agent_name, msg_type, timeout)

    # ── Broadcast ─────────────────────────────────────────────────────────────
    def _get_all_agents_sync(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT to_agent FROM agent_mailbox "
                "UNION SELECT DISTINCT from_agent FROM agent_mailbox"
            ).fetchall()
        return [r[0] for r in rows]

    async def broadcast(
        self,
        from_agent: str,
        msg_type: str,
        payload: str = "{}",
        agents: list[str] | None = None,
    ) -> list[str]:
        """Send a message to all known agents, or a specific list."""
        targets = agents or await asyncio.to_thread(self._get_all_agents_sync)
        if not targets:
            logger.warning(f"Broadcast from {from_agent} has no targets")
            return []
        msg_ids: list[str] = []
        for target in targets:
            if target == from_agent:
                continue
            mid = await self.send(from_agent, target, msg_type, payload)
            msg_ids.append(mid)
        logger.debug(f"Broadcast: {from_agent} → {len(msg_ids)} agents [{msg_type}]")
        return msg_ids

    # ── Queries ───────────────────────────────────────────────────────────────
    def _get_pending_count_sync(self, agent_name: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM agent_mailbox WHERE to_agent = ? AND read = 0",
                (agent_name,),
            ).fetchone()
        return row[0]

    async def get_pending_count(self, agent_name: str) -> int:
        """Count unread messages for an agent."""
        return await asyncio.to_thread(self._get_pending_count_sync, agent_name)

    def _get_all_messages_sync(self, agent_name: str, limit: int = 50) -> list[Message]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_mailbox WHERE to_agent = ? ORDER BY created_at DESC LIMIT ?",
                (agent_name, limit),
            ).fetchall()
        return [
            Message(
                id=r["id"],
                from_agent=r["from_agent"],
                to_agent=r["to_agent"],
                message_type=r["message_type"],
                payload=json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"],
                priority=r["priority"],
                read=bool(r["read"]),
                timestamp=r["created_at"],
            )
            for r in rows
        ]

    async def get_all_messages(self, agent_name: str, limit: int = 50) -> list[Message]:
        """Get all messages for an agent (newest first)."""
        return await asyncio.to_thread(self._get_all_messages_sync, agent_name, limit)


_mailbox: AgentMailbox | None = None


def get_mailbox() -> AgentMailbox:
    """Return the singleton AgentMailbox instance."""
    global _mailbox
    if _mailbox is None:
        _mailbox = AgentMailbox()
    return _mailbox

"""Market reports and market signals persistence."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.persistence.engine import _get_engine
from shared.constants import MAX_SIGNALS_PER_BATCH, TRUNC_RAW_ANALYSIS


async def save_market_report(
    signals_count: int,
    opportunities: list[dict],
    raw_analysis: str | None = None,
) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        await db.execute(
            text("""
                INSERT INTO market_reports (signals_count, opportunities_json, raw_analysis, created_at)
                VALUES (:signals_count, :opportunities_json, :raw_analysis, :created_at)
            """),
            {
                "signals_count": signals_count,
                "opportunities_json": json.dumps(opportunities, ensure_ascii=False),
                "raw_analysis": (raw_analysis or "")[:TRUNC_RAW_ANALYSIS],
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
        await db.commit()


async def save_market_signals(signals: list[dict]) -> None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        for sig in signals[:MAX_SIGNALS_PER_BATCH]:
            try:
                await db.execute(
                    text("""
                        INSERT INTO market_signals (source, signal_type, genre, title, data, score, captured_at)
                        VALUES (:source, :signal_type, :genre, :title, :data, :score, :captured_at)
                    """),
                    {
                        "source": sig.get("source", "unknown"),
                        "signal_type": "market",
                        "genre": sig.get("genre", "unknown"),
                        "title": sig.get("title", "")[:200],
                        "data": json.dumps(sig.get("data", {})),
                        "score": float(sig.get("score", 0)),
                        "captured_at": sig.get("captured_at", datetime.now(UTC).isoformat()),
                    },
                )
            except Exception as e:
                logging.getLogger(__name__).warning(f"Failed to insert market signal: {e}")
        await db.commit()


async def get_latest_market_report() -> dict | None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = await db.execute(
            text("SELECT id, opportunities_json FROM market_reports ORDER BY id DESC LIMIT 1")
        )
        row = rows.fetchone()
    if row:
        return {"id": row.id, "opportunities_json": row.opportunities_json}
    return None


async def get_market_report_detail() -> dict | None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        row = (
            await db.execute(text("SELECT * FROM market_reports ORDER BY id DESC LIMIT 1"))
        ).fetchone()
    if row:
        return dict(row._mapping)
    return None


async def get_latest_market_signals(limit: int = 50) -> list[dict]:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        rows = (
            await db.execute(
                text(
                    "SELECT id, source, signal_type, genre, title, data, score, captured_at FROM market_signals ORDER BY captured_at DESC LIMIT :lim"
                ),
                {"lim": limit},
            )
        ).fetchall()
    signals = []
    for row in rows:
        d = dict(row._mapping)
        if isinstance(d.get("data"), str):
            d["data"] = json.loads(d["data"])
        signals.append(d)
    return signals


async def get_last_scan_time() -> str | None:
    engine = _get_engine()
    async with AsyncSession(engine) as db:
        row = (
            await db.execute(text("SELECT MAX(captured_at) as last_scan FROM market_signals"))
        ).fetchone()
    return row.last_scan if row and row.last_scan else None

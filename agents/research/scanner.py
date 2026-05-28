from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger

from orchestrator.state import CompanyState, PipelinePhase
from shared.config import load_config, load_sources

from .sources import scan_all_sources
from .analyzer import analyze_signals
from orchestrator.persistence import save_agent_log, save_market_report


async def scan_market(state: CompanyState) -> dict:
    """Scan all configured market data sources and analyze trends."""
    logger.info("Market scan starting...")
    config = load_config()
    sources = load_sources()

    started_at = datetime.now(timezone.utc).isoformat()

    signals = await scan_all_sources(sources.sources)
    logger.info(f"Collected {len(signals)} market signals")

    if not signals:
        logger.warning("No market signals collected")
        await save_agent_log("scan", "failed", phase="scanning", error="No signals collected", started_at=started_at)
        return {"phase": PipelinePhase.IDLE, "market_insights": []}

    opportunities, raw_analysis = await analyze_signals(signals, config)

    duration_ms = int((datetime.now(timezone.utc) - datetime.fromisoformat(started_at)).total_seconds() * 1000)
    await save_agent_log("scan", "completed", phase="scanning", duration_ms=duration_ms, started_at=started_at)
    await save_market_report(len(signals), opportunities, raw_analysis)

    return {"phase": PipelinePhase.EVALUATING, "market_insights": opportunities}

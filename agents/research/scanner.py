from __future__ import annotations

from loguru import logger

from orchestrator.state import CompanyState, PipelinePhase
from shared.config import load_config, load_sources

from .sources import scan_all_sources
from .analyzer import analyze_signals


async def scan_market(state: CompanyState) -> dict:
    """Scan all configured market data sources and analyze trends."""
    logger.info("Market scan starting...")
    config = load_config()
    sources = load_sources()

    signals = await scan_all_sources(sources.sources)
    logger.info(f"Collected {len(signals)} market signals")

    if not signals:
        logger.warning("No market signals collected")
        return {"phase": PipelinePhase.IDLE, "market_insights": []}

    opportunities = await analyze_signals(signals, config)

    return {"phase": PipelinePhase.EVALUATING, "market_insights": opportunities}

"""Market signal analyzer — cross-source correlation and opportunity scoring.

Collects market signals, builds an analysis prompt with genre counts,
cross-source agreement, and competition density, then calls LLM to
identify the top 3 game opportunities.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from loguru import logger

from shared.config import AppConfig
from shared.constants import DEFAULT_ANALYSIS_MODEL
from shared.llm_client import llm
from shared.models import MarketSignal


async def analyze_signals(
    signals: list[MarketSignal],
    config: AppConfig,
) -> tuple[list[dict], str]:
    """Returns (opportunities, raw_analysis_text)."""
    genre_counts = Counter(s.genre for s in signals if s.genre)
    logger.info(f"Analyzing {len(signals)} signals: genres={dict(genre_counts.most_common(10))}")

    prompt = _build_analysis_prompt(signals, genre_counts)

    model = DEFAULT_ANALYSIS_MODEL
    if not config.minimax_api_key:
        logger.error("No AI API key configured (need MINIMAX_API_KEY)")
        return [], ""

    analysis_text, usage = await llm.chat_completion(
        model=model,
        messages=[
            {"role": "system", "content": ANALYST_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
        max_tokens=2000,
        agent_name="analyzer",
        project_name="",
    )

    opportunities = _parse_opportunities(analysis_text)
    logger.info(f"Identified {len(opportunities)} market opportunities")

    return opportunities, analysis_text


ANALYST_SYSTEM_PROMPT = """You are a market analyst for a web mini-game company. 
Analyze the provided market data and identify the TOP 3 game opportunities.

For each opportunity, provide a JSON object with these exact fields:
- name: A catchy game name (2-4 words)
- genre: The game genre (e.g., "idle-clicker", "puzzle-match", "tower-defense", "platformer")
- description: Brief game concept (2-3 sentences)
- estimated_dev_hours: Number, 8-40 range
- market_opportunity_score: Float 0.0-1.0
- target_platforms: ["itch.io", "web"]
- differentiation: What makes this different from existing games
- reference_games: List of 2-3 similar successful games
- competition_analysis: Brief assessment of competition density for this genre (low/medium/high)
- source_agreement_score: Float 0.0-1.0 indicating how many independent sources agree on this trend
- trend_direction: One of "rising", "stable", or "declining"

Return ONLY a JSON array of 3 objects, no other text."""


def _build_analysis_prompt(signals: list[MarketSignal], genre_counts: Counter) -> str:
    """Build the LLM analysis prompt from collected signals."""
    top_genres = genre_counts.most_common(10)
    top_titles = sorted(signals, key=lambda s: s.score, reverse=True)[:15]

    genre_sources: dict[str, set[str]] = {}
    for s in signals:
        if s.genre:
            genre_sources.setdefault(s.genre, set()).add(s.source)

    title_counts: Counter = Counter(s.title for s in signals)
    title_overlap = [(t, c) for t, c in title_counts.most_common(10) if c > 1]

    lines = [
        f"Market data collected at {datetime.now().isoformat()}",
        f"Total signals: {len(signals)}",
        "",
        "## Top Genres",
    ]
    for genre, count in top_genres:
        sources_list = genre_sources.get(genre, set())
        source_agreement = len(sources_list) / max(len(set(s.source for s in signals)), 1)
        lines.append(
            f"- {genre}: {count} mentions (sources: {', '.join(sorted(sources_list))}, agreement: {source_agreement:.0%})"
        )

    lines.append("")
    lines.append("## Cross-Source Genre Correlation")
    for genre, sources in sorted(genre_sources.items(), key=lambda x: -len(x[1]))[:8]:
        if len(sources) >= 2:
            lines.append(
                f"- {genre}: confirmed by {len(sources)} sources ({', '.join(sorted(sources))})"
            )

    lines.append("")
    lines.append("## Competition Density")
    for genre, count in top_genres[:5]:
        lines.append(f"- {genre}: {count} competing titles detected")

    lines.append("")
    lines.append("## Top Trending Games")
    for s in top_titles:
        lines.append(f"- [{s.source}] {s.title} (score: {s.score:.2f}, genre: {s.genre})")
        if s.data.get("tags"):
            lines.append(f"  tags: {', '.join(s.data['tags'][:5])}")

    if title_overlap:
        lines.append("")
        lines.append("## Multi-Source Title Mentions")
        for title, count in title_overlap:
            lines.append(f'- "{title}" found in {count} sources')

    lines.append("")
    lines.append(
        "Identify the best 3 game opportunities based on this data. "
        "Consider cross-source agreement, competition density, and trend direction."
    )

    return "\n".join(lines)


def _parse_opportunities(text: str) -> list[dict]:
    """Parse LLM response into structured opportunity dicts."""
    import json

    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]

    try:
        result = json.loads(text)
        if isinstance(result, list):
            return _normalize_opportunities(result)
    except json.JSONDecodeError:
        logger.warning("Failed to parse AI analysis as JSON, attempting extraction")
        try:
            start = text.index("[")
            end = text.rindex("]") + 1
            result = json.loads(text[start:end])
            return _normalize_opportunities(result)
        except (ValueError, json.JSONDecodeError):
            logger.error("Could not extract opportunities from analysis")
            return []

    return []


_FIELD_MAP = {
    "estimated_hours": "estimated_dev_hours",
    "score": "market_opportunity_score",
    "target_platform": "target_platforms",
    "platforms": "target_platforms",
    "platform": "target_platforms",
    "reference_games_list": "reference_games",
    "game_name": "name",
    "competition": "competition_analysis",
    "agreement_score": "source_agreement_score",
    "trend": "trend_direction",
}


def _normalize_opportunities(opportunities: list[dict]) -> list[dict]:
    """Normalize field names in opportunity dicts using _FIELD_MAP."""
    for opp in opportunities:
        for old_key, new_key in _FIELD_MAP.items():
            if old_key in opp and new_key not in opp:
                opp[new_key] = opp.pop(old_key)
        if "target_platforms" not in opp:
            opp["target_platforms"] = ["itch.io", "crazygames", "poki"]
        if "competition_analysis" not in opp:
            opp["competition_analysis"] = "medium"
        if "source_agreement_score" not in opp:
            opp["source_agreement_score"] = 0.5
        if "trend_direction" not in opp:
            opp["trend_direction"] = "stable"
    return opportunities

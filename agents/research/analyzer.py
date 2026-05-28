from __future__ import annotations

from collections import Counter
from datetime import datetime

from loguru import logger

from shared.config import AppConfig
from shared.llm_client import llm
from shared.models import MarketSignal


async def analyze_signals(
    signals: list[MarketSignal],
    config: AppConfig,
) -> tuple[list[dict], str]:
    """Returns (opportunities, raw_analysis_text)."""
    genre_counts = Counter(s.genre for s in signals if s.genre)
    source_counts = Counter(s.source for s in signals)
    logger.info(f"Analyzing {len(signals)} signals: genres={dict(genre_counts.most_common(10))}")

    prompt = _build_analysis_prompt(signals, genre_counts)

    if config.zhipu_api_key:
        model = "glm-4-flash"
    elif config.deepseek_api_key:
        model = "deepseek-chat"
    else:
        logger.error("No AI API key configured (need ZHIPU_API_KEY or DEEPSEEK_API_KEY)")
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

Return ONLY a JSON array of 3 objects, no other text."""


def _build_analysis_prompt(signals: list[MarketSignal], genre_counts: Counter) -> str:
    top_genres = genre_counts.most_common(10)
    top_titles = sorted(signals, key=lambda s: s.score, reverse=True)[:15]

    lines = [
        f"Market data collected at {datetime.now().isoformat()}",
        f"Total signals: {len(signals)}",
        "",
        "## Top Genres",
    ]
    for genre, count in top_genres:
        lines.append(f"- {genre}: {count} mentions")

    lines.append("")
    lines.append("## Top Trending Games")
    for s in top_titles:
        lines.append(f"- [{s.source}] {s.title} (score: {s.score:.2f}, genre: {s.genre})")
        if s.data.get("tags"):
            lines.append(f"  tags: {', '.join(s.data['tags'][:5])}")

    lines.append("")
    lines.append("Identify the best 3 game opportunities based on this data.")

    return "\n".join(lines)


def _parse_opportunities(text: str) -> list[dict]:
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
}


def _normalize_opportunities(opportunities: list[dict]) -> list[dict]:
    for opp in opportunities:
        for old_key, new_key in _FIELD_MAP.items():
            if old_key in opp and new_key not in opp:
                opp[new_key] = opp.pop(old_key)
        if "target_platforms" not in opp:
            opp["target_platforms"] = ["itch.io", "web"]
    return opportunities

from __future__ import annotations

from collections import Counter
from datetime import datetime

from loguru import logger
from openai import AsyncOpenAI

from shared.config import AppConfig
from shared.models import MarketSignal


async def analyze_signals(
    signals: list[MarketSignal],
    config: AppConfig,
) -> list[dict]:
    genre_counts = Counter(s.genre for s in signals if s.genre)
    source_counts = Counter(s.source for s in signals)

    logger.info(f"Analyzing {len(signals)} signals: genres={dict(genre_counts.most_common(10))}")

    prompt = _build_analysis_prompt(signals, genre_counts)

    client = AsyncOpenAI(api_key=config.deepseek_api_key, base_url="https://api.deepseek.com")
    response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": ANALYST_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
        max_tokens=2000,
    )

    analysis_text = response.choices[0].message.content or ""

    opportunities = _parse_opportunities(analysis_text)
    logger.info(f"Identified {len(opportunities)} market opportunities")

    return opportunities


ANALYST_SYSTEM_PROMPT = """You are a market analyst for a web mini-game company. 
Analyze the provided market data and identify the TOP 3 game opportunities.

For each opportunity, provide a JSON object with these fields:
- name: A catchy game name (2-4 words)
- genre: The game genre (e.g., "idle-clicker", "puzzle-match", "tower-defense")
- description: Brief game concept (2-3 sentences)
- estimated_hours: Estimated dev hours (number, 8-40 range)
- score: Market opportunity score 0.0-1.0
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
            return result
    except json.JSONDecodeError:
        logger.warning("Failed to parse AI analysis as JSON, attempting extraction")
        try:
            start = text.index("[")
            end = text.rindex("]") + 1
            return json.loads(text[start:end])
        except (ValueError, json.JSONDecodeError):
            logger.error("Could not extract opportunities from analysis")
            return []

    return []

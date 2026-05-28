from __future__ import annotations

import json

from loguru import logger

from shared.config import AppConfig
from shared.llm_client import llm
from shared.models import GameProposal


DESIGNER_SYSTEM_PROMPT = """You are an expert game designer specializing in web mini-games.
Given a game proposal, create a detailed Game Design Document (GDD).

The GDD must be a JSON object with these sections:
{
  "title": "Game Title",
  "genre": "genre-name",
  "summary": "One paragraph game concept",
  "core_loop": ["step1", "step2", "step3"],
  "mechanics": {
    "mechanic_name": "description of how it works"
  },
  "progression": "How the player progresses",
  "win_condition": "What constitutes winning or completion",
  "monetization": "How the game could monetize (ads, iap, etc)",
  "art_style": {
    "theme": "e.g., pixel-art, cartoon, minimalist",
    "color_palette": ["#hex1", "#hex2", "#hex3", "#hex4"],
    "reference": "visual reference description"
  },
  "audio": {
    "bgm_mood": "e.g., upbeat, chill, intense",
    "sfx_list": ["jump", "collect", "game_over", "level_up"]
  },
  "scenes": [
    {"name": "Boot", "description": "Loading assets"},
    {"name": "Menu", "description": "Main menu"},
    {"name": "Game", "description": "Main gameplay"},
    {"name": "GameOver", "description": "Score display and restart"}
  ],
  "entities": [
    {"name": "Player", "type": "sprite", "behaviors": ["move", "jump"]},
    {"name": "Enemy", "type": "sprite", "behaviors": ["patrol", "chase"]}
  ],
  "ui_layout": {
    "hud": ["score", "lives", "level"],
    "menus": ["pause", "settings", "game_over"]
  },
  "balance": {
    "starting_lives": 3,
    "difficulty_curve": "gradual increase over 10 levels"
  },
  "estimated_play_session_minutes": 5
}

Return ONLY the JSON object, no other text."""


async def generate_gdd(proposal: GameProposal, config: AppConfig) -> dict:
    logger.info(f"Generating GDD for: {proposal.name} ({proposal.genre})")

    if config.zhipu_api_key:
        model = "glm-4-flash"
    elif config.deepseek_api_key:
        model = "deepseek-chat"
    else:
        logger.error("No AI API key configured")
        return {"title": proposal.name, "genre": proposal.genre, "scenes": []}

    user_prompt = f"""Create a GDD for this game proposal:

Name: {proposal.name}
Genre: {proposal.genre}
Description: {proposal.description}
Target Platforms: {', '.join(proposal.target_platforms)}
Differentiation: {proposal.differentiation}
Reference Games: {', '.join(proposal.reference_games)}
Market Score: {proposal.market_opportunity_score}

Generate a complete, detailed GDD. Make the game fun and engaging for web play."""

    text, usage = await llm.chat_completion(
        model=model,
        messages=[
            {"role": "system", "content": DESIGNER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.8,
        max_tokens=3000,
        agent_name="designer",
        project_name=proposal.name,
    )
    gdd = _parse_gdd(text)
    logger.info(f"GDD generated: {gdd.get('title', 'untitled')} with {len(gdd.get('scenes', []))} scenes")

    return gdd


def _parse_gdd(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        logger.error("Failed to parse GDD JSON")
        return {"title": "Unknown", "genre": "unknown", "scenes": []}

from __future__ import annotations

import json

from loguru import logger

from shared.config import AppConfig
from shared.constants import DEFAULT_ANALYSIS_MODEL
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
  "mechanics": [
    {
      "name": "mechanic_name",
      "description": "what this mechanic does in 1-2 sentences",
      "inputs": ["keyboard_input", "game_loop"],
      "outputs": ["updated_position", "animation_frame"],
      "constraints": ["speed_cap_200px_s", "no_wall_clipping"],
      "dependencies": ["other_mechanic_name"],
      "implementation_order": 0,
      "complexity": "low" | "medium" | "high"
    }
  ],
  "progression": "How the player progresses",
  "win_condition": "What constitutes winning or completion",
  "monetization": {
    "model": "free_to_play" | "ad_supported" | "premium",
    "ad_placement": [
      "interstitial_between_levels",
      "rewarded_video_for_powerup",
      "banner_game_over"
    ],
    "iap_tiers": [
      {"name": "starter_pack", "price_usd": 0.99, "contents": "description"},
      {"name": "premium_pack", "price_usd": 2.99, "contents": "description"}
    ],
    "retention_hooks": [
      "daily_challenge", "achievement_system",
      "leaderboard", "streak_bonus"
    ],
    "engagement_mechanics": [
      "power_up_system", "unlock_system", "social_sharing"
    ]
  },
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

COMPLEXITY REQUIREMENTS (MANDATORY — games that are too simple will be rejected by QA):
- Minimum 5 mechanics in the "mechanics" list (not just movement + score; include at least 2 unique gameplay mechanics)
- Each mechanic MUST have: name, description, inputs (2+), outputs (2+), constraints (1+), implementation_order, complexity
- Each mechanic's complexity should be "medium" or higher for at least 3 mechanics
- Minimum 4 scenes (Boot, Menu, Game, GameOver — prefer 5-6 with Tutorial or LevelSelect)
- Minimum 3 entity types with unique behaviors (e.g., player + 2 enemy/obstacle types with different AI)
- A progression system: at least 5 levels or stages with increasing difficulty
- At least 2 input modalities (keyboard + mouse or touch)
- A scoring system with depth: combos, multipliers, or time bonuses (not just +1 per action)
- At least 3 distinct enemy/obstacle patterns (not just static objects)
- Include a tutorial or gradual mechanic introduction in the first level
- "balance" must specify: starting_lives, difficulty_curve, and at least 3 difficulty parameters

COMMERCIAL REQUIREMENTS (MANDATORY):
- The "monetization" field MUST be a structured object (not a plain string) with: model, ad_placement (2+), iap_tiers (1+), retention_hooks (2+), engagement_mechanics (2+)
- Include at least 2 retention mechanics in the game design (e.g., daily challenges, streak bonuses, unlock systems)
- Include at least 1 engagement mechanic per game (e.g., power-ups, social sharing, collection systems)
- Design ad placements that don't disrupt core gameplay (between levels, game over, rewarded voluntary)
- Include a scoring/combo system that encourages replay and sharing

Do NOT design a trivial game. The target play session is 5-10 minutes with replay value.

Return ONLY the JSON object, no other text."""


async def generate_gdd(proposal: GameProposal, config: AppConfig) -> dict:
    logger.info(f"Generating GDD for: {proposal.name} ({proposal.genre})")

    model = DEFAULT_ANALYSIS_MODEL
    if not config.minimax_api_key:
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
Estimated Dev Hours: {proposal.estimated_dev_hours}
Complexity Target: {"simple (8h)" if proposal.estimated_dev_hours <= 10 else "standard (16h)" if proposal.estimated_dev_hours <= 20 else "complex (32h+)"}

Generate a complete, detailed GDD. Make the game fun and engaging for web play.
Scale complexity to match the dev hours: more hours = more mechanics, scenes, and depth.

IMPORTANT: This game should have enough depth to engage a player for 5-10 minutes. Simple one-button games will be rejected."""

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
        raise ValueError("Failed to parse GDD JSON")

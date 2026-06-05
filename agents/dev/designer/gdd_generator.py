from __future__ import annotations

import json

from loguru import logger

from shared.config import AppConfig
from shared.constants import DEFAULT_ANALYSIS_MODEL
from shared.llm_client import llm
from shared.models import GameProposal
from shared.vn_schema import is_visual_novel, validate_gdd

# Genre → Phaser architecture knowledge (loaded from config)
try:
    from pathlib import Path
    import yaml as _yaml

    _phaser_kb_path = Path(__file__).resolve().parent.parent.parent.parent / "config" / "phaser_knowledge.yaml"
    if _phaser_kb_path.exists():
        with open(_phaser_kb_path) as _f:
            _PHASER_KB = _yaml.safe_load(_f)
    else:
        _PHASER_KB = None
except Exception:
    _PHASER_KB = None


def _genre_architecture_hint(genre: str) -> str:
    """Return a Phaser architecture hint for the given genre from the knowledge base."""
    if not _PHASER_KB:
        return ""
    genre_map = _PHASER_KB.get("genre_architecture_map", {})
    entry = genre_map.get(genre, genre_map.get(genre.replace("-", "_"), genre_map.get(genre.replace("-", ""), None)))
    if not entry:
        return ""
    lines = [
        f"\n## Recommended Architecture for {genre}:",
        f"- Physics: {entry.get('recommended_physics', 'arcade')}",
        f"- Pattern: {entry.get('recommended_pattern', 'state_machine')}",
        f"- Core Systems: {', '.join(entry.get('core_systems', []))}",
        f"- Data-Driven Files: {', '.join(entry.get('data_driven', []))}",
        f"- Scenes: {', '.join(entry.get('typical_scenes', []))}",
        f"- Minimum Mechanics: {entry.get('min_mechanics', 5)}",
        f"- Code Organization: {entry.get('code_organization', 'scenes/entities/systems')}",
    ]
    return "\n".join(lines)

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
  "estimated_play_session_minutes": 5,
  "technical_architecture": {
    "game_pattern": "state_machine | entity_component | grid_based | wave_based | upgrade_tree",
    "physics_engine": "arcade | matter | none",
    "phaser_plugins": ["list of needed plugins"],
    "scene_architecture": {
      "GameScene": {
        "sub_systems": ["LevelManager", "EnemySpawner"],
        "uses_physics": true,
        "physics_engine": "arcade"
      }
    },
    "code_organization": "scenes/entities/systems/data",
    "data_driven": {
      "levels": "data/levels.json",
      "enemies": "data/enemies.json",
      "powerups": "data/powerups.json"
    },
    "reusable_components": ["HUD", "UpgradeShop", "ComboCounter"]
  }
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

TECHNICAL ARCHITECTURE (MANDATORY):
- The "technical_architecture" field MUST be included with: game_pattern, physics_engine, phaser_plugins, scene_architecture, code_organization, data_driven, reusable_components
- Choose game_pattern based on genre: platformer/shooter/runner→state_machine, puzzle/card→grid_based, tower-defense→wave_based, idle→upgrade_tree, rpg→entity_component
- Choose physics_engine: platformer/shooter→arcade, puzzle→none, physics_puzzle→matter
- scene_architecture MUST describe each scene's sub_systems and whether it uses physics
- data_driven MUST specify at least 2 JSON data files for game content (levels, enemies, powerups, upgrades, waves)
- reusable_components MUST list at least 2 components that should be shared across scenes
- code_organization MUST specify the directory structure: scenes/, entities/, systems/, data/

HYBRID VISUAL NOVEL EXTENSION (apply ONLY if your design is a story-driven game
with player choices, character relationships, and branching outcomes — a hybrid
Visual Novel with light stat-based/branching mechanics). If you decide this is a
VN, you MUST add these fields to the JSON object. The GDD will be rejected by the
schema validator if any are missing or malformed. Do NOT include these fields for
non-VN games.

- "narrative_premise": str — a 2-3 sentence logline of the story hook.
- "player_protagonist": {"name": str, "pronouns": str, "portrait_key": str}.
- "character_roster": list of >=2 entries, each:
    {"name": str, "role": "protagonist"|"heroine"|"antagonist"|"npc",
     "sprite_set": str (path under public/assets/characters/),
     "expression_variants": list of >=3 of "neutral"|"happy"|"sad"|"surprised"|"angry",
     "personality": str, "stat_affinities": list of stat names}.
- "route_structure": {"common_route_chapters": int (>=1),
     "character_routes": list of {"key": str, "name": str, "chapters": int, "unlock": str}}.
- "stat_system": {"stats": list of >=5 entries, each:
     {"name": str, "range": [min: number, max: number] where min < max,
      "decay": number, "branching_thresholds": list of {"op": str, "value": number, "route": str}}}.
- "branching_tree": {"root": str (must be a key in nodes),
     "nodes": dict of >=8 entries, each {"scene_key": str, "dialogue": list, "choices": list of {"label": str, "next_node": str, "stat_delta": optional {"stat_name": number}, "flag_set": optional [str]}}}.
     ALL nodes MUST be reachable from root via BFS through the choices. NO cycles.
- "ending_conditions": list of >=3 entries, each:
     {"name": str, "trigger": dict (e.g. {"stat:empathy": {">=": 5}}),
      "epilogue_key": str, "is_good_ending": 0|1}.
     Each trigger dict MUST be unique across the list (no two endings with identical triggers).
- "cg_milestones": list of >=1 entries, each {"scene_id": str, "cg_key": str, "condition": str}.
- "save_points": list of {"scene_id": str, "save_key": str}.
- "vn_schema_version": "1.0"

Return ONLY the JSON object, no other text."""


async def generate_gdd(proposal: GameProposal, config: AppConfig) -> dict:
    logger.info(f"Generating GDD for: {proposal.name} ({proposal.genre})")

    model = DEFAULT_ANALYSIS_MODEL

    # For complex VN GDDs, prefer DeepSeek which handles large structured JSON better
    if config.deepseek_api_key and proposal.estimated_dev_hours >= 20:
        model = "deepseek-v4-flash"
        logger.info(f"Using {model} for complex GDD generation")

    if not config.deepseek_api_key and not config.minimax_api_key:
        logger.error("No AI API key configured")
        return {"title": proposal.name, "genre": proposal.genre, "scenes": []}

    user_prompt = f"""Create a GDD for this game proposal:

Name: {proposal.name}
Genre: {proposal.genre}
Description: {proposal.description}
Target Platforms: {", ".join(proposal.target_platforms)}
Differentiation: {proposal.differentiation}
Reference Games: {", ".join(proposal.reference_games)}
Market Score: {proposal.market_opportunity_score}
Estimated Dev Hours: {proposal.estimated_dev_hours}
Complexity Target: {"simple (8h)" if proposal.estimated_dev_hours <= 10 else "standard (16h)" if proposal.estimated_dev_hours <= 20 else "complex (32h+)"}
{_genre_architecture_hint(proposal.genre)}

Generate a complete, detailed GDD. Make the game fun and engaging for web play.
Scale complexity to match the dev hours: more hours = more mechanics, scenes, and depth.

IMPORTANT: This game should have enough depth to engage a player for 5-10 minutes. Simple one-button games will be rejected.

DESIGN FOR DEPTH: Include data-driven content (levels with varying enemy compositions, upgrade trees with meaningful choices, multiple enemy AI patterns). The game should feel like it was made by a skilled game designer, not a template.

CRITICAL: Return ONLY the raw JSON object. No markdown, no explanation, no preamble. Start with {{ and end with }}. Do NOT include any text before or after the JSON."""

    text, usage = await llm.chat_completion(
        model=model,
        messages=[
            {"role": "system", "content": DESIGNER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        max_tokens=16000,
        agent_name="designer",
        project_name=proposal.name,
    )
    gdd = _parse_gdd(text)

    if is_visual_novel(gdd):
        errors = validate_gdd(gdd)
        if errors:
            logger.warning(f"GDD validation: {len(errors)} issues, retrying with fix prompt")
            for e in errors:
                logger.warning(f"  - {e}")
            fix_prompt = (
                "The previous GDD JSON had validation errors:\n"
                + "\n".join(f"- {e}" for e in errors)
                + "\n\nReturn the COMPLETE corrected GDD JSON. "
                "Do NOT truncate. Ensure ALL required fields are present."
            )
            text2, _ = await llm.chat_completion(
                model=model,
                messages=[
                    {"role": "system", "content": DESIGNER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": fix_prompt},
                ],
                temperature=0.3,
                max_tokens=16000,
                agent_name="designer",
                project_name=proposal.name,
            )
            gdd2 = _parse_gdd(text2)
            errors2 = validate_gdd(gdd2)
            if not errors2:
                gdd = gdd2
                logger.info("GDD validation fixed on retry ✓")
            else:
                logger.warning(f"GDD still has {len(errors2)} issues after retry")

    logger.info(
        f"GDD generated: {gdd.get('title', 'untitled')} with {len(gdd.get('scenes', []))} scenes"
    )

    return gdd


def _parse_gdd(text: str) -> dict:
    text = text.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    # Strip any leading non-JSON content (LLM may add preamble)
    json_start = text.find("{")
    if json_start > 0:
        text = text[json_start:]
    elif json_start < 0:
        raise ValueError(
            f"No JSON object found in LLM response (length={len(text)})"
        )

    # Strip trailing non-JSON after last }
    json_end = text.rfind("}") + 1
    if json_end > 0:
        text = text[:json_end]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    try:
        return _repair_truncated_json(text)
    except Exception:
        pass

    raise ValueError(
        f"Failed to parse GDD JSON (text length={len(text)}, "
        f"first 200 chars: {text[:200]})"
    )


def _repair_truncated_json(text: str) -> dict:
    """Attempt to repair a truncated JSON object by balancing braces/brackets."""
    stack: list[str] = []
    in_string = False
    escape = False

    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()

    suffix = ""
    for opener in reversed(stack):
        if opener == "{":
            suffix += "}"
        elif opener == "[":
            suffix += "]"

    if not suffix:
        raise ValueError("Cannot repair JSON")

    repaired = text + suffix
    return json.loads(repaired)

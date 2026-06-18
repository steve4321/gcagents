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

    _phaser_kb_path = (
        Path(__file__).resolve().parent.parent.parent.parent / "config" / "phaser_knowledge.yaml"
    )
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
    entry = genre_map.get(
        genre, genre_map.get(genre.replace("-", "_"), genre_map.get(genre.replace("-", ""), None))
    )
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


VN_FOUNDATION_SYSTEM_PROMPT = """You are an expert game designer specializing in Visual Novels.
Your task is to design the FOUNDATION of a hybrid Visual Novel game.

Return ONLY a JSON object with these EXACT fields (no other text, no markdown):

{
  "title": "Game Title",
  "genre": "visual-novel",
  "summary": "One paragraph game concept (2-3 sentences)",
  "narrative_premise": "A 2-3 sentence logline of the story hook",
  "player_protagonist": {
    "name": "Protagonist Name",
    "pronouns": "he/him | she/her | they/them",
    "portrait_key": "protagonist_neutral"
  },
  "character_roster": [
    {
      "name": "Character Name",
      "role": "protagonist | heroine | antagonist | npc",
      "sprite_set": "characters/character_id",
      "expression_variants": ["neutral", "happy", "sad", "surprised", "angry"],
      "personality": "Brief personality description (1 sentence)",
      "stat_affinities": ["stat_name_1", "stat_name_2"]
    }
  ],
  "stat_system": {
    "stats": [
      {
        "name": "stat_name",
        "range": [0, 10],
        "decay": 0,
        "branching_thresholds": [
          {"op": ">=", "value": 5, "route": "route_key"},
          {"op": ">=", "value": 8, "route": "true_route_key"}
        ]
      }
    ]
  },
  "art_style": {
    "theme": "e.g., anime, watercolor, pixel-art",
    "color_palette": ["#hex1", "#hex2", "#hex3"],
    "reference": "visual reference description"
  },
  "audio": {
    "bgm_mood": "e.g., romantic, melancholic, upbeat",
    "sfx_list": ["page_turn", "choice_select", "heartbeat"]
  }
}

STRICT REQUIREMENTS:
- character_roster MUST have >= 2 entries
- Each character MUST have >= 3 expression_variants from: neutral, happy, sad, surprised, angry
- stat_system.stats MUST have >= 5 entries
- Each stat MUST have range as [min, max] where min < max
- Stat names must be simple lowercase identifiers (e.g., "courage", "empathy") — NOT prefixed with "stat:"

CRITICAL: Return ONLY valid JSON. Every key must be double-quoted. No YAML. No explanations."""


VN_COMMON_ROUTE_PROMPT = """You are an expert Visual Novel story designer.
Your task is to design the ROUTE STRUCTURE and COMMON ROUTE for a hybrid Visual Novel.

You will receive the game's foundation (characters, stats, premise).
Design the route structure and the shared common route (NOT character routes — those are generated separately).

Return ONLY a JSON object with these EXACT fields (no other text, no markdown, no YAML, no pseudo-code):

{
  "route_structure": {
    "common_route_chapters": 3,
    "character_routes": [
      {"key": "akari", "name": "Akari", "chapters": 2, "unlock": "After common chapter 3"}
    ]
  },
  "common_route_nodes": {
    "common_01": {
      "scene_key": "prologue",
      "dialogue": ["d_prologue_01", "d_prologue_02"],
      "choices": [
        {"label": "Choice text", "next_node": "common_02", "stat_delta": {"courage": 1}}
      ]
    }
  }
}

STRICT RULES:
- common_route_nodes MUST have exactly 15 entries (common_01 through common_15)
- Use EXACTLY 15 nodes in the common route
- Each node key MUST be "common_01" through "common_15" (zero-padded 2 digits)
- Each node MUST have scene_key (string) and dialogue (list of strings)
- Choices are optional. If a node has no choices, use an empty list []
- For common_12, common_13, common_14, common_15: include choices that lead to "route_<key>_01" nodes
- All common_01 through common_11 nodes should chain forward via choices
- DO NOT include character route nodes (route_*). Only common route.
- DO NOT include ending nodes. Only common route.
- stat_delta keys MUST match stat names from the foundation
- character_routes list MUST have one entry per heroine in character_roster

NODE COUNT: EXACTLY 15 nodes. No more, no less.

CRITICAL: Return ONLY valid JSON. Every key must be double-quoted. Every string value must be double-quoted. No YAML. No pseudo-code. No explanations."""


VN_CHARACTER_ROUTE_PROMPT = """You are an expert Visual Novel story designer.
Your task is to design a SINGLE CHARACTER ROUTE and its ending nodes for a hybrid Visual Novel.

You will receive the game's foundation (characters, stats) and the route structure.
Generate nodes for ONE character route specified by route_key.

Return ONLY a JSON object with these EXACT fields (no other text, no markdown, no YAML, no pseudo-code):

{
  "route_key": "akari",
  "route_nodes": {
    "route_akari_01": {
      "scene_key": "akari_intro",
      "dialogue": ["d_akari_01"],
      "choices": [
        {"label": "Next", "next_node": "route_akari_02", "stat_delta": {"affection": 1}}
      ]
    },
    "ending_akari_good": {
      "scene_key": "akari_good_end",
      "dialogue": ["d_akari_end_good"],
      "choices": []
    }
  }
}

STRICT RULES:
- route_nodes MUST have exactly 11 entries:
  - 8 story nodes: route_<key>_01 through route_<key>_08
  - 3 ending nodes: ending_<key>_good, ending_<key>_normal, ending_<key>_bad
- Each node key MUST use the format route_<key>_NN or ending_<key>_<type>
- Each node MUST have scene_key (string) and dialogue (list of strings)
- Story nodes should chain forward: route_<key>_01 -> route_<key>_02 -> ... -> route_<key>_08
- route_<key>_08 should have choices leading to ending nodes
- Ending nodes have empty choices list []
- stat_delta keys MUST match stat names from the foundation

NODE COUNT: EXACTLY 11 nodes (8 story + 3 ending). No more, no less.

CRITICAL: Return ONLY valid JSON. Every key must be double-quoted. Every string value must be double-quoted. No YAML. No pseudo-code. No explanations."""


VN_ENDINGS_SYSTEM_PROMPT = """You are an expert Visual Novel designer.
Your task is to design the ENDING CONDITIONS, CG MILESTONES, and SAVE POINTS for a hybrid Visual Novel.

You will receive the game's foundation (characters, stats) and branching tree.

Return ONLY a JSON object with these EXACT fields (no other text, no markdown, no YAML, no pseudo-code):

{
  "ending_conditions": [
    {
      "name": "Good Ending Name",
      "trigger": {"empathy": 8, "courage": 5},
      "epilogue_key": "epilogue_good",
      "is_good_ending": 1
    }
  ],
  "cg_milestones": [
    {"scene_id": "common_05", "cg_key": "cg_school_festival", "condition": "Reached school festival scene"}
  ],
  "save_points": [
    {"scene_id": "common_01", "save_key": "save_prologue"}
  ]
}

STRICT REQUIREMENTS:
- ending_conditions MUST have >= 4 entries
- Each ending MUST have unique trigger (no two endings with identical trigger dicts)
- Trigger keys MUST match stat names from the foundation
- Each ending should have at least 1 good ending (is_good_ending: 1) and at least 1 bad ending (is_good_ending: 0)
- cg_milestones MUST have >= 3 entries
- save_points should have >= 3 entries at key story moments
- Scene IDs in cg_milestones and save_points MUST exist in the branching tree

CRITICAL: Return ONLY valid JSON. Every key must be double-quoted. Every string value must be double-quoted. No YAML. No pseudo-code. No explanations."""


async def generate_gdd(proposal: GameProposal, config: AppConfig) -> dict:
    logger.info(f"Generating GDD for: {proposal.name} ({proposal.genre})")

    is_vn = proposal.genre in ("visual-novel", "vn", "gal", "galgame", "visual_novel")

    if is_vn:
        return await _generate_vn_gdd_multiround(proposal, config)

    return await _generate_generic_gdd(proposal, config)


async def _generate_generic_gdd(proposal: GameProposal, config: AppConfig) -> dict:
    """Single-round GDD generation for non-VN games."""
    model = DEFAULT_ANALYSIS_MODEL

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


async def _generate_vn_gdd_multiround(proposal: GameProposal, config: AppConfig) -> dict:
    model = DEFAULT_ANALYSIS_MODEL
    if config.deepseek_api_key and proposal.estimated_dev_hours >= 20:
        model = "deepseek-v4-flash"
    logger.info(f"VN GDD: using {model}, 3-round generation for {proposal.name}")

    if not config.deepseek_api_key and not config.minimax_api_key:
        logger.error("No AI API key configured")
        return {"title": proposal.name, "genre": proposal.genre}

    logger.info("VN GDD Round 1/4: foundation")
    foundation = await _generate_vn_foundation(proposal, model, config)
    if not foundation:
        logger.error("VN GDD Round 1 failed, falling back to single-round")
        return await _generate_generic_gdd(proposal, config)

    logger.info("VN GDD Round 2/4: common route + route structure")
    common_route = await _generate_vn_common_route(proposal, foundation, model, config)
    if not common_route:
        logger.error("VN GDD Round 2 failed")
        common_route = _default_common_route(foundation)

    char_routes_count = len(common_route.get("route_structure", {}).get("character_routes", []))
    if char_routes_count == 0:
        heros = [
            c
            for c in foundation.get("character_roster", [])
            if c.get("role") in ("heroine", "protagonist")
        ]
        char_routes_count = min(len(heros), 2)

    max_routes = (
        2 if proposal.estimated_dev_hours <= 10 else 3 if proposal.estimated_dev_hours <= 20 else 5
    )
    char_routes_count = min(char_routes_count, max_routes)

    logger.info(f"VN GDD Round 3/4: character routes ({char_routes_count} routes)")
    character_routes = await _generate_vn_character_routes(
        proposal, foundation, common_route, char_routes_count, model, config
    )
    if not character_routes:
        logger.error("VN GDD Round 3 failed, using defaults")
        character_routes = []

    branching = _assemble_branching_tree(foundation, common_route, character_routes)

    logger.info("VN GDD Round 4/4: endings + CG + save points")
    endings = await _generate_vn_endings(proposal, foundation, branching, model, config)
    if not endings:
        logger.error("VN GDD Round 4 failed, using defaults")
        endings = {
            "ending_conditions": _default_endings(foundation),
            "cg_milestones": _default_cg_milestones(branching),
            "save_points": _default_save_points(branching),
        }

    gdd = _merge_vn_gdd(foundation, branching, endings)

    errors = validate_gdd(gdd)
    if errors:
        logger.warning(f"VN GDD validation: {len(errors)} issues, attempting repair")
        for e in errors:
            logger.warning(f"  - {e}")
        gdd = _repair_vn_gdd(gdd, foundation)
        final_errors = validate_gdd(gdd)
        if not final_errors:
            logger.info("VN GDD validation repaired ✓")
        else:
            logger.warning(f"VN GDD still has {len(final_errors)} issues after repair")
            for e in final_errors:
                logger.warning(f"  - {e}")

    logger.info(
        f"VN GDD generated: {gdd.get('title', 'untitled')} "
        f"with {len(gdd.get('branching_tree', {}).get('nodes', {}))} branching nodes, "
        f"{len(gdd.get('ending_conditions', []))} endings"
    )

    return gdd


async def _generate_vn_foundation(proposal: GameProposal, model: str, config: AppConfig) -> dict:
    user_prompt = f"""Design the foundation for this Visual Novel:

Name: {proposal.name}
Genre: {proposal.genre}
Description: {proposal.description}
Target Platforms: {", ".join(proposal.target_platforms)}
Differentiation: {proposal.differentiation}
Market Score: {proposal.market_opportunity_score}
Complexity Target: {"simple (8h)" if proposal.estimated_dev_hours <= 10 else "standard (16h)" if proposal.estimated_dev_hours <= 20 else "complex (32h+)"}

IMPORTANT: Create 2-3 main characters and a 5-stat system appropriate for a {"small-scale" if proposal.estimated_dev_hours <= 10 else "standard"} VN."""

    try:
        text, _ = await llm.chat_completion(
            model=model,
            messages=[
                {"role": "system", "content": VN_FOUNDATION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=4000,
            agent_name="designer",
            project_name=proposal.name,
        )
        foundation = _parse_gdd(text)
        if not isinstance(foundation, dict):
            logger.warning("VN Round 1: parsed result is not a dict")
            return {}
        required = ["title", "narrative_premise", "character_roster", "stat_system"]
        missing = [f for f in required if f not in foundation]
        if missing:
            logger.warning(f"VN Round 1: missing fields: {missing}")
            return {}
        logger.info(
            f"VN Round 1: {len(foundation.get('character_roster', []))} characters, "
            f"{len(foundation.get('stat_system', {}).get('stats', []))} stats"
        )
        return foundation
    except Exception as e:
        logger.error(f"VN Round 1 failed: {e}")
        return {}


async def _generate_vn_common_route(
    proposal: GameProposal,
    foundation: dict,
    model: str,
    config: AppConfig,
) -> dict:
    char_names = [
        c.get("name", "?")
        for c in foundation.get("character_roster", [])
        if c.get("role") in ("heroine", "protagonist", "npc")
    ]
    stat_names = [s.get("name", "?") for s in foundation.get("stat_system", {}).get("stats", [])]

    user_prompt = f"""Design the common route for this Visual Novel:

Title: {foundation.get("title", proposal.name)}
Premise: {foundation.get("narrative_premise", "")}
Characters available for routes: {", ".join(char_names[:4])}
Available stats for stat_delta: {", ".join(stat_names)}

Create EXACTLY 15 common route nodes (common_01 to common_15) and define the character_routes list.
The last 4 nodes (common_12-common_15) should have choices that lead to character routes."""

    try:
        text, _ = await llm.chat_completion(
            model=model,
            messages=[
                {"role": "system", "content": VN_COMMON_ROUTE_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=6000,
            agent_name="designer",
            project_name=proposal.name,
        )
        result = _parse_gdd(text)
        if not isinstance(result, dict):
            logger.warning("VN Round 2: parsed result is not a dict")
            return {}
        nodes = result.get("common_route_nodes", {})
        if not nodes:
            logger.warning("VN Round 2: missing common_route_nodes")
            return {}
        logger.info(f"VN Round 2: {len(nodes)} common route nodes generated")
        return result
    except Exception as e:
        logger.error(f"VN Round 2 failed: {e}")
        return {}


async def _generate_vn_character_routes(
    proposal: GameProposal,
    foundation: dict,
    common_route: dict,
    num_routes: int,
    model: str,
    config: AppConfig,
) -> list[dict]:
    char_routes = common_route.get("route_structure", {}).get("character_routes", [])
    if not char_routes:
        heros = [
            c
            for c in foundation.get("character_roster", [])
            if c.get("role") in ("heroine", "protagonist")
        ]
        char_routes = [
            {
                "key": h.get("name", f"route_{i}").lower().split()[0],
                "name": h.get("name", f"Hero {i}"),
            }
            for i, h in enumerate(heros[:num_routes])
        ]

    stat_names = [s.get("name", "?") for s in foundation.get("stat_system", {}).get("stats", [])]
    all_routes: list[dict] = []

    for i, route_info in enumerate(char_routes[:num_routes]):
        route_key = route_info.get("key", f"route_{i}")
        route_name = route_info.get("name", route_key)
        logger.info(
            f"VN Round 3: generating character route '{route_key}' ({i + 1}/{len(char_routes[:num_routes])})"
        )

        user_prompt = f"""Design the character route "{route_name}" (key: {route_key}) for this Visual Novel:

Title: {foundation.get("title", proposal.name)}
Premise: {foundation.get("narrative_premise", "")}
Available stats for stat_delta: {", ".join(stat_names)}

Create EXACTLY 11 nodes: 8 story nodes (route_{route_key}_01 to route_{route_key}_08) + 3 ending nodes (ending_{route_key}_good, ending_{route_key}_normal, ending_{route_key}_bad)."""

        try:
            text, _ = await llm.chat_completion(
                model=model,
                messages=[
                    {"role": "system", "content": VN_CHARACTER_ROUTE_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                max_tokens=4000,
                agent_name="designer",
                project_name=proposal.name,
            )
            result = _parse_gdd(text)
            if not isinstance(result, dict):
                logger.warning(f"VN Round 3.{i}: not a dict, skipping route {route_key}")
                continue
            nodes = result.get("route_nodes", {})
            if not nodes:
                logger.warning(f"VN Round 3.{i}: missing route_nodes, skipping route {route_key}")
                continue
            logger.info(f"VN Round 3.{i}: {len(nodes)} nodes for route '{route_key}'")
            all_routes.append(result)
        except Exception as e:
            logger.error(f"VN Round 3.{i} failed for route {route_key}: {e}")
            continue

    return all_routes


def _assemble_branching_tree(
    foundation: dict, common_route: dict, character_routes: list[dict]
) -> dict:
    branching_tree: dict = {"root": "common_01", "nodes": {}}

    common_nodes = common_route.get("common_route_nodes", {})
    for nid, ndata in common_nodes.items():
        if _is_valid_scene_node(nid, ndata):
            branching_tree["nodes"][nid] = ndata

    for route in character_routes:
        route_nodes = route.get("route_nodes", {})
        for nid, ndata in route_nodes.items():
            if _is_valid_scene_node(nid, ndata):
                branching_tree["nodes"][nid] = ndata

    nodes = branching_tree["nodes"]
    if not nodes:
        branching_tree["root"] = "common_01"
    else:
        first_key = next(iter(nodes.keys()), "common_01")
        if not branching_tree["root"] or branching_tree["root"] not in nodes:
            branching_tree["root"] = first_key

    if len(branching_tree["nodes"]) < 30:
        filler = _generate_filler_nodes(
            branching_tree["nodes"], count=30 - len(branching_tree["nodes"])
        )
        branching_tree["nodes"].update(filler)

    char_routes = common_route.get("route_structure", {}).get("character_routes", [])
    if not char_routes:
        heros = [
            c
            for c in foundation.get("character_roster", [])
            if c.get("role") in ("heroine", "protagonist")
        ]
        char_routes = [
            {
                "key": h.get("name", f"hero_{i}").lower().split()[0],
                "name": h.get("name", f"Hero {i}"),
            }
            for i, h in enumerate(heros[:2])
        ]

    return {
        "route_structure": {
            "common_route_chapters": common_route.get("route_structure", {}).get(
                "common_route_chapters", 3
            ),
            "character_routes": char_routes,
        },
        "branching_tree": branching_tree,
    }


def _is_valid_scene_node(node_id: str, node_data) -> bool:
    if not isinstance(node_data, dict):
        return False
    if not node_data.get("scene_key"):
        return False
    if not isinstance(node_data.get("scene_key"), str):
        return False
    if not node_id or not isinstance(node_id, str):
        return False
    if not node_id.startswith(("common_", "route_", "ending_")):
        return False
    return True


def _generate_filler_nodes(existing_nodes: dict, count: int) -> dict:
    filler: dict = {}
    for i in range(count):
        idx = len(existing_nodes) + i + 1
        node_id = f"filler_{idx:02d}"
        filler[node_id] = {
            "scene_key": f"filler_scene_{idx:02d}",
            "title": f"Transition Scene {idx}",
            "type": "transition",
            "choices": [],
            "filler": True,
        }
    return filler


def _default_common_route(foundation: dict) -> dict:
    heros = [
        c
        for c in foundation.get("character_roster", [])
        if c.get("role") in ("heroine", "protagonist")
    ]
    char_routes = [
        {
            "key": h.get("name", f"hero_{i}").lower().split()[0],
            "name": h.get("name", f"Hero {i}"),
            "chapters": 2,
            "unlock": "After common chapter 3",
        }
        for i, h in enumerate(heros[:2])
    ]

    common_nodes: dict = {}
    for i in range(1, 16):
        nid = f"common_{i:02d}"
        choices = []
        if i < 15:
            choices.append({"label": "Continue", "next_node": f"common_{i + 1:02d}"})
        if i == 13 and char_routes:
            for cr in char_routes:
                choices.append(
                    {
                        "label": f"Pursue {cr['name']}",
                        "next_node": f"route_{cr['key']}_01",
                    }
                )
        common_nodes[nid] = {
            "scene_key": f"common_scene_{i}",
            "dialogue": [f"d_common_{i:02d}"],
            "choices": choices,
        }
    common_nodes["common_15"]["choices"] = []

    return {
        "route_structure": {
            "common_route_chapters": 3,
            "character_routes": char_routes,
        },
        "common_route_nodes": common_nodes,
    }


async def _generate_vn_endings(
    proposal: GameProposal,
    foundation: dict,
    branching: dict,
    model: str,
    config: AppConfig,
) -> dict:
    stat_names = [s.get("name", "?") for s in foundation.get("stat_system", {}).get("stats", [])]
    node_ids = list(branching.get("branching_tree", {}).get("nodes", {}).keys())

    user_prompt = f"""Design endings, CG milestones, and save points for this VN:

Title: {foundation.get("title", proposal.name)}
Available stats: {", ".join(stat_names)}
Branching tree has {len(node_ids)} nodes. Sample node IDs: {", ".join(node_ids[:10])}

Create:
- 4+ ending conditions with unique stat-based triggers
- 3+ CG milestones at key story moments
- 3+ save points at chapter transitions"""

    try:
        text, _ = await llm.chat_completion(
            model=model,
            messages=[
                {"role": "system", "content": VN_ENDINGS_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=4000,
            agent_name="designer",
            project_name=proposal.name,
        )
        endings = _parse_gdd(text)
        if not isinstance(endings, dict):
            logger.warning("VN Round 3: parsed result is not a dict")
            return {}
        required = ["ending_conditions", "cg_milestones", "save_points"]
        missing = [f for f in required if f not in endings]
        if missing:
            logger.warning(f"VN Round 3: missing fields: {missing}")
            return {}
        logger.info(
            f"VN Round 3: {len(endings.get('ending_conditions', []))} endings, "
            f"{len(endings.get('cg_milestones', []))} CG milestones, "
            f"{len(endings.get('save_points', []))} save points"
        )
        return endings
    except Exception as e:
        logger.error(f"VN Round 3 failed: {e}")
        return {}


def _merge_vn_gdd(foundation: dict, branching: dict, endings: dict) -> dict:
    gdd = dict(foundation)
    gdd.update(branching)
    gdd.update(endings)
    gdd.setdefault("vn_schema_version", "1.0")
    gdd.setdefault("core_loop", ["Read story", "Make choice", "See outcome"])
    gdd.setdefault("progression", "Linear visual novel with branching routes")
    gdd.setdefault("win_condition", "Reach an ending")
    gdd.setdefault(
        "monetization", {"model": "free_to_play", "ad_placement": [], "retention_hooks": []}
    )
    gdd.setdefault("mechanics", [])
    gdd.setdefault("scenes", [])
    gdd.setdefault("entities", [])
    gdd.setdefault("estimated_play_session_minutes", 15)
    return gdd


def _default_endings(foundation: dict) -> list:
    stats = foundation.get("stat_system", {}).get("stats", [])
    if not stats:
        return [
            {
                "name": "True End",
                "trigger": {"affection": 10},
                "epilogue_key": "ep_true",
                "is_good_ending": 1,
            }
        ]
    primary = stats[0].get("name", "affection")
    return [
        {
            "name": "Good End",
            "trigger": {primary: 8},
            "epilogue_key": "ep_good",
            "is_good_ending": 1,
        },
        {
            "name": "Normal End",
            "trigger": {primary: 5},
            "epilogue_key": "ep_normal",
            "is_good_ending": 0,
        },
        {"name": "Bad End", "trigger": {primary: 2}, "epilogue_key": "ep_bad", "is_good_ending": 0},
        {
            "name": "Secret End",
            "trigger": {primary: 10, "courage": 8} if len(stats) > 1 else {primary: 12},
            "epilogue_key": "ep_secret",
            "is_good_ending": 1,
        },
    ]


def _default_cg_milestones(branching: dict) -> list:
    nodes = branching.get("branching_tree", {}).get("nodes", {})
    common_ids = sorted([nid for nid in nodes if nid.startswith("common_")])
    milestones = []
    for i, idx in enumerate([0, len(common_ids) // 2, len(common_ids) - 1]):
        if idx < len(common_ids):
            scene_id = common_ids[idx]
            milestones.append(
                {
                    "scene_id": scene_id,
                    "cg_key": f"cg_{scene_id}",
                    "condition": f"Reached {scene_id}",
                }
            )
    return milestones


def _default_save_points(branching: dict) -> list:
    nodes = branching.get("branching_tree", {}).get("nodes", {})
    common_ids = sorted([nid for nid in nodes if nid.startswith("common_")])
    if not common_ids:
        return []
    save_ids = [common_ids[0]]
    if len(common_ids) >= 5:
        save_ids.append(common_ids[len(common_ids) // 2])
    if len(common_ids) >= 2:
        save_ids.append(common_ids[-1])
    return [{"scene_id": sid, "save_key": f"save_{sid}"} for sid in save_ids]


def _repair_vn_gdd(gdd: dict, foundation: dict) -> dict:
    gdd = _fix_unreachable_nodes(gdd)
    gdd = _fix_undefined_stats(gdd, foundation)
    return gdd


def _fix_unreachable_nodes(gdd: dict) -> dict:
    """Connect unreachable nodes to the root or a common node."""
    tree = gdd.get("branching_tree", {})
    if not isinstance(tree, dict):
        return gdd
    nodes = tree.get("nodes", {})
    if not isinstance(nodes, dict) or not nodes:
        return gdd
    root = tree.get("root", "")
    if not root or root not in nodes:
        root = next(iter(nodes.keys()), None)
        if not root:
            return gdd
        tree["root"] = root

    visited: set[str] = set()
    queue: list[str] = [root]
    while queue:
        cur = queue.pop(0)
        if cur in visited:
            continue
        visited.add(cur)
        node = nodes.get(cur)
        if not isinstance(node, dict):
            continue
        for choice in node.get("choices", []) or []:
            if isinstance(choice, dict):
                nxt = choice.get("next_node")
                if isinstance(nxt, str) and nxt in nodes:
                    queue.append(nxt)

    unreachable = set(nodes.keys()) - visited
    if unreachable:
        first_reachable = root
        for uid in sorted(unreachable):
            node = nodes.get(uid)
            if not isinstance(node, dict):
                continue
            if not node.get("choices"):
                node["choices"] = []
            if uid != first_reachable:
                nodes[first_reachable].setdefault("choices", []).append(
                    {"label": f"Continue ({uid})", "next_node": uid}
                )
                visited.add(uid)
    return gdd


def _fix_undefined_stats(gdd: dict, foundation: dict) -> dict:
    """Replace stat references with defined stat names."""
    defined_stats = [
        s.get("name", "")
        for s in foundation.get("stat_system", {}).get("stats", [])
        if isinstance(s, dict) and s.get("name")
    ]
    if not defined_stats:
        return gdd

    stat_aliases: dict[str, str] = {}
    for stat in defined_stats:
        stat_aliases[stat.lower()] = stat
        stat_aliases[f"stat:{stat}".lower()] = stat

    def clean_trigger(trigger: dict) -> dict:
        if not isinstance(trigger, dict):
            return trigger
        cleaned = {}
        for key, val in trigger.items():
            if not isinstance(key, str):
                cleaned[key] = val
                continue
            lower = key.lower()
            resolved = stat_aliases.get(lower, key)
            if ":" in resolved:
                resolved = resolved.split(":", 1)[0]
                if resolved.lower() in stat_aliases:
                    resolved = stat_aliases[resolved.lower()]
            if resolved in defined_stats:
                cleaned[resolved] = val
            else:
                cleaned[key] = val
        return cleaned

    for ending in gdd.get("ending_conditions", []):
        if isinstance(ending, dict) and "trigger" in ending:
            ending["trigger"] = clean_trigger(ending["trigger"])

    tree = gdd.get("branching_tree", {})
    if isinstance(tree, dict):
        for _nid, node in tree.get("nodes", {}).items():
            if not isinstance(node, dict):
                continue
            for choice in node.get("choices", []) or []:
                if isinstance(choice, dict) and "stat_delta" in choice:
                    delta = choice["stat_delta"]
                    if isinstance(delta, dict):
                        new_delta = {}
                        for k, v in delta.items():
                            resolved = stat_aliases.get(k.lower(), k)
                            if ":" in resolved:
                                resolved = resolved.split(":", 1)[0]
                                if resolved.lower() in stat_aliases:
                                    resolved = stat_aliases[resolved.lower()]
                            new_delta[resolved] = v
                        choice["stat_delta"] = new_delta
    return gdd


CONTENT_EXPANSION_PROMPT = """You are a game designer adding new content to an EXISTING game.

You will receive:
1. The existing game's GDD summary
2. The existing content inventory (what towers/enemies/waves/items already exist)
3. Optional player feedback hints

Your job: design NEW content that fits seamlessly with the existing game.

Return a JSON object with this structure:
{
  "rationale": "Why this content was chosen (1-2 sentences)",
  "target_files": ["towers.json", "enemies.json"],
  "new_content": {
    "towers.json": {
      "add_entries": [
        {
          "id": "laser_tower",
          "name": "Laser Tower",
          "damage": 25,
          "range": 150,
          "cost": 120,
          "fire_rate": 2.0,
          "description": "Continuous beam damage"
        }
      ]
    },
    "enemies.json": {
      "add_entries": [
        {
          "id": "fast_scout",
          "name": "Fast Scout",
          "hp": 30,
          "speed": 200,
          "armor": 0,
          "reward": 5
        }
      ]
    }
  },
  "balance_notes": "Laser tower is high-DPS but expensive. Fast scout counters slow-firing towers."
}

RULES:
1. Use the EXACT same field names and structure as existing entries (study the inventory carefully)
2. All new IDs must be UNIQUE — do not reuse any existing ID
3. Design content that is BALANCED with existing content (similar power level)
4. Add 2-5 new entries per file — enough to be meaningful but not overwhelming
5. Consider player feedback hints if provided
6. Choose target_files wisely — only include files that benefit from new content

Return ONLY the JSON object, no other text."""


async def generate_content_expansion(
    existing_gdd: dict,
    existing_content_summary: dict[str, list[str]],
    config: AppConfig,
    feedback_hints: list[str] | None = None,
) -> dict:
    genre = existing_gdd.get("genre", "unknown")
    title = existing_gdd.get("title", "Game")
    summary = existing_gdd.get("summary", "")
    balance = json.dumps(existing_gdd.get("balance", {}))

    inventory_block = "\n".join(
        f"- {fname}: {', '.join(ids)}" for fname, ids in existing_content_summary.items()
    )

    feedback_block = ""
    if feedback_hints:
        feedback_block = "\n\nPlayer feedback:\n" + "\n".join(f"- {h}" for h in feedback_hints)

    user_prompt = f"""Add new content to this existing game:

Title: {title}
Genre: {genre}
Summary: {summary}
Balance: {balance}

EXISTING CONTENT INVENTORY:
{inventory_block}
{feedback_block}

Design new content that complements the existing game. Return the JSON expansion spec."""

    logger.info(f"Generating content expansion for: {title} ({genre})")

    text, _usage = await llm.chat_completion(
        model=DEFAULT_ANALYSIS_MODEL,
        messages=[
            {"role": "system", "content": CONTENT_EXPANSION_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        max_tokens=8000,
        agent_name="designer",
        project_name=title,
    )
    result = _parse_gdd(text)

    new_content = result.get("new_content", {})
    for fname, spec in new_content.items():
        entries = spec.get("add_entries", []) if isinstance(spec, dict) else []
        logger.info(f"  {fname}: +{len(entries)} new entries")
    logger.info(
        f"Content expansion done: {len(new_content)} files, "
        f"rationale={result.get('rationale', '')[:80]}"
    )

    return result


def _parse_gdd(text: str) -> dict:
    text = text.strip()

    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    json_start = text.find("{")
    if json_start > 0:
        text = text[json_start:]
    elif json_start < 0:
        raise ValueError(f"No JSON object found in LLM response (length={len(text)})")

    json_end = text.rfind("}") + 1
    if json_end > 0:
        text = text[:json_end]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    try:
        return _repair_truncated_json(text)
    except Exception as e:
        logger.debug(f"GDD JSON repair failed: {e}")

    try:
        from json_repair import repair_json

        repaired = repair_json(text, return_objects=True)
        if isinstance(repaired, dict):
            logger.info("GDD JSON repaired via json_repair library")
            return repaired
        if isinstance(repaired, list) and repaired:
            best = max(
                repaired, key=lambda o: len(json.dumps(o)) if isinstance(o, (dict, list)) else 0
            )
            if isinstance(best, dict):
                logger.info(
                    f"GDD JSON repaired via json_repair (selected best of {len(repaired)} objects)"
                )
                return best
    except Exception as e:
        logger.debug(f"json_repair failed: {e}")

    raise ValueError(
        f"Failed to parse GDD JSON (text length={len(text)}, first 200 chars: {text[:200]})"
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

"""Resilient per-chapter code generator.

Unlike generate_game_code() which crashes if any route round fails to parse,
this module runs rounds individually and skips failed ones, so partial
data can still be used.
"""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

from loguru import logger


async def generate_chapter_code_resilient(
    chapter_gdd: dict,
    project_dir: Path,
    art_assets_path: str | None = None,
) -> dict:
    """Run code generation for one chapter, resilient to per-round failures.

    Returns:
        {
            "code_path": Path,
            "rounds_completed": int,
            "rounds_failed": [round_labels],
            "data": {"branching": ..., "dialogue": ...} if extracted
        }
    """
    from agents.dev.programmer.code_generator import (
        _vn_llm_round,
        _try_direct_json_parse,
        _extract_partial_data,
        _count_nodes,
        _summarize_files,
        _add_round_summary,
        _copy_vn_data_to_public,
        _install_and_build,
        _merge_vn_data,
        DEFAULT_CODE_MODEL,
    )
    from shared.config import load_config

    project_dir.mkdir(parents=True, exist_ok=True)
    config = load_config()
    game_title = chapter_gdd.get("title", "visual_novel")
    model = DEFAULT_CODE_MODEL

    route_structure = chapter_gdd.get("route_structure", {})
    common_route = route_structure.get("common_route", {})
    character_routes = route_structure.get("character_routes", [])

    accumulated: dict[str, str] = {}
    partial_data_list: list[dict] = []
    round_summaries: list[str] = []
    rounds_completed = 0
    rounds_failed: list[str] = []

    char_summary = json.dumps(chapter_gdd.get("character_roster", []), indent=2)[:2000]
    stats_summary = json.dumps(chapter_gdd.get("stat_system", {}), indent=2)[:2000]

    art_instruction = ""
    if art_assets_path:
        art_instruction = (
            f"\nArt assets available at: {art_assets_path}\n"
            "Load images via this.load.image() in BootScene. Reference as 'assets/<filename>'.\n"
        )

    round_specs = [
        ("Engine Code", "engine", 16384, _build_engine_prompt(game_title, chapter_gdd, art_instruction)),
        ("Common Route", "data", 16384, _build_common_route_prompt(
            game_title, chapter_gdd, common_route, round_summaries, char_summary, stats_summary
        )),
    ]

    for route in character_routes:
        route_name = route.get("name", "route")
        route["heroine"] = route.get("heroine", "")
        route["theme"] = route.get("theme", "")
        round_specs.append((
            f"Route: {route_name}",
            "data",
            16384,
            _build_route_prompt(
                game_title, chapter_gdd, route, round_summaries, char_summary, stats_summary
            ),
        ))

    round_specs.append(("Endings & Data", "files", 16384, _build_endings_prompt(
        game_title, chapter_gdd, char_summary, stats_summary, round_summaries
    )))
    round_specs.append(("Scene Code", "files", 16384, _build_scene_prompt(
        game_title, chapter_gdd, accumulated, round_summaries, art_instruction
    )))

    for round_label, round_type, max_tokens, prompt in round_specs:
        logger.info(f"  Chapter round: {round_label}")
        try:
            result = await _vn_llm_round(prompt, model, max_tokens, game_title, round_label)
            if round_type == "data":
                partial = _extract_partial_data(result)
                partial_data_list.append(partial)
                node_count = _count_nodes(result)
                _add_round_summary(round_summaries, round_label, {}, node_count=node_count)
            else:
                accumulated.update(result)
                _add_round_summary(round_summaries, round_label, result)
            rounds_completed += 1
        except Exception as e:
            logger.warning(f"  Round '{round_label}' FAILED: {e}")
            rounds_failed.append(round_label)
            continue

    if partial_data_list:
        try:
            merged_branching, merged_dialogue = _merge_vn_data(partial_data_list, chapter_gdd)
            data_dir = project_dir / "src" / "game" / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "branching.json").write_text(
                json.dumps(merged_branching, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            (data_dir / "dialogue.json").write_text(
                json.dumps(merged_dialogue, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            (data_dir / "stats.json").write_text(
                json.dumps(chapter_gdd.get("stat_system", {}).get("stats", []), indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            (data_dir / "endings.json").write_text(
                json.dumps(chapter_gdd.get("ending_conditions", []), indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            accumulated["src/game/data/branching.json"] = json.dumps(merged_branching, indent=2, ensure_ascii=False)
            accumulated["src/game/data/dialogue.json"] = json.dumps(merged_dialogue, indent=2, ensure_ascii=False)
            _copy_vn_data_to_public(project_dir)
        except Exception as e:
            logger.warning(f"Merge failed: {e}")

    for file_path, content in accumulated.items():
        if not str(file_path).startswith("src/"):
            continue
        full_path = project_dir / file_path
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, str):
                full_path.write_text(content, encoding="utf-8")
            else:
                full_path.write_text(json.dumps(content, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to write {file_path}: {e}")

    try:
        _install_and_build(project_dir)
    except Exception as e:
        logger.warning(f"Build failed: {e}")

    return {
        "code_path": project_dir,
        "rounds_completed": rounds_completed,
        "rounds_failed": rounds_failed,
    }


def _build_engine_prompt(game_title: str, gdd: dict, art_instruction: str) -> str:
    return f"""You are building a hybrid Visual Novel with Phaser 4 + TypeScript. ROUND 1: ENGINE CODE.

Game: {game_title}
Chapter: {gdd.get('chapter_title', '')}
Synopsis: {gdd.get('synopsis', '')[:300]}

Generate a JSON object mapping file paths to file contents:
1. src/game/config.ts — Phaser game config (width 1024, height 768, parent 'game-container', scale FIT).
2. src/game/data/stats.json — {json.dumps(gdd.get('stat_system', {}).get('stats', []))[:500]}
3. src/game/systems/BranchingEngine.ts — Manages branching node traversal. Methods: getCurrentNode(), chooseChoice(choiceIdx), isEnding(), getStats().
4. src/game/systems/StatSystem.ts — Tracks player stats. Methods: get(name), set(name, value), modify(name, delta), toJSON(), fromJSON().
5. src/game/systems/ChoiceSystem.ts — Renders choice buttons. Methods: show(choices, onChoose), hide(), isComplete().
6. src/game/systems/DialogueSystem.ts — Renders dialogue text. Methods: showDialogue(text, speaker), setSpeakers(speakers), advance(), isComplete().

Rules:
- `import * as Phaser from 'phaser';`
- FORBIDDEN: 'fs', 'path', 'os' imports
- TypeScript strict mode
- Real implementation, no TODOs
{art_instruction}

Return ONLY a JSON object mapping file paths to file contents."""


def _build_common_route_prompt(game_title, gdd, common_route, round_summaries, char_summary, stats_summary):
    nodes = common_route.get("nodes", 20) if isinstance(common_route, dict) else 20
    return f"""ROUND 2: COMMON ROUTE DATA for {game_title} - {gdd.get('chapter_title', '')}.

Chapter synopsis: {gdd.get('synopsis', '')[:400]}
Writing directive: {gdd.get('writing_directive', '')[:300]}
Common route theme: {common_route.get('theme', 'introduction') if isinstance(common_route, dict) else ''}
Expected nodes: ~{nodes}
Character roster: {char_summary[:500]}
Stat system: {stats_summary[:500]}

Generate a JSON object with EXACTLY these two keys:
- "branching": dict with "nodes" (dict of node_id -> {{scene_key, dialogue_refs, choices?}}) and "edges" (list).
  Generate ~{nodes} nodes for the common route. Use IDs like "common_01", "common_02", "common_start".
- "dialogue": dict mapping dialogue_id -> {{id, scene_id, speaker, text}}.
  Generate 20-30 dialogue entries. Each "text" must be 200-400 Chinese characters of literary prose.

Return ONLY a JSON object with "branching" and "dialogue" keys."""


def _build_route_prompt(game_title, gdd, route, round_summaries, char_summary, stats_summary):
    route_name = route.get("name", "route")
    route_nodes = route.get("nodes", 10) if isinstance(route.get("nodes", 10), int) else 10
    return f"""ROUND: CHARACTER ROUTE "{route_name}" for {game_title}.

Chapter: {gdd.get('chapter_title', '')}
Writing directive: {gdd.get('writing_directive', '')[:300]}
Route theme: {route.get('theme', '')}
Expected nodes: ~{route_nodes}

Generate a JSON object with EXACTLY these two keys:
- "branching": dict with "nodes" and "edges". Generate ~{route_nodes} nodes for this route.
  Use IDs like "{route_name}_01", "{route_name}_02", etc. First: "{route_name}_start".
  Each node: scene_key, dialogue_refs, optional choices ({{text, next_node, stat_deltas, id, label}}).
- "dialogue": dict mapping dialogue_id -> {{id, scene_id, speaker, text}}.
  Generate 15-25 dialogue entries. Each "text" 200-400 Chinese chars of literary prose.

Return ONLY a JSON object with "branching" and "dialogue" keys."""


def _build_endings_prompt(game_title, gdd, char_summary, stats_summary, round_summaries):
    return f"""ROUND: ENDINGS & DATA FILES for {game_title} - {gdd.get('chapter_title', '')}.

Generate a JSON object mapping file paths to file contents:
1. src/game/data/endings.json — ending definitions. Each: name, trigger, epilogue_key, is_good_ending.
2. src/game/data/stats.json — stat definitions with name, range, decay, branching_thresholds.

Return ONLY a JSON object mapping file paths to file contents."""


def _build_scene_prompt(game_title, gdd, accumulated, round_summaries, art_instruction):
    return f"""ROUND: SCENE CODE for {game_title}.

Generate these scene files (return JSON mapping path -> content):
1. src/game/scenes/BootScene.ts — Load data via this.load.json() using RELATIVE path 'assets/data/<filename>.json', transition to TitleScene.
2. src/game/scenes/TitleScene.ts — Title screen with Chinese game name, press any key.
3. src/game/scenes/MenuScene.ts — NEW GAME / CONTINUE menu.
4. src/game/scenes/NovelScene.ts — integrates BranchingEngine, StatSystem, ChoiceSystem, DialogueSystem.

Rules:
- `import * as Phaser from 'phaser';`
- FORBIDDEN: 'fs', 'path', 'os' imports
- Real implementation, no TODOs
{art_instruction}

Return ONLY a JSON object mapping file paths to file contents."""

"""Production Planner — generates a complete asset/code manifest BEFORE any generation.

The plan is the contract. Every generation track (art/audio/code) reads the
plan to know what to produce, and reports against it. Integration phase
verifies the plan is fully fulfilled.

This module:
1. Reads GDD + World Bible
2. Produces production_plan.json with manifests for:
   - Art assets: backgrounds, characters, CGs (per chapter, per scene)
   - Audio assets: BGM (per mood), SFX list
   - Code modules: all .ts files needed
   - Data files: branching.json, dialogue.json, stats.json, etc.
3. Estimates cost (LLM tokens, ComfyUI images, audio duration)
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def generate_production_plan(
    gdd: dict,
    bible: dict,
    chapter_gdds: list[dict] | None = None,
    output_path: Path | None = None,
) -> dict:
    """Generate the full production plan from GDD + Bible + chapter GDDs.

    The plan is generated BEFORE any art/code/audio production. It serves
    as the contract that all generators must fulfill.
    """
    num_chapters = len(chapter_gdds) if chapter_gdds else 1

    art_manifest = _build_art_manifest(gdd, bible, chapter_gdds or [gdd])
    audio_manifest = _build_audio_manifest(gdd, bible)
    code_manifest = _build_code_manifest(gdd, bible, num_chapters)
    data_manifest = _build_data_manifest(gdd, bible, num_chapters)

    plan = {
        "version": "1.0",
        "game_title": gdd.get("title", "Visual Novel"),
        "genre": gdd.get("genre", "visual-novel"),
        "num_chapters": num_chapters,
        "estimated_scale": {
            "art_assets": sum(len(items) for items in art_manifest.values()),
            "audio_assets": sum(len(items) for items in audio_manifest.values()),
            "code_modules": sum(len(items) for items in code_manifest.values()),
            "data_files": len(data_manifest),
            "estimated_chars": 0,
            "estimated_code_lines": 0,
        },
        "art": art_manifest,
        "audio": audio_manifest,
        "code": code_manifest,
        "data": data_manifest,
        "world_bible_path": "world_bible.json",
        "integration_targets": {
            "single_entry_point": "index.html",
            "single_main_module": "src/main.ts",
            "asset_paths": {
                "backgrounds": "public/assets/backgrounds/",
                "characters": "public/assets/characters/",
                "cg": "public/assets/cg/",
                "audio": "public/assets/audio/",
            },
        },
    }

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")

    return plan


def _build_art_manifest(gdd: dict, bible: dict, chapter_gdds: list[dict]) -> dict:
    """Build the complete art asset manifest across all chapters.

    Per chapter, we generate:
    - N backgrounds (one per unique scene)
    - M character sprites (one neutral expression per character)
    - K CG illustrations (one per CG milestone in this chapter)
    """
    backgrounds = []
    characters = []
    cgs = []

    for ch in chapter_gdds:
        ch_id = ch.get("chapter_id", 1)
        ch_title = ch.get("chapter_title", f"Chapter {ch_id}")

        for scene in ch.get("scenes", [])[:4]:
            scene_id = scene.get("name", "unknown").lower().replace(" ", "_")
            scene_id = re.sub(r"[^a-z0-9_]", "", scene_id)
            backgrounds.append({
                "id": f"ch{ch_id}_{scene_id}",
                "chapter": ch_id,
                "scene_name": scene.get("name", "scene"),
                "scene_description": scene.get("description", scene.get("name", "scene")),
                "mood": scene.get("mood", "neutral"),
                "file_path": f"public/assets/backgrounds/ch{ch_id}_{scene_id}.png",
                "status": "pending",
            })

        for char in ch.get("character_roster", [])[:5]:
            char_id = char.get("name", "unknown").lower().replace(" ", "_")
            char_id = re.sub(r"[^a-z0-9_]", "", char_id)
            if not any(c["id"] == char_id for c in characters):
                characters.append({
                    "id": char_id,
                    "name": char.get("name", "Unknown"),
                    "visual_description": char.get("description", ""),
                    "expressions": ["neutral"],
                    "file_paths": {
                        "neutral": f"public/assets/characters/{char_id}_neutral.png",
                    },
                    "status": "pending",
                })

        for cg in ch.get("cg_milestones", []):
            cg_key = cg.get("cg_key", "unknown").lower().replace(" ", "_")
            cg_key = re.sub(r"[^a-z0-9_]", "", cg_key)
            cgs.append({
                "id": f"ch{ch_id}_{cg_key}",
                "chapter": ch_id,
                "cg_key": cg.get("cg_key", ""),
                "description": cg.get("description", ""),
                "file_path": f"public/assets/cg/ch{ch_id}_{cg_key}.png",
                "status": "pending",
            })

    return {
        "backgrounds": backgrounds,
        "characters": characters,
        "cg": cgs,
        "style_guide": bible.get("art_style", {}),
    }


def _build_audio_manifest(gdd: dict, bible: dict) -> dict:
    """Build audio asset manifest.

    - BGM: one track per mood across the whole game
    - SFX: standard VN SFX list
    """
    mood_guide = bible.get("music_mood", {}).get("mood_per_scene", {})
    bgm_tracks = [
        {"id": f"bgm_{mood}", "mood": mood, "file_path": f"public/assets/audio/bgm_{mood}.mp3", "status": "pending"}
        for mood in mood_guide.keys()
    ]
    if not bgm_tracks:
        bgm_tracks = [
            {"id": "bgm_ambient", "mood": "ambient", "file_path": "public/assets/audio/bgm_ambient.mp3", "status": "pending"},
        ]

    sfx_list = [
        {"id": "sfx_click", "event": "ui_click", "file_path": "public/assets/audio/sfx_click.wav", "status": "pending"},
        {"id": "sfx_choice", "event": "choice_select", "file_path": "public/assets/audio/sfx_choice.wav", "status": "pending"},
        {"id": "sfx_transition", "event": "scene_transition", "file_path": "public/assets/audio/sfx_transition.wav", "status": "pending"},
        {"id": "sfx_alert", "event": "important_event", "file_path": "public/assets/audio/sfx_alert.wav", "status": "pending"},
    ]

    return {
        "bgm": bgm_tracks,
        "sfx": sfx_list,
    }


def _build_code_manifest(gdd: dict, bible: dict, num_chapters: int) -> dict:
    """Build the code module manifest.

    Every TS file the game needs:
    - Engine + systems (one set, reused across chapters)
    - Scenes (BootScene, TitleScene, MenuScene, NovelScene, ChapterMenuScene, EndingScene)
    - Main entry
    """
    return {
        "config": [
            {"id": "game_config", "file_path": "src/game/config.ts", "status": "pending"},
        ],
        "systems": [
            {"id": "branching_engine", "file_path": "src/game/systems/BranchingEngine.ts", "status": "pending"},
            {"id": "stat_system", "file_path": "src/game/systems/StatSystem.ts", "status": "pending"},
            {"id": "choice_system", "file_path": "src/game/systems/ChoiceSystem.ts", "status": "pending"},
            {"id": "dialogue_system", "file_path": "src/game/systems/DialogueSystem.ts", "status": "pending"},
            {"id": "save_system", "file_path": "src/game/systems/SaveSystem.ts", "status": "pending"},
        ],
        "scenes": [
            {"id": "boot_scene", "file_path": "src/game/scenes/BootScene.ts", "status": "pending"},
            {"id": "title_scene", "file_path": "src/game/scenes/TitleScene.ts", "status": "pending"},
            {"id": "menu_scene", "file_path": "src/game/scenes/MenuScene.ts", "status": "pending"},
            {"id": "chapter_menu_scene", "file_path": "src/game/scenes/ChapterMenuScene.ts", "status": "pending"},
            {"id": "novel_scene", "file_path": "src/game/scenes/NovelScene.ts", "status": "pending"},
            {"id": "ending_scene", "file_path": "src/game/scenes/EndingScene.ts", "status": "pending"},
        ],
        "main": [
            {"id": "main", "file_path": "src/main.ts", "status": "pending"},
        ],
        "entry": [
            {"id": "index_html", "file_path": "index.html", "status": "pending"},
            {"id": "package_json", "file_path": "package.json", "status": "pending"},
            {"id": "tsconfig", "file_path": "tsconfig.json", "status": "pending"},
            {"id": "vite_config", "file_path": "vite.config.ts", "status": "pending"},
        ],
    }


def _build_data_manifest(gdd: dict, bible: dict, num_chapters: int) -> list[dict]:
    """Build the data file manifest.

    Data files per game (not per chapter):
    - world_bible.json (shared)
    - cross_chapter.json (save state schema)
    - branching.json (all chapter nodes)
    - dialogue.json (all chapter dialogue)
    - stats.json (stat definitions)
    - endings.json (all endings across chapters)
    """
    return [
        {"id": "world_bible", "file_path": "public/assets/data/world_bible.json", "status": "pending"},
        {"id": "cross_chapter", "file_path": "public/assets/data/cross_chapter.json", "status": "pending"},
        {"id": "branching", "file_path": "public/assets/data/branching.json", "status": "pending"},
        {"id": "dialogue", "file_path": "public/assets/data/dialogue.json", "status": "pending"},
        {"id": "stats", "file_path": "public/assets/data/stats.json", "status": "pending"},
        {"id": "endings", "file_path": "public/assets/data/endings.json", "status": "pending"},
    ]


def update_plan_status(plan: dict, category: str, item_id: str, status: str) -> dict:
    """Update an item's status in the plan (called by generation tracks)."""
    if category in plan:
        items = plan[category]
        if isinstance(items, list):
            for item in items:
                if item.get("id") == item_id:
                    item["status"] = status
                    break
        elif isinstance(items, dict):
            for sub_list in items.values():
                if isinstance(sub_list, list):
                    for item in sub_list:
                        if item.get("id") == item_id:
                            item["status"] = status
                            break
    return plan


def plan_completion_summary(plan: dict) -> dict:
    """Check how much of the plan has been fulfilled."""
    counts = {"total": 0, "pending": 0, "in_progress": 0, "completed": 0, "failed": 0}

    def _count(items):
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and "status" in item:
                    counts["total"] += 1
                    status = item.get("status", "pending")
                    counts[status] = counts.get(status, 0) + 1
        elif isinstance(items, dict):
            for v in items.values():
                _count(v)

    for category in ("art", "audio", "code", "data"):
        _count(plan.get(category, {}))

    pct = (counts["completed"] / counts["total"] * 100) if counts["total"] > 0 else 0
    return {
        **counts,
        "completion_pct": round(pct, 1),
        "is_complete": counts["pending"] == 0 and counts["in_progress"] == 0,
    }

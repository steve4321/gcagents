"""Story IR (Intermediate Representation) — engine-agnostic story format.

The story content is the most valuable asset and must outlive any engine
choice. This module defines a JSON-based story format that can be:
- Generated once by the LLM
- Output to RenJS YAML (current pipeline)
- Output to Godot/Dialogic format (future)
- Output to WeChat Mini Program data (future)
- Output to PDF/manuscript for editing

IR structure:
{
  "meta": {title, version, ...},
  "characters": {id: {name, description, default_expression}},
  "variables": {stat_name: {initial, min, max, description}},
  "scenes": {
    scene_id: {
      "chapter": 1,
      "background": "ch1_office",
      "music": "bgm_tense",
      "events": [
        {"type": "show", "what": "li_wei", "expression": "neutral", "position": "center"},
        {"type": "say", "speaker": "li_wei", "expression": "neutral", "text": "..."},
        {"type": "choice", "options": [
          {"text": "...", "effects": {"morality": 5}, "target": "ch1_office_a"},
        ]},
        {"type": "play", "track": "bgm_tense"},
        {"type": "set", "variable": "met_li_wei", "value": true},
        {"type": "modify", "variable": "morality", "delta": 5},
        {"type": "show_cg", "cg_id": "cg_office_meeting"},
        {"type": "jump", "target": "ch1_office_a"},
        {"type": "if", "condition": "morality >= 80", "then_jump": "good_ending"},
        {"type": "end"}
      ]
    }
  },
  "endings": {ending_id: {name, condition, epilogue}},
}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


STORY_IR_VERSION = "1.0"


def init_story_ir(meta: dict, bible: dict) -> dict:
    """Create an empty story IR from the World Bible."""
    characters: dict[str, Any] = {}
    for c in bible.get("characters", []):
        cid = c.get("id", "unknown")
        characters[cid] = {
            "name": c.get("name", cid),
            "description": c.get("description", ""),
            "default_expression": "neutral",
        }

    variables: dict[str, Any] = {}
    for s in bible.get("stats", []):
        sname = s.get("name", "unknown")
        rng = s.get("range", [0, 100])
        variables[sname] = {
            "initial": rng[0] if len(rng) > 0 else 0,
            "min": rng[0] if len(rng) > 0 else 0,
            "max": rng[1] if len(rng) > 1 else 100,
            "description": s.get("description", ""),
        }

    return {
        "version": STORY_IR_VERSION,
        "meta": {
            "title": meta.get("title", "Visual Novel"),
            "genre": meta.get("genre", "visual-novel"),
            "chapters": meta.get("num_chapters", 1),
            "language": "zh-CN",
        },
        "characters": characters,
        "variables": variables,
        "scenes": {},
        "endings": {},
    }


def build_ir_generation_prompt(
    chapter_gdd: dict,
    world_bible: dict,
    chapter_index: int,
    total_chapters: int,
    available_assets: dict,
) -> str:
    """Build the LLM prompt for generating one chapter's Story IR.

    The output is a JSON object matching the IR schema, NOT engine-specific
    YAML. This is the only thing the LLM writes per chapter.
    """
    ch_id = chapter_gdd.get("chapter_id", chapter_index + 1)
    ch_title = chapter_gdd.get("chapter_title", f"Chapter {ch_id}")
    is_last = ch_id == total_chapters

    char_schema = json.dumps(
        {c["id"]: c["name"] for c in world_bible.get("characters", [])},
        ensure_ascii=False,
    )
    var_schema = json.dumps(
        {s["name"]: {"min": s.get("range", [0, 100])[0],
                     "max": s.get("range", [0, 100])[1] if len(s.get("range", [0, 100])) > 1 else 100}
         for s in world_bible.get("stats", [])},
        ensure_ascii=False,
    )
    bg_ids = json.dumps(available_assets.get("backgrounds", []), ensure_ascii=False)
    cg_ids = json.dumps(available_assets.get("cgs", []), ensure_ascii=False)

    return f"""You are writing Chapter {ch_id} of {total_chapters} of a Visual Novel in STORY IR format.

The IR (Intermediate Representation) is a JSON object that is ENGINE-AGNOSTIC.
Adapters will translate it to RenJS YAML, Godot Dialogic, Mini Program, etc.
You write ONCE in IR, and the same story works on all engines.

=== GAME BIBLE (canon) ===
Title: {world_bible.get('title')}
Setting: {world_bible.get('world', {}).get('setting', '')[:300]}

Characters (use these EXACT IDs):
{char_schema}

Variables/stats (use these EXACT names):
{var_schema}

=== CHAPTER INSTRUCTIONS ===
Chapter title: {ch_title}
Synopsis: {chapter_gdd.get('synopsis', '')[:500]}
Writing directive: {chapter_gdd.get('writing_directive', '')[:400]}

=== AVAILABLE ASSETS ===
Backgrounds (use these EXACT IDs in "background" field):
{bg_ids}
CGs (use these EXACT IDs in show_cg events):
{cg_ids}

=== STORY IR SCHEMA (return JSON, not YAML) ===
{{
  "chapter_id": {ch_id},
  "scenes": {{
    "<scene_id>": {{
      "background": "<background_id_from_assets>",
      "music": "<bgm_id or null>",
      "events": [
        {{"type": "show", "what": "<character_id>", "expression": "neutral", "position": "center"}},
        {{"type": "say", "speaker": "<character_id>", "expression": "neutral",
          "text": "<Chinese dialogue, 200-400 characters, literary prose>"}},
        {{"type": "choice", "options": [
          {{"text": "<choice text>", "effects": {{"<stat_name>": <delta>}}, "target": "<scene_id>"}},
          ...
        ]}},
        {{"type": "play", "track": "<bgm_id>"}},
        {{"type": "set", "variable": "<name>", "value": <value>}},
        {{"type": "modify", "variable": "<stat_name>", "delta": <number>}},
        {{"type": "hide", "what": "<character_id>"}},
        {{"type": "show_cg", "cg_id": "<cg_id>"}},
        {{"type": "jump", "target": "<scene_id>"}},
        {{"type": "if", "condition": "<var> >= <value>", "then_jump": "<scene_id>",
          "else_jump": "<scene_id>"}},
        {{"type": "end"}}
      ]
    }},
    ...
  }},
  "endings": {{
    "<ending_id>": {{"name": "<Chinese name>", "epilogue": "<short Chinese epilogue text>"}}
  }}
}}

CRITICAL RULES:
1. Use ONLY character IDs from the bible character list
2. Use ONLY stat/variable names from the bible variable list
3. Use ONLY background IDs from the available assets list
4. Generate 25-40 scenes per chapter
5. Each "say" event text MUST be 200-400 Chinese characters of literary prose
6. Include 3-5 meaningful choices that modify stats
7. {('End the chapter with a jump to the first scene of the next chapter' if not is_last else 'End with 2-3 distinct endings based on stat values')}
8. The first scene ID MUST be "ch<{ch_id}>_start"
9. Output ONLY the JSON object, no markdown fences, no commentary

Output the JSON starting with {{ and ending with }}"""


def load_ir(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_ir(ir: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ir, indent=2, ensure_ascii=False), encoding="utf-8")


def merge_chapter_irs(chapter_irs: list[dict]) -> dict:
    """Merge multiple chapter IRs into a single unified IR.

    Chapter scenes are kept separate (namespaced by chapter id).
    Variables and characters come from the first chapter.
    Endings are collected from all chapters.
    """
    if not chapter_irs:
        return {}

    merged = {
        "version": STORY_IR_VERSION,
        "meta": dict(chapter_irs[0].get("meta", {})),
        "characters": dict(chapter_irs[0].get("characters", {})),
        "variables": dict(chapter_irs[0].get("variables", {})),
        "scenes": {},
        "endings": {},
    }
    merged["meta"]["chapters"] = len(chapter_irs)

    for ch_ir in chapter_irs:
        ch_id = ch_ir.get("chapter_id", 1)
        for scene_id, scene in ch_ir.get("scenes", {}).items():
            namespaced_id = f"ch{ch_id}_{scene_id}" if not str(scene_id).startswith(f"ch{ch_id}_") else scene_id
            merged["scenes"][namespaced_id] = {
                **scene,
                "chapter_id": ch_id,
            }
        for ending_id, ending in ch_ir.get("endings", {}).items():
            merged["endings"][ending_id] = ending

    return merged


def validate_ir(ir: dict) -> list[str]:
    """Validate an IR against the schema. Returns list of errors."""
    errors: list[str] = []
    if "version" not in ir:
        errors.append("Missing 'version' field")
    if "scenes" not in ir or not isinstance(ir["scenes"], dict):
        errors.append("Missing or invalid 'scenes' field")
    return errors

"""RenJS Adapter: convert Story IR → RenJS YAML.

This is the ONLY engine-specific code path right now. When we add Godot
or Mini Program support, we create godot_adapter.py / miniprogram_adapter.py
with similar structure. The IR stays the same; only the adapter changes.
"""
from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

_MOOD_FALLBACK = {
    "tense": "bgm_tense", "tension": "bgm_tense", "suspense": "bgm_tense",
    "alarm": "bgm_tense", "dark": "bgm_tense", "chase": "bgm_tense",
    "hack": "bgm_tense", "action": "bgm_tense", "sneaky": "bgm_tense",
    "escape": "bgm_tense", "paranoia": "bgm_tense",
    "romantic": "bgm_romantic", "love": "bgm_romantic", "warm": "bgm_romantic",
    "triumphant": "bgm_triumphant", "victory": "bgm_triumphant", "triumph": "bgm_triumphant",
    "epic": "bgm_triumphant", "confrontation": "bgm_triumphant",
    "success": "bgm_triumphant", "rise": "bgm_triumphant",
    "melancholic": "bgm_melancholic", "sad": "bgm_melancholic", "sorrow": "bgm_melancholic",
    "sacrifice": "bgm_melancholic", "nightmare": "bgm_melancholic",
    "credits": "bgm_melancholic",
    "hopeful": "bgm_hopeful", "hope": "bgm_hopeful", "bright": "bgm_hopeful",
    "departure": "bgm_hopeful", "close": "bgm_hopeful",
    "ambient": "bgm_hopeful", "city": "bgm_hopeful", "piano": "bgm_hopeful",
    "bgm": "bgm_tense",
}


def ir_to_renjs_yaml(ir: dict, valid_music_ids: list[str] | None = None) -> str:
    """Convert a Story IR into RenJS Story.yaml.

    The first scene is always named 'start' (RenJS's required entry point).
    Other scene names are taken from the IR but prefixed with 'ch<N>_'
    to be chapter-namespaced.

    Args:
        ir: The unified story IR (from merge_chapter_irs).
        valid_music_ids: List of BGM IDs defined in Setup.yaml. Play events
            referencing unknown tracks will be remapped to the closest match.
    """
    if valid_music_ids is None:
        valid_music_ids = []

    lines: list[str] = []
    first_scene = True
    scene_renames: dict[str, str] = {}

    for scene_id, scene in ir.get("scenes", {}).items():
        if first_scene:
            renjs_scene_id = "start"
        else:
            renjs_scene_id = scene_id
        scene_renames[scene_id] = renjs_scene_id
        first_scene = False
        lines.append(f"{renjs_scene_id}:")
        events = scene.get("events", [])
        if not events:
            lines.append("  - narrator says: ...")
            continue

        background = scene.get("background")
        music = scene.get("music")

        first_event = True
        prev_was_choice = False
        for event in events:
            indent = "  "
            if first_event and background:
                lines.append(f'  - show {background}: WITH FADE CONTINUE')
                first_event = False
            if first_event and music and event["type"] != "play":
                lines.append(f'  - play {music}:')
                first_event = False
            if first_event and event["type"] not in ("play",):
                first_event = False

            if event.get("type") == "jump" and prev_was_choice:
                prev_was_choice = event.get("type") == "choice"
                continue

            lines.extend(_event_to_renjs(event, indent, valid_music_ids))
            prev_was_choice = event.get("type") == "choice"
        lines.append("")

    if ir.get("endings"):
        emitted_ids = set(scene_renames.values())
        lines.append("# === Endings ===")
        for ending_id, ending in ir.get("endings", {}).items():
            if ending_id in emitted_ids:
                continue
            lines.append(f"{ending_id}:")
            lines.append(f'  - narrator says: {ending.get("epilogue", "...")}')
            lines.append(f"  - end:")
            lines.append("")

    all_scene_names = _collect_scene_names(lines)
    if all_scene_names:
        lines = _fix_undefined_scene_refs(lines, all_scene_names)

    return "\n".join(lines)


def _collect_scene_names(lines: list[str]) -> set[str]:
    """Extract all top-level scene names from generated YAML lines."""
    names = set()
    for line in lines:
        stripped = line.strip()
        if stripped.endswith(":") and not stripped.startswith("-") and not stripped.startswith("#"):
            candidate = stripped.rstrip(":").strip()
            if candidate and " " not in candidate:
                names.add(candidate)
    return names


def _fix_undefined_scene_refs(lines: list[str], all_scene_names: set[str]) -> list[str]:
    """Replace scene: targets that don't resolve to any defined scene."""
    fixed = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- scene:"):
            target = stripped.split("scene:", 1)[1].strip()
            if target and target not in all_scene_names:
                matches = difflib.get_close_matches(target, all_scene_names, n=1, cutoff=0.3)
                fallback = matches[0] if matches else (list(all_scene_names)[0] if all_scene_names else "start")
                line = line.replace(target, fallback)
        fixed.append(line)
    return fixed


def _event_to_renjs(event: dict, indent: str = "  ",
                    valid_music_ids: list[str] | None = None) -> list[str]:
    """Convert a single IR event to RenJS action lines."""
    etype = event.get("type")

    if etype == "show":
        what = event.get("what", "")
        expr = event.get("expression", "neutral")
        pos = event.get("position", "CENTER")
        return [f"{indent}- show {what}: {expr} AT {pos} WITH FADE"]

    if etype == "say":
        speaker = event.get("speaker") or "narrator"
        if not speaker or speaker == "None":
            speaker = "narrator"
        expr = event.get("expression", "")
        if expr == "neutral":
            expr = ""
        text = event.get("text", "")
        expr_part = f" {expr}" if expr else ""
        return [f"{indent}- {speaker} says{expr_part}: {text}"]

    if etype == "choice":
        lines = [f"{indent}- choice:"]
        for opt in event.get("options", []):
            opt_text = opt.get("text", "")
            lines.append(f'{indent}    - "{opt_text}":')
            effects = opt.get("effects", {})
            for var, delta in effects.items():
                if delta != 0:
                    lines.append(f"{indent}        - modify {var}: {delta}")
            target = opt.get("target")
            if target:
                lines.append(f"{indent}        - scene: {target}")
        return lines

    if etype == "play":
        track = event.get("track", "")
        if valid_music_ids and track not in valid_music_ids:
            resolved = _resolve_music_fallback(track, valid_music_ids)
            track = resolved or (valid_music_ids[0] if valid_music_ids else track)
        return [f"{indent}- play {track}:"]

    if etype == "set":
        var = event.get("variable", "")
        val = event.get("value")
        return [f"{indent}- set {var}: {val}"]

    if etype == "modify":
        var = event.get("variable", "")
        delta = event.get("delta", 0)
        return [f"{indent}- modify {var}: {delta}"]

    if etype == "hide":
        what = event.get("what", "")
        return [f"{indent}- hide {what}:"]

    if etype == "show_cg":
        cg_id = event.get("cg_id", "")
        return [f"{indent}- show {cg_id}: WITH FADE"]

    if etype == "jump":
        target = event.get("target", "")
        return [f"{indent}- scene: {target}"]

    if etype == "if":
        cond = event.get("condition", "")
        then_jump = event.get("then_jump", "")
        else_jump = event.get("else_jump", "")
        lines = [f"{indent}- if {cond}:"]
        if then_jump:
            lines.append(f"{indent}    - scene: {then_jump}")
        if else_jump:
            lines.append(f"{indent}- else:")
            lines.append(f"{indent}    - scene: {else_jump}")
        return lines

    if etype == "end":
        return [f"{indent}- end:"]

    return [f"{indent}- narrator says: [unknown event type: {etype}]"]


def _resolve_music_fallback(track: str, valid_ids: list[str]) -> str | None:
    """Try to map an unknown track name to a valid BGM ID by mood keywords."""
    track_lower = track.lower()
    for mood_key, fallback_id in _MOOD_FALLBACK.items():
        if mood_key in track_lower and fallback_id in valid_ids:
            return fallback_id
    return None

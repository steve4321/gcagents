"""RenJS Adapter: convert Story IR → RenJS YAML.

This is the ONLY engine-specific code path right now. When we add Godot
or Mini Program support, we create godot_adapter.py / miniprogram_adapter.py
with similar structure. The IR stays the same; only the adapter changes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def ir_to_renjs_yaml(ir: dict) -> str:
    """Convert a Story IR into RenJS Story.yaml.

    IR scene IDs become RenJS scene names.
    IR events become RenJS actions:
      - show → "show <char>: <expr> AT <pos> [WITH FADE]"
      - say → "<char> says [expr]: <text>"
      - choice → "choice:" with indented options
      - play → "play <track>:"
      - set → "set <var>: <value>"
      - modify → "modify <var>: <delta>"
      - hide → "hide <what>:"
      - show_cg → "show cg <id>:" / "show_cg: <id>"
      - jump → "scene: <target>"
      - if → "if <cond>:" with nested actions
      - end → "end:"
    """
    lines: list[str] = []

    for scene_id, scene in ir.get("scenes", {}).items():
        lines.append(f"{scene_id}:")
        events = scene.get("events", [])
        if not events:
            lines.append("  - narrator says: ...")
            continue

        background = scene.get("background")
        music = scene.get("music")

        first_event = True
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
            lines.extend(_event_to_renjs(event, indent))
        lines.append("")

    if ir.get("endings"):
        lines.append("# === Endings ===")
        for ending_id, ending in ir.get("endings", {}).items():
            lines.append(f"{ending_id}:")
            lines.append(f'  - narrator says: {ending.get("epilogue", "...")}')
            lines.append(f"  - end:")
            lines.append("")

    return "\n".join(lines)


def _event_to_renjs(event: dict, indent: str = "  ") -> list[str]:
    """Convert a single IR event to RenJS action lines."""
    etype = event.get("type")

    if etype == "show":
        what = event.get("what", "")
        expr = event.get("expression", "neutral")
        pos = event.get("position", "CENTER")
        return [f"{indent}- show {what}: {expr} AT {pos} WITH FADE"]

    if etype == "say":
        speaker = event.get("speaker", "narrator")
        expr = event.get("expression", "")
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

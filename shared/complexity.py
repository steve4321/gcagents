"""Game complexity scoring — rejects trivially simple games at QA stage."""
from __future__ import annotations

from pathlib import Path

MIN_PASSING_SCORE = 0.35  # Below this, QA fails regardless of functional checks


def score_gdd(gdd: dict) -> tuple[float, list[str]]:
    """Score a GDD for complexity. Returns (score_0_to_1, list_of_issues)."""
    issues = []

    # --- Metrics ---
    mechanics = gdd.get("mechanics", {})
    if isinstance(mechanics, dict):
        mech_count = len(mechanics)
    elif isinstance(mechanics, list):
        mech_count = len(mechanics)
    else:
        mech_count = 0

    scenes = gdd.get("scenes", [])
    scene_count = len(scenes)

    entities = gdd.get("entities", [])
    entity_count = len(entities)

    has_progression = bool(gdd.get("progression"))
    has_balance = isinstance(gdd.get("balance"), dict) and len(gdd.get("balance", {})) >= 2
    has_win_condition = bool(gdd.get("win_condition"))

    ui_layout = gdd.get("ui_layout", {})
    hud_count = len(ui_layout.get("hud", [])) if isinstance(ui_layout, dict) else 0

    # --- Scoring (each 0-1, weighted) ---

    # Mechanics (weight 0.30): min 3, target 8+
    mech_score = min(mech_count / 8, 1.0)
    if mech_count < 3:
        issues.append(f"Only {mech_count} mechanics, minimum 3 required")

    # Scenes (weight 0.10): min 4, target 6
    scene_score = min(scene_count / 6, 1.0)
    if scene_count < 4:
        issues.append(f"Only {scene_count} scenes, minimum 4 required")

    # Entities (weight 0.20): min 2, target 5
    entity_score = min(entity_count / 5, 1.0)
    if entity_count < 2:
        issues.append(f"Only {entity_count} entity types, minimum 2 required")

    # Depth indicators (weight 0.25): progression + balance + win_condition + hud
    depth_signals = sum([has_progression, has_balance, has_win_condition, hud_count >= 3])
    depth_score = depth_signals / 4
    if depth_signals < 2:
        issues.append(f"Only {depth_signals}/4 depth signals (progression, balance, win_condition, HUD)")

    # Core loop (weight 0.15): min 3 steps, target 5+
    core_loop = gdd.get("core_loop", [])
    loop_score = min(len(core_loop) / 5, 1.0)
    if len(core_loop) < 3:
        issues.append(f"Core loop has only {len(core_loop)} steps, minimum 3")

    total = (mech_score * 0.30 + scene_score * 0.10 + entity_score * 0.20 +
             depth_score * 0.25 + loop_score * 0.15)

    if total < MIN_PASSING_SCORE:
        issues.append(f"Complexity score {total:.2f} below minimum {MIN_PASSING_SCORE}")

    return round(total, 2), issues


def score_code(game_dir: Path) -> tuple[float, dict]:
    """Score generated game code for complexity. Returns (score_0_to_1, metrics_dict)."""
    src_dir = game_dir / "src"
    if not src_dir.exists():
        return 0.0, {"error": "no src/ directory"}

    ts_files = list(src_dir.rglob("*.ts"))
    if not ts_files:
        return 0.0, {"error": "no .ts files"}

    total_lines = sum(f.read_text(encoding="utf-8", errors="replace").count("\n") for f in ts_files)

    # Read GameScene for detailed analysis
    game_scene_path = src_dir / "game" / "scenes" / "GameScene.ts"
    game_code = game_scene_path.read_text(encoding="utf-8", errors="replace") if game_scene_path.exists() else ""

    metrics = {
        "total_files": len(ts_files),
        "total_lines": total_lines,
        "game_scene_lines": game_code.count("\n"),
        "has_physics": "this.physics" in game_code,
        "has_collision": "collider" in game_code or "overlap" in game_code,
        "has_tween": "this.tweens" in game_code,
        "has_timer": "this.time.addEvent" in game_code or "setInterval" in game_code,
        "input_types": sum([
            "keyboard" in game_code.lower() or "cursors" in game_code.lower() or "wasd" in game_code.lower(),
            "pointerdown" in game_code or "pointermove" in game_code,
            "keydown" in game_code.lower() or "keyup" in game_code.lower(),
        ]),
        "scene_count": len(list((src_dir / "game" / "scenes").glob("*.ts"))) if (src_dir / "game" / "scenes").exists() else 0,
        "entity_count": len(list((src_dir / "game" / "entities").glob("*.ts"))) if (src_dir / "game" / "entities").exists() else 0,
        "has_update_loop": "update(" in game_code,
        "has_score_system": "score" in game_code.lower(),
        "has_level_system": "level" in game_code.lower(),
    }

    # Scoring
    file_score = min(metrics["total_files"] / 10, 1.0)
    line_score = min(total_lines / 1500, 1.0)
    feature_signals = sum([
        metrics["has_physics"], metrics["has_collision"], metrics["has_tween"],
        metrics["has_timer"], metrics["has_update_loop"], metrics["has_score_system"],
        metrics["has_level_system"],
    ])
    feature_score = feature_signals / 7
    input_score = min(metrics["input_types"] / 2, 1.0)
    scene_score = min(metrics["scene_count"] / 5, 1.0)

    total = (file_score * 0.15 + line_score * 0.20 + feature_score * 0.30 +
             input_score * 0.15 + scene_score * 0.20)

    metrics["complexity_score"] = round(total, 2)
    return round(total, 2), metrics

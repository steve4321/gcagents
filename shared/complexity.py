"""Game complexity scoring — rejects trivially simple games at QA stage."""

from __future__ import annotations

from pathlib import Path

MIN_PASSING_SCORE = 0.45  # Below this, QA fails regardless of functional checks


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

    # --- Commercial viability metrics ---
    monetization = gdd.get("monetization", {})
    if isinstance(monetization, dict):
        has_model = bool(monetization.get("model"))
        ad_count = len(monetization.get("ad_placement", []))
        iap_count = len(monetization.get("iap_tiers", []))
        retention_count = len(monetization.get("retention_hooks", []))
        engagement_count = len(monetization.get("engagement_mechanics", []))

        commercial_signals = sum(
            [
                has_model,
                ad_count >= 2,
                iap_count >= 1,
                retention_count >= 2,
                engagement_count >= 2,
            ]
        )
        commercial_score = commercial_signals / 5
        if commercial_signals < 2:
            issues.append(
                f"Only {commercial_signals}/5 commercial signals "
                "(model, ads, iap, retention, engagement)"
            )
    else:
        commercial_score = 0.0
        issues.append(
            "No structured monetization in GDD — must include model, ad_placement, "
            "iap_tiers, retention_hooks, engagement_mechanics"
        )

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
        issues.append(
            f"Only {depth_signals}/4 depth signals (progression, balance, win_condition, HUD)"
        )

    # Core loop (weight 0.15): min 3 steps, target 5+
    core_loop = gdd.get("core_loop", [])
    loop_score = min(len(core_loop) / 5, 1.0)
    if len(core_loop) < 3:
        issues.append(f"Core loop has only {len(core_loop)} steps, minimum 3")

    total = (
        mech_score * 0.25
        + scene_score * 0.05
        + entity_score * 0.15
        + depth_score * 0.20
        + loop_score * 0.15
        + commercial_score * 0.20
    )

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

    game_scene_path = src_dir / "game" / "scenes" / "GameScene.ts"
    novel_scene_path = src_dir / "game" / "scenes" / "NovelScene.ts"
    primary_scene = game_scene_path if game_scene_path.exists() else novel_scene_path
    game_code = (
        primary_scene.read_text(encoding="utf-8", errors="replace")
        if primary_scene.exists()
        else ""
    )

    metrics = {
        "total_files": len(ts_files),
        "total_lines": total_lines,
        "game_scene_lines": game_code.count("\n"),
        "has_physics": "this.physics" in game_code,
        "has_collision": "collider" in game_code or "overlap" in game_code,
        "has_tween": "this.tweens" in game_code,
        "has_timer": "this.time.addEvent" in game_code or "setInterval" in game_code,
        "input_types": sum(
            [
                "keyboard" in game_code.lower()
                or "cursors" in game_code.lower()
                or "wasd" in game_code.lower(),
                "pointerdown" in game_code or "pointermove" in game_code,
                "keydown" in game_code.lower() or "keyup" in game_code.lower(),
            ]
        ),
        "scene_count": len(list((src_dir / "game" / "scenes").glob("*.ts")))
        if (src_dir / "game" / "scenes").exists()
        else 0,
        "entity_count": len(list((src_dir / "game" / "entities").glob("*.ts")))
        if (src_dir / "game" / "entities").exists()
        else 0,
        "has_update_loop": "update(" in game_code,
        "has_score_system": "score" in game_code.lower(),
        "has_level_system": "level" in game_code.lower(),
    }

    file_score = min(metrics["total_files"] / 10, 1.0)
    line_score = min(total_lines / 1500, 1.0)
    feature_signals = sum(
        [
            metrics["has_physics"],
            metrics["has_collision"],
            metrics["has_tween"],
            metrics["has_timer"],
            metrics["has_update_loop"],
            metrics["has_score_system"],
            metrics["has_level_system"],
        ]
    )
    feature_score = feature_signals / 7
    input_score = min(metrics["input_types"] / 2, 1.0)
    scene_score = min(metrics["scene_count"] / 5, 1.0)

    base_total = (
        file_score * 0.15
        + line_score * 0.20
        + feature_score * 0.30
        + input_score * 0.15
        + scene_score * 0.20
    )

    vn_metrics = _score_vn_signals(src_dir, game_code)
    vn_signals = vn_metrics.pop("vn_signals_detected", False)
    vn_total = sum(vn_metrics.values()) if vn_signals else 0.0
    vn_cap = 0.20

    total = base_total + min(vn_total, vn_cap)

    metrics["vn_signals_detected"] = vn_signals
    for k, v in vn_metrics.items():
        metrics[k] = v

    metrics["complexity_score"] = round(total, 2)
    return round(total, 2), metrics


def _score_vn_signals(src_dir: Path, game_code: str) -> dict:
    """Read VN data files and game code, return per-signal bonus values.

    Keys are per-signal bonus values (0.0-0.10 each), plus a boolean
    ``vn_signals_detected`` indicating whether any VN data file was present.
    The total bonus is capped at 0.20 in the caller.
    """
    import json as _json

    data_dir = src_dir / "game" / "data"
    out: dict = {"vn_signals_detected": False}

    if not data_dir.exists():
        return out

    stat_count = 0
    character_count = 0
    min_expr_per_char = 99
    ending_count = 0
    branch_count = 0
    has_save_load = "SaveLoadSystem" in game_code
    has_localization = "LocalizationManager" in game_code

    stats_path = data_dir / "stats.json"
    if stats_path.exists():
        try:
            stats = _json.loads(stats_path.read_text(encoding="utf-8", errors="replace"))
            stat_count = len(stats.get("stats", []))
            out["vn_signals_detected"] = True
        except (ValueError, OSError):
            pass

    chars_path = data_dir / "characters.json"
    if chars_path.exists():
        try:
            chars = _json.loads(chars_path.read_text(encoding="utf-8", errors="replace"))
            char_list = chars.get("characters", [])
            character_count = len(char_list)
            for c in char_list:
                ev = c.get("expression_variants", []) if isinstance(c, dict) else []
                if isinstance(ev, list) and ev:
                    min_expr_per_char = min(min_expr_per_char, len(ev))
            if character_count > 0:
                out["vn_signals_detected"] = True
        except (ValueError, OSError):
            pass

    endings_path = data_dir / "endings.json"
    if endings_path.exists():
        try:
            endings = _json.loads(endings_path.read_text(encoding="utf-8", errors="replace"))
            ending_count = len(endings.get("endings", []))
            out["vn_signals_detected"] = True
        except (ValueError, OSError):
            pass

    branching_path = data_dir / "branching.json"
    if branching_path.exists():
        try:
            br = _json.loads(branching_path.read_text(encoding="utf-8", errors="replace"))
            branch_count = len(br.get("branching_tree", {}).get("nodes", {}))
            out["vn_signals_detected"] = True
        except (ValueError, OSError):
            pass

    out["vn_stat_count"] = 0.05 if stat_count >= 5 else 0.0
    out["vn_ending_count"] = 0.05 if ending_count >= 3 else 0.0
    out["vn_branch_count"] = 0.10 if branch_count >= 8 else 0.0
    out["vn_expression_per_char"] = 0.05 if min_expr_per_char >= 3 else 0.0
    out["vn_character_count"] = 0.05 if character_count >= 2 else 0.0
    out["vn_has_save_load"] = 0.05 if has_save_load else 0.0
    out["vn_has_localization"] = 0.05 if has_localization else 0.0

    return out

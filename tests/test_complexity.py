"""Tests for shared/complexity.py — game complexity scoring."""

from __future__ import annotations

from shared.complexity import MIN_PASSING_SCORE, score_code, score_gdd


def test_score_gdd_empty():
    score, issues = score_gdd({})
    assert score == 0.0
    assert len(issues) > 0


def test_score_gdd_minimal():
    gdd = {
        "mechanics": {"m1": {}, "m2": {}, "m3": {}},
        "scenes": ["s1", "s2", "s3", "s4"],
        "entities": ["e1", "e2"],
        "progression": True,
        "balance": {"min": 1, "max": 10},
        "win_condition": "score > 100",
        "core_loop": ["a", "b", "c"],
        "ui_layout": {"hud": ["h1", "h2", "h3"]},
    }
    score, issues = score_gdd(gdd)
    assert score >= MIN_PASSING_SCORE


def test_score_gdd_mechanics_as_list():
    gdd = {"mechanics": ["a", "b", "c", "d", "e", "f", "g", "h"]}
    score, issues = score_gdd(gdd)
    assert score > 0


def test_score_gdd_mechanics_dict():
    gdd = {"mechanics": {"a": {}, "b": {}, "c": {}}}
    score, issues = score_gdd(gdd)
    assert score > 0


def test_score_gdd_no_mechanics():
    gdd = {"mechanics": {}}
    score, issues = score_gdd(gdd)
    assert any("mechanics" in i.lower() for i in issues)


def test_score_gdd_too_few_scenes():
    gdd = {
        "mechanics": {"m1": {}, "m2": {}, "m3": {}},
        "scenes": ["s1", "s2"],
    }
    score, issues = score_gdd(gdd)
    assert any("scenes" in i.lower() for i in issues)


def test_score_gdd_too_few_entities():
    gdd = {
        "mechanics": {"m1": {}, "m2": {}, "m3": {}},
        "scenes": ["s1", "s2", "s3", "s4"],
        "entities": ["e1"],
    }
    score, issues = score_gdd(gdd)
    assert any("entity" in i.lower() for i in issues)


def test_score_gdd_few_depth_signals():
    gdd = {
        "mechanics": {"m1": {}, "m2": {}, "m3": {}},
        "scenes": ["s1", "s2", "s3", "s4"],
        "entities": ["e1", "e2"],
    }
    score, issues = score_gdd(gdd)
    assert any("depth" in i.lower() for i in issues)


def test_score_gdd_short_core_loop():
    gdd = {
        "mechanics": {"m1": {}, "m2": {}, "m3": {}},
        "scenes": ["s1", "s2", "s3", "s4"],
        "entities": ["e1", "e2"],
        "core_loop": ["a"],
    }
    score, issues = score_gdd(gdd)
    assert any("core loop" in i.lower() for i in issues)


def test_score_code_no_src(tmp_path):
    score, metrics = score_code(tmp_path)
    assert score == 0.0
    assert "error" in metrics


def test_score_code_empty_src(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    score, metrics = score_code(tmp_path)
    assert score == 0.0
    assert "error" in metrics


def test_score_code_with_files(tmp_path):
    src = tmp_path / "src" / "game" / "scenes"
    src.mkdir(parents=True)
    (src / "GameScene.ts").write_text("""
export class GameScene extends Phaser.Scene {
    update() {
        this.physics.add.collider(player, platforms);
        this.tweens.add({ targets: player, x: 100 });
        this.time.addEvent({ delay: 1000 });
        score += 1;
        level = 1;
        this.input.keyboard.on('keydown');
        this.input.on('pointerdown');
    }
}
""")
    score, metrics = score_code(tmp_path)
    assert score > 0
    assert metrics["total_files"] == 1
    assert metrics["has_physics"] is True
    assert metrics["has_collision"] is True
    assert metrics["has_tween"] is True
    assert metrics["has_timer"] is True
    assert metrics["has_update_loop"] is True
    assert metrics["has_score_system"] is True
    assert metrics["has_level_system"] is True

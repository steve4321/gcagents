"""Tests for shared/quality_gate.py — 6-check hard-veto quality gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.quality_gate import (
    COMPLEXITY_THRESHOLD,
    GENRE_MECHANIC_PATTERNS,
    GateReport,
    GateResult,
    _check_asset_existence,
    _check_complexity,
    _check_mechanic_completeness,
    _normalize_genre,
    run_quality_gate,
)


TD_SOURCE_FILES = {
    "src/main.ts": "export function bootGame() { console.log('boot'); }",
    "src/game/config.ts": "export const __GAME_CONFIG__ = { canvas: { width: 800 } };",
    "src/game/entities/Tower.ts": """
        export class TowerFactory {
            placeTower(col: number, row: number, type: string): boolean {
                return true;
            }
        }
    """,
    "src/game/entities/Enemy.ts": """
        export class Enemy {
            followPath(waypoint: { x: number; y: number }): void {
                this.x += 1;
            }
        }
    """,
    "src/game/entities/Projectile.ts": """
        export class Projectile {
            shootAt(target: { x: number; y: number }): void {
                this.dealDamage(10);
            }
        }
    """,
    "src/game/entities/Base.ts": """
        export class Base {
            takeDamage(amount: number): void {
                this.health -= amount;
            }
        }
    """,
    "src/game/systems/WaveManager.ts": """
        export class WaveManager {
            startNextWave(): boolean { return true; }
        }
    """,
    "src/game/systems/EconomyManager.ts": """
        export class EconomyManager {
            addGold(n: number): void {}
        }
    """,
    "src/game/systems/TowerUpgrade.ts": """
        export function upgradeTower(col: number, row: number): boolean {
            return true;
        }
    """,
    "src/game/scenes/GameScene.ts": "export class GameScene {}",
}

TD_GDD = {
    "title": "Test TD",
    "genre": "tower-defense",
    "mechanics": ["tower_placement", "path", "shooting", "waves"],
    "scenes": ["Boot", "Menu", "Game", "GameOver"],
    "entities": ["Tower", "Enemy", "Projectile", "Base"],
    "progression": "10 waves with increasing difficulty",
    "balance": {"start_gold": 100, "tower_cost": 50},
    "win_condition": "Defeat all 10 waves",
    "core_loop": ["place tower", "start wave", "shoot enemies", "earn gold", "upgrade"],
    "ui_layout": {"hud": ["gold", "hp", "wave", "tower_menu"]},
    "monetization": {
        "model": "ads",
        "ad_placement": ["between waves", "on game over"],
        "iap_tiers": [{"name": "gold_pack", "price": 0.99}],
        "retention_hooks": ["daily_reward", "achievements"],
        "engagement_mechanics": ["leaderboard", "challenges"],
    },
}


def _make_td_project(tmp_path: Path) -> Path:
    game_dir = tmp_path / "test-td"
    game_dir.mkdir()
    for rel_path, content in TD_SOURCE_FILES.items():
        full_path = game_dir / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
    return game_dir


class TestDataclasses:
    def test_gate_result_defaults(self):
        r = GateResult("test", "hard_veto", True)
        assert r.name == "test"
        assert r.severity == "hard_veto"
        assert r.passed is True
        assert r.evidence == ""

    def test_gate_report_empty_passes(self):
        report = GateReport()
        assert report.overall_passed is True
        assert report.hard_failures == []
        assert report.soft_warnings == []

    def test_gate_report_hard_failure_fails(self):
        report = GateReport(results=[
            GateResult("mech", "hard_veto", True),
            GateResult("asset", "hard_veto", False, "missing.png"),
        ])
        assert report.overall_passed is False
        assert len(report.hard_failures) == 1
        assert report.hard_failures[0].name == "asset"
        assert report.soft_warnings == []

    def test_gate_report_soft_warning_passes(self):
        report = GateReport(results=[
            GateResult("mech", "hard_veto", True),
            GateResult("complexity", "soft_warn", False, "low score"),
        ])
        assert report.overall_passed is True
        assert report.hard_failures == []
        assert len(report.soft_warnings) == 1

    def test_gate_report_to_dict(self):
        report = GateReport(results=[
            GateResult("a", "hard_veto", True, "ok"),
            GateResult("b", "soft_warn", False, "low"),
        ])
        d = report.to_dict()
        assert d["overall_passed"] is True
        assert d["hard_failures"] == []
        assert len(d["soft_warnings"]) == 1
        assert d["soft_warnings"][0]["name"] == "b"
        assert len(d["results"]) == 2


class TestGenreNormalization:
    def test_kebab_case(self):
        assert _normalize_genre("tower-defense") == "tower-defense"

    def test_underscore_to_hyphen(self):
        assert _normalize_genre("tower_defense") == "tower-defense"

    def test_space_to_hyphen(self):
        assert _normalize_genre("Tower Defense") == "tower-defense"

    def test_uppercase(self):
        assert _normalize_genre("TOWER DEFENSE") == "tower-defense"


class TestMechanicCompleteness:
    def test_all_mechanics_present(self, tmp_path):
        game_dir = _make_td_project(tmp_path)
        result = _check_mechanic_completeness(game_dir, TD_GDD)
        assert result.severity == "hard_veto"
        assert result.passed is True
        assert "mechanics found" in result.evidence

    def test_missing_mechanics(self, tmp_path):
        game_dir = _make_td_project(tmp_path)
        (game_dir / "src/game/systems/WaveManager.ts").unlink()
        result = _check_mechanic_completeness(game_dir, TD_GDD)
        assert result.passed is False
        assert "waves" in result.evidence

    def test_no_source_directory(self, tmp_path):
        game_dir = tmp_path / "empty"
        game_dir.mkdir()
        result = _check_mechanic_completeness(game_dir, TD_GDD)
        assert result.passed is False
        assert "No TypeScript" in result.evidence

    def test_unknown_genre_passes(self, tmp_path):
        game_dir = _make_td_project(tmp_path)
        result = _check_mechanic_completeness(game_dir, {"genre": "racing"})
        assert result.passed is True
        assert "No mechanic patterns" in result.evidence

    def test_all_required_keys_covered(self):
        expected = {
            "tower_placement",
            "enemy_path",
            "shooting",
            "waves",
            "economy",
            "base_defense",
            "upgrade",
        }
        assert set(GENRE_MECHANIC_PATTERNS["tower-defense"].keys()) == expected


class TestAssetExistence:
    def test_no_assets_referenced(self, tmp_path):
        game_dir = _make_td_project(tmp_path)
        result = _check_asset_existence(game_dir)
        assert result.passed is True
        assert "No external assets" in result.evidence

    def test_existing_asset_in_public(self, tmp_path):
        game_dir = _make_td_project(tmp_path)
        asset = game_dir / "public" / "assets" / "tower.png"
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_bytes(b"\x89PNG")

        ts_path = game_dir / "src" / "game" / "scenes" / "BootScene.ts"
        ts_path.write_text(
            "this.load.image('tower', 'assets/tower.png');", encoding="utf-8"
        )
        result = _check_asset_existence(game_dir)
        assert result.passed is True

    def test_missing_asset(self, tmp_path):
        game_dir = _make_td_project(tmp_path)
        ts_path = game_dir / "src" / "game" / "scenes" / "BootScene.ts"
        ts_path.write_text(
            "this.load.image('ghost', 'assets/ghost.png');", encoding="utf-8"
        )
        result = _check_asset_existence(game_dir)
        assert result.passed is False
        assert "ghost.png" in result.evidence

    def test_no_source(self, tmp_path):
        game_dir = tmp_path / "empty"
        game_dir.mkdir()
        result = _check_asset_existence(game_dir)
        assert result.passed is False


class TestComplexity:
    def test_complexity_returns_soft_warn(self, tmp_path):
        game_dir = _make_td_project(tmp_path)
        result = _check_complexity(TD_GDD, game_dir)
        assert result.severity == "soft_warn"
        assert isinstance(result.passed, bool)

    def test_empty_gdd_soft_warns(self, tmp_path):
        game_dir = _make_td_project(tmp_path)
        result = _check_complexity({}, game_dir)
        assert result.passed is False
        assert result.severity == "soft_warn"


class TestRunQualityGate:
    @pytest.mark.asyncio
    async def test_no_dist_falls_back(self, tmp_path):
        game_dir = _make_td_project(tmp_path)
        report = await run_quality_gate(game_dir, TD_GDD, mode="quick")
        assert isinstance(report, GateReport)
        assert any(r.name == "mechanic_completeness" for r in report.results)
        assert any(r.name == "asset_existence" for r in report.results)
        assert any(r.name == "complexity" for r in report.results)

    @pytest.mark.asyncio
    async def test_full_run_on_golden_template(self):
        template_dir = Path("game-templates/tower-defense")
        if not (template_dir / "src" / "main.ts").exists():
            pytest.skip("Golden template not built — skipping integration test")

        report = await run_quality_gate(template_dir, TD_GDD, mode="quick")
        mech_result = next(
            r for r in report.results if r.name == "mechanic_completeness"
        )
        assert mech_result.passed is True, (
            f"Golden template should pass mechanic check: {mech_result.evidence}"
        )

    @pytest.mark.asyncio
    async def test_static_check_failure_in_strict_mode(self, tmp_path):
        game_dir = _make_td_project(tmp_path)
        (game_dir / "src/game/systems/WaveManager.ts").unlink()
        (game_dir / "src/game/systems/EconomyManager.ts").unlink()

        report = await run_quality_gate(game_dir, TD_GDD, mode="strict")
        mech = next(r for r in report.results if r.name == "mechanic_completeness")
        assert mech.passed is False
        assert report.overall_passed is False


class TestThreshold:
    def test_threshold_is_above_minimum(self):
        from shared.complexity import MIN_PASSING_SCORE

        assert COMPLEXITY_THRESHOLD > MIN_PASSING_SCORE

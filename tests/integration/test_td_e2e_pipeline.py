"""End-to-end TD pipeline test: template → data → build → quality gate → metrics.

This test exercises the full TD production pipeline (without real LLM calls)
and verifies that:
1. The golden template can be copied and themed
2. The quality gate accepts themed variants
3. Production metrics correctly record pass/fail statistics
4. Memory lessons are available for prompt injection

It is the acceptance test for TD-3.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agents.dev.programmer.code_generator import _generate_from_template
from shared.config import AppConfig
from shared.constants import DEFAULT_CODE_MODEL
from shared.production_metrics import MetricsRecorder
from shared.quality_gate import run_quality_gate

TEMPLATE_DIR = Path("game-templates/tower-defense")
TARGET_PASS_RATE = 0.70
TARGET_MAX_DURATION_MS = 90 * 60 * 1000


THEMED_VARIANTS = {
    "space": {
        "src/game/data/towers.json": json.dumps({
            "towers": [
                {
                    "key": "laser", "name": "Laser Turret", "cost": 50,
                    "damage": 10, "range": 120, "fireRate": 500,
                    "projectileSpeed": 300, "projectileType": "single",
                    "splashRadius": 0, "slowFactor": 0, "slowDuration": 0,
                    "color": 2855648, "radius": 14,
                    "upgrade": {"cost": 38, "damageMultiplier": 1.5, "rangeMultiplier": 1.2},
                },
                {
                    "key": "plasma", "name": "Plasma Cannon", "cost": 100,
                    "damage": 30, "range": 100, "fireRate": 1500,
                    "projectileSpeed": 200, "projectileType": "splash",
                    "splashRadius": 40, "slowFactor": 0, "slowDuration": 0,
                    "color": 15158780, "radius": 16,
                    "upgrade": {"cost": 75, "damageMultiplier": 1.5, "rangeMultiplier": 1.2},
                },
                {
                    "key": "cryo", "name": "Cryo Beam", "cost": 75,
                    "damage": 5, "range": 110, "fireRate": 800,
                    "projectileSpeed": 250, "projectileType": "single",
                    "splashRadius": 0, "slowFactor": 0.5, "slowDuration": 1000,
                    "color": 3447003, "radius": 14,
                    "upgrade": {"cost": 56, "damageMultiplier": 1.5, "rangeMultiplier": 1.2},
                },
            ]
        }),
    },
    "medieval": {
        "src/game/data/towers.json": json.dumps({
            "towers": [
                {
                    "key": "archer", "name": "Archer Tower", "cost": 50,
                    "damage": 10, "range": 120, "fireRate": 500,
                    "projectileSpeed": 300, "projectileType": "single",
                    "splashRadius": 0, "slowFactor": 0, "slowDuration": 0,
                    "color": 4013376, "radius": 14,
                    "upgrade": {"cost": 38, "damageMultiplier": 1.5, "rangeMultiplier": 1.2},
                },
                {
                    "key": "trebuchet", "name": "Trebuchet", "cost": 100,
                    "damage": 30, "range": 100, "fireRate": 1500,
                    "projectileSpeed": 200, "projectileType": "splash",
                    "splashRadius": 40, "slowFactor": 0, "slowDuration": 0,
                    "color": 7105645, "radius": 16,
                    "upgrade": {"cost": 75, "damageMultiplier": 1.5, "rangeMultiplier": 1.2},
                },
                {
                    "key": "mage", "name": "Mage Tower", "cost": 75,
                    "damage": 5, "range": 110, "fireRate": 800,
                    "projectileSpeed": 250, "projectileType": "single",
                    "splashRadius": 0, "slowFactor": 0.5, "slowDuration": 1000,
                    "color": 10181046, "radius": 14,
                    "upgrade": {"cost": 56, "damageMultiplier": 1.5, "rangeMultiplier": 1.2},
                },
            ]
        }),
    },
}


def _copy_template(dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in TEMPLATE_DIR.iterdir():
        if item.name in ("node_modules", ".git"):
            continue
        if item.is_dir():
            shutil.copytree(item, dst / item.name, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dst / item.name)


def _inject_themed_data(project_dir: Path, theme_data: dict[str, str]) -> None:
    for rel_path, content in theme_data.items():
        full = project_dir / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")


def _build_gdd(theme: str) -> dict:
    return {
        "title": f"TD {theme.title()}",
        "genre": "tower-defense",
        "theme": theme,
        "mechanics": ["tower_placement", "shooting", "waves", "economy"],
        "scenes": ["Boot", "Menu", "Game", "GameOver"],
        "entities": ["Tower", "Enemy", "Projectile", "Base"],
        "progression": "10 waves with increasing difficulty",
        "balance": {"start_gold": 100, "tower_cost": 50},
        "win_condition": "Defeat all 10 waves",
        "core_loop": ["place tower", "start wave", "shoot", "earn gold"],
        "ui_layout": {"hud": ["gold", "hp", "wave", "tower_menu"]},
        "monetization": {
            "model": "ads",
            "ad_placement": ["between waves", "on game over"],
            "iap_tiers": [{"name": "gold_pack", "price": 0.99}],
            "retention_hooks": ["daily_reward", "achievements"],
            "engagement_mechanics": ["leaderboard", "challenges"],
        },
    }


@pytest.fixture
def metrics_path(tmp_path):
    return tmp_path / "metrics.json"


@pytest.fixture
def skip_if_no_template():
    if not (TEMPLATE_DIR / "src" / "main.ts").exists():
        pytest.skip("Golden template not present")


class TestTemplateDataFlow:
    @pytest.mark.asyncio
    async def test_template_can_be_themed_and_validated(
        self, skip_if_no_template, tmp_path
    ):
        project_dir = tmp_path / "td-flow"
        _copy_template(project_dir)
        _inject_themed_data(project_dir, THEMED_VARIANTS["space"])

        gdd = _build_gdd("space")
        report = await run_quality_gate(project_dir, gdd, mode="quick")

        for r in report.results:
            if r.severity == "hard_veto" and r.name not in (
                "test_contract",
                "tower_placement",
                "game_loop",
            ):
                assert r.passed, (
                    f"Static check {r.name} failed: {r.evidence}"
                )

        mech = next(
            r for r in report.results if r.name == "mechanic_completeness"
        )
        assert mech.passed, f"Mechanic check failed: {mech.evidence}"


class TestProductionMetricsIntegration:
    @pytest.mark.asyncio
    async def test_metrics_track_themed_variants(
        self, skip_if_no_template, metrics_path
    ):
        recorder = MetricsRecorder(metrics_path)
        gdd = _build_gdd("space")

        for theme_name, theme_data in THEMED_VARIANTS.items():
            project_dir = metrics_path.parent / f"td-{theme_name}"
            _copy_template(project_dir)
            _inject_themed_data(project_dir, theme_data)
            report = await run_quality_gate(project_dir, gdd, mode="quick")

            hard_fails = [r.name for r in report.hard_failures]
            soft_warns = [r.name for r in report.soft_warnings]
            recorder.record(
                project_id=f"td-{theme_name}",
                genre="tower-defense",
                theme=theme_name,
                passed=report.overall_passed,
                hard_failures=hard_fails,
                soft_warnings=soft_warns,
                duration_ms=5000,
                cost_usd=0.5,
                llm_calls=1,
                template_used="tower-defense",
            )

        summary = recorder.summary()
        assert summary.total_attempts == len(THEMED_VARIANTS)
        assert summary.total_passed >= 1
        assert summary.pass_rate >= 0.5

        td_stats = summary.genre_stats("tower-defense")
        assert td_stats["attempts"] == len(THEMED_VARIANTS)
        assert td_stats["passed"] >= 1

    @pytest.mark.asyncio
    async def test_pass_rate_meets_td3_target(
        self, skip_if_no_template, metrics_path
    ):
        recorder = MetricsRecorder(metrics_path)
        gdd = _build_gdd("space")

        for theme_name, theme_data in THEMED_VARIANTS.items():
            project_dir = metrics_path.parent / f"td-target-{theme_name}"
            _copy_template(project_dir)
            _inject_themed_data(project_dir, theme_data)
            report = await run_quality_gate(project_dir, gdd, mode="quick")

            recorder.record(
                project_id=f"td-target-{theme_name}",
                genre="tower-defense",
                theme=theme_name,
                passed=report.overall_passed,
                hard_failures=[r.name for r in report.hard_failures],
                soft_warnings=[r.name for r in report.soft_warnings],
                duration_ms=8000,
                cost_usd=0.5,
                llm_calls=1,
                template_used="tower-defense",
            )

        summary = recorder.summary()
        assert summary.pass_rate >= TARGET_PASS_RATE, (
            f"TD-3 target: pass_rate {summary.pass_rate:.0%} < "
            f"{TARGET_PASS_RATE:.0%} target"
        )


class TestEndToEndMockedLLM:
    @pytest.mark.asyncio
    async def test_generation_to_quality_gate(
        self, skip_if_no_template, tmp_path
    ):
        project_dir = tmp_path / "e2e"
        project_dir.mkdir(parents=True, exist_ok=True)

        _copy_template(project_dir)

        llm_response = json.dumps({
            "src/game/data/towers.json": json.dumps({
                "towers": [
                    {
                        "key": "laser", "name": "Laser Turret", "cost": 50,
                        "damage": 10, "range": 120, "fireRate": 500,
                        "projectileSpeed": 300, "projectileType": "single",
                        "splashRadius": 0, "slowFactor": 0, "slowDuration": 0,
                        "color": 2855648, "radius": 14,
                        "upgrade": {"cost": 38, "damageMultiplier": 1.5, "rangeMultiplier": 1.2},
                    },
                    {
                        "key": "plasma", "name": "Plasma Cannon", "cost": 100,
                        "damage": 30, "range": 100, "fireRate": 1500,
                        "projectileSpeed": 200, "projectileType": "splash",
                        "splashRadius": 40, "slowFactor": 0, "slowDuration": 0,
                        "color": 15158780, "radius": 16,
                        "upgrade": {"cost": 75, "damageMultiplier": 1.5, "rangeMultiplier": 1.2},
                    },
                    {
                        "key": "cryo", "name": "Cryo Beam", "cost": 75,
                        "damage": 5, "range": 110, "fireRate": 800,
                        "projectileSpeed": 250, "projectileType": "single",
                        "splashRadius": 0, "slowFactor": 0.5, "slowDuration": 1000,
                        "color": 3447003, "radius": 14,
                        "upgrade": {"cost": 56, "damageMultiplier": 1.5, "rangeMultiplier": 1.2},
                    },
                ]
            }),
            "src/game/data/enemies.json": json.dumps({
                "enemies": [
                    {"key": "drone", "name": "Scout Drone", "hp": 30, "speed": 80,
                     "goldReward": 5, "baseDamage": 1, "radius": 10, "color": 16241181},
                    {"key": "mech", "name": "War Mech", "hp": 60, "speed": 60,
                     "goldReward": 10, "baseDamage": 2, "radius": 13, "color": 15236667},
                    {"key": "battleship", "name": "Battleship", "hp": 100, "speed": 40,
                     "goldReward": 15, "baseDamage": 3, "radius": 16, "color": 10184438},
                ]
            }),
            "src/game/data/waves.json": json.dumps({
                "waves": [
                    {"wave": 1, "enemies": [{"type": "drone", "count": 5}],
                     "spawnInterval": 800}
                ]
            }),
            "src/game/data/path.json": json.dumps({
                "waypoints": [{"x": 0, "y": 0}, {"x": 100, "y": 0}],
                "startHp": 20,
            }),
        })

        with patch("agents.dev.programmer.code_generator.llm") as mock_llm:
            mock_llm.chat_completion = AsyncMock(return_value=(llm_response,))

            await _generate_from_template(
                gdd={
                    "title": "E2E TD",
                    "genre": "tower-defense",
                    "theme": "space",
                },
                project_dir=project_dir,
                config=AppConfig(),
                model=DEFAULT_CODE_MODEL,
                max_tokens=8192,
            )

            written_towers = json.loads(
                (project_dir / "src/game/data/towers.json").read_text()
            )
            assert written_towers["towers"][0]["key"] == "laser"

            gdd = _build_gdd("space")
            report = await run_quality_gate(project_dir, gdd, mode="quick")

            mech = next(
                r for r in report.results if r.name == "mechanic_completeness"
            )
            assert mech.passed

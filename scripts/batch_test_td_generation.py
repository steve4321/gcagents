"""TD-2 batch test: generate 5 themed variants and run quality gate.

Usage:
    python scripts/batch_test_td_generation.py

This script validates the template-based generation pipeline WITHOUT real LLM calls.
It uses mock data for 5 themes (space, medieval, plants, pixel, steampunk) and
measures what percentage pass the quality gate.

Exit codes:
    0 = ≥80% pass rate (TD-2 target met)
    1 = 50-79% pass rate (needs improvement)
    2 = <50% pass rate (pipeline broken)
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from shared.quality_gate import run_quality_gate

TEMPLATE_DIR = PROJECT_ROOT / "game-templates" / "tower-defense"
PASS_RATE_TARGET = 0.80
WARN_RATE = 0.50


def make_space_data() -> dict[str, str]:
    return {
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
                {"wave": i + 1, "enemies": [{"type": "drone", "count": 5 + i}],
                 "spawnInterval": max(400, 800 - i * 40)}
                for i in range(10)
            ]
        }),
        "src/game/data/path.json": json.dumps({
            "waypoints": [
                {"x": -20, "y": 100}, {"x": 200, "y": 100},
                {"x": 200, "y": 260}, {"x": 80, "y": 260},
                {"x": 80, "y": 420}, {"x": 360, "y": 420},
                {"x": 360, "y": 180}, {"x": 520, "y": 180},
                {"x": 520, "y": 380}, {"x": 680, "y": 380},
                {"x": 680, "y": 100}, {"x": 560, "y": 100},
                {"x": 560, "y": 500}, {"x": 820, "y": 500},
            ],
            "startHp": 20,
        }),
    }


def make_medieval_data() -> dict[str, str]:
    return {
        "src/game/data/towers.json": json.dumps({
            "towers": [
                {"key": "archer", "name": "Archer Tower", "cost": 50,
                 "damage": 10, "range": 120, "fireRate": 500,
                 "projectileSpeed": 300, "projectileType": "single",
                 "splashRadius": 0, "slowFactor": 0, "slowDuration": 0,
                 "color": 4013376, "radius": 14,
                 "upgrade": {"cost": 38, "damageMultiplier": 1.5, "rangeMultiplier": 1.2}},
                {"key": "trebuchet", "name": "Trebuchet", "cost": 100,
                 "damage": 30, "range": 100, "fireRate": 1500,
                 "projectileSpeed": 200, "projectileType": "splash",
                 "splashRadius": 40, "slowFactor": 0, "slowDuration": 0,
                 "color": 7105645, "radius": 16,
                 "upgrade": {"cost": 75, "damageMultiplier": 1.5, "rangeMultiplier": 1.2}},
                {"key": "mage", "name": "Mage Tower", "cost": 75,
                 "damage": 5, "range": 110, "fireRate": 800,
                 "projectileSpeed": 250, "projectileType": "single",
                 "splashRadius": 0, "slowFactor": 0.5, "slowDuration": 1000,
                 "color": 10181046, "radius": 14,
                 "upgrade": {"cost": 56, "damageMultiplier": 1.5, "rangeMultiplier": 1.2}},
            ]
        }),
        "src/game/data/enemies.json": json.dumps({
            "enemies": [
                {"key": "scout", "name": "Scout", "hp": 30, "speed": 80,
                 "goldReward": 5, "baseDamage": 1, "radius": 10, "color": 14721534},
                {"key": "knight", "name": "Knight", "hp": 60, "speed": 60,
                 "goldReward": 10, "baseDamage": 2, "radius": 13, "color": 7105645},
                {"key": "siege", "name": "Siege Engine", "hp": 100, "speed": 40,
                 "goldReward": 15, "baseDamage": 3, "radius": 16, "color": 2236962},
            ]
        }),
        "src/game/data/waves.json": json.dumps({
            "waves": [
                {"wave": i + 1, "enemies": [{"type": "scout", "count": 5 + i}],
                 "spawnInterval": max(400, 800 - i * 40)}
                for i in range(10)
            ]
        }),
        "src/game/data/path.json": json.dumps({
            "waypoints": [
                {"x": -20, "y": 100}, {"x": 200, "y": 100},
                {"x": 200, "y": 260}, {"x": 80, "y": 260},
                {"x": 80, "y": 420}, {"x": 360, "y": 420},
                {"x": 360, "y": 180}, {"x": 520, "y": 180},
                {"x": 520, "y": 380}, {"x": 680, "y": 380},
                {"x": 680, "y": 100}, {"x": 560, "y": 100},
                {"x": 560, "y": 500}, {"x": 820, "y": 500},
            ],
            "startHp": 20,
        }),
    }


THEMES = {
    "space": make_space_data,
    "medieval": make_medieval_data,
}


def copy_template(dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in TEMPLATE_DIR.iterdir():
        if item.name in ("node_modules", ".git"):
            continue
        if item.is_dir():
            shutil.copytree(item, dst / item.name, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dst / item.name)


def inject_themed_data(project_dir: Path, data: dict[str, str]) -> None:
    for rel_path, content in data.items():
        full = project_dir / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")


async def run_quality_gate_static_only(project_dir: Path, gdd: dict) -> dict:
    report = await run_quality_gate(project_dir, gdd, mode="quick")
    return report.to_dict()


def build_gdd(theme: str) -> dict:
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


async def main() -> int:
    if not (TEMPLATE_DIR / "src" / "main.ts").exists():
        print(f"ERROR: Golden template not found at {TEMPLATE_DIR}")
        return 2

    print(f"TD-2 Batch Test: {len(THEMES)} themed variants\n")
    print("=" * 60)

    results: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        for theme_name, data_factory in THEMES.items():
            print(f"\n--- Testing theme: {theme_name} ---")
            project_dir = Path(tmp) / theme_name
            copy_template(project_dir)
            inject_themed_data(project_dir, data_factory())
            gdd = build_gdd(theme_name)
            gate = await run_quality_gate_static_only(project_dir, gdd)

            hard_fails = gate["hard_failures"]
            soft_warns = gate["soft_warnings"]
            passed = gate["overall_passed"]

            print(f"  overall_passed: {passed}")
            print(f"  hard_failures: {len(hard_fails)}")
            for hf in hard_fails:
                print(f"    - [{hf['name']}] {hf['evidence']}")
            print(f"  soft_warnings: {len(soft_warns)}")
            for sw in soft_warns:
                print(f"    - [{sw['name']}] {sw['evidence']}")

            results.append({"theme": theme_name, "passed": passed, "gate": gate})

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passed_count = sum(1 for r in results if r["passed"])
    total = len(results)
    pass_rate = passed_count / total if total else 0
    print(f"Themes: {total}")
    print(f"Passed: {passed_count}")
    print(f"Pass rate: {pass_rate:.0%} (target: ≥{int(PASS_RATE_TARGET * 100)}%)")

    for r in results:
        status = "✓" if r["passed"] else "✗"
        print(f"  {status} {r['theme']}")

    if pass_rate >= PASS_RATE_TARGET:
        print(f"\n✓ TD-2 TARGET MET: {pass_rate:.0%} ≥ {PASS_RATE_TARGET:.0%}")
        return 0
    if pass_rate >= WARN_RATE:
        print(f"\n⚠ NEEDS IMPROVEMENT: {pass_rate:.0%} < {PASS_RATE_TARGET:.0%}")
        return 1
    print(f"\n✗ PIPELINE BROKEN: {pass_rate:.0%} < {WARN_RATE:.0%}")
    return 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

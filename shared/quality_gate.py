from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from loguru import logger

Severity = Literal["hard_veto", "soft_warn"]


@dataclass
class GateResult:
    name: str
    severity: Severity
    passed: bool
    evidence: str = ""


@dataclass
class GateReport:
    results: list[GateResult] = field(default_factory=list)

    @property
    def overall_passed(self) -> bool:
        return all(r.passed for r in self.results if r.severity == "hard_veto")

    @property
    def hard_failures(self) -> list[GateResult]:
        return [r for r in self.results if r.severity == "hard_veto" and not r.passed]

    @property
    def soft_warnings(self) -> list[GateResult]:
        return [r for r in self.results if r.severity == "soft_warn" and not r.passed]

    def to_dict(self) -> dict:
        return {
            "overall_passed": self.overall_passed,
            "hard_failures": [
                {"name": r.name, "evidence": r.evidence} for r in self.hard_failures
            ],
            "soft_warnings": [
                {"name": r.name, "evidence": r.evidence}
                for r in self.soft_warnings
            ],
            "results": [
                {
                    "name": r.name,
                    "severity": r.severity,
                    "passed": r.passed,
                    "evidence": r.evidence,
                }
                for r in self.results
            ],
        }


GENRE_MECHANIC_PATTERNS: dict[str, dict[str, list[str]]] = {
    "tower-defense": {
        "tower_placement": [r"TowerFactory|placeTower|build.*tower|place.*tower"],
        "enemy_path": [r"PathFinder|waypoint|followPath|moveAlong"],
        "shooting": [r"Projectile|shootAt|fireAt|dealDamage|attack"],
        "waves": [r"WaveManager|startNextWave|spawnWave|waveData"],
        "economy": [r"gold|currency|EconomyManager|spendGold|addGold"],
        "base_defense": [r"\bBase\b|baseHealth|baseHp|damageBase|takeDamage"],
        "upgrade": [r"upgrade|Upgrade|upgradeTower"],
    },
}

REQUIRED_STATE_FIELDS = [
    "gold",
    "baseHealth",
    "currentWave",
    "isGameOver",
    "isVictory",
]

COMPLEXITY_THRESHOLD = 0.55


def _normalize_genre(genre: str) -> str:
    return genre.lower().replace("_", "-").replace(" ", "-")


def _read_all_ts(game_dir: Path) -> str:
    src = game_dir / "src"
    if not src.exists():
        return ""
    parts: list[str] = []
    for f in sorted(src.rglob("*.ts")):
        parts.append(f.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def _check_mechanic_completeness(game_dir: Path, gdd: dict) -> GateResult:
    genre = _normalize_genre(gdd.get("genre", ""))
    patterns = GENRE_MECHANIC_PATTERNS.get(genre)
    if not patterns:
        return GateResult(
            "mechanic_completeness",
            "hard_veto",
            True,
            f"No mechanic patterns defined for genre '{genre}' — skipped",
        )

    code = _read_all_ts(game_dir)
    if not code.strip():
        return GateResult(
            "mechanic_completeness", "hard_veto", False, "No TypeScript source found"
        )

    missing: list[str] = []
    for mechanic, keywords in patterns.items():
        found = any(re.search(kw, code, re.IGNORECASE) for kw in keywords)
        if not found:
            missing.append(mechanic)

    if missing:
        return GateResult(
            "mechanic_completeness",
            "hard_veto",
            False,
            f"Missing mechanics: {', '.join(missing)}",
        )
    return GateResult(
        "mechanic_completeness",
        "hard_veto",
        True,
        f"All {len(patterns)} required mechanics found in source",
    )


def _check_asset_existence(game_dir: Path) -> GateResult:
    code = _read_all_ts(game_dir)
    if not code.strip():
        return GateResult(
            "asset_existence", "hard_veto", False, "No source to analyze"
        )

    patterns = [
        r"this\.load\.image\([^)]+,\s*['\"]([^'\"]+)['\"]",
        r"this\.load\.spritesheet\([^)]+,\s*['\"]([^'\"]+)['\"]",
        r"this\.load\.audio\([^)]+,\s*['\"]([^'\"]+)['\"]",
        r"this\.load\.atlas\([^)]+,\s*['\"]([^'\"]+)['\"]",
    ]

    referenced: set[str] = set()
    for pat in patterns:
        referenced.update(re.findall(pat, code))

    if not referenced:
        return GateResult(
            "asset_existence",
            "hard_veto",
            True,
            "No external assets referenced (runtime-generated textures)",
        )

    missing: list[str] = []
    for asset_path in sorted(referenced):
        clean = asset_path.lstrip("./")
        found = (game_dir / "public" / clean).exists() or (
            game_dir / "dist" / clean
        ).exists()
        if not found:
            missing.append(asset_path)

    if missing:
        return GateResult(
            "asset_existence",
            "hard_veto",
            False,
            f"Missing {len(missing)} asset(s): {', '.join(missing[:5])}",
        )
    return GateResult(
        "asset_existence",
        "hard_veto",
        True,
        f"All {len(referenced)} referenced assets exist",
    )


def _check_complexity(gdd: dict, game_dir: Path) -> GateResult:
    from shared.complexity import score_code, score_gdd

    gdd_score, gdd_issues = score_gdd(gdd)
    code_score, _ = score_code(game_dir)
    combined = min(gdd_score, code_score)

    if combined >= COMPLEXITY_THRESHOLD:
        return GateResult(
            "complexity",
            "soft_warn",
            True,
            f"GDD={gdd_score:.2f} Code={code_score:.2f} Combined={combined:.2f}",
        )
    return GateResult(
        "complexity",
        "soft_warn",
        False,
        f"Combined={combined:.2f} below {COMPLEXITY_THRESHOLD} "
        f"(GDD={gdd_score:.2f} Code={code_score:.2f}). "
        f"Issues: {'; '.join(gdd_issues[:3])}",
    )


async def _start_game_and_get_page(
    browser, dist_dir: Path
):
    import http.server
    import threading

    handler = http.server.SimpleHTTPRequestHandler
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}/index.html"
    prev_cwd = os.getcwd()
    os.chdir(dist_dir)

    try:
        context = await browser.new_context(viewport={"width": 800, "height": 600})
        page = await context.new_page()
        await page.goto(url, wait_until="networkidle", timeout=15000)
        await page.wait_for_timeout(1500)

        start_btn = await page.query_selector(
            "button:has-text('Start'), button:has-text('Play'), "
            "button:has-text('start'), button:has-text('play'), "
            "button:has-text('START')"
        )
        if start_btn:
            await start_btn.click()
            await page.wait_for_timeout(1000)

        return page, context
    finally:
        os.chdir(prev_cwd)
        server.shutdown()


async def _wait_for_test_ready(page, timeout_s: int = 10) -> bool:
    for _ in range(timeout_s * 2):
        ready = await page.evaluate(
            "typeof window.__TEST__ !== 'undefined' && window.__TEST__ && window.__TEST__.ready"
        )
        if ready:
            return True
        await page.wait_for_timeout(500)
    return False


async def _check_test_contract(page) -> GateResult:
    has_test = await page.evaluate(
        "typeof window.__TEST__ !== 'undefined' && window.__TEST__ !== null"
    )
    if not has_test:
        return GateResult(
            "test_contract", "hard_veto", False, "__TEST__ not defined on window"
        )

    ready = await page.evaluate("window.__TEST__.ready")
    if not ready:
        return GateResult(
            "test_contract", "hard_veto", False, "__TEST__.ready is false"
        )

    state = await page.evaluate("window.__TEST__.state()")
    if not isinstance(state, dict):
        return GateResult(
            "test_contract", "hard_veto", False, "state() did not return an object"
        )

    missing = [
        f for f in REQUIRED_STATE_FIELDS if f not in state or state[f] is None
    ]
    if missing:
        return GateResult(
            "test_contract",
            "hard_veto",
            False,
            f"state() missing fields: {', '.join(missing)}",
        )

    for cmd in ("placeTower", "startNextWave", "upgradeTower"):
        exists = await page.evaluate(
            f"typeof window.__TEST__.{cmd} === 'function'"
        )
        if not exists:
            return GateResult(
                "test_contract",
                "hard_veto",
                False,
                f"__TEST__.{cmd}() is not a function",
            )

    return GateResult(
        "test_contract",
        "hard_veto",
        True,
        f"ready=true, state() has {len(REQUIRED_STATE_FIELDS)} required fields, "
        "commands verified",
    )


async def _check_tower_placement(page) -> GateResult:
    initial = await page.evaluate(
        "typeof window.__TEST__.getTowerCount === 'function' "
        "? window.__TEST__.getTowerCount() : -1"
    )

    test_positions = [(2, 2), (17, 13), (2, 13), (17, 2), (10, 7)]
    placed_any = False
    for col, row in test_positions:
        result = await page.evaluate(
            f"window.__TEST__.placeTower({col}, {row}, 'arrow')"
        )
        if result:
            placed_any = True
            break

    if not placed_any:
        return GateResult(
            "tower_placement",
            "hard_veto",
            False,
            f"Could not place tower at any of {len(test_positions)} positions "
            "(path overlap or placement bug)",
        )

    final = await page.evaluate(
        "typeof window.__TEST__.getTowerCount === 'function' "
        "? window.__TEST__.getTowerCount() : -1"
    )
    if initial >= 0 and final > initial:
        return GateResult(
            "tower_placement",
            "hard_veto",
            True,
            f"Tower placed successfully: count {initial} -> {final}",
        )
    if initial < 0:
        return GateResult(
            "tower_placement",
            "hard_veto",
            True,
            "Tower placed (getTowerCount not available for verification)",
        )
    return GateResult(
        "tower_placement",
        "hard_veto",
        False,
        f"placeTower returned true but count unchanged: {initial} -> {final}",
    )


async def _check_game_loop_closure(page, timeout_s: int = 60) -> GateResult:
    has_fast_forward = await page.evaluate(
        "typeof window.__TEST__.fastForward === 'function'"
    )

    elapsed = 0
    while elapsed < timeout_s:
        state = await page.evaluate("window.__TEST__.state()")
        if state.get("isGameOver"):
            return GateResult(
                "game_loop",
                "hard_veto",
                True,
                f"Game over (defeat) at wave {state.get('currentWave', '?')}, "
                f"base HP reached 0",
            )
        if state.get("isVictory"):
            return GateResult(
                "game_loop",
                "hard_veto",
                True,
                "Victory — all waves cleared with base intact",
            )

        if not state.get("isWaveInProgress"):
            started = await page.evaluate("window.__TEST__.startNextWave()")
            if not started:
                pass

        if has_fast_forward:
            await page.evaluate("window.__TEST__.fastForward(2000)")
            await page.wait_for_timeout(300)
            elapsed += 2
        else:
            await page.wait_for_timeout(2000)
            elapsed += 2

    return GateResult(
        "game_loop",
        "hard_veto",
        False,
        f"Game did not reach end state within {timeout_s}s "
        f"(last wave: {state.get('currentWave', '?')}, "
        f"enemies alive: {state.get('enemiesAlive', '?')})",
    )


async def run_quality_gate(
    game_dir: Path,
    gdd: dict,
    mode: str = "standard",
) -> GateReport:
    report = GateReport()

    report.results.append(_check_mechanic_completeness(game_dir, gdd))
    report.results.append(_check_asset_existence(game_dir))

    static_failed = any(
        not r.passed and r.severity == "hard_veto" for r in report.results
    )
    if static_failed and mode == "strict":
        logger.warning("Static checks failed — skipping Playwright checks (strict mode)")
        report.results.append(_check_complexity(gdd, game_dir))
        return report

    dist_dir = game_dir / "dist"
    if not dist_dir.exists() or not (dist_dir / "index.html").exists():
        logger.warning("No dist/ build found — skipping Playwright checks")
        report.results.append(
            GateResult(
                "test_contract", "hard_veto", False, "No dist/ build to test"
            )
        )
        report.results.append(
            GateResult(
                "tower_placement", "hard_veto", False, "No dist/ build to test"
            )
        )
        report.results.append(
            GateResult(
                "game_loop", "hard_veto", False, "No dist/ build to test"
            )
        )
        report.results.append(_check_complexity(gdd, game_dir))
        return report

    if mode == "quick":
        logger.info("Quick mode — skipping Playwright checks")
        report.results.append(_check_complexity(gdd, game_dir))
        return report

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page, context = await _start_game_and_get_page(browser, dist_dir)

                ready = await _wait_for_test_ready(page)
                if not ready:
                    report.results.append(
                        GateResult(
                            "test_contract",
                            "hard_veto",
                            False,
                            "__TEST__.ready never became true within 10s",
                        )
                    )
                    report.results.append(
                        GateResult(
                            "tower_placement",
                            "hard_veto",
                            False,
                            "Skipped — __TEST__ not ready",
                        )
                    )
                    report.results.append(
                        GateResult(
                            "game_loop",
                            "hard_veto",
                            False,
                            "Skipped — __TEST__ not ready",
                        )
                    )
                else:
                    report.results.append(await _check_test_contract(page))
                    report.results.append(await _check_tower_placement(page))
                    report.results.append(await _check_game_loop_closure(page))

                await context.close()
            finally:
                await browser.close()
    except ImportError:
        logger.warning("Playwright not installed — skipping runtime checks")
        for name in ("test_contract", "tower_placement", "game_loop"):
            report.results.append(
                GateResult(name, "hard_veto", False, "Playwright not installed")
            )
    except Exception as e:
        logger.error(f"Quality gate Playwright error: {e}")
        for name in ("test_contract", "tower_placement", "game_loop"):
            report.results.append(
                GateResult(name, "hard_veto", False, f"Browser error: {e!s}")
            )

    report.results.append(_check_complexity(gdd, game_dir))

    hard_fails = len(report.hard_failures)
    logger.info(
        f"Quality gate: {'PASSED' if report.overall_passed else 'FAILED'} "
        f"({hard_fails} hard failures, {len(report.soft_warnings)} soft warnings)"
    )

    return report

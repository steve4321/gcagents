"""Automated playtest runner using headless Playwright."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from loguru import logger
from playwright.async_api import async_playwright

from .playtest_checks import (
    check_canvas_exists,
    check_canvas_renders,
    check_click_start,
    check_interactive_elements,
    check_no_white_screen,
    check_page_loads,
    check_score_system,
)


async def run_auto_playtest(game_dist_path: str | Path, game_dir: str | Path | None = None) -> dict:
    """Run all playtest checks on a built game.

    Args:
        game_dist_path: Path to game's dist/ directory containing index.html
        game_dir: Path to game's root directory (for complexity scoring).

    Returns:
        dict with: passed (bool), score (float 0-1), checks (list), duration_ms (int)
    """
    game_path = Path(game_dist_path)
    index_html = game_path / "index.html"
    if not index_html.exists():
        return {"passed": False, "score": 0.0, "error": f"index.html not found at {index_html}"}

    url = f"file://{index_html.resolve()}"
    started_at = datetime.now(timezone.utc)

    all_errors: list[str] = []
    results: list[dict] = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 800, "height": 600},
                js_enabled=True,
            )
            page = await context.new_page()
            page.on("pageerror", lambda err: all_errors.append(str(err)))

            checks = [
                ("page_loads", lambda: check_page_loads(page, url)),
                ("canvas_exists", lambda: check_canvas_exists(page)),
                ("canvas_renders", lambda: check_canvas_renders(page)),
                ("not_white_screen", lambda: check_no_white_screen(page)),
                ("interactive_elements", lambda: check_interactive_elements(page)),
                ("click_start", lambda: check_click_start(page)),
                ("score_system", lambda: check_score_system(page)),
            ]

            for name, check_fn in checks:
                try:
                    result = await check_fn()
                    results.append(result)
                    status = "PASS" if result["passed"] else "FAIL"
                    logger.info(f"Playtest [{status}] {name}")
                except Exception as e:
                    results.append({"name": name, "passed": False, "error": str(e)})
                    logger.warning(f"Playtest [ERROR] {name}: {e}")

            results.append({
                "name": "console_errors",
                "passed": len(all_errors) == 0,
                "error_count": len(all_errors),
                "errors": all_errors[:5],
            })

            if game_dir:
                from agents.dev.qa.playtest_checks import check_complexity_score
                complexity_result = check_complexity_score(game_dir, page)
                results.append(complexity_result)

            await browser.close()

    except Exception as e:
        logger.error(f"Playtest browser error: {e}")
        return {
            "passed": False,
            "score": 0.0,
            "error": str(e),
            "checks": results,
        }

    passed_count = sum(1 for r in results if r.get("passed"))
    total_count = len(results)
    base_score = passed_count / total_count if total_count > 0 else 0.0

    complexity_passed = all(
        c.get("passed", True) for c in results if c.get("name") == "complexity_score"
    )
    complexity_score = next(
        (c.get("score", 1.0) for c in results if c.get("name") == "complexity_score"), 1.0
    )
    final_score = round(min(base_score, complexity_score), 2)

    elapsed = datetime.now(timezone.utc) - started_at
    duration_ms = int(elapsed.total_seconds() * 1000)

    return {
        "passed": passed_count >= total_count - 1 and complexity_passed,
        "score": final_score,
        "checks": results,
        "passed_count": passed_count,
        "total_count": total_count,
        "console_errors": len(all_errors),
        "duration_ms": duration_ms,
    }

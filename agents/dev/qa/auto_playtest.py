"""Automated playtest runner using headless Playwright."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger
from playwright.async_api import async_playwright

from .playtest_checks import (
    check_branching_integrity,
    check_canvas_exists,
    check_canvas_renders,
    check_choices_appear,
    check_click_start,
    check_dialogue_plays,
    check_dialogue_text_overflow,
    check_ending_reachable_static,
    check_interactive_elements,
    check_no_runtime_errors,
    check_no_white_screen,
    check_page_loads,
    check_stat_updates,
)


async def run_auto_playtest(game_dist_path: str | Path, game_dir: str | Path | None = None) -> dict:
    """Run all playtest checks on a built game.

    Args:
        game_dist_path: Path to game's dist/ directory containing index.html
        game_dir: Path to game's root directory (for complexity scoring and static analysis).

    Returns:
        dict with: passed (bool), score (float 0-1), checks (list), duration_ms (int)
    """
    game_path = Path(game_dist_path)
    index_html = game_path / "index.html"
    if not index_html.exists():
        return {"passed": False, "score": 0.0, "error": f"index.html not found at {index_html}"}

    import http.server
    import threading

    handler = http.server.SimpleHTTPRequestHandler
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    os.chdir(game_path)
    url = f"http://127.0.0.1:{port}/index.html"
    started_at = datetime.now(UTC)

    game_dir_resolved = Path(game_dir) if game_dir else None

    all_errors: list[str] = []
    results: list[dict] = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 800, "height": 600},
            )
            page = await context.new_page()
            page.on("pageerror", lambda err: all_errors.append(str(err)))

            # Phase 1: Surface + deep static checks
            checks = [
                ("page_loads", lambda: check_page_loads(page, url)),
                ("canvas_exists", lambda: check_canvas_exists(page)),
                ("canvas_renders", lambda: check_canvas_renders(page)),
                ("not_white_screen", lambda: check_no_white_screen(page)),
                ("interactive_elements", lambda: check_interactive_elements(page)),
                ("click_start", lambda: check_click_start(page)),
                ("branching_integrity", lambda: check_branching_integrity(page, game_dir_resolved)),
                ("dialogue_plays", lambda: check_dialogue_plays(page)),
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

            # Phase 2: Gameplay simulation — advance dialogue, click choices, verify stats
            for check_name, check_fn in [
                ("choices_appear", lambda: check_choices_appear(page)),
                ("stat_updates", lambda: check_stat_updates(page)),
            ]:
                try:
                    result = await check_fn()
                    results.append(result)
                    status = "PASS" if result["passed"] else "FAIL"
                    logger.info(f"Playtest [{status}] {check_name}")
                except Exception as e:
                    results.append({"name": check_name, "passed": False, "error": str(e)})
                    logger.warning(f"Playtest [ERROR] {check_name}: {e}")

            # Phase 3: VN QA checks (always run — no env gate)
            vn_results = await _run_vn_qa_checks(page, game_dir_resolved or game_path)
            results.extend(vn_results)

            # Phase 4: Runtime errors (must be last interactive check)
            runtime_result = await check_no_runtime_errors(page, all_errors)
            results.append(runtime_result)
            status = "PASS" if runtime_result["passed"] else "FAIL"
            logger.info(f"Playtest [{status}] no_runtime_errors")

            if game_dir:
                from agents.dev.qa.playtest_checks import check_complexity_score

                complexity_result = check_complexity_score(game_dir)
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
    complexity_score_val = next(
        (c.get("score", 1.0) for c in results if c.get("name") == "complexity_score"), 1.0
    )
    final_score = round(min(base_score, complexity_score_val), 2)

    elapsed = datetime.now(UTC) - started_at
    duration_ms = int(elapsed.total_seconds() * 1000)

    min_pass_count = max(total_count - 2, 1)
    server.shutdown()
    return {
        "passed": passed_count >= min_pass_count and complexity_passed,
        "score": final_score,
        "checks": results,
        "passed_count": passed_count,
        "total_count": total_count,
        "console_errors": len(all_errors),
        "duration_ms": duration_ms,
    }


async def _run_vn_qa_checks(page, game_path: Path) -> list[dict]:
    """Run deep VN-specific checks: ending reachability and dialogue overflow.

    Each check is wrapped in try/except so a single failure does not abort
    the whole batch. Returns a list of result dicts.
    """
    out: list[dict] = []

    try:
        result = await check_ending_reachable_static(page, game_path)
        out.append(result)
        logger.info(f"VN QA [{'PASS' if result['passed'] else 'FAIL'}] {result['name']}")
    except Exception as e:
        out.append({"name": "ending_reachable_static", "passed": False, "error": str(e)})
        logger.warning(f"VN QA check [ending_reachable_static] error: {e}")

    try:
        result = await check_dialogue_text_overflow(page)
        out.append(result)
        logger.info(f"VN QA [{'PASS' if result['passed'] else 'FAIL'}] {result['name']}")
    except Exception as e:
        out.append({"name": "dialogue_overflow", "passed": False, "error": str(e)})
        logger.warning(f"VN QA check [dialogue_overflow] error: {e}")

    return out

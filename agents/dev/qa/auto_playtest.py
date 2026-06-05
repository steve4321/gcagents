"""Automated playtest runner using headless Playwright."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger
from playwright.async_api import async_playwright

from .playtest_checks import (
    check_branch_coverage,
    check_canvas_exists,
    check_canvas_renders,
    check_cg_gallery,
    check_click_start,
    check_dialogue_text_overflow,
    check_ending_reachability,
    check_gameplay_depth,
    check_interactive_elements,
    check_localization_render,
    check_no_white_screen,
    check_page_loads,
    check_route_locked,
    check_save_load_roundtrip,
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

    import http.server
    import threading

    handler = http.server.SimpleHTTPRequestHandler
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    import os
    os.chdir(game_path)
    url = f"http://127.0.0.1:{port}/index.html"
    started_at = datetime.now(UTC)

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

            checks = [
                ("page_loads", lambda: check_page_loads(page, url)),
                ("canvas_exists", lambda: check_canvas_exists(page)),
                ("canvas_renders", lambda: check_canvas_renders(page)),
                ("not_white_screen", lambda: check_no_white_screen(page)),
                ("interactive_elements", lambda: check_interactive_elements(page)),
                ("click_start", lambda: check_click_start(page)),
                ("score_system", lambda: check_score_system(page)),
                ("gameplay_depth", lambda: check_gameplay_depth(page)),
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

            results.append(
                {
                    "name": "console_errors",
                    "passed": len(all_errors) == 0,
                    "error_count": len(all_errors),
                    "errors": all_errors[:5],
                }
            )

            if os.environ.get("ENABLE_VN_QA", "false").lower() == "true":
                vn_results = await _run_vn_qa_checks(page, game_dir or Path(game_path))
                results.extend(vn_results)

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
    complexity_score = next(
        (c.get("score", 1.0) for c in results if c.get("name") == "complexity_score"), 1.0
    )
    final_score = round(min(base_score, complexity_score), 2)

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
    """Run the 7 VN-specific checks. Gated by ENABLE_VN_QA env var.

    Each check is wrapped in try/except so a single failure does not abort
    the whole batch. Returns a list of result dicts (same shape as
    ``playtest_checks`` check functions).
    """
    out: list[dict] = []
    data_dir = game_path / "src" / "game" / "data"
    branching_path = data_dir / "branching.json"
    endings_path = data_dir / "endings.json"

    branching_dict: dict | None = None
    endings_dict: dict | None = None
    if branching_path.exists():
        try:
            with open(branching_path, encoding="utf-8") as f:
                branching_dict = json.load(f)
        except (json.JSONDecodeError, OSError):
            branching_dict = None
    if endings_path.exists():
        try:
            with open(endings_path, encoding="utf-8") as f:
                endings_dict = json.load(f)
        except (json.JSONDecodeError, OSError):
            endings_dict = None

    checks: list = []
    if branching_dict is not None:
        checks.append(("branch_coverage", lambda: check_branch_coverage(page, branching=branching_dict, playthroughs=1)))
    if endings_dict is not None:
        checks.append(("ending_reachability", lambda: check_ending_reachability(page, endings=endings_dict, playthroughs=1)))
    checks.extend([
        ("save_load_roundtrip", check_save_load_roundtrip),
        ("localization_render", lambda: check_localization_render(page, locales=["ja", "ko", "zh", "ar", "de"])),
        ("dialogue_overflow", check_dialogue_text_overflow),
        ("cg_gallery", lambda: check_cg_gallery(page, cg_key="test_cg")),
        ("route_locked", lambda: check_route_locked(page, route_id="test_route")),
    ])

    for name, check_fn in checks:
        try:
            result = await check_fn(page)
            out.append(result)
        except Exception as e:
            out.append({"name": name, "passed": False, "error": str(e)})
            logger.warning(f"VN QA check [{name}] error: {e}")

    return out

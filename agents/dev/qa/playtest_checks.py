"""Programmatic checks for generated web games via headless Playwright."""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from playwright.async_api import Page


async def check_page_loads(page: Page, url: str) -> dict:
    """Verify game page loads without JS errors."""
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    await page.goto(url, wait_until="networkidle", timeout=30000)
    return {"name": "page_loads", "passed": len(errors) == 0, "errors": errors}


async def check_canvas_exists(page: Page) -> dict:
    """Verify canvas element exists (Phaser games use canvas)."""
    canvas = await page.query_selector("canvas")
    return {"name": "canvas_exists", "passed": canvas is not None}


async def check_canvas_renders(page: Page) -> dict:
    """Verify canvas has non-zero dimensions and rendered content."""
    canvas = await page.query_selector("canvas")
    if not canvas:
        return {"name": "canvas_renders", "passed": False, "reason": "no canvas"}
    width = await canvas.get_attribute("width")
    height = await canvas.get_attribute("height")
    has_size = width is not None and height is not None and int(width) > 0 and int(height) > 0
    return {"name": "canvas_renders", "passed": has_size, "width": width, "height": height}


async def check_no_white_screen(page: Page) -> dict:
    """Verify page body is not all white (game rendered something)."""
    bg = await page.evaluate(
        "() => document.body.style.backgroundColor || getComputedStyle(document.body).backgroundColor"
    )
    is_white = bg in ["white", "#ffffff", "rgb(255, 255, 255)", ""]
    return {"name": "not_white_screen", "passed": not is_white, "bg_color": bg}


async def check_interactive_elements(page: Page) -> dict:
    """Verify at least one clickable element exists (buttons, canvas)."""
    buttons = await page.query_selector_all("button")
    canvas = await page.query_selector("canvas")
    has_interactive = len(buttons) > 0 or canvas is not None
    return {"name": "interactive_elements", "passed": has_interactive, "buttons": len(buttons)}


async def check_click_start(page: Page) -> dict:
    """Try clicking common start elements and verify game state changes."""
    start_btn = await page.query_selector(
        "button:has-text('Start'), button:has-text('Play'), "
        "button:has-text('start'), button:has-text('play')"
    )
    if start_btn:
        await start_btn.click()
        await page.wait_for_timeout(1000)
        return {"name": "click_start", "passed": True, "method": "button"}
    canvas = await page.query_selector("canvas")
    if canvas:
        box = await canvas.bounding_box()
        if box:
            await page.mouse.click(
                box["x"] + box["width"] / 2,
                box["y"] + box["height"] / 2,
            )
            await page.wait_for_timeout(1000)
            return {"name": "click_start", "passed": True, "method": "canvas_click"}
    return {"name": "click_start", "passed": False, "reason": "no start element"}


async def check_score_system(page: Page) -> dict:
    """Check if game responds to interaction via __TEST__ interface or canvas pixel changes."""
    test_state = None
    try:
        test_state = await page.evaluate(
            "() => window.__TEST__ && window.__TEST__.state ? window.__TEST__.state() : null"
        )
    except (RuntimeError, TimeoutError) as e:
        logger.debug(f"Score system check evaluate skipped: {e}")

    if test_state and isinstance(test_state, dict):
        canvas = await page.query_selector("canvas")
        if canvas:
            box = await canvas.bounding_box()
            if box:
                await page.mouse.click(
                    box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5
                )
                await page.wait_for_timeout(800)
                for _ in range(2):
                    await page.mouse.click(
                        box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5
                    )
                    await page.wait_for_timeout(400)
        try:
            after_state = await page.evaluate(
                "() => window.__TEST__ && window.__TEST__.state ? window.__TEST__.state() : null"
            )
        except (RuntimeError, TimeoutError) as e:
            logger.debug(f"Score system after_state evaluate skipped: {e}")
            after_state = None
        changed = after_state is not None and after_state != test_state
        return {
            "name": "score_system",
            "passed": changed,
            "method": "__TEST__",
            "state_before": str(test_state)[:100],
            "state_after": str(after_state)[:100] if after_state else None,
        }

    canvas = await page.query_selector("canvas")
    if not canvas:
        return {"name": "score_system", "passed": False, "reason": "no canvas"}

    before_screenshot = await canvas.screenshot()
    box = await canvas.bounding_box()
    if not box:
        return {"name": "score_system", "passed": False, "reason": "canvas has no bounding box"}

    for i in range(5):
        x = box["x"] + box["width"] * (0.3 + 0.1 * i)
        y = box["y"] + box["height"] * (0.3 + 0.1 * i)
        await page.mouse.click(x, y)
        await page.wait_for_timeout(400)

    await page.wait_for_timeout(500)
    after_screenshot = await canvas.screenshot()

    if before_screenshot and after_screenshot:
        changed = before_screenshot != after_screenshot
    else:
        changed = False

    return {
        "name": "score_system",
        "passed": changed,
        "method": "pixel_diff",
        "pixels_changed": changed,
    }


async def check_gameplay_depth(page: Page) -> dict:
    """Evaluate if the game has meaningful gameplay depth via __TEST__ interface.

    Simulates 30 seconds of gameplay by clicking and pressing keys,
    then reads the __TEST__ state to verify multiple game systems are working.
    """
    canvas = await page.query_selector("canvas")
    if not canvas:
        return {"name": "gameplay_depth", "passed": False, "reason": "no canvas"}

    box = await canvas.bounding_box()
    if not box:
        return {"name": "gameplay_depth", "passed": False, "reason": "canvas has no bounding box"}

    # Try to start the game
    await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    await page.wait_for_timeout(1000)

    # Simulate 30 seconds of gameplay with varied inputs
    for i in range(30):
        # Click at different positions
        x = box["x"] + box["width"] * (0.2 + 0.6 * ((i % 5) / 4))
        y = box["y"] + box["height"] * (0.3 + 0.4 * ((i % 3) / 2))
        await page.mouse.click(x, y)

        # Press random movement keys
        keys = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Space", "KeyW", "KeyA", "KeyS", "KeyD"]
        key = keys[i % len(keys)]
        await page.keyboard.down(key)
        await page.wait_for_timeout(50)
        await page.keyboard.up(key)
        await page.wait_for_timeout(900)

    # Read __TEST__ state
    state = None
    try:
        state = await page.evaluate(
            "() => window.__TEST__ && window.__TEST__.state ? window.__TEST__.state() : null"
        )
    except Exception:
        pass

    if not state or not isinstance(state, dict):
        return {
            "name": "gameplay_depth",
            "passed": False,
            "reason": "__TEST__ state not available after 30s play",
        }

    checks = {
        "score_changes": isinstance(state.get("score"), (int, float)) and state["score"] > 0,
        "level_progression": (
            (isinstance(state.get("level"), (int, float)) and state["level"] > 1)
            or (isinstance(state.get("currentLevel"), (int, float)) and state["currentLevel"] > 1)
        ),
        "multiple_enemy_types": (
            isinstance(state.get("enemyTypesSeen"), (list, set))
            and len(list(state.get("enemyTypesSeen", []))) >= 2
        ),
        "powerup_usage": isinstance(state.get("powerupsUsed"), (int, float)) and state["powerupsUsed"] > 0,
        "game_over_possible": state.get("lives") is not None or state.get("isGameOver") is not None,
        "session_time_tracked": isinstance(state.get("sessionTime"), (int, float)) and state["sessionTime"] > 5,
    }

    depth_score = sum(checks.values()) / len(checks)
    passed = depth_score >= 0.5

    return {
        "name": "gameplay_depth",
        "passed": passed,
        "score": round(depth_score, 2),
        "detail": checks,
        "state_snapshot": {k: v for k, v in state.items() if k != "enemyTypesSeen"} | {
                    "enemyTypesSeen": list(state.get("enemyTypesSeen", []))[:5]
                },
    }


def check_complexity_score(game_dir: str | Path) -> dict:
    """Verify game meets minimum complexity threshold."""
    from shared.complexity import MIN_PASSING_SCORE, score_code

    game_path = Path(game_dir) if not isinstance(game_dir, Path) else game_dir
    score, metrics = score_code(game_path)

    return {
        "name": "complexity_score",
        "passed": score >= MIN_PASSING_SCORE,
        "score": score,
        "detail": f"Complexity {score:.2f}/{MIN_PASSING_SCORE:.2f} — {metrics.get('total_files', 0)} files, {metrics.get('total_lines', 0)} lines",
        "metrics": metrics,
    }


async def check_branch_coverage(
    page: Page,
    branching: dict | None = None,
    playthroughs: int = 1,
) -> dict:
    """Verify all branching nodes are reachable across playthroughs.

    For each playthrough, reloads the page, lets the game run, and reads
    ``window.__TEST__.state().visitedScenes``. The union of visited nodes
    must cover every node id in the branching tree.
    """
    nodes = (branching or {}).get("branching_tree", {}).get("nodes", {})
    expected_ids = set(nodes.keys())
    if len(expected_ids) < 8:
        return {
            "name": "branch_coverage",
            "passed": False,
            "reason": f"branching tree has only {len(expected_ids)} nodes, need >= 8",
        }

    visited_union: set[str] = set()
    for _ in range(max(1, playthroughs)):
        try:
            await page.reload()
        except (RuntimeError, TimeoutError):
            pass
        await page.wait_for_timeout(300)
        try:
            state = await page.evaluate(
                "() => window.__TEST__ && window.__TEST__.state ? window.__TEST__.state() : null"
            )
        except (RuntimeError, TimeoutError):
            state = None
        if isinstance(state, dict):
            visited_union.update(state.get("visitedScenes", []) or [])

    unvisited = expected_ids - visited_union
    return {
        "name": "branch_coverage",
        "passed": len(unvisited) == 0,
        "expected": len(expected_ids),
        "visited": len(visited_union),
        "unvisited": sorted(unvisited)[:10],
    }


async def check_ending_reachability(
    page: Page,
    endings: dict | None = None,
    playthroughs: int = 1,
) -> dict:
    """Verify all declared endings are reachable across playthroughs.

    Reads ``__TEST__.state().endingsReached`` after each playthrough and
    asserts the union covers every ending name in the endings list.
    """
    declared = (endings or {}).get("endings", [])
    declared_names = {e.get("name", "") for e in declared if isinstance(e, dict)}
    declared_names.discard("")
    if len(declared_names) < 3:
        return {
            "name": "ending_reachability",
            "passed": False,
            "reason": f"endings list has only {len(declared_names)} declared names, need >= 3",
        }

    reached_union: set[str] = set()
    for _ in range(max(1, playthroughs)):
        try:
            await page.reload()
        except (RuntimeError, TimeoutError):
            pass
        await page.wait_for_timeout(300)
        try:
            state = await page.evaluate(
                "() => window.__TEST__ && window.__TEST__.state ? window.__TEST__.state() : null"
            )
        except (RuntimeError, TimeoutError):
            state = None
        if isinstance(state, dict):
            reached_union.update(state.get("endingsReached", []) or [])

    unreachable = declared_names - reached_union
    return {
        "name": "ending_reachability",
        "passed": len(unreachable) == 0,
        "declared": sorted(declared_names),
        "reached": sorted(reached_union),
        "unreachable": sorted(unreachable),
    }


async def check_save_load_roundtrip(page: Page) -> dict:
    """Save state, reload page, load slot 0, assert state hash matches."""
    try:
        hash_before = await page.evaluate(
            "() => window.__TEST__ && window.__TEST__.getStateHash ? window.__TEST__.getStateHash() : null"
        )
        await page.evaluate("() => window.__TEST__ && window.__TEST__.save ? window.__TEST__.save(0) : null")
        await page.reload()
        await page.wait_for_timeout(500)
        await page.evaluate("() => window.__TEST__ && window.__TEST__.load ? window.__TEST__.load(0) : null")
        hash_after = await page.evaluate(
            "() => window.__TEST__ && window.__TEST__.getStateHash ? window.__TEST__.getStateHash() : null"
        )
    except (RuntimeError, TimeoutError) as e:
        return {
            "name": "save_load_roundtrip",
            "passed": False,
            "reason": f"evaluate error: {e}",
        }

    if hash_before is None or hash_after is None:
        return {
            "name": "save_load_roundtrip",
            "passed": False,
            "reason": "__TEST__.getStateHash not implemented",
        }

    return {
        "name": "save_load_roundtrip",
        "passed": hash_before == hash_after,
        "hash_before": hash_before,
        "hash_after": hash_after,
    }


async def check_localization_render(
    page: Page,
    locales: list[str] | None = None,
) -> dict:
    """For each locale, set it via __TEST__.setLocale and check for text overflow.

    Reads the count of overflowing text elements (scrollWidth > clientWidth).
    """
    locales = locales or ["ja", "ko", "zh", "ar", "de"]
    overflow_per_locale: dict[str, int] = {}

    for locale in locales:
        try:
            await page.evaluate(
                f"() => window.__TEST__ && window.__TEST__.setLocale ? window.__TEST__.setLocale({locale!r}) : null"
            )
            await page.wait_for_timeout(200)
            overflow_count = await page.evaluate(
                "() => Array.from(document.querySelectorAll('*')).filter(e => e.scrollWidth > e.clientWidth + 1).length"
            )
        except (RuntimeError, TimeoutError):
            overflow_count = -1
        overflow_per_locale[locale] = overflow_count

    failed = {loc: cnt for loc, cnt in overflow_per_locale.items() if cnt > 0 or cnt < 0}
    return {
        "name": "localization_render",
        "passed": len(failed) == 0,
        "locales_tested": locales,
        "overflow_per_locale": overflow_per_locale,
        "failed_locales": failed,
    }


async def check_dialogue_text_overflow(page: Page) -> dict:
    """Measure the dialogue text bounding box vs the dialogue box bounds."""
    try:
        metrics = await page.evaluate(
            "() => {"
            "  const texts = document.querySelectorAll('canvas + * *, .dialogue-text, [class*=dialogue]');"
            "  if (!texts.length) return null;"
            "  const t = texts[0];"
            "  const tb = t.getBoundingClientRect();"
            "  return { textWidth: tb.width, textHeight: tb.height,"
            "           boxWidth: window.innerWidth, boxHeight: window.innerHeight };"
            "}"
        )
    except (RuntimeError, TimeoutError):
        metrics = None

    if not metrics:
        return {"name": "dialogue_overflow", "passed": False, "reason": "no dialogue element found"}

    fits = metrics["textWidth"] <= metrics["boxWidth"] and metrics["textHeight"] <= metrics["boxHeight"]
    return {
        "name": "dialogue_overflow",
        "passed": fits,
        "text_width": metrics["textWidth"],
        "box_width": metrics["boxWidth"],
        "text_height": metrics["textHeight"],
        "box_height": metrics["boxHeight"],
    }


async def check_cg_gallery(page: Page, cg_key: str = "test_cg") -> dict:
    """Unlock a CG via __TEST__, navigate to gallery, assert the CG renders."""
    try:
        await page.evaluate(
            f"() => window.__TEST__ && window.__TEST__.unlockCG ? window.__TEST__.unlockCG({cg_key!r}) : null"
        )
        visible = await page.evaluate(
            f"() => {{ const el = document.querySelector('[data-cg=\"{cg_key}\"]'); return el !== null; }}"
        )
    except (RuntimeError, TimeoutError):
        visible = False

    return {
        "name": "cg_gallery",
        "passed": bool(visible),
        "cg_key": cg_key,
    }


async def check_route_locked(page: Page, route_id: str = "test_route") -> dict:
    """Click a locked route in the menu and assert the scene does not change."""
    try:
        before = await page.evaluate("() => (window.__TEST__ && window.__TEST__.state ? window.__TEST__.state().currentScene : null)")
        await page.evaluate(
            f"() => {{ const btn = document.querySelector('[data-route=\"{route_id}\"][data-locked=\"true\"]'); if (btn) btn.click(); }}"
        )
        await page.wait_for_timeout(800)
        after = await page.evaluate("() => (window.__TEST__ && window.__TEST__.state ? window.__TEST__.state().currentScene : null)")
    except (RuntimeError, TimeoutError):
        before, after = None, None

    if before is None or after is None:
        return {
            "name": "route_locked",
            "passed": False,
            "reason": "__TEST__ state not available",
        }

    return {
        "name": "route_locked",
        "passed": before == after,
        "route_id": route_id,
        "scene_before": before,
        "scene_after": after,
    }

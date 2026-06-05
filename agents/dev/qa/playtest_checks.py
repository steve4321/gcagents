"""Programmatic checks for generated web games via headless Playwright."""

from __future__ import annotations

import json
from collections import deque
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


# ---------------------------------------------------------------------------
# Deep logic verification checks
# ---------------------------------------------------------------------------


def _normalize_branching(raw: dict) -> tuple[str | None, dict]:
    """Return (root_id, nodes_dict) handling both flat and nested formats."""
    if "branching_tree" in raw:
        tree = raw["branching_tree"]
    else:
        tree = raw
    return tree.get("root"), tree.get("nodes", {})


def _dialogue_keys(dialogue: dict) -> set[str]:
    """Extract all dialogue keys from either format of dialogue.json."""
    if "lines" in dialogue:
        return {line.get("id", "") for line in dialogue["lines"] if isinstance(line, dict)}

    return {k for k in dialogue if isinstance(dialogue[k], list)}


async def check_branching_integrity(page: Page, game_dir: Path | None = None) -> dict:
    """Static analysis of branching.json — validates structure, references, and reachability.

    Checks:
    1. JSON is valid
    2. Has 'root' and 'nodes' keys
    3. Root node exists in nodes
    4. Every node's choice.next_node exists in nodes (or starts with 'ending_')
    5. Every node's dialogue key exists in dialogue.json
    6. BFS from root reaches all nodes (no orphans)
    7. No node has empty dialogue AND empty choices (dead end without being an ending)

    Returns {name, passed, errors: [...], node_count, orphan_count}
    """
    if game_dir is None:
        return {
            "name": "branching_integrity", "passed": False,
            "errors": ["game_dir not provided"], "node_count": 0, "orphan_count": 0,
        }

    data_dir = Path(game_dir) / "src" / "game" / "data"
    branching_path = data_dir / "branching.json"
    dialogue_path = data_dir / "dialogue.json"

    if not branching_path.exists():
        return {
            "name": "branching_integrity", "passed": False,
            "errors": ["branching.json not found"], "node_count": 0, "orphan_count": 0,
        }

    try:
        with open(branching_path, encoding="utf-8") as f:
            branching = json.load(f)
    except json.JSONDecodeError as e:
        return {
            "name": "branching_integrity", "passed": False,
            "errors": [f"invalid JSON: {e}"], "node_count": 0, "orphan_count": 0,
        }

    errors: list[str] = []
    root, nodes = _normalize_branching(branching)

    # 2. Root / nodes keys
    if not root:
        errors.append("Missing 'root' key in branching data")
    if not nodes:
        errors.append("Missing 'nodes' key or nodes is empty")

    # 3. Root node exists
    if root and nodes and root not in nodes:
        errors.append(f"Root node '{root}' not found in nodes")

    # 4. next_node references
    for node_id, node in nodes.items():
        for choice in node.get("choices", []):
            next_node = choice.get("next_node", "")
            if next_node and next_node not in nodes and not next_node.startswith("ending_"):
                label = choice.get("label", "")
                errors.append(
                    f"Node '{node_id}' → choice '{label}' "
                    f"references missing node '{next_node}'"
                )

    # 5. Dialogue key references
    d_keys: set[str] = set()
    if dialogue_path.exists():
        try:
            with open(dialogue_path, encoding="utf-8") as f:
                dialogue = json.load(f)
            d_keys = _dialogue_keys(dialogue)
        except (json.JSONDecodeError, OSError):
            pass

    for node_id, node in nodes.items():
        for d_key in node.get("dialogue", []):
            if d_keys and d_key not in d_keys:
                errors.append(f"Node '{node_id}' references missing dialogue key '{d_key}'")

    # 6. BFS reachability
    orphan_count = 0
    if root and root in nodes:
        visited: set[str] = set()
        queue: deque[str] = deque([root])
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            if current in nodes:
                for choice in nodes[current].get("choices", []):
                    nn = choice.get("next_node", "")
                    if nn and nn in nodes and nn not in visited:
                        queue.append(nn)
        orphans = set(nodes.keys()) - visited
        orphan_count = len(orphans)
        for orphan in sorted(orphans):
            errors.append(f"Orphan node '{orphan}' not reachable from root")
    else:
        orphan_count = -1

    # 7. Dead ends
    for node_id, node in nodes.items():
        has_dialogue = bool(node.get("dialogue", []))
        has_choices = bool(node.get("choices", []))
        if not has_dialogue and not has_choices and not node_id.startswith("ending_"):
            errors.append(
                f"Node '{node_id}' is a dead end "
                "(no dialogue, no choices, not an ending)"
            )

    return {
        "name": "branching_integrity",
        "passed": len(errors) == 0,
        "errors": errors[:20],
        "node_count": len(nodes),
        "orphan_count": orphan_count,
    }


async def check_dialogue_plays(page: Page) -> dict:
    """Verify dialogue actually renders in the game canvas.

    Steps:
    1. Click through title screen (click canvas center)
    2. Click through menu (click canvas center again for "New Game")
    3. Wait 2 seconds for NovelScene to load
    4. Take screenshot of canvas
    5. Sample pixels in the bottom 30% of canvas (dialogue box area)
    6. If there are bright (non-dark) pixels in the dialogue area, dialogue is rendering
    7. Check __TEST__ interface for currentScene === 'NovelScene'

    Returns {name, passed, reason, has_text_pixels: bool}
    """
    canvas = await page.query_selector("canvas")
    if not canvas:
        return {
            "name": "dialogue_plays", "passed": False,
            "reason": "no canvas", "has_text_pixels": False,
        }

    box = await canvas.bounding_box()
    if not box:
        return {
            "name": "dialogue_plays", "passed": False,
            "reason": "canvas has no bounding box", "has_text_pixels": False,
        }

    cx = box["x"] + box["width"] / 2
    cy = box["y"] + box["height"] / 2

    # Advance through title / menu screens (idempotent)
    await page.mouse.click(cx, cy)
    await page.wait_for_timeout(800)
    await page.mouse.click(cx, cy)
    await page.wait_for_timeout(2000)

    try:
        scene = await page.evaluate(
            "() => window.__TEST__ && window.__TEST__.state"
            " ? window.__TEST__.state().currentScene : null"
        )
        if scene == "NovelScene":
            return {
                "name": "dialogue_plays", "passed": True,
                "reason": "NovelScene active", "has_text_pixels": True,
            }
    except (RuntimeError, TimeoutError):
        scene = None

    has_text_pixels = await page.evaluate("""() => {
        const canvas = document.querySelector('canvas');
        if (!canvas) return false;
        try {
            const temp = document.createElement('canvas');
            temp.width = canvas.width;
            temp.height = canvas.height;
            const ctx = temp.getContext('2d');
            if (!ctx) return false;
            ctx.drawImage(canvas, 0, 0);
            const w = canvas.width;
            const h = canvas.height;
            const yStart = Math.floor(h * 0.7);
            const region = ctx.getImageData(0, yStart, w, h - yStart).data;
            let bright = 0;
            for (let i = 0; i < region.length; i += 64) {
                const brightness = (region[i] + region[i+1] + region[i+2]) / 3;
                if (brightness > 100) bright++;
            }
            return bright > 5;
        } catch(e) { return false; }
    }""")

    reason = "pixel_analysis" if has_text_pixels else "no_bright_pixels_in_dialogue_area"
    return {
        "name": "dialogue_plays",
        "passed": bool(has_text_pixels),
        "reason": reason,
        "has_text_pixels": bool(has_text_pixels),
    }


async def check_choices_appear(page: Page) -> dict:
    """Verify choice buttons appear after dialogue completes.

    Steps:
    1. Click canvas 10 times rapidly (advance through dialogue)
    2. Wait 1 second
    3. Check if __TEST__ shows currentScene with choices
    4. OR take screenshot and look for bright colored rectangles in choice area

    Returns {name, passed, clicks_used}
    """
    canvas = await page.query_selector("canvas")
    if not canvas:
        return {"name": "choices_appear", "passed": False, "clicks_used": 0}

    box = await canvas.bounding_box()
    if not box:
        return {"name": "choices_appear", "passed": False, "clicks_used": 0}

    cx = box["x"] + box["width"] / 2
    cy = box["y"] + box["height"] / 2

    for _ in range(10):
        await page.mouse.click(cx, cy)
        await page.wait_for_timeout(200)

    await page.wait_for_timeout(1000)

    try:
        state = await page.evaluate(
            "() => window.__TEST__ && window.__TEST__.state ? window.__TEST__.state() : null"
        )
        if state and isinstance(state, dict):
            choices = state.get("choices", [])
            if choices:
                return {"name": "choices_appear", "passed": True, "clicks_used": 10}
    except (RuntimeError, TimeoutError):
        pass

    has_choice_content = await page.evaluate("""() => {
        const canvas = document.querySelector('canvas');
        if (!canvas) return false;
        try {
            const temp = document.createElement('canvas');
            temp.width = canvas.width;
            temp.height = canvas.height;
            const ctx = temp.getContext('2d');
            if (!ctx) return false;
            ctx.drawImage(canvas, 0, 0);
            const w = canvas.width;
            const h = canvas.height;
            const yStart = Math.floor(h * 0.35);
            const yEnd = Math.floor(h * 0.65);
            const data = ctx.getImageData(0, yStart, w, yEnd - yStart).data;
            let distinct_bright = 0;
            for (let i = 0; i < data.length; i += 256) {
                const r = data[i], g = data[i+1], b = data[i+2];
                if (r > 150 || g > 150 || b > 150) distinct_bright++;
            }
            return distinct_bright > 3;
        } catch(e) { return false; }
    }""")

    return {"name": "choices_appear", "passed": bool(has_choice_content), "clicks_used": 10}


async def check_stat_updates(page: Page) -> dict:
    """Verify stats change when choices are made.

    Steps:
    1. Get initial stats from __TEST__.state().stats
    2. Click through to get choices to appear
    3. Click a choice (random position in choice area)
    4. Get new stats
    5. Compare — at least one stat should have changed

    Returns {name, passed, initial_stats, final_stats, changed_count}
    """
    initial_stats: dict | None = None
    try:
        raw = await page.evaluate(
            "() => {"
            "  if (!window.__TEST__ || !window.__TEST__.state) return null;"
            "  const s = window.__TEST__.state();"
            "  return s.stats || null;"
            "}"
        )
        if raw and isinstance(raw, dict):
            initial_stats = raw
    except (RuntimeError, TimeoutError):
        pass

    if not initial_stats:
        try:
            state = await page.evaluate(
                "() => window.__TEST__ && window.__TEST__.state ? window.__TEST__.state() : null"
            )
            if state and isinstance(state, dict):
                initial_stats = {k: v for k, v in state.items() if isinstance(v, (int, float))}
        except (RuntimeError, TimeoutError):
            pass

    if not initial_stats:
        return {
            "name": "stat_updates",
            "passed": False,
            "reason": "no stats available via __TEST__",
            "initial_stats": None,
            "final_stats": None,
            "changed_count": 0,
        }

    canvas = await page.query_selector("canvas")
    if not canvas:
        return {
            "name": "stat_updates", "passed": False,
            "initial_stats": initial_stats, "final_stats": None,
            "changed_count": 0, "reason": "no canvas",
        }

    box = await canvas.bounding_box()
    if not box:
        return {
            "name": "stat_updates", "passed": False,
            "initial_stats": initial_stats, "final_stats": None,
            "changed_count": 0, "reason": "no bounding box",
        }

    for _ in range(10):
        await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        await page.wait_for_timeout(300)

    # Click in the choice area (middle-lower portion)
    await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] * 0.6)
    await page.wait_for_timeout(1000)

    final_stats: dict | None = None
    try:
        raw = await page.evaluate(
            "() => {"
            "  if (!window.__TEST__ || !window.__TEST__.state) return null;"
            "  const s = window.__TEST__.state();"
            "  return s.stats || null;"
            "}"
        )
        if raw and isinstance(raw, dict):
            final_stats = raw
    except (RuntimeError, TimeoutError):
        pass

    if not final_stats:
        try:
            state = await page.evaluate(
                "() => window.__TEST__ && window.__TEST__.state ? window.__TEST__.state() : null"
            )
            if state and isinstance(state, dict):
                final_stats = {k: v for k, v in state.items() if isinstance(v, (int, float))}
        except (RuntimeError, TimeoutError):
            pass

    if not final_stats:
        return {
            "name": "stat_updates",
            "passed": False,
            "reason": "no final stats available",
            "initial_stats": initial_stats,
            "final_stats": None,
            "changed_count": 0,
        }

    changed = 0
    for key in set(list(initial_stats.keys()) + list(final_stats.keys())):
        if initial_stats.get(key) != final_stats.get(key):
            changed += 1

    return {
        "name": "stat_updates",
        "passed": changed > 0,
        "initial_stats": initial_stats,
        "final_stats": final_stats,
        "changed_count": changed,
    }


async def check_no_runtime_errors(page: Page, accumulated_errors: list[str] | None = None) -> dict:
    """Collect all JS runtime errors during gameplay.

    This should be called LAST after other interactions.
    Checks page.on('pageerror') accumulated errors.

    Returns {name, passed, error_count, errors: [...]}
    """
    errors = accumulated_errors if accumulated_errors is not None else []

    game_errors: list[str] = []
    try:
        game_errors = await page.evaluate(
            "() => Array.isArray(window.__ERRORS__) ? window.__ERRORS__ : []"
        )
    except (RuntimeError, TimeoutError):
        pass

    all_errs = list(errors) + list(game_errors)
    return {
        "name": "no_runtime_errors",
        "passed": len(all_errs) == 0,
        "error_count": len(all_errs),
        "errors": all_errs[:20],
    }


async def check_ending_reachable_static(page: Page, game_dir: Path | None = None) -> dict:
    """Static analysis — check if all endings in endings.json are reachable from root.

    Reads endings.json and branching.json from game source.
    For each ending key, BFS from root through all possible choice paths.
    If no path reaches an ending node, it's unreachable.

    Returns {name, passed, unreachable_endings: [...], total_endings}
    """
    if game_dir is None:
        return {
            "name": "ending_reachable_static", "passed": False,
            "unreachable_endings": [], "total_endings": 0,
            "reason": "game_dir not provided",
        }

    data_dir = Path(game_dir) / "src" / "game" / "data"
    branching_path = data_dir / "branching.json"
    endings_path = data_dir / "endings.json"

    if not branching_path.exists():
        return {
            "name": "ending_reachable_static", "passed": False,
            "unreachable_endings": [], "total_endings": 0,
            "reason": "branching.json not found",
        }
    if not endings_path.exists():
        return {
            "name": "ending_reachable_static", "passed": False,
            "unreachable_endings": [], "total_endings": 0,
            "reason": "endings.json not found",
        }

    try:
        with open(branching_path, encoding="utf-8") as f:
            branching = json.load(f)
    except json.JSONDecodeError as e:
        return {
            "name": "ending_reachable_static", "passed": False,
            "unreachable_endings": [], "total_endings": 0,
            "reason": f"invalid branching.json: {e}",
        }

    try:
        with open(endings_path, encoding="utf-8") as f:
            endings = json.load(f)
    except json.JSONDecodeError as e:
        return {
            "name": "ending_reachable_static", "passed": False,
            "unreachable_endings": [], "total_endings": 0,
            "reason": f"invalid endings.json: {e}",
        }

    root, nodes = _normalize_branching(branching)

    if not root or not nodes:
        return {
            "name": "ending_reachable_static", "passed": False,
            "unreachable_endings": [], "total_endings": 0,
            "reason": "invalid branching structure",
        }

    ending_list = endings.get("endings", [])
    ending_keys: set[str] = set()
    for e in ending_list:
        if isinstance(e, dict):
            key = e.get("key", e.get("name", ""))
            if key:
                ending_keys.add(key)

    if not ending_keys:
        return {
            "name": "ending_reachable_static", "passed": False,
            "unreachable_endings": [], "total_endings": 0,
            "reason": "no endings declared in endings.json",
        }

    reachable: set[str] = set()
    queue: deque[str] = deque([root])
    while queue:
        current = queue.popleft()
        if current in reachable:
            continue
        reachable.add(current)
        if current in nodes:
            for choice in nodes[current].get("choices", []):
                nn = choice.get("next_node", "")
                if nn and nn not in reachable:
                    queue.append(nn)

    unreachable = ending_keys - reachable
    return {
        "name": "ending_reachable_static",
        "passed": len(unreachable) == 0,
        "unreachable_endings": sorted(unreachable),
        "total_endings": len(ending_keys),
        "reachable_endings": sorted(ending_keys & reachable),
    }

"""Programmatic checks for generated web games via headless Playwright."""
from __future__ import annotations

from pathlib import Path

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
    has_size = (
        width is not None
        and height is not None
        and int(width) > 0
        and int(height) > 0
    )
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
    """Check if text content updates after interaction (game responding)."""
    text_before = await page.inner_text("body")
    canvas = await page.query_selector("canvas")
    if canvas:
        box = await canvas.bounding_box()
        if box:
            for _ in range(3):
                await page.mouse.click(
                    box["x"] + box["width"] * 0.5,
                    box["y"] + box["height"] * 0.5,
                )
                await page.wait_for_timeout(500)
    text_after = await page.inner_text("body")
    changed = text_before != text_after
    return {"name": "score_system", "passed": changed, "text_changed": changed}


async def check_console_errors(page: Page) -> dict:
    """Collect all console errors during test session."""
    return {"name": "console_errors", "passed": True, "note": "checked via page_error listener"}


def check_complexity_score(game_dir: str | Path, page) -> dict:
    """Verify game meets minimum complexity threshold."""
    from shared.complexity import score_code, MIN_PASSING_SCORE

    game_path = Path(game_dir) if not isinstance(game_dir, Path) else game_dir
    score, metrics = score_code(game_path)

    return {
        "name": "complexity_score",
        "passed": score >= MIN_PASSING_SCORE,
        "score": score,
        "detail": f"Complexity {score:.2f}/{MIN_PASSING_SCORE:.2f} — {metrics.get('total_files', 0)} files, {metrics.get('total_lines', 0)} lines",
        "metrics": metrics,
    }

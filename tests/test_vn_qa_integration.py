"""Real Playwright integration test for VN QA checks against the built template.

Skipped if the template has not been built (no ``dist/index.html``).
Run with: ``pytest tests/test_vn_qa_integration.py -v`` after building the template.
"""

from __future__ import annotations

from pathlib import Path

import pytest

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "game-templates" / "visual-novel"
DIST_INDEX = TEMPLATE_DIR / "dist" / "index.html"

pytestmark = pytest.mark.skipif(
    not DIST_INDEX.exists(),
    reason=f"template not built ({DIST_INDEX} not found; run `npm run build` in game-templates/visual-novel/)",
)


@pytest.mark.asyncio
async def test_dialogue_overflow_runs_against_real_template():
    from playwright.async_api import async_playwright

    from agents.dev.qa.playtest_checks import check_dialogue_text_overflow

    url = f"file://{DIST_INDEX.resolve()}"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(viewport={"width": 800, "height": 600})
            page = await context.new_page()
            await page.goto(url, wait_until="networkidle", timeout=15000)
            await page.wait_for_timeout(2000)
            result = await check_dialogue_text_overflow(page)
        finally:
            await browser.close()

    assert "name" in result
    assert result["name"] == "dialogue_overflow"
    assert "passed" in result
    assert isinstance(result["passed"], bool)


@pytest.mark.asyncio
async def test_branch_coverage_returns_structured_result_against_real_template():
    from playwright.async_api import async_playwright

    from agents.dev.qa.playtest_checks import check_branch_coverage

    nodes = {f"n{i:02d}": {"scene_key": f"s{i:02d}"} for i in range(8)}
    branching = {"branching_tree": {"root": "n00", "nodes": nodes, "edges": []}}

    url = f"file://{DIST_INDEX.resolve()}"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(viewport={"width": 800, "height": 600})
            page = await context.new_page()
            await page.goto(url, wait_until="networkidle", timeout=15000)
            await page.wait_for_timeout(2000)
            result = await check_branch_coverage(page, branching=branching, playthroughs=1)
        finally:
            await browser.close()

    assert result["name"] == "branch_coverage"
    assert result["expected"] == 8
    assert "passed" in result
    assert isinstance(result["passed"], bool)

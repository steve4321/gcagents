"""Run the anti-capitalist galgame production pipeline step by step.

This script bypasses the scheduler and calls each agent directly,
allowing us to inspect and fix issues at every step.

Usage:
    python scripts/run_anti_capitalist_vn.py [--step STEP]

Steps:
    1. design   — Generate VN GDD
    2. art      — Generate art assets (or placeholders)
    3. music    — Generate music
    4. code     — Generate game code
    5. qa       — Run QA + Playtest
    6. build    — Final build
    all         — Run everything (default)
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from loguru import logger
from shared.config import load_config
from shared.models import GameProposal
from shared.vn_schema import validate_gdd, is_visual_novel
from orchestrator.state import CompanyState, PipelinePhase


# ── Game Concept ──────────────────────────────────────────────────────────────
GAME_PROPOSAL = GameProposal(
    name="capital-revolt",
    genre="visual-novel",
    description=(
        "《资本崩塌》——一个反资本主义主题的视觉小说。"
        "你是一名996大厂的底层程序员，偶然发现了公司非法窃取用户数据的证据。"
        "面对资本的力量，你可以选择：屈服于高薪诱惑成为帮凶、"
        "联合同事发起罢工、匿名向媒体举报、或者发动一场开源革命。"
        "每个选择都会影响你的声望、良知、经济状况和人际关系。"
        "四条角色路线分别代表不同的反抗路径——工会领袖、黑客、记者、和理想主义创业者。"
        "拥有统计系统追踪你的道德值、经济状况、社会影响力、心理健康和技术能力。"
        "至少8个结局，从'成为新资本家'到'真正的集体觉醒'。"
    ),
    target_platforms=["itch.io"],
    estimated_dev_hours=40,
    market_opportunity_score=0.85,
    differentiation="Anti-capitalist theme with deep stat-based branching; no other web VN tackles labor exploitation, tech monopoly, and collective action.",
    reference_games=["Doki Doki Literature Club", "Disco Elysium", "Papers Please"],
)

PROJECT_DIR = ROOT / "data" / "games" / "capital-revolt"
GDD_PATH = PROJECT_DIR / "gdd.json"


async def step_design() -> dict:
    """Step 1: Generate VN GDD."""
    logger.info("=" * 60)
    logger.info("STEP 1: Generating VN GDD for 'Capital Revolt'")
    logger.info("=" * 60)

    config = load_config()

    # Skip if GDD already exists
    if GDD_PATH.exists():
        logger.info(f"GDD already exists at {GDD_PATH}, loading...")
        with open(GDD_PATH) as f:
            gdd = json.load(f)
        logger.info(f"Loaded GDD: {gdd.get('title', 'untitled')}")
    else:
        from agents.dev.designer.gdd_generator import generate_gdd

        gdd = await generate_gdd(GAME_PROPOSAL, config)

        # Validate
        if is_visual_novel(gdd):
            errors = validate_gdd(gdd)
            if errors:
                logger.error(f"VN GDD validation errors ({len(errors)}):")
                for e in errors:
                    logger.error(f"  - {e}")
                logger.info("Attempting to fix GDD by re-generating...")
                # Retry once
                gdd = await generate_gdd(GAME_PROPOSAL, config)
                if is_visual_novel(gdd):
                    errors = validate_gdd(gdd)
                    if errors:
                        logger.error(f"Still {len(errors)} validation errors after retry")
                        for e in errors:
                            logger.error(f"  - {e}")
            else:
                logger.info("VN GDD validation passed ✓")

        # Save GDD
        PROJECT_DIR.mkdir(parents=True, exist_ok=True)
        with open(GDD_PATH, "w", encoding="utf-8") as f:
            json.dump(gdd, f, ensure_ascii=False, indent=2)
        logger.info(f"GDD saved to {GDD_PATH}")

    # Print summary
    logger.info(f"Title: {gdd.get('title', 'N/A')}")
    logger.info(f"Genre: {gdd.get('genre', 'N/A')}")
    logger.info(f"Scenes: {len(gdd.get('scenes', []))}")
    logger.info(f"Mechanics: {len(gdd.get('mechanics', []))}")
    characters = gdd.get("character_roster", [])
    logger.info(f"Characters: {len(characters)}")
    for c in characters:
        logger.info(f"  - {c.get('name', '?')}: {c.get('role', '?')}")
    stats = gdd.get("stat_system", {}).get("stats", [])
    logger.info(f"Stats: {len(stats)}")
    for s in stats:
        logger.info(f"  - {s.get('name', '?')} [{s.get('range', [])}]")
    tree = gdd.get("branching_tree", {}).get("nodes", {})
    logger.info(f"Branching nodes: {len(tree)}")
    endings = gdd.get("ending_conditions", [])
    logger.info(f"Endings: {len(endings)}")
    for e in endings:
        logger.info(f"  - {e.get('name', '?')} (good={e.get('is_good_ending', '?')})")

    return gdd


async def step_art(gdd: dict) -> str | None:
    """Step 2: Generate art assets or create placeholder structure."""
    logger.info("=" * 60)
    logger.info("STEP 2: Art Generation")
    logger.info("=" * 60)

    assets_dir = PROJECT_DIR / "public" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    # Create character asset directories
    characters_dir = assets_dir / "characters"
    characters_dir.mkdir(exist_ok=True)

    for char in gdd.get("character_roster", []):
        char_name = char.get("name", "unknown").lower().replace(" ", "_")
        char_dir = characters_dir / char_name
        char_dir.mkdir(exist_ok=True)
        for expr in char.get("expression_variants", ["neutral", "happy", "sad"]):
            # Create placeholder PNG markers
            marker = char_dir / f"{expr}.png"
            if not marker.exists():
                marker.write_bytes(b"")

    # Create BG directories
    bg_dir = assets_dir / "backgrounds"
    bg_dir.mkdir(exist_ok=True)
    for scene in gdd.get("scenes", []):
        scene_name = scene.get("name", "unknown").lower().replace(" ", "_")
        bg_marker = bg_dir / f"{scene_name}.png"
        if not bg_marker.exists():
            bg_marker.write_bytes(b"")

    # Create CG directory
    cg_dir = assets_dir / "cg"
    cg_dir.mkdir(exist_ok=True)
    for cg in gdd.get("cg_milestones", []):
        cg_key = cg.get("cg_key", "unknown").lower().replace(" ", "_")
        cg_marker = cg_dir / f"{cg_key}.png"
        if not cg_marker.exists():
            cg_marker.write_bytes(b"")

    logger.info(f"Asset structure created at {assets_dir}")
    logger.info("Note: ComfyUI not available — code gen will use Phaser shape rendering")

    return str(assets_dir)


async def step_music(gdd: dict) -> dict:
    """Step 3: Generate music."""
    logger.info("=" * 60)
    logger.info("STEP 3: Music Generation")
    logger.info("=" * 60)

    state = CompanyState(
        phase=PipelinePhase.DEVELOPING,
        project_name=GAME_PROPOSAL.name,
        gdd=gdd,
    )

    from agents.dev.music.music_generator import generate_music

    result = await generate_music(state)
    logger.info(f"Music generation result: {json.dumps(result, default=str, indent=2)}")
    return result


async def step_code(gdd: dict, art_path: str | None = None, music_result: dict | None = None) -> str:
    """Step 4: Generate game code."""
    logger.info("=" * 60)
    logger.info("STEP 4: Code Generation")
    logger.info("=" * 60)

    state = CompanyState(
        phase=PipelinePhase.DEVELOPING,
        project_name=GAME_PROPOSAL.name,
        gdd=gdd,
        art_assets_path=art_path,
    )

    from agents.dev.programmer.agent import develop_game

    result = await develop_game(state)

    code_path = result.get("game_code_path")
    if code_path:
        logger.info(f"Game code generated at: {code_path}")
    else:
        logger.error(f"Code generation failed: {result}")

    return result


async def step_qa(code_path: str) -> dict:
    """Step 5: QA + Playtest."""
    logger.info("=" * 60)
    logger.info("STEP 5: QA + Playtest")
    logger.info("=" * 60)

    state = CompanyState(
        phase=PipelinePhase.TESTING,
        project_name=GAME_PROPOSAL.name,
        game_code_path=code_path,
    )

    from agents.dev.qa.qa_agent import run_qa

    result = await run_qa(state)
    logger.info(f"QA result: passed={result.get('qa_results', {}).get('passed', False)}")
    return result


async def step_build(code_path: str) -> dict:
    """Step 6: Final build."""
    logger.info("=" * 60)
    logger.info("STEP 6: Final Build")
    logger.info("=" * 60)

    state = CompanyState(
        phase=PipelinePhase.BUILDING,
        project_name=GAME_PROPOSAL.name,
        game_code_path=code_path,
    )

    from agents.dev.builder.build_agent import build_game

    result = await build_game(state)
    logger.info(f"Build result: {json.dumps(result, default=str, indent=2)}")
    return result


async def run_all():
    """Run the complete pipeline."""
    start = datetime.now()
    logger.info(f"Pipeline started at {start}")
    logger.info(f"Game: {GAME_PROPOSAL.name}")
    logger.info(f"Genre: {GAME_PROPOSAL.genre}")
    logger.info(f"Project dir: {PROJECT_DIR}")

    # Step 1: Design
    gdd = await step_design()

    # Step 2: Art
    art_path = await step_art(gdd)

    # Step 3: Music
    music_result = await step_music(gdd)

    # Step 4: Code
    code_result = await step_code(gdd, art_path, music_result)
    code_path = code_result.get("game_code_path")
    if not code_path:
        logger.error("Code generation failed — stopping pipeline")
        sys.exit(1)

    # Step 5: QA
    qa_result = await step_qa(code_path)
    if not qa_result.get("qa_results", {}).get("passed", False):
        logger.warning("QA failed — will need to fix and retry")
        logger.info(f"QA details: {json.dumps(qa_result, default=str, indent=2)}")

    # Step 6: Build
    build_result = await step_build(code_path)

    elapsed = (datetime.now() - start).total_seconds()
    logger.info(f"\n{'=' * 60}")
    logger.info(f"Pipeline completed in {elapsed:.0f}s")
    logger.info(f"Project dir: {PROJECT_DIR}")
    if code_path:
        dist = Path(code_path) / "dist"
        if dist.exists():
            logger.info(f"Build output: {dist}")
            logger.info(f"  Open {dist / 'index.html'} in a browser to play")
    logger.info(f"{'=' * 60}")


async def run_step(step: str):
    """Run a single step."""
    if step == "design":
        await step_design()
    elif step == "art":
        gdd = _load_gdd()
        await step_art(gdd)
    elif step == "music":
        gdd = _load_gdd()
        await step_music(gdd)
    elif step == "code":
        gdd = _load_gdd()
        await step_code(gdd)
    elif step == "qa":
        gdd = _load_gdd()
        code_result = await step_code(gdd)
        code_path = code_result.get("game_code_path", "")
        if code_path:
            await step_qa(code_path)
    elif step == "build":
        gdd = _load_gdd()
        code_result = await step_code(gdd)
        code_path = code_result.get("game_code_path", "")
        if code_path:
            await step_build(code_path)
    else:
        logger.error(f"Unknown step: {step}")
        sys.exit(1)


def _load_gdd() -> dict:
    if not GDD_PATH.exists():
        logger.error(f"No GDD found at {GDD_PATH}. Run step 'design' first.")
        sys.exit(1)
    with open(GDD_PATH, encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    step = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--step" else "all"
    if step == "all":
        asyncio.run(run_all())
    else:
        asyncio.run(run_step(step))

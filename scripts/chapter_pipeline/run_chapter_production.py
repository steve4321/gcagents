"""Chapter-based production orchestrator.

Usage:
    python -m scripts.chapter_pipeline.run_chapter_production \\
        --gdd data/games/capital-revolt/gdd.json \\
        --output data/games/capital-revolt-chapters \\
        --chapters 5 \\
        --per-chapter-nodes 25

Pipeline per chapter:
1. Extract/load World Bible
2. Generate chapter GDD (or use provided one)
3. Run art pipeline (ComfyUI backgrounds + character sprites)
4. Run code generation (route-by-route, but constrained to chapter)
5. Validate chapter against bible
6. After all chapters: merge into unified game with chapter selection
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from loguru import logger

from scripts.chapter_pipeline.world_bible import (
    extract_world_bible,
    validate_chapter_against_bible,
)
from scripts.chapter_pipeline.chapter_splitter import split_gdd_into_chapters
from scripts.chapter_pipeline.chapter_merger import merge_chapters, generate_chapter_selection_html


async def run_chapter_production(
    gdd_path: Path,
    output_dir: Path,
    num_chapters: int = 5,
    per_chapter_nodes: int = 25,
) -> dict:
    """Run the full chapter-based production pipeline."""
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"=== Chapter Production: {num_chapters} chapters ===")
    logger.info(f"GDD: {gdd_path}")
    logger.info(f"Output: {output_dir}")

    logger.info("Step 1: Extracting World Bible...")
    gdd = json.loads(gdd_path.read_text(encoding="utf-8"))
    bible = extract_world_bible(gdd, output_dir / "data" / "world_bible.json")
    logger.info(
        f"World Bible: {len(bible['characters'])} characters, "
        f"{len(bible['locations'])} locations, {len(bible['stats'])} stats, "
        f"{len(bible['routes'])} routes"
    )

    logger.info(f"Step 2: Splitting into {num_chapters} chapters...")
    chapter_gdds = split_gdd_into_chapters(
        gdd, bible, num_chapters=num_chapters,
        output_dir=output_dir / "chapter_gdds",
    )
    for ch in chapter_gdds:
        logger.info(
            f"  Chapter {ch['chapter_id']}: {ch['chapter_title']} "
            f"({len(ch['route_structure']['character_routes'])} routes)"
        )

    chapter_data_list = []
    for ch_gdd in chapter_gdds:
        ch_id = ch_gdd["chapter_id"]
        logger.info(f"=== Generating Chapter {ch_id}: {ch_gdd['chapter_title']} ===")

        ch_output = output_dir / f"chapter_{ch_id}"
        ch_output.mkdir(exist_ok=True)

        logger.info(f"  [{ch_id}.1] Generating art assets...")
        art_result = await _run_chapter_art(ch_gdd, ch_output / "public" / "assets")
        logger.info(f"  [{ch_id}.1] Art: {art_result}")

        logger.info(f"  [{ch_id}.2] Generating code + data...")
        code_result = await _run_chapter_code(ch_gdd, ch_output, art_result)
        logger.info(f"  [{ch_id}.2] Code: {code_result}")

        ch_data = _extract_chapter_data(ch_output, ch_gdd)
        if ch_data:
            errors = validate_chapter_against_bible(ch_data, bible)
            if errors:
                logger.warning(f"  [{ch_id}.3] Bible validation issues ({len(errors)}):")
                for e in errors[:5]:
                    logger.warning(f"    - {e}")
            else:
                logger.info(f"  [{ch_id}.3] Bible validation passed ✅")
            chapter_data_list.append(ch_data)
        else:
            logger.error(f"  [{ch_id}] No data extracted — skipping")

    logger.info(f"Step 4: Merging {len(chapter_data_list)} chapters into unified game...")
    merge_result = merge_chapters(chapter_data_list, bible, output_dir / "final")
    logger.info(f"Merged: {merge_result['stats']}")

    chapter_selection_html = generate_chapter_selection_html(bible, chapter_gdds)
    (output_dir / "final" / "chapter_select.html").write_text(
        chapter_selection_html, encoding="utf-8"
    )

    _copy_art_assets(output_dir, output_dir / "final" / "public" / "assets")

    return {
        "bible": bible,
        "chapters": chapter_gdds,
        "merge_result": merge_result,
        "output_dir": output_dir,
    }


async def _run_chapter_art(chapter_gdd: dict, output_dir: Path) -> dict:
    """Run ComfyUI art generation for one chapter."""
    from agents.dev.artist.comfyui_client import ComfyUIClient
    from agents.dev.artist.sprite_generator import SpriteGenerator
    from agents.dev.artist.art_style import resolve_art_style

    output_dir.mkdir(parents=True, exist_ok=True)
    bg_dir = output_dir / "backgrounds"
    char_dir = output_dir / "characters"
    bg_dir.mkdir(exist_ok=True)
    char_dir.mkdir(exist_ok=True)

    generated = {"backgrounds": 0, "characters": 0, "errors": []}
    try:
        client = ComfyUIClient(base_url="http://localhost:8188")
        style = resolve_art_style(chapter_gdd)
        gen = SpriteGenerator(client, art_style=style)

        bg_names = [f"ch{chapter_gdd['chapter_id']}_{scene.get('name','scene').lower().replace(' ','_')}"
                    for scene in chapter_gdd.get("scenes", [])[:3]]
        for i, scene in enumerate(chapter_gdd.get("scenes", [])[:3]):
            bg_name = bg_names[i]
            try:
                result = await gen.generate_vn_background(
                    scene_name=bg_name,
                    scene_description=scene.get("description", scene.get("name", "scene")),
                    output_dir=bg_dir,
                )
                if result:
                    generated["backgrounds"] += 1
            except Exception as e:
                generated["errors"].append(f"BG {bg_name}: {e}")

        if chapter_gdd.get("character_roster"):
            try:
                char_results = await gen.generate_vn_character_sprites(
                    characters=chapter_gdd["character_roster"][:4],
                    output_dir=char_dir,
                )
                if char_results:
                    generated["characters"] += len(char_results)
            except Exception as e:
                generated["errors"].append(f"Characters: {e}")
    except Exception as e:
        generated["errors"].append(f"Pipeline: {e}")

    return generated


async def _run_chapter_code(chapter_gdd: dict, output_dir: Path, art_result: dict) -> dict:
    """Run code generation for one chapter using the resilient per-chapter pipeline."""
    from scripts.chapter_pipeline.chapter_codegen import generate_chapter_code_resilient

    art_path = str(output_dir / "public" / "assets") if art_result.get("backgrounds", 0) > 0 else None
    try:
        result = await generate_chapter_code_resilient(
            chapter_gdd=chapter_gdd,
            project_dir=output_dir,
            art_assets_path=art_path,
        )
        return result
    except Exception as e:
        logger.error(f"Code gen failed for chapter: {e}")
        return {"error": str(e), "code_path": output_dir}


def _extract_chapter_data(ch_output: Path, ch_gdd: dict) -> dict | None:
    """Extract branching/dialogue/endings from a generated chapter output."""
    data_dir = ch_output / "src" / "game" / "data"
    branching_path = data_dir / "branching.json"
    dialogue_path = data_dir / "dialogue.json"
    endings_path = data_dir / "endings.json"

    if not branching_path.exists() or not dialogue_path.exists():
        return None

    branching = json.loads(branching_path.read_text(encoding="utf-8"))
    dialogue = json.loads(dialogue_path.read_text(encoding="utf-8"))
    endings = []
    if endings_path.exists():
        endings = json.loads(endings_path.read_text(encoding="utf-8"))
        if not isinstance(endings, list):
            endings = endings.get("endings", [])

    return {
        "chapter_id": ch_gdd["chapter_id"],
        "chapter_title": ch_gdd["chapter_title"],
        "entry_node": ch_gdd.get("entry_node", "common_start"),
        "exit_node": ch_gdd.get("exit_node"),
        "branching": branching,
        "dialogue": dialogue,
        "endings": endings,
    }


def _copy_art_assets(source_dir: Path, target_dir: Path) -> None:
    """Copy all generated art assets from chapter outputs to the final game."""
    import shutil
    target_dir.mkdir(parents=True, exist_ok=True)
    for ch_dir in source_dir.glob("chapter_*"):
        if not ch_dir.is_dir():
            continue
        src_assets = ch_dir / "public" / "assets"
        if not src_assets.exists():
            continue
        for sub in src_assets.iterdir():
            if sub.is_dir():
                dest = target_dir / sub.name
                dest.mkdir(exist_ok=True)
                for f in sub.iterdir():
                    if f.is_file() and f.suffix in (".png", ".jpg", ".wav", ".mp3", ".ogg"):
                        shutil.copy2(f, dest / f.name)


def main():
    parser = argparse.ArgumentParser(description="Chapter-based VN production")
    parser.add_argument("--gdd", type=Path, required=True, help="Path to full GDD")
    parser.add_argument("--output", type=Path, required=True, help="Output directory")
    parser.add_argument("--chapters", type=int, default=5, help="Number of chapters")
    parser.add_argument("--per-chapter-nodes", type=int, default=25, help="Target nodes per chapter route")
    args = parser.parse_args()

    asyncio.run(run_chapter_production(
        gdd_path=args.gdd,
        output_dir=args.output,
        num_chapters=args.chapters,
        per_chapter_nodes=args.per_chapter_nodes,
    ))


if __name__ == "__main__":
    main()

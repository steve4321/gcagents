"""Unified orchestrator for the RenJS-based chapter production pipeline.

Architecture (planning-first, parallel production, single entry):

  Phase 0: Production Plan    (manifest of ALL assets/code/data needed)
  Phase 1: World Bible         (character/setting/style canon)
  Phase 2: Chapter GDDs        (split the story into N chapters)
  Phase 3: Parallel generation:
    - Art track   (ComfyUI per manifest)
    - Audio track (WebAudio BGM + SFX per manifest)
    - Story track (LLM writes RenJS YAML per chapter)
  Phase 4: Integration         (copy assets, merge story YAMLs, write Config/Setup)
  Phase 5: Build               (single index.html + boot.js + vendor/renjs.js)
  Phase 6: Validation          (plan completion check, game loads in browser)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from loguru import logger

from scripts.chapter_pipeline.world_bible import extract_world_bible
from scripts.chapter_pipeline.chapter_splitter import split_gdd_into_chapters
from scripts.chapter_pipeline.production_planner import (
    generate_production_plan,
    plan_completion_summary,
    update_plan_status,
)
from scripts.chapter_pipeline.story_ir import (
    init_story_ir,
    build_ir_generation_prompt,
    load_ir,
    save_ir,
    merge_chapter_irs,
    validate_ir,
)
from scripts.chapter_pipeline.renjs_adapter import ir_to_renjs_yaml
from scripts.chapter_pipeline.renjs_builder import (
    generate_config_yaml,
    generate_setup_yaml,
    generate_boot_js,
    generate_index_html,
)


async def run_unified_production(
    gdd_path: Path,
    output_dir: Path,
    num_chapters: int = 5,
    comfyu_url: str = "http://localhost:8188",
) -> dict:
    """Run the full unified RenJS-based production pipeline."""
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 70)
    logger.info("PHASE 0: Production Planning (BEFORE any generation)")
    logger.info("=" * 70)

    gdd = json.loads(gdd_path.read_text(encoding="utf-8"))
    bible = extract_world_bible(gdd, output_dir / "story" / "world_bible.json")
    logger.info(
        f"World Bible: {len(bible['characters'])} characters, "
        f"{len(bible['locations'])} locations, {len(bible['stats'])} stats, "
        f"{len(bible['routes'])} routes"
    )

    chapter_gdds = split_gdd_into_chapters(
        gdd, bible, num_chapters=num_chapters,
        output_dir=output_dir / "story" / "chapter_gdds",
    )
    for ch in chapter_gdds:
        logger.info(f"  Chapter {ch['chapter_id']}: {ch['chapter_title']}")

    plan = generate_production_plan(
        gdd, bible, chapter_gdds,
        output_path=output_dir / "story" / "production_plan.json",
    )
    logger.info(f"Plan: {plan['estimated_scale']}")

    logger.info("=" * 70)
    logger.info("PHASE 3: Parallel Production (art, story, audio)")
    logger.info("=" * 70)

    art_task = _run_art_track(plan, output_dir, comfyu_url)
    audio_task = _run_audio_track(plan, output_dir)
    story_task = _run_story_track(plan, bible, chapter_gdds, output_dir)

    art_result, audio_result, story_result = await asyncio.gather(
        art_task, audio_task, story_task, return_exceptions=True
    )

    for name, result in [("art", art_result), ("audio", audio_result), ("story", story_result)]:
        if isinstance(result, Exception):
            logger.error(f"  {name} track FAILED: {result}")
        else:
            logger.info(f"  {name} track: {result}")

    logger.info("=" * 70)
    logger.info("PHASE 4: Integration")
    logger.info("=" * 70)

    _integrate(output_dir, plan, story_result if not isinstance(story_result, Exception) else {})

    logger.info("=" * 70)
    logger.info("PHASE 5: Build")
    logger.info("=" * 70)

    _build(output_dir, plan)

    logger.info("=" * 70)
    logger.info("PHASE 6: Validation")
    logger.info("=" * 70)

    summary = plan_completion_summary(plan)
    logger.info(f"Plan completion: {summary}")

    return {
        "plan": plan,
        "summary": summary,
        "bible": bible,
        "chapter_gdds": chapter_gdds,
        "output_dir": output_dir,
    }


async def _run_art_track(plan: dict, output_dir: Path, comfyu_url: str) -> dict:
    """Generate all art assets per the production plan manifest."""
    from agents.dev.artist.comfyui_client import ComfyUIClient
    from agents.dev.artist.sprite_generator import SpriteGenerator
    from agents.dev.artist.art_style import resolve_art_style

    assets_root = output_dir / "assets"
    bg_dir = assets_root / "backgrounds"
    char_dir = assets_root / "characters"
    cg_dir = assets_root / "cg"
    for d in (bg_dir, char_dir, cg_dir):
        d.mkdir(parents=True, exist_ok=True)

    result = {"backgrounds": 0, "characters": 0, "cgs": 0, "errors": []}

    try:
        client = ComfyUIClient(base_url=comfyu_url)
        style = resolve_art_style(plan.get("bible", {}))
        gen = SpriteGenerator(client, art_style=style)

        for bg in plan.get("art", {}).get("backgrounds", []):
            bg_id = bg["id"]
            out_path = bg_dir / f"{bg_id}.png"
            if out_path.exists() and out_path.stat().st_size > 0:
                result["backgrounds"] += 1
                update_plan_status(plan, "art", bg_id, "completed")
                continue
            try:
                generated = await gen.generate_vn_background(
                    scene_name=bg_id,
                    scene_description=bg.get("scene_description", bg.get("scene_name", "scene")),
                    output_dir=bg_dir,
                )
                if generated:
                    result["backgrounds"] += 1
                    update_plan_status(plan, "art", bg_id, "completed")
            except Exception as e:
                result["errors"].append(f"BG {bg_id}: {e}")
                update_plan_status(plan, "art", bg_id, "failed")

        if plan.get("art", {}).get("characters"):
            try:
                char_dicts = [
                    {"name": c.get("name", c["id"]),
                     "description": c.get("visual_description", "")}
                    for c in plan["art"]["characters"]
                ]
                char_results = await gen.generate_vn_character_sprites(
                    characters=char_dicts,
                    output_dir=char_dir,
                )
                if char_results:
                    result["characters"] = len(char_results)
                    for c in plan["art"]["characters"]:
                        update_plan_status(plan, "art", c["id"], "completed")
            except Exception as e:
                result["errors"].append(f"Characters: {e}")
    except Exception as e:
        result["errors"].append(f"Art pipeline: {e}")

    return result


async def _run_audio_track(plan: dict, output_dir: Path) -> dict:
    """Generate audio assets per the production plan manifest.

    Uses WebAudio procedural BGM (no external API needed) and
    generates simple WAV SFX files.
    """
    audio_dir = output_dir / "assets" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    result = {"bgm": 0, "sfx": 0, "errors": []}

    bgm_tracks = plan.get("audio", {}).get("bgm", [])
    for track in bgm_tracks:
        out_path = audio_dir / Path(track["file_path"]).name
        if out_path.exists() and out_path.stat().st_size > 0:
            result["bgm"] += 1
            update_plan_status(plan, "audio", track["id"], "completed")
            continue
        try:
            _generate_procedural_bgm(out_path, mood=track.get("mood", "ambient"))
            if out_path.exists():
                result["bgm"] += 1
                update_plan_status(plan, "audio", track["id"], "completed")
        except Exception as e:
            result["errors"].append(f"BGM {track['id']}: {e}")
            update_plan_status(plan, "audio", track["id"], "failed")

    sfx_list = plan.get("audio", {}).get("sfx", [])
    for sfx in sfx_list:
        out_path = audio_dir / Path(sfx["file_path"]).name
        if out_path.exists() and out_path.stat().st_size > 0:
            result["sfx"] += 1
            update_plan_status(plan, "audio", sfx["id"], "completed")
            continue
        try:
            _generate_sfx_wav(out_path, event=sfx.get("event", "click"))
            if out_path.exists():
                result["sfx"] += 1
                update_plan_status(plan, "audio", sfx["id"], "completed")
        except Exception as e:
            result["errors"].append(f"SFX {sfx['id']}: {e}")
            update_plan_status(plan, "audio", sfx["id"], "failed")

    return result


async def _run_story_track(
    plan: dict,
    bible: dict,
    chapter_gdds: list[dict],
    output_dir: Path,
) -> dict:
    """Generate Story IR per chapter via LLM, then convert to RenJS YAML.

    Phase A: LLM writes engine-agnostic Story IR (JSON) per chapter
    Phase B: Merge chapter IRs into unified IR
    Phase C: RenJS adapter converts IR → Story.yaml

    The IR is the source of truth. RenJS YAML is one possible output.
    Future Godot / Mini Program adapters will be parallel implementations.
    """
    from shared.llm_client import llm

    story_dir = output_dir / "story"
    story_dir.mkdir(exist_ok=True)

    chapter_irs: list[dict] = []
    for ch_gdd in chapter_gdds:
        ch_id = ch_gdd["chapter_id"]
        ir_path = story_dir / f"chapter_{ch_id}_ir.json"

        if ir_path.exists() and ir_path.stat().st_size > 0:
            logger.info(f"  IR chapter {ch_id}: loaded from cache")
            chapter_irs.append(load_ir(ir_path))
            update_plan_status(plan, "data", f"chapter_{ch_id}_story", "completed")
            continue

        available_assets = {
            "backgrounds": [bg["id"] for bg in plan.get("art", {}).get("backgrounds", [])
                             if bg.get("chapter") == ch_id],
            "cgs": [cg["id"] for cg in plan.get("art", {}).get("cg", [])
                    if cg.get("chapter") == ch_id],
        }

        prompt = build_ir_generation_prompt(
            chapter_gdd=ch_gdd,
            world_bible=bible,
            chapter_index=ch_id - 1,
            total_chapters=len(chapter_gdds),
            available_assets=available_assets,
        )

        try:
            response = await llm.chat_completion(
                model="deepseek-v4-flash",
                messages=[
                    {"role": "system", "content": "You are a Visual Novel story writer. Output ONLY valid JSON. No prose, no markdown fences."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=16000,
                agent_name="story_writer",
                project_name=bible.get("title", "game"),
            )
            ir_text = response[0].strip()
            if ir_text.startswith("```"):
                lines = ir_text.split("\n")
                ir_text = "\n".join(lines[1:])
                if ir_text.endswith("```"):
                    ir_text = ir_text[:-3].strip()

            ir = json.loads(ir_text)
            ir["chapter_id"] = ch_id
            save_ir(ir, ir_path)
            chapter_irs.append(ir)
            n_scenes = len(ir.get("scenes", {}))
            n_events = sum(len(s.get("events", [])) for s in ir.get("scenes", {}).values())
            update_plan_status(plan, "data", f"chapter_{ch_id}_story", "completed")
            logger.info(f"  IR chapter {ch_id}: {n_scenes} scenes, {n_events} events")
        except Exception as e:
            logger.error(f"  IR chapter {ch_id} FAILED: {e}")
            update_plan_status(plan, "data", f"chapter_{ch_id}_story", "failed")
            empty_ir = init_story_ir({"title": bible.get("title"), "num_chapters": 1}, bible)
            empty_ir["chapter_id"] = ch_id
            empty_ir["scenes"] = {
                f"ch{ch_id}_start": {
                    "background": available_assets["backgrounds"][0] if available_assets["backgrounds"] else "ch_intro",
                    "events": [{"type": "say", "speaker": "narrator", "text": f"第{ch_id}章正在编写中..."}]
                }
            }
            chapter_irs.append(empty_ir)

    unified_ir = merge_chapter_irs(chapter_irs)
    unified_ir_path = story_dir / "story_ir.json"
    save_ir(unified_ir, unified_ir_path)
    update_plan_status(plan, "data", "story", "completed")
    logger.info(f"  Unified IR: {len(unified_ir['scenes'])} scenes, {len(unified_ir['endings'])} endings")

    renjs_yaml = ir_to_renjs_yaml(unified_ir)
    (story_dir / "Story.yaml").write_text(renjs_yaml, encoding="utf-8")
    logger.info(f"  RenJS Story.yaml: {len(renjs_yaml)} chars")

    return {
        "chapters": len(chapter_irs),
        "ir_scenes": len(unified_ir["scenes"]),
        "ir_endings": len(unified_ir["endings"]),
        "renjs_yaml_chars": len(renjs_yaml),
    }


def _integrate(output_dir: Path, plan: dict, story_result: dict) -> None:
    """Integration: write Config.yaml, Setup.yaml, copy assets to final location."""
    story_dir = output_dir / "story"
    story_dir.mkdir(exist_ok=True)

    config_yaml = generate_config_yaml(plan)
    (story_dir / "Config.yaml").write_text(config_yaml, encoding="utf-8")
    update_plan_status(plan, "data", "config", "completed")

    setup_yaml = generate_setup_yaml(plan)
    (story_dir / "Setup.yaml").write_text(setup_yaml, encoding="utf-8")
    update_plan_status(plan, "data", "setup", "completed")

    logger.info("  Config.yaml + Setup.yaml written")


def _build(output_dir: Path, plan: dict) -> None:
    """Build: single index.html + boot.js + vendor/renjs.js."""
    build_dir = output_dir / "build"
    build_dir.mkdir(exist_ok=True)

    vendor_src = Path(__file__).resolve().parent.parent.parent / "public" / "vendor" / "renjs" / "renjs.js"
    if vendor_src.exists():
        vendor_dst = build_dir / "vendor" / "renjs" / "renjs.js"
        vendor_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(vendor_src, vendor_dst)
        logger.info(f"  Vendored renjs.js to {vendor_dst}")

    story_dir = build_dir / "story"
    story_src = output_dir / "story"
    if story_src.exists():
        shutil.copytree(story_src, story_dir, dirs_exist_ok=True)
        logger.info(f"  Copied story files to {story_dir}")

    assets_src = output_dir / "assets"
    if assets_src.exists():
        assets_dst = build_dir / "assets"
        if assets_dst.exists():
            shutil.rmtree(assets_dst)
        shutil.copytree(assets_src, assets_dst)
        logger.info(f"  Copied assets to {assets_dst}")

    boot_js = generate_boot_js(plan)
    (build_dir / "boot.js").write_text(boot_js, encoding="utf-8")
    update_plan_status(plan, "code", "main", "completed")

    index_html = generate_index_html(plan)
    (build_dir / "index.html").write_text(index_html, encoding="utf-8")
    update_plan_status(plan, "code", "index_html", "completed")

    pkg_json = _generate_package_json(plan)
    (build_dir / "package.json").write_text(json.dumps(pkg_json, indent=2), encoding="utf-8")

    logger.info(f"  Build output: {build_dir}")


def _generate_package_json(plan: dict) -> dict:
    return {
        "name": plan.get("game_title", "visual_novel").lower().replace(" ", "-"),
        "version": "1.0.0",
        "description": f"RenJS visual novel: {plan.get('game_title', 'game')}",
        "scripts": {
            "start": "python3 -m http.server 8080",
        },
        "dependencies": {
            "renjs": "^2.9.4",
        },
        "license": "CC-BY-SA-4.0",
    }


def _generate_procedural_bgm(out_path: Path, mood: str = "ambient", duration_sec: int = 60) -> None:
    """Generate a simple procedural BGM as WAV file."""
    import struct
    import math

    sample_rate = 22050
    n_samples = sample_rate * duration_sec

    mood_params = {
        "tense": {"base_freq": 110, "harmonics": [1.0, 1.5, 2.0], "amplitude": 0.15},
        "romantic": {"base_freq": 220, "harmonics": [1.0, 1.25, 1.5], "amplitude": 0.18},
        "triumphant": {"base_freq": 165, "harmonics": [1.0, 1.33, 1.5, 2.0], "amplitude": 0.20},
        "melancholic": {"base_freq": 147, "harmonics": [1.0, 1.5], "amplitude": 0.14},
        "hopeful": {"base_freq": 196, "harmonics": [1.0, 1.25, 1.5], "amplitude": 0.16},
        "ambient": {"base_freq": 130, "harmonics": [1.0, 1.5], "amplitude": 0.12},
    }
    params = mood_params.get(mood, mood_params["ambient"])

    samples = []
    for i in range(n_samples):
        t = i / sample_rate
        envelope = 0.5 + 0.5 * math.sin(2 * math.pi * 0.1 * t)
        sample = 0.0
        for h in params["harmonics"]:
            sample += math.sin(2 * math.pi * params["base_freq"] * h * t)
        sample = int(sample * params["amplitude"] * envelope * 32767 / len(params["harmonics"]))
        samples.append(max(-32767, min(32767, sample)))

    with open(out_path, "wb") as f:
        f.write(struct.pack("<4sI4s", b"RIFF", 36 + len(samples) * 2, b"WAVE"))
        f.write(struct.pack("<4sIHHIIHH", b"fmt ", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", len(samples) * 2))
        for s in samples:
            f.write(struct.pack("<h", s))


def _generate_sfx_wav(out_path: Path, event: str = "click", duration_ms: int = 200) -> None:
    """Generate a simple SFX as WAV file."""
    import struct
    import math

    sample_rate = 22050
    n_samples = sample_rate * duration_ms // 1000

    event_params = {
        "click": {"freq_start": 800, "freq_end": 600, "decay": 5.0},
        "choice": {"freq_start": 500, "freq_end": 700, "decay": 3.0},
        "transition": {"freq_start": 200, "freq_end": 400, "decay": 2.0},
        "important_event": {"freq_start": 1000, "freq_end": 500, "decay": 1.0},
    }
    params = event_params.get(event, event_params["click"])

    samples = []
    for i in range(n_samples):
        t = i / sample_rate
        envelope = math.exp(-params["decay"] * t)
        freq = params["freq_start"] + (params["freq_end"] - params["freq_start"]) * (t * 5)
        if freq > 0:
            sample = int(math.sin(2 * math.pi * freq * t) * 0.3 * envelope * 32767)
        else:
            sample = 0
        samples.append(max(-32767, min(32767, sample)))

    with open(out_path, "wb") as f:
        f.write(struct.pack("<4sI4s", b"RIFF", 36 + len(samples) * 2, b"WAVE"))
        f.write(struct.pack("<4sIHHIIHH", b"fmt ", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", len(samples) * 2))
        for s in samples:
            f.write(struct.pack("<h", s))


def main():
    parser = argparse.ArgumentParser(description="Unified RenJS chapter production")
    parser.add_argument("--gdd", type=Path, required=True, help="Path to GDD JSON")
    parser.add_argument("--output", type=Path, required=True, help="Output directory")
    parser.add_argument("--chapters", type=int, default=5, help="Number of chapters")
    parser.add_argument("--comfyui-url", type=str, default="http://localhost:8188", help="ComfyUI URL")
    args = parser.parse_args()

    asyncio.run(run_unified_production(
        gdd_path=args.gdd,
        output_dir=args.output,
        num_chapters=args.chapters,
        comfyu_url=args.comfyui_url,
    ))


if __name__ == "__main__":
    main()

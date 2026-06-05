from __future__ import annotations

import asyncio
import re

import httpx
from loguru import logger

from orchestrator.state import CompanyState, PipelinePhase
from shared.config import load_config
from shared.vn_schema import is_visual_novel

from .art_style import resolve_art_style
from .comfyui_client import ComfyUIClient
from .sprite_generator import SpriteGenerator


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_")


async def generate_art(state: CompanyState) -> dict:
    gdd = state.gdd
    if not gdd:
        logger.error("No GDD available for art generation")
        return {"phase": PipelinePhase.DEVELOPING, "errors": ["Missing GDD"]}

    config = load_config()
    project_name = _slugify(gdd.get("title", "untitled_game"))
    output_dir = config.games_output_dir / project_name / "assets"
    output_dir.mkdir(parents=True, exist_ok=True)

    art_style_config = resolve_art_style(gdd)
    style = art_style_config.style_key

    if is_visual_novel(gdd):
        return await _generate_vn_art(state, gdd, config, art_style_config)

    entities = gdd.get("entities", [])
    scenes = gdd.get("scenes", [])
    ui_layout = gdd.get("ui_layout", {})

    sprite_characters = [e["name"] for e in entities if e.get("type") == "sprite"]
    scene_themes = [s.get("name", "scene") for s in scenes]
    ui_elements = ui_layout.get("hud", []) + ui_layout.get("menus", [])

    client = ComfyUIClient(base_url=config.comfyui_url)
    generator = SpriteGenerator(client, art_style=art_style_config)

    try:
        tasks = []
        if sprite_characters:
            tasks.append(generator.generate_character_sprites(style, sprite_characters, output_dir))

        for scene in scene_themes:
            theme = f"{scene} scene for {project_name}"
            tasks.append(generator.generate_background(theme, output_dir=output_dir))

        if ui_elements:
            tasks.append(generator.generate_ui_elements(style, ui_elements, output_dir))

        if tasks:
            await asyncio.gather(*tasks)

        logger.info(f"Art generation complete for: {project_name}")
        return {"phase": PipelinePhase.DEVELOPING, "art_assets_path": str(output_dir)}

    except httpx.HTTPError:
        logger.warning(
            "ComfyUI unavailable - falling back to Phaser shape rendering (no art assets needed)"
        )
        return {"phase": PipelinePhase.DEVELOPING, "art_assets_path": ""}
    except Exception as e:
        logger.error(f"Art generation failed: {e}")
        return {"phase": PipelinePhase.DEVELOPING, "art_assets_path": "", "errors": [str(e)]}


async def _generate_vn_art(
    state: CompanyState,
    gdd: dict,
    config,
    art_style_config,
) -> dict:
    project_name = _slugify(gdd.get("title", "untitled_game"))
    output_dir = config.games_output_dir / project_name / "assets"
    output_dir.mkdir(parents=True, exist_ok=True)

    client = ComfyUIClient(base_url=config.comfyui_url)
    generator = SpriteGenerator(client, art_style=art_style_config)

    try:
        tasks = []

        character_roster = gdd.get("character_roster", [])
        if character_roster:
            characters_for_sprites = []
            for char in character_roster:
                characters_for_sprites.append({
                    "name": char.get("name", "unknown"),
                    "description": char.get("base_description", char.get("description", "")),
                    "expressions": char.get("expression_variants", ["neutral"]),
                })
            tasks.append(
                generator.generate_vn_character_sprites(characters_for_sprites, output_dir)
            )

        scenes = gdd.get("scenes", [])
        for scene in scenes:
            scene_name = scene.get("name", scene.get("scene_key", "scene"))
            scene_desc = scene.get("description", scene_name)
            tasks.append(
                generator.generate_vn_background(scene_name, scene_desc, output_dir)
            )

        cg_milestones = gdd.get("cg_milestones", [])
        for cg in cg_milestones:
            cg_key = cg.get("cg_key", "cg")
            scene_desc = cg.get("description", cg.get("scene_id", ""))
            characters = cg.get("characters", [])
            tasks.append(
                generator.generate_vn_cg(cg_key, scene_desc, characters, output_dir)
            )

        if tasks:
            await asyncio.gather(*tasks)

        logger.info(f"VN art generation complete for: {project_name}")
        return {"phase": PipelinePhase.DEVELOPING, "art_assets_path": str(output_dir)}

    except httpx.HTTPError:
        logger.warning(
            "ComfyUI unavailable for VN art - skipping art assets"
        )
        return {"phase": PipelinePhase.DEVELOPING, "art_assets_path": ""}
    except Exception as e:
        logger.error(f"VN art generation failed: {e}")
        return {"phase": PipelinePhase.DEVELOPING, "art_assets_path": "", "errors": [str(e)]}

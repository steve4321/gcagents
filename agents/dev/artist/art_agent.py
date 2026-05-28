from __future__ import annotations

import re
from pathlib import Path

import httpx
from loguru import logger

from orchestrator.state import CompanyState, PipelinePhase
from shared.config import load_config

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

    art_style = gdd.get("art_style", {})
    style = art_style.get("theme", "pixel-art")

    entities = gdd.get("entities", [])
    scenes = gdd.get("scenes", [])
    ui_layout = gdd.get("ui_layout", {})

    sprite_characters = [e["name"] for e in entities if e.get("type") == "sprite"]
    scene_themes = [s.get("name", "scene") for s in scenes]
    ui_elements = ui_layout.get("hud", []) + ui_layout.get("menus", [])

    client = ComfyUIClient(base_url=config.comfyui_url)
    generator = SpriteGenerator(client)

    try:
        if sprite_characters:
            await generator.generate_character_sprites(style, sprite_characters, output_dir)

        for scene in scene_themes:
            theme = f"{scene} scene for {project_name}"
            await generator.generate_background(theme, output_dir=output_dir)

        if ui_elements:
            await generator.generate_ui_elements(style, ui_elements, output_dir)

        logger.info(f"Art generation complete for: {project_name}")
        return {"phase": PipelinePhase.DEVELOPING, "art_assets_path": str(output_dir)}

    except httpx.ConnectError:
        logger.warning("ComfyUI unavailable - falling back to Phaser shape rendering (no art assets needed)")
        return {"phase": PipelinePhase.DEVELOPING, "art_assets_path": ""}
    except Exception as e:
        logger.error(f"Art generation failed: {e}")
        return {"phase": PipelinePhase.DEVELOPING, "art_assets_path": "", "errors": [str(e)]}

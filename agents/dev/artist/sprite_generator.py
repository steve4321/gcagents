from __future__ import annotations

from pathlib import Path

from loguru import logger

from .comfyui_client import ComfyUIClient
from .workflows import (
    BACKGROUND_WORKFLOW,
    CHARACTER_SPRITE_WORKFLOW,
    UI_ELEMENT_WORKFLOW,
    build_workflow,
)

DEFAULT_NEGATIVE_PROMPT = "blurry, low quality, distorted, ugly, bad anatomy, watermark, text, signature, realistic, photo"


class SpriteGenerator:
    def __init__(self, client: ComfyUIClient):
        self._client = client

    async def generate_character_sprites(
        self,
        style: str,
        characters: list[str],
        output_dir: Path,
    ) -> dict[str, Path]:
        logger.info(f"Generating {len(characters)} character sprites in style: {style}")
        results: dict[str, Path] = {}

        for character in characters:
            positive = f"pixel art character sprite {character}, {style} style, game asset, transparent background, full body centered, 8-bit retro game character, high quality, clean outlines"
            workflow = build_workflow(CHARACTER_SPRITE_WORKFLOW, positive, DEFAULT_NEGATIVE_PROMPT)
            workflow["7"]["inputs"]["filename_prefix"] = f"char_{character.lower().replace(' ', '_')}"

            prompt_id = await self._client.queue_prompt(workflow)
            images = await self._client.get_output_images(prompt_id, output_dir)
            if images:
                results[character] = images[0]
                logger.info(f"Generated sprite for {character}: {images[0]}")

        return results

    async def generate_background(
        self,
        theme: str,
        dimensions: tuple[int, int] = (1024, 512),
        output_dir: Path | None = None,
    ) -> Path | None:
        logger.info(f"Generating background: {theme} ({dimensions[0]}x{dimensions[1]})")

        positive = f"pixel art game background {theme}, game environment tileset, 2D side-scrolling level, retro game scenery, vibrant colors, looping tile"
        workflow = build_workflow(BACKGROUND_WORKFLOW, positive, DEFAULT_NEGATIVE_PROMPT)
        workflow["4"]["inputs"]["width"] = dimensions[0]
        workflow["4"]["inputs"]["height"] = dimensions[1]
        workflow["7"]["inputs"]["filename_prefix"] = f"bg_{theme.lower().replace(' ', '_')}"

        prompt_id = await self._client.queue_prompt(workflow)
        images = await self._client.get_output_images(prompt_id, output_dir)

        if images:
            logger.info(f"Generated background: {images[0]}")
            return images[0]

        return None

    async def generate_ui_elements(
        self,
        style: str,
        elements: list[str],
        output_dir: Path,
    ) -> dict[str, Path]:
        logger.info(f"Generating {len(elements)} UI elements in style: {style}")
        results: dict[str, Path] = {}

        for element in elements:
            positive = f"pixel art ui icon {element}, {style} style, game user interface element, high contrast, retro game ui, 32x32 icon, flat design"
            workflow = build_workflow(UI_ELEMENT_WORKFLOW, positive, DEFAULT_NEGATIVE_PROMPT)
            workflow["7"]["inputs"]["filename_prefix"] = f"ui_{element.lower().replace(' ', '_')}"

            prompt_id = await self._client.queue_prompt(workflow)
            images = await self._client.get_output_images(prompt_id, output_dir)
            if images:
                results[element] = images[0]
                logger.info(f"Generated UI element {element}: {images[0]}")

        return results

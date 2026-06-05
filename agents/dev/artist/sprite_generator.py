from __future__ import annotations

import asyncio
from pathlib import Path

from loguru import logger

from .art_style import ArtStyleConfig
from .comfyui_client import ComfyUIClient
from .workflows import (
    BACKGROUND_WORKFLOW,
    CHARACTER_SPRITE_WORKFLOW,
    UI_ELEMENT_WORKFLOW,
    VN_BACKGROUND_WORKFLOW,
    VN_CG_WORKFLOW,
    VN_CHARACTER_SPRITE_WORKFLOW,
    build_workflow,
)

DEFAULT_NEGATIVE_PROMPT = (
    "blurry, low quality, distorted, ugly, bad anatomy, "
    "watermark, text, signature, realistic, photo"
)


class SpriteGenerator:
    def __init__(self, client: ComfyUIClient, art_style: ArtStyleConfig | None = None):
        self._client = client
        self._art_style = art_style

    def _negative_prompt(self) -> str:
        if self._art_style:
            return self._art_style.negative_prompt
        return DEFAULT_NEGATIVE_PROMPT

    async def _generate_single_character(
        self,
        character: str,
        style: str,
        output_dir: Path,
    ) -> tuple[str, Path | None]:
        base_prompt = (
            f"pixel art character sprite {character}, {style} style, game asset, "
            f"transparent background, full body centered, 8-bit retro game character, "
            "high quality, clean outlines"
        )
        positive = self._art_style.enrich_prompt(base_prompt) if self._art_style else base_prompt
        workflow = build_workflow(CHARACTER_SPRITE_WORKFLOW, positive, self._negative_prompt())
        workflow["7"]["inputs"]["filename_prefix"] = f"char_{character.lower().replace(' ', '_')}"

        prompt_id = await self._client.queue_prompt(workflow)
        images = await self._client.get_output_images(prompt_id, output_dir)
        if images:
            logger.info(f"Generated sprite for {character}: {images[0]}")
            return character, images[0]
        return character, None

    async def generate_character_sprites(
        self,
        style: str,
        characters: list[str],
        output_dir: Path,
    ) -> dict[str, Path]:
        logger.info(f"Generating {len(characters)} character sprites in style: {style}")

        tasks = [self._generate_single_character(char, style, output_dir) for char in characters]
        results_list = await asyncio.gather(*tasks)

        results: dict[str, Path] = {}
        for char, path in results_list:
            if path:
                results[char] = path

        return results

    async def generate_background(
        self,
        theme: str,
        dimensions: tuple[int, int] = (1024, 512),
        output_dir: Path | None = None,
    ) -> Path | None:
        logger.info(f"Generating background: {theme} ({dimensions[0]}x{dimensions[1]})")

        base_prompt = (
            f"pixel art game background {theme}, game environment tileset, "
            "2D side-scrolling level, retro game scenery, vibrant colors, looping tile"
        )
        positive = self._art_style.enrich_prompt(base_prompt) if self._art_style else base_prompt
        workflow = build_workflow(BACKGROUND_WORKFLOW, positive, self._negative_prompt())
        workflow["4"]["inputs"]["width"] = dimensions[0]
        workflow["4"]["inputs"]["height"] = dimensions[1]
        workflow["7"]["inputs"]["filename_prefix"] = f"bg_{theme.lower().replace(' ', '_')}"

        prompt_id = await self._client.queue_prompt(workflow)
        images = await self._client.get_output_images(prompt_id, output_dir)

        if images:
            logger.info(f"Generated background: {images[0]}")
            return images[0]

        return None

    async def _generate_single_ui_element(
        self,
        element: str,
        style: str,
        output_dir: Path,
    ) -> tuple[str, Path | None]:
        base_prompt = (
            f"pixel art ui icon {element}, {style} style, "
            "game user interface element, high contrast, retro game ui, 32x32 icon, flat design"
        )
        positive = self._art_style.enrich_prompt(base_prompt) if self._art_style else base_prompt
        workflow = build_workflow(UI_ELEMENT_WORKFLOW, positive, self._negative_prompt())
        workflow["7"]["inputs"]["filename_prefix"] = f"ui_{element.lower().replace(' ', '_')}"

        prompt_id = await self._client.queue_prompt(workflow)
        images = await self._client.get_output_images(prompt_id, output_dir)
        if images:
            logger.info(f"Generated UI element {element}: {images[0]}")
            return element, images[0]
        return element, None

    async def generate_ui_elements(
        self,
        style: str,
        elements: list[str],
        output_dir: Path,
    ) -> dict[str, Path]:
        logger.info(f"Generating {len(elements)} UI elements in style: {style}")

        tasks = [self._generate_single_ui_element(elem, style, output_dir) for elem in elements]
        results_list = await asyncio.gather(*tasks)

        results: dict[str, Path] = {}
        for elem, path in results_list:
            if path:
                results[elem] = path

        return results

    async def _generate_vn_character_expression(
        self,
        character_name: str,
        description: str,
        expression: str,
        seed: int,
        output_dir: Path,
    ) -> tuple[str, str, Path | None]:
        gender_tag = "1girl" if any(
            w in description.lower() for w in ["girl", "woman", "female", "she"]
        ) else "1boy"
        positive = (
            f"{gender_tag}, {description}, {expression} expression, "
            "anime visual novel character, transparent background, "
            "high quality, clean lineart"
        )
        negative = (
            "realistic, photo, blurry, low quality, watermark, text, "
            "bad anatomy, multiple characters"
        )
        workflow = build_workflow(VN_CHARACTER_SPRITE_WORKFLOW, positive, negative, seed=seed)
        slug = character_name.lower().replace(" ", "_")
        workflow["7"]["inputs"]["filename_prefix"] = f"vn_{slug}_{expression}"

        prompt_id = await self._client.queue_prompt(workflow)
        images = await self._client.get_output_images(prompt_id, output_dir)
        if images:
            logger.info(f"Generated VN sprite {character_name}/{expression}: {images[0]}")
            return character_name, expression, images[0]
        return character_name, expression, None

    async def generate_vn_character_sprites(
        self,
        characters: list[dict],
        output_dir: Path,
        base_seed: int = 42,
    ) -> dict[str, dict[str, Path]]:
        logger.info(f"Generating VN sprites for {len(characters)} characters")

        tasks = []
        for idx, char in enumerate(characters):
            name = char["name"]
            description = char.get("description", "")
            expressions = char.get("expressions", ["neutral"])
            seed = base_seed + idx
            for expr in expressions:
                tasks.append(
                    self._generate_vn_character_expression(
                        name, description, expr, seed, output_dir
                    )
                )

        results_list = await asyncio.gather(*tasks)

        results: dict[str, dict[str, Path]] = {}
        for char_name, expression, path in results_list:
            if path:
                results.setdefault(char_name, {})[expression] = path

        return results

    async def generate_vn_background(
        self,
        scene_name: str,
        scene_description: str,
        output_dir: Path,
    ) -> Path | None:
        logger.info(f"Generating VN background: {scene_name}")

        positive = (
            f"{scene_description}, anime visual novel background, "
            "detailed environment, cinematic lighting, no characters"
        )
        negative = (
            "characters, people, realistic, photo, blurry, low quality, "
            "watermark, text, signature"
        )
        workflow = build_workflow(VN_BACKGROUND_WORKFLOW, positive, negative)
        slug = scene_name.lower().replace(" ", "_")
        workflow["7"]["inputs"]["filename_prefix"] = f"vn_bg_{slug}"

        prompt_id = await self._client.queue_prompt(workflow)
        images = await self._client.get_output_images(prompt_id, output_dir)
        if images:
            logger.info(f"Generated VN background {scene_name}: {images[0]}")
            return images[0]
        return None

    async def generate_vn_cg(
        self,
        cg_key: str,
        scene_description: str,
        characters: list[str],
        output_dir: Path,
    ) -> Path | None:
        logger.info(f"Generating VN CG: {cg_key}")

        char_text = ", ".join(characters) if characters else ""
        char_clause = f", {char_text}" if char_text else ""
        positive = (
            f"{scene_description}{char_clause}, "
            "anime visual novel CG, dramatic lighting, detailed"
        )
        negative = (
            "realistic, photo, blurry, low quality, watermark, text, "
            "signature, bad anatomy"
        )
        workflow = build_workflow(VN_CG_WORKFLOW, positive, negative)
        slug = cg_key.lower().replace(" ", "_")
        workflow["7"]["inputs"]["filename_prefix"] = f"vn_cg_{slug}"

        prompt_id = await self._client.queue_prompt(workflow)
        images = await self._client.get_output_images(prompt_id, output_dir)
        if images:
            logger.info(f"Generated VN CG {cg_key}: {images[0]}")
            return images[0]
        return None

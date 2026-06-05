"""Per-project art style configuration for consistent visual identity."""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

ART_STYLES = {
    "pixel_16": {
        "name": "16-bit Pixel Art",
        "prompt_suffix": ", pixel art style, 16-bit, retro, clean pixels, no anti-aliasing",
        "sprite_size": 32,
        "negative_prompt": "blurry, smooth, realistic, 3d, photo",
        "palette": "limited_16_colors",
    },
    "pixel_8": {
        "name": "8-bit Pixel Art",
        "prompt_suffix": ", 8-bit pixel art, nes style, very simple, blocky",
        "sprite_size": 16,
        "negative_prompt": "blurry, detailed, smooth, realistic",
        "palette": "limited_8_colors",
    },
    "cartoon": {
        "name": "Cartoon Style",
        "prompt_suffix": ", cartoon style, bold outlines, flat colors, vibrant, simple",
        "sprite_size": 64,
        "negative_prompt": "realistic, photo, detailed texture, blurry",
        "palette": "vibrant_32_colors",
    },
    "flat_design": {
        "name": "Flat Design",
        "prompt_suffix": ", flat design, minimal, geometric, modern, solid colors, no gradients",
        "sprite_size": 64,
        "negative_prompt": "realistic, 3d, shadow, gradient, detailed",
        "palette": "material_design",
    },
    "handdrawn": {
        "name": "Hand-drawn",
        "prompt_suffix": ", hand drawn, sketch style, pencil lines, watercolor fill",
        "sprite_size": 64,
        "negative_prompt": "perfect geometry, vector, 3d, photo",
        "palette": "muted_natural",
    },
    "anime_vn": {
        "name": "Anime Visual Novel",
        "prompt_suffix": (
            ", anime style, visual novel game, clean lines, "
            "flat shading, high quality illustration"
        ),
        "sprite_size": 512,
        "negative_prompt": (
            "realistic, photo, 3d render, blurry, low quality, "
            "watermark, text, signature, western cartoon"
        ),
    },
}


@dataclass
class ArtStyleConfig:
    style_key: str = "pixel_16"
    palette_override: list[str] | None = None
    size_override: int | None = None
    custom_prompt_prefix: str = ""
    reference_image_path: str | None = None

    @property
    def style(self) -> dict:
        return ART_STYLES.get(self.style_key, ART_STYLES["pixel_16"])

    @property
    def sprite_size(self) -> int:
        return self.size_override or self.style["sprite_size"]

    def enrich_prompt(self, base_prompt: str) -> str:
        parts = [base_prompt]
        if self.custom_prompt_prefix:
            parts.insert(0, self.custom_prompt_prefix)
        parts.append(self.style["prompt_suffix"])
        return ", ".join(parts)

    @property
    def negative_prompt(self) -> str:
        return self.style["negative_prompt"]

    def to_dict(self) -> dict:
        return {
            "style_key": self.style_key,
            "palette_override": self.palette_override,
            "size_override": self.size_override,
            "custom_prompt_prefix": self.custom_prompt_prefix,
            "reference_image_path": self.reference_image_path,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ArtStyleConfig:
        return cls(
            style_key=d.get("style_key", "pixel_16"),
            palette_override=d.get("palette_override"),
            size_override=d.get("size_override"),
            custom_prompt_prefix=d.get("custom_prompt_prefix", ""),
            reference_image_path=d.get("reference_image_path"),
        )


def select_style_for_genre(genre: str) -> str:
    """Auto-select art style based on game genre."""
    genre_lower = genre.lower()
    if any(g in genre_lower for g in ["visual novel", "vn", "dating sim", "galgame", "otome"]):
        return "anime_vn"
    if any(g in genre_lower for g in ["platformer", "arcade", "retro"]):
        return "pixel_16"
    if any(g in genre_lower for g in ["puzzle", "casual", "match"]):
        return "flat_design"
    if any(g in genre_lower for g in ["rpg", "adventure", "dungeon"]):
        return "pixel_16"
    if any(g in genre_lower for g in ["idle", "clicker", "tycoon"]):
        return "cartoon"
    return "pixel_16"


def resolve_art_style(gdd: dict) -> ArtStyleConfig:
    """Resolve ArtStyleConfig from GDD, auto-selecting if not set."""
    raw = gdd.get("art_style")
    if raw and isinstance(raw, dict) and "style_key" in raw:
        logger.info(f"Using existing art style: {raw['style_key']}")
        return ArtStyleConfig.from_dict(raw)

    genre = gdd.get("genre", "")
    style_key = select_style_for_genre(genre)
    config = ArtStyleConfig(style_key=style_key)
    gdd["art_style"] = config.to_dict()
    logger.info(f"Auto-selected art style '{style_key}' for genre '{genre}'")
    return config

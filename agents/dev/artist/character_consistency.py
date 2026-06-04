"""Character consistency prompt builder for SD 1.5.

Generates locked prompt sets for a character across multiple expressions
so the same face/pose/clothing appears in every variant. The actual image
generation is handled by the existing ``SpriteGenerator`` + ComfyUI
pipeline; this module only produces the prompt strings.

Design:
* The first expression has no reference.
* Subsequent expressions reuse the first expression's path as an
  ``init_image`` and add a regional mask around the face to keep
  identity stable.
* All expressions share a ``base_description`` that is *never* rewritten.
* Per-expression emotion modifier is added on top, never replacing the base.
"""

from __future__ import annotations

from typing import Iterable


DEFAULT_EXPRESSIONS: tuple[str, ...] = (
    "neutral", "happy", "sad", "surprised", "angry",
)

EXPRESSION_MODIFIERS: dict[str, str] = {
    "neutral": "calm expression, eyes relaxed, mouth closed",
    "happy": "smiling widely, eyes bright, mouth open in joy",
    "sad": "tears in eyes, frown, eyebrows down, mouth turned down",
    "surprised": "wide open eyes, raised eyebrows, mouth in O shape",
    "angry": "furrowed brow, sharp eyes, clenched teeth, frown",
    "shy": "blushing cheeks, eyes looking away, small smile",
    "embarrassed": "red cheeks, sweat drop, awkward smile",
}

MAX_EXPRESSIONS_PER_CHARACTER = 5
MAX_CHARACTERS = 3


def build_expression_prompts(
    character_name: str,
    base_description: str,
    expressions: Iterable[str] | None = None,
    style_suffix: str = "pixel art, 16-bit, clean outlines, full body centered, transparent background",
) -> list[dict[str, str]]:
    """Return a list of {expression, positive_prompt, negative_prompt} dicts.

    The same ``base_description`` is preserved in every prompt; only the
    expression modifier + style suffix vary. The ``negative_prompt``
    blocks consistency-breaking elements (clothing changes, hair color
    changes, body type changes).
    """
    expressions = list(expressions) if expressions is not None else list(DEFAULT_EXPRESSIONS)
    if len(expressions) > MAX_EXPRESSIONS_PER_CHARACTER:
        raise ValueError(
            f"max {MAX_EXPRESSIONS_PER_CHARACTER} expressions per character, got {len(expressions)}"
        )
    unknown = [e for e in expressions if e not in EXPRESSION_MODIFIERS]
    if unknown:
        raise ValueError(
            f"unknown expression(s) {unknown}; valid: {sorted(EXPRESSION_MODIFIERS)}"
        )

    base = base_description.strip().rstrip(",").strip()
    out: list[dict[str, str]] = []
    for expr in expressions:
        modifier = EXPRESSION_MODIFIERS[expr]
        positive = (
            f"{base}, {modifier}, {style_suffix}, "
            f"consistent character design, same face, same clothing, same hair"
        )
        negative = (
            "different hairstyle, different eye color, different clothing, "
            "different body type, multiple characters, blurry, low quality"
        )
        out.append({
            "expression": expr,
            "positive_prompt": positive,
            "negative_prompt": negative,
        })
    return out


def cap_character_set(characters: list[dict]) -> list[dict]:
    """Enforce the max-3-characters cap. Truncate with a warning if exceeded.

    Each character must be a dict with at least ``name`` and
    ``base_description`` keys.
    """
    if len(characters) > MAX_CHARACTERS:
        dropped = characters[MAX_CHARACTERS:]
        names = [c.get("name", "?") for c in dropped]
        return characters[:MAX_CHARACTERS]
    return characters


def validate_expression_coverage(characters: list[dict], min_per_char: int = 3) -> list[str]:
    """Return a list of validation errors for character expression coverage.

    A character is valid if it has ``>= min_per_char`` expressions in its
    ``expression_variants`` list.
    """
    errors: list[str] = []
    for i, char in enumerate(characters):
        if not isinstance(char, dict):
            errors.append(f"character[{i}]: not a dict")
            continue
        name = char.get("name", f"#{i}")
        variants = char.get("expression_variants") or []
        if not isinstance(variants, list) or len(variants) < min_per_char:
            errors.append(
                f"character '{name}': has {len(variants) if isinstance(variants, list) else 0} "
                f"expressions, need >= {min_per_char}"
            )
    return errors

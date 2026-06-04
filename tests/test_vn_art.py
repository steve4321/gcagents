"""Tests for agents/dev/artist/character_consistency.py."""

from __future__ import annotations

import pytest

from agents.dev.artist.character_consistency import (
    DEFAULT_EXPRESSIONS,
    EXPRESSION_MODIFIERS,
    MAX_CHARACTERS,
    MAX_EXPRESSIONS_PER_CHARACTER,
    build_expression_prompts,
    cap_character_set,
    validate_expression_coverage,
)


def test_build_expression_prompts_returns_one_per_expression():
    out = build_expression_prompts(
        "Alice", "18yo female, blue hair, school uniform"
    )
    assert len(out) == len(DEFAULT_EXPRESSIONS)
    assert [d["expression"] for d in out] == list(DEFAULT_EXPRESSIONS)


def test_build_expression_prompts_preserves_base_description():
    out = build_expression_prompts("Alice", "18yo female, blue hair, school uniform")
    for d in out:
        assert "18yo female, blue hair, school uniform" in d["positive_prompt"]
        assert "different hairstyle" in d["negative_prompt"]
        assert "same face" in d["positive_prompt"]


def test_build_expression_prompts_substitutes_modifier():
    out = build_expression_prompts("X", "base")
    assert "smiling widely" in out[1]["positive_prompt"]
    assert "wide open eyes" in out[3]["positive_prompt"]
    assert "furrowed brow" in out[4]["positive_prompt"]


def test_build_expression_prompts_custom_subset():
    out = build_expression_prompts("X", "base", expressions=["happy", "sad"])
    assert len(out) == 2
    assert [d["expression"] for d in out] == ["happy", "sad"]


def test_build_expression_prompts_rejects_too_many():
    with pytest.raises(ValueError, match="max 5"):
        build_expression_prompts("X", "base", expressions=["happy"] * 6)


def test_build_expression_prompts_rejects_unknown_expression():
    with pytest.raises(ValueError, match="unknown expression"):
        build_expression_prompts("X", "base", expressions=["happy", "rage"])


def test_cap_character_set_truncates_to_max():
    chars = [{"name": f"c{i}"} for i in range(5)]
    capped = cap_character_set(chars)
    assert len(capped) == MAX_CHARACTERS == 3
    assert [c["name"] for c in capped] == ["c0", "c1", "c2"]


def test_cap_character_set_passes_through_small_sets():
    chars = [{"name": "a"}, {"name": "b"}]
    assert cap_character_set(chars) == chars


def test_validate_expression_coverage_passes_with_enough():
    chars = [
        {"name": "A", "expression_variants": ["n", "h", "s"]},
        {"name": "B", "expression_variants": ["n", "h", "s", "x"]},
    ]
    assert validate_expression_coverage(chars) == []


def test_validate_expression_coverage_flags_insufficient():
    chars = [
        {"name": "A", "expression_variants": ["n"]},
        {"name": "B", "expression_variants": ["n", "h"]},
    ]
    errors = validate_expression_coverage(chars)
    assert len(errors) == 2
    assert all(">= 3" in e for e in errors)


def test_validate_expression_coverage_handles_missing_key():
    chars = [{"name": "A"}, {"name": "B", "expression_variants": None}]
    errors = validate_expression_coverage(chars)
    assert len(errors) == 2


def test_default_expressions_count():
    assert len(DEFAULT_EXPRESSIONS) <= MAX_EXPRESSIONS_PER_CHARACTER
    assert MAX_EXPRESSIONS_PER_CHARACTER == 5

"""Tests for VN-specific mechanic planning in agents/dev/designer/mechanic_planner.py."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from agents.dev.designer.mechanic_planner import (
    VN_MANDATORY_MECHANICS,
    build_vn_mechanic_instructions,
    is_vn_gdd,
    plan_mechanics,
    validate_vn_mechanic_anchors,
)


VN_MECHANIC_COUNT = 8


def test_is_vn_gdd_positive():
    assert is_vn_gdd({"narrative_premise": "A story."}) is True
    assert is_vn_gdd({"narrative_premise": "A story.", "branching_tree": {}}) is True


def test_is_vn_gdd_negative():
    assert is_vn_gdd({}) is False
    assert is_vn_gdd({"title": "No premise"}) is False
    assert is_vn_gdd({"narrative_premise": ""}) is False
    assert is_vn_gdd({"narrative_premise": "   "}) is False


def test_vn_mandatory_mechanics_count():
    assert len(VN_MANDATORY_MECHANICS) == VN_MECHANIC_COUNT


def test_vn_mandatory_mechanics_have_required_fields():
    for m in VN_MANDATORY_MECHANICS:
        assert "name" in m
        assert "category" in m
        assert "complexity" in m
        assert "code_anchor" in m


def test_vn_mandatory_mechanics_unique_names():
    names = [m["name"] for m in VN_MANDATORY_MECHANICS]
    assert len(names) == len(set(names))


def test_vn_mandatory_mechanics_unique_anchors():
    anchors = [m["code_anchor"] for m in VN_MANDATORY_MECHANICS]
    assert len(anchors) == len(set(anchors))


def test_build_vn_mechanic_instructions_includes_all_anchors():
    text = build_vn_mechanic_instructions()
    for m in VN_MANDATORY_MECHANICS:
        assert m["code_anchor"] in text, f"missing anchor {m['code_anchor']!r} in instructions"


def test_build_vn_mechanic_instructions_mentions_mandatory():
    text = build_vn_mechanic_instructions().lower()
    assert "mandatory" in text
    assert "8" in text or "eight" in text


def test_build_vn_mechanic_instructions_is_nonempty():
    text = build_vn_mechanic_instructions()
    assert len(text) > 200


def test_validate_vn_mechanic_anchors_all_present():
    mechanics = [
        {**m, "implementation_order": i, "description": "x", "inputs": ["a"], "outputs": ["b"], "constraints": ["c"], "dependencies": []}
        for i, m in enumerate(VN_MANDATORY_MECHANICS)
    ]
    assert validate_vn_mechanic_anchors(mechanics) == []


def test_validate_vn_mechanic_anchors_one_missing():
    mechanics = [
        {**m, "implementation_order": i, "description": "x", "inputs": ["a"], "outputs": ["b"], "constraints": ["c"], "dependencies": []}
        for i, m in enumerate(VN_MANDATORY_MECHANICS[:-1])
    ]
    errors = validate_vn_mechanic_anchors(mechanics)
    assert len(errors) == 1
    assert VN_MANDATORY_MECHANICS[-1]["code_anchor"] in errors[0]


def test_validate_vn_mechanic_anchors_multiple_missing():
    mechanics = [
        {**m, "implementation_order": i, "description": "x", "inputs": ["a"], "outputs": ["b"], "constraints": ["c"], "dependencies": []}
        for i, m in enumerate(VN_MANDATORY_MECHANICS[:3])
    ]
    errors = validate_vn_mechanic_anchors(mechanics)
    assert len(errors) == VN_MECHANIC_COUNT - 3


def test_validate_vn_mechanic_anchors_empty_input():
    errors = validate_vn_mechanic_anchors([])
    assert len(errors) == VN_MECHANIC_COUNT


@pytest.mark.asyncio
async def test_plan_mechanics_injects_vn_block_for_vn_gdd():
    vn_gdd = {
        "title": "Test VN",
        "narrative_premise": "A test story.",
        "branching_tree": {"root": "n0", "nodes": {"n0": {"scene_key": "s0"}}},
    }
    captured: dict = {}

    async def fake_chat_completion(model, messages, **kwargs):
        captured["model"] = model
        captured["messages"] = messages
        all_mechanics = list(VN_MANDATORY_MECHANICS)
        for i, m in enumerate(all_mechanics):
            all_mechanics[i] = {
                **m,
                "description": "x",
                "inputs": ["a"],
                "outputs": ["b"],
                "constraints": ["c"],
                "dependencies": [],
                "implementation_order": i,
            }
        return [json.dumps(all_mechanics), {"prompt_tokens": 0, "completion_tokens": 0}]

    with patch("agents.dev.designer.mechanic_planner.llm") as mock_llm:
        mock_llm.chat_completion = AsyncMock(side_effect=fake_chat_completion)
        result = await plan_mechanics(vn_gdd)

    user_msg = captured["messages"][1]["content"]
    assert "MANDATORY" in user_msg or "mandatory" in user_msg
    for m in VN_MANDATORY_MECHANICS:
        assert m["code_anchor"] in user_msg
    assert len(result) == VN_MECHANIC_COUNT


@pytest.mark.asyncio
async def test_plan_mechanics_no_vn_block_for_non_vn_gdd():
    gdd = {"title": "Generic"}
    captured: dict = {}

    async def fake_chat_completion(model, messages, **kwargs):
        captured["messages"] = messages
        return [json.dumps([
            {"name": "m1", "description": "x", "inputs": ["a"], "outputs": ["b"], "constraints": ["c"], "dependencies": [], "implementation_order": 0, "complexity": "low", "category": "core_gameplay"},
        ]), {"prompt_tokens": 0, "completion_tokens": 0}]

    with patch("agents.dev.designer.mechanic_planner.llm") as mock_llm:
        mock_llm.chat_completion = AsyncMock(side_effect=fake_chat_completion)
        await plan_mechanics(gdd)

    user_msg = captured["messages"][1]["content"]
    assert "MANDATORY" not in user_msg or "Visual Novel" not in user_msg.split("MANDATORY")[0]


@pytest.mark.asyncio
async def test_plan_mechanics_warns_on_missing_vn_anchors():
    from loguru import logger as _loguru

    vn_gdd = {
        "title": "Test VN",
        "narrative_premise": "A test story.",
        "branching_tree": {"root": "n0", "nodes": {"n0": {"scene_key": "s0"}}},
    }

    async def fake_chat_completion(model, messages, **kwargs):
        partial = [
            {**VN_MANDATORY_MECHANICS[0], "description": "x", "inputs": ["a"], "outputs": ["b"], "constraints": ["c"], "dependencies": [], "implementation_order": 0},
        ]
        return [json.dumps(partial), {"prompt_tokens": 0, "completion_tokens": 0}]

    captured: list[str] = []
    sink_id = _loguru.add(lambda msg: captured.append(str(msg)), level="WARNING")

    try:
        with patch("agents.dev.designer.mechanic_planner.llm") as mock_llm:
            mock_llm.chat_completion = AsyncMock(side_effect=fake_chat_completion)
            result = await plan_mechanics(vn_gdd)
    finally:
        _loguru.remove(sink_id)

    assert len(result) == 1
    joined = "\n".join(captured)
    assert "missing mandatory mechanic code_anchor" in joined
    assert "class BGMController" in joined or "class ChoiceSystem" in joined

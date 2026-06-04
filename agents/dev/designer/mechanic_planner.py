from __future__ import annotations

import json

from loguru import logger

from shared.constants import DEFAULT_ANALYSIS_MODEL
from shared.llm_client import llm
from shared.memory import get_memory_store

MECHANIC_PLANNER_SYSTEM = (
    "You are a game mechanic decomposition expert. "
    "Break down game designs into ordered, "
    "implementable mechanic specifications."
)


async def plan_mechanics(gdd: dict) -> list[dict]:
    """Decompose a GDD into ordered mechanic specifications.

    Returns list of mechanic dicts sorted by implementation_order.
    """

    model = DEFAULT_ANALYSIS_MODEL

    genre = gdd.get("genre", "unknown")
    past_lessons = ""
    try:
        memory = get_memory_store()
        lessons = await memory.search_long_term(
            query=f"mechanic patterns {genre}",
            category="lesson:mechanic_planner",
            limit=3,
        )
        if lessons:
            past_lessons = "\n\nPast successful mechanic patterns for this genre:\n" + "\n".join(
                f"- {l.get('summary', l.get('content', ''))[:200]}" for l in lessons
            )
    except Exception:
        pass

    prompt = (
        "Analyze this Game Design Document and decompose it "
        "into implementable game mechanics.\n\n"
        f"GDD:\n{json.dumps(gdd, indent=2, ensure_ascii=False)}\n\n"
        "For EACH mechanic, provide a JSON object with:\n"
        '- name: snake_case identifier (e.g., "player_movement", '
        '"score_system")\n'
        "- description: what this mechanic does in 1-2 sentences\n"
        '- inputs: list of triggers (e.g., ["keyboard_input", '
        '"game_loop"])\n'
        '- outputs: list of results (e.g., ["updated_position", '
        '"animation_frame"])\n'
        '- constraints: list of rules (e.g., ["speed_cap_200px_s", '
        '"no_wall_clipping"])\n'
        "- dependencies: list of other mechanic names that must be "
        "implemented first\n"
        "- implementation_order: integer (0=first, must be sequential)\n"
        '- complexity: "low" | "medium" | "high"\n'
        '- category: "core_gameplay" | "monetization" | "retention" | '
        '"engagement" | "polish"\n\n'
        "Order mechanics by dependency: core systems first "
        "(movement, rendering), gameplay next (scoring, enemies), "
        "polish last (effects, sound).\n\n"
        "IMPORTANT COMPLEXITY RULES:\n"
        "- Generate AT LEAST 5 mechanics for any game (minimum: player_movement, score_system, enemy_system, level_progression, and one unique gameplay mechanic)\n"
        '- Each mechanic\'s complexity should be "medium" or higher for at least 3 mechanics\n'
        '- The "inputs" and "outputs" lists must each have at least 2 items\n'
        '- The "constraints" list must have at least 1 item per mechanic\n'
        "- Each mechanic MUST have a 'category' tag indicating its purpose\n"
        "- At least 1 mechanic should be categorized as 'retention' (e.g., daily challenges, streak systems)\n"
        "- At least 1 mechanic should be categorized as 'engagement' (e.g., power-ups, collections, social features)\n\n"
        "Return ONLY a JSON array of mechanic objects, no other text."
        f"{past_lessons}"
    )

    response, usage = await llm.chat_completion(
        model=model,
        messages=[
            {"role": "system", "content": MECHANIC_PLANNER_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=3000,
        agent_name="mechanic_planner",
        project_name=gdd.get("title", "unknown"),
    )

    mechanics = _parse_mechanics(response)
    mechanics.sort(key=lambda m: m.get("implementation_order", 99))

    logger.info(f"Planned {len(mechanics)} mechanics for '{gdd.get('title', 'unknown')}'")
    for m in mechanics:
        order = m.get("implementation_order", "?")
        name = m.get("name", "?")
        cx = m.get("complexity", "?")
        logger.debug(f"  [{order}] {name} ({cx})")

    return mechanics


def _parse_mechanics(text: str) -> list[dict]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]

    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "mechanics" in result:
            return result["mechanics"]
    except json.JSONDecodeError:
        pass

    try:
        start = text.index("[")
        end = text.rindex("]") + 1
        result = json.loads(text[start:end])
        if isinstance(result, list):
            return result
    except (ValueError, json.JSONDecodeError):
        pass

    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        wrapper = json.loads(text[start:end])
        if isinstance(wrapper, dict) and "mechanics" in wrapper:
            return wrapper["mechanics"]
    except (ValueError, json.JSONDecodeError):
        pass

    raise ValueError("Failed to parse mechanics JSON")

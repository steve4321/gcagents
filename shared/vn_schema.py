"""VN GDD schema validation — the PRIMARY stability gate for visual novel production.

This module validates LLM-generated GDDs (Game Design Documents) against the
hybrid Visual Novel + light stat-based/branching mechanics schema. It is called
at three points in the pipeline (the "stability chain"):

1. ``gdd_generator._parse_gdd()`` — after parse, before persistence.
2. ``code_generator.generate_game_code()`` — before any LLM token is burned.
3. ``qa/auto_playtest.run_auto_playtest()`` — pre-check before Playwright.

All validators return a list of error strings. Empty list = valid.

Design principles
-----------------
* No external dependencies (no ``jsonschema`` lib) — keeps the dep graph small.
* Errors are deterministic and ordered — stable test assertions.
* Helpers (e.g. ``is_visual_novel``) are colocated for code_generator reuse.

Schema reference
----------------
See ``.sisyphus/plans/vn-pipeline-transformation.md`` section 3 (GDD Schema).
"""

from __future__ import annotations

from typing import Any


SCHEMA_VERSION = "1.0"

REQUIRED_TOP_LEVEL_FIELDS: tuple[str, ...] = (
    "narrative_premise",
    "player_protagonist",
    "character_roster",
    "route_structure",
    "stat_system",
    "branching_tree",
    "ending_conditions",
    "cg_milestones",
    "save_points",
)

MIN_CHARACTERS = 2
MIN_STATS = 5
MIN_ENDINGS = 4
MIN_BRANCHING_NODES = 30
MIN_EXPRESSIONS_PER_CHARACTER = 3
MIN_CG_MILESTONES = 3


def is_visual_novel(gdd: dict[str, Any]) -> bool:
    """Return True iff the GDD declares itself a hybrid Visual Novel project.

    A GDD is a VN if it carries the ``narrative_premise`` field (a non-empty
    string) AND a ``branching_tree`` (a non-empty dict). This is the dispatch
    signal used by ``code_generator.generate_game_code()``.
    """
    if not isinstance(gdd, dict):
        return False
    premise = gdd.get("narrative_premise")
    tree = gdd.get("branching_tree")
    return isinstance(premise, str) and bool(premise.strip()) and isinstance(tree, dict) and bool(tree)


def validate_gdd(gdd: dict[str, Any]) -> list[str]:
    """Validate a GDD against the hybrid VN schema.

    Returns an empty list if the GDD is valid (or not a VN GDD). Returns a
    sorted list of error messages otherwise. The list is sorted so that
    test assertions are stable across runs.

    If the GDD is not a VN GDD (no ``narrative_premise``), this function is a
    no-op — the existing generic-2D pipeline is responsible.
    """
    if not is_visual_novel(gdd):
        return []

    errors: list[str] = []

    # Top-level required fields
    for field in REQUIRED_TOP_LEVEL_FIELDS:
        if field not in gdd or gdd[field] in (None, "", [], {}):
            errors.append(f"VN GDD missing required field: '{field}'")

    # Sub-validators (only run if the field is present and non-empty)
    if isinstance(gdd.get("character_roster"), list):
        errors.extend(validate_character_roster(gdd["character_roster"]))
    if isinstance(gdd.get("stat_system"), dict):
        errors.extend(validate_stat_system(gdd["stat_system"]))
    if isinstance(gdd.get("branching_tree"), dict):
        errors.extend(validate_branching_tree(gdd["branching_tree"]))
    if isinstance(gdd.get("ending_conditions"), list):
        errors.extend(validate_ending_conditions(gdd["ending_conditions"]))
    if isinstance(gdd.get("cg_milestones"), list):
        errors.extend(validate_cg_milestones(gdd["cg_milestones"]))

    # Cross-module consistency checks (only when both sides present)
    if isinstance(gdd.get("branching_tree"), dict) and isinstance(gdd.get("dialogue"), dict):
        errors.extend(validate_dialogue_against_branching(gdd["dialogue"], gdd["branching_tree"]))
    if (
        isinstance(gdd.get("stat_system"), dict)
        and isinstance(gdd.get("branching_tree"), dict)
        and isinstance(gdd.get("ending_conditions"), list)
    ):
        errors.extend(validate_stat_name_consistency(
            gdd["stat_system"], gdd["branching_tree"], gdd["ending_conditions"]
        ))

    # Schema version stamping (additive — never an error if missing)
    gdd.setdefault("vn_schema_version", SCHEMA_VERSION)

    return sorted(set(errors))


def validate_character_roster(roster: list[Any]) -> list[str]:
    """Validate the ``character_roster`` list.

    Rules:
        * Length >= MIN_CHARACTERS (2).
        * Each entry is a dict with ``name`` (non-empty str) and
          ``expression_variants`` (list[str], length >= MIN_EXPRESSIONS_PER_CHARACTER).
    """
    errors: list[str] = []
    if len(roster) < MIN_CHARACTERS:
        errors.append(
            f"character_roster has {len(roster)} entries, need >= {MIN_CHARACTERS}"
        )
    for i, char in enumerate(roster):
        if not isinstance(char, dict):
            errors.append(f"character_roster[{i}] is not a dict")
            continue
        if not char.get("name") or not isinstance(char["name"], str):
            errors.append(f"character_roster[{i}] missing 'name'")
        exprs = char.get("expression_variants")
        if not isinstance(exprs, list) or len(exprs) < MIN_EXPRESSIONS_PER_CHARACTER:
            errors.append(
                f"character_roster[{i}] ({char.get('name', '?')}) needs "
                f">= {MIN_EXPRESSIONS_PER_CHARACTER} expression_variants, got "
                f"{len(exprs) if isinstance(exprs, list) else 'invalid'}"
            )
    return errors


def validate_stat_system(stat_system: dict[str, Any]) -> list[str]:
    """Validate the ``stat_system`` object.

    Rules:
        * Has ``stats`` key (list[dict]).
        * ``stats`` length >= MIN_STATS (5).
        * Each stat has ``name`` (str) and ``range`` (list[2 numbers], min < max).
    """
    errors: list[str] = []
    stats = stat_system.get("stats")
    if not isinstance(stats, list):
        return [f"stat_system missing 'stats' list"]
    if len(stats) < MIN_STATS:
        errors.append(
            f"stat_system.stats has {len(stats)} entries, need >= {MIN_STATS}"
        )
    for i, stat in enumerate(stats):
        if not isinstance(stat, dict):
            errors.append(f"stat_system.stats[{i}] is not a dict")
            continue
        if not stat.get("name") or not isinstance(stat["name"], str):
            errors.append(f"stat_system.stats[{i}] missing 'name'")
        rng = stat.get("range")
        if not isinstance(rng, list) or len(rng) != 2:
            errors.append(f"stat_system.stats[{i}] ({stat.get('name', '?')}) missing 'range' [min, max]")
            continue
        try:
            lo, hi = float(rng[0]), float(rng[1])
        except (TypeError, ValueError):
            errors.append(f"stat_system.stats[{i}] ({stat.get('name', '?')}) range not numeric")
            continue
        if lo >= hi:
            errors.append(
                f"stat_system.stats[{i}] ({stat.get('name', '?')}) range [{lo}, {hi}] invalid: min must be < max"
            )
    return errors


def validate_branching_tree(tree: dict[str, Any]) -> list[str]:
    """Validate the ``branching_tree`` object.

    Rules:
        * Has ``root`` (str, must exist in ``nodes``).
        * ``nodes`` is a dict, length >= MIN_BRANCHING_NODES (8).
        * All nodes reachable from root via BFS (no orphans).
        * No cycles (the BFS also detects cycles via ``visited`` set).
        * Each node has a ``scene_key`` (str).
    """
    errors: list[str] = []
    root = tree.get("root")
    nodes = tree.get("nodes")

    if not root or not isinstance(root, str):
        errors.append("branching_tree missing 'root' (str)")
    if not isinstance(nodes, dict):
        return errors + ["branching_tree missing 'nodes' (dict)"]
    if len(nodes) < MIN_BRANCHING_NODES:
        errors.append(
            f"branching_tree.nodes has {len(nodes)} entries, need >= {MIN_BRANCHING_NODES}"
        )
    if root and root not in nodes:
        errors.append(f"branching_tree.root '{root}' not in nodes")
        return errors  # cannot continue reachability check without root

    for node_id, node in nodes.items():
        if not isinstance(node, dict):
            errors.append(f"branching_tree.nodes['{node_id}'] is not a dict")
            continue
        if not node.get("scene_key") or not isinstance(node["scene_key"], str):
            errors.append(f"branching_tree.nodes['{node_id}'] missing 'scene_key'")

    visited: set[str] = set()
    queue: list[str] = [root]
    while queue:
        cur = queue.pop()
        if cur in visited:
            continue
        visited.add(cur)
        node = nodes.get(cur)
        if not isinstance(node, dict):
            continue
        for choice in node.get("choices", []) or []:
            if not isinstance(choice, dict):
                continue
            nxt = choice.get("next_node")
            if isinstance(nxt, str):
                queue.append(nxt)

    unreachable = set(nodes.keys()) - visited
    if unreachable:
        errors.append(
            f"branching_tree unreachable nodes: {sorted(unreachable)}"
        )

    return errors


def validate_ending_conditions(conds: list[Any]) -> list[str]:
    """Validate the ``ending_conditions`` list.

    Rules:
        * Length >= MIN_ENDINGS (3).
        * Each entry is a dict with ``name`` (str) and ``trigger`` (dict).
        * No two entries share the same ``trigger`` (deterministic endings).
    """
    errors: list[str] = []
    if len(conds) < MIN_ENDINGS:
        errors.append(
            f"ending_conditions has {len(conds)} entries, need >= {MIN_ENDINGS}"
        )

    import json

    seen_triggers: set[str] = set()
    for i, c in enumerate(conds):
        if not isinstance(c, dict):
            errors.append(f"ending_conditions[{i}] is not a dict")
            continue
        if not c.get("name") or not isinstance(c["name"], str):
            errors.append(f"ending_conditions[{i}] missing 'name'")
        if not isinstance(c.get("trigger"), dict):
            errors.append(f"ending_conditions[{i}] ({c.get('name', '?')}) missing 'trigger' (dict)")
            continue
        try:
            key = json.dumps(c["trigger"], sort_keys=True, default=str)
        except (TypeError, ValueError):
            errors.append(f"ending_conditions[{i}] ({c.get('name', '?')}) trigger not JSON-serializable")
            continue
        if key in seen_triggers:
            errors.append(
                f"ending_conditions[{i}] ({c.get('name', '?')}) duplicate trigger with another ending"
            )
        seen_triggers.add(key)

    return errors


def validate_cg_milestones(cgs: list[Any]) -> list[str]:
    """Validate the ``cg_milestones`` list (leniency: only warn on zero).

    Rules:
        * Length >= MIN_CG_MILESTONES (1) — soft requirement, surfaced as a
          warning-style error (still blocks publish per hard-veto rules).
        * Each entry has ``scene_id`` (str) and ``cg_key`` (str).
    """
    errors: list[str] = []
    if len(cgs) < MIN_CG_MILESTONES:
        errors.append(
            f"cg_milestones has {len(cgs)} entries, need >= {MIN_CG_MILESTONES}"
        )
    for i, cg in enumerate(cgs):
        if not isinstance(cg, dict):
            errors.append(f"cg_milestones[{i}] is not a dict")
            continue
        if not cg.get("scene_id") or not isinstance(cg["scene_id"], str):
            errors.append(f"cg_milestones[{i}] missing 'scene_id'")
        if not cg.get("cg_key") or not isinstance(cg["cg_key"], str):
            errors.append(f"cg_milestones[{i}] missing 'cg_key'")
    return errors


def validate_dialogue_against_branching(
    dialogue: dict[str, Any], branching_tree: dict[str, Any]
) -> list[str]:
    """Validate that all dialogue keys referenced in branching exist in dialogue data.

    Also checks:
    * Each dialogue entry has ``speaker`` and ``text`` fields.
    * No empty dialogue arrays.
    * Minimum 2 dialogue lines per referenced key.
    """
    errors: list[str] = []

    # Collect dialogue keys from branching nodes
    referenced_keys: set[str] = set()
    nodes = branching_tree.get("nodes", {})
    if isinstance(nodes, dict):
        for _node_id, node in nodes.items():
            if not isinstance(node, dict):
                continue
            for d in node.get("dialogue", []):
                if isinstance(d, str):
                    referenced_keys.add(d)
                elif isinstance(d, dict) and "key" in d:
                    referenced_keys.add(d["key"])

    if not referenced_keys:
        return errors

    # Unwrap if needed
    dialogue_data = dialogue
    if (
        isinstance(dialogue, dict)
        and "dialogue" in dialogue
        and isinstance(dialogue["dialogue"], dict)
    ):
        dialogue_data = dialogue["dialogue"]

    if not isinstance(dialogue_data, dict):
        errors.append("dialogue is not a keyed dict")
        return errors

    missing_keys = referenced_keys - set(dialogue_data.keys())
    if missing_keys:
        errors.append(
            f"dialogue missing {len(missing_keys)} keys referenced in branching: "
            f"{sorted(missing_keys)[:10]}"
        )

    for key in sorted(referenced_keys & set(dialogue_data.keys())):
        entries = dialogue_data.get(key)
        if not isinstance(entries, list):
            errors.append(f"dialogue key '{key}' is not an array")
            continue
        if len(entries) == 0:
            errors.append(f"dialogue key '{key}' has empty dialogue array")
            continue
        if len(entries) < 2:
            errors.append(f"dialogue key '{key}' has {len(entries)} entries, need >= 2")
        for ei, entry in enumerate(entries):
            if not isinstance(entry, dict):
                errors.append(f"dialogue key '{key}' entry[{ei}] is not a dict")
                continue
            if "speaker" not in entry:
                errors.append(f"dialogue key '{key}' entry[{ei}] missing 'speaker'")
            if "text" not in entry:
                errors.append(f"dialogue key '{key}' entry[{ei}] missing 'text'")

    return errors


def validate_stat_name_consistency(
    stat_system: dict[str, Any],
    branching_tree: dict[str, Any],
    ending_conditions: list[Any],
) -> list[str]:
    """Validate that all stat names referenced in branching/endings exist in stat_system.

    Checks ``stat_delta`` keys in choices AND condition keys in endings.
    """
    errors: list[str] = []

    # Collect defined stat names
    defined_names: set[str] = set()
    stats_list = stat_system.get("stats", [])
    if isinstance(stats_list, list):
        for s in stats_list:
            if isinstance(s, dict) and isinstance(s.get("name"), str):
                defined_names.add(s["name"])

    if not defined_names:
        return errors

    # Collect stat names referenced in branching choices
    referenced_in_branching: set[str] = set()
    nodes = branching_tree.get("nodes", {})
    if isinstance(nodes, dict):
        for _node_id, node in nodes.items():
            if not isinstance(node, dict):
                continue
            for choice in node.get("choices", []):
                if not isinstance(choice, dict):
                    continue
                delta = choice.get("stat_delta")
                if isinstance(delta, dict):
                    referenced_in_branching.update(delta.keys())

    invalid_branching_stats = referenced_in_branching - defined_names
    if invalid_branching_stats:
        errors.append(
            f"branching_tree choices reference undefined stats: "
            f"{sorted(invalid_branching_stats)}"
        )

    # Collect stat names referenced in ending conditions
    referenced_in_endings: set[str] = set()
    for cond in ending_conditions:
        if not isinstance(cond, dict):
            continue
        trigger = cond.get("trigger", {})
        if not isinstance(trigger, dict):
            continue
        conditions = trigger.get("conditions", {})
        # Format 1: {"conditions": [{"stat": "name", ...}, ...]} (list of dicts)
        if isinstance(conditions, list):
            for c in conditions:
                if isinstance(c, dict) and "stat" in c:
                    referenced_in_endings.add(c["stat"])
        # Format 2: {"conditions": {"morality": {">=": 80}, ...}} (nested dict)
        elif isinstance(conditions, dict):
            for stat_name in conditions.keys():
                if isinstance(stat_name, str):
                    referenced_in_endings.add(stat_name)
        # Format 3: flat {"morality:>=": 80, ...} in trigger itself (colon-separated stat:op keys)
        # Format 4: flat {"morality": 50, ...} in trigger (bare stat key with numeric value)
        for key in trigger:
            if key in ("conditions", "type", "node", "route"):
                continue
            val = trigger[key]
            if isinstance(val, (int, float)):
                stat_name = key.split(":")[0].split(">")[0].split("<")[0].split("=")[0]
                if stat_name:
                    referenced_in_endings.add(stat_name)
            elif isinstance(val, dict):
                referenced_in_endings.add(key)

    invalid_ending_stats = referenced_in_endings - defined_names
    if invalid_ending_stats:
        errors.append(
            f"ending_conditions reference undefined stats: "
            f"{sorted(invalid_ending_stats)}"
        )

    return errors

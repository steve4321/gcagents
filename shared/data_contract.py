"""Schema contract layer — enforces consistency between GDD, data files, and game code.

This module bridges the gap between GDD output, generated JSON data files,
and TypeScript game code. It extracts expected schemas from a validated GDD
and then validates that generated artifacts conform to those schemas.

Used by ``code_generator._generate_visual_novel()`` after file generation
to catch cross-module inconsistencies before the build step.

Design principles
-----------------
* No external dependencies — stdlib only (re, json, collections).
* Errors are specific and actionable (include field names, expected values).
* Regex-based code analysis — no AST dependency.
"""

from __future__ import annotations

import re
from collections import deque
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FORBIDDEN_BROWSER_IMPORTS: tuple[str, ...] = (
    "fs",
    "path",
    "os",
    "child_process",
    "net",
    "http",
    "https",
)

VN_CODE_INTERFACES: dict[str, dict[str, Any]] = {
    "ChoiceSystem": {
        "file_pattern": "ChoiceSystem.ts",
        "required_methods": [
            "showChoices",
            "showAnimated",
            "hideAnimated",
            "destroy",
        ],
    },
    "BranchingEngine": {
        "file_pattern": "BranchingEngine.ts",
        "required_methods": [
            "getCurrentNode",
            "advance",
            "getVisitedNodes",
            "getActiveRoutes",
        ],
    },
    "StatSystem": {
        "file_pattern": "StatSystem.ts",
        "required_methods": [
            "get",
            "set",
            "applyDeltas",
            "evaluateConditions",
        ],
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_dialogue_keys_from_branching(branching_tree: dict) -> list[str]:
    """Walk branching_tree nodes and collect all dialogue array keys."""
    keys: list[str] = []
    nodes = branching_tree.get("nodes", {})
    if not isinstance(nodes, dict):
        return keys
    for _node_id, node in nodes.items():
        if not isinstance(node, dict):
            continue
        for d in node.get("dialogue", []):
            if isinstance(d, str):
                keys.append(d)
            elif isinstance(d, dict) and "key" in d:
                keys.append(d["key"])
    return keys


def _collect_stat_names_from_branching(branching_tree: dict) -> set[str]:
    """Collect all stat names referenced in branching choices (stat_delta keys)."""
    names: set[str] = set()
    nodes = branching_tree.get("nodes", {})
    if not isinstance(nodes, dict):
        return names
    for _node_id, node in nodes.items():
        if not isinstance(node, dict):
            continue
        for choice in node.get("choices", []):
            if not isinstance(choice, dict):
                continue
            delta = choice.get("stat_delta")
            if isinstance(delta, dict):
                names.update(delta.keys())
    return names


def _collect_ending_node_ids(branching_tree: dict) -> list[str]:
    """Find nodes that have no choices (terminal / ending nodes)."""
    ending_ids: list[str] = []
    nodes = branching_tree.get("nodes", {})
    if not isinstance(nodes, dict):
        return ending_ids
    for node_id, node in nodes.items():
        if not isinstance(node, dict):
            continue
        choices = node.get("choices")
        if not choices or (isinstance(choices, list) and len(choices) == 0):
            ending_ids.append(node_id)
    return ending_ids


def _collect_stat_names_from_endings(ending_conditions: list) -> set[str]:
    """Collect stat names referenced in ending trigger conditions."""
    names: set[str] = set()
    for cond in ending_conditions:
        if not isinstance(cond, dict):
            continue
        trigger = cond.get("trigger", {})
        if not isinstance(trigger, dict):
            continue
        # trigger may have "conditions" list or direct stat keys
        conditions = trigger.get("conditions", [])
        if isinstance(conditions, list):
            for c in conditions:
                if isinstance(c, dict) and "stat" in c:
                    names.add(c["stat"])
        # Also check for direct stat references in trigger (e.g. {"stat_name": value})
        for key in trigger:
            if key != "conditions" and key != "type" and key != "node":
                # heuristic: if value is numeric, key is likely a stat name
                val = trigger[key]
                if isinstance(val, (int, float)):
                    names.add(key)
    return names


def _reachable_nodes(branching_tree: dict) -> set[str]:
    """BFS from root to find all reachable node IDs."""
    root = branching_tree.get("root", "")
    nodes = branching_tree.get("nodes", {})
    if not root or not isinstance(nodes, dict) or root not in nodes:
        return set()
    visited: set[str] = set()
    queue: deque[str] = deque([root])
    while queue:
        cur = queue.popleft()
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
            if isinstance(nxt, str) and nxt:
                queue.append(nxt)
    return visited


# ---------------------------------------------------------------------------
# extract_data_schemas
# ---------------------------------------------------------------------------

def extract_data_schemas(gdd: dict) -> dict:
    """Extract data schemas from a validated GDD.

    Returns a dict with ``branching_schema``, ``dialogue_schema``,
    ``stats_schema``, ``endings_schema``, and ``code_interfaces``.
    """
    branching_tree = gdd.get("branching_tree", {})
    stat_system = gdd.get("stat_system", {})
    ending_conditions = gdd.get("ending_conditions", [])

    # --- branching schema ---
    node_count = len(
        branching_tree.get("nodes", {})
    ) if isinstance(branching_tree.get("nodes"), dict) else 0
    min_nodes = max(30, node_count)

    dialogue_keys = _collect_dialogue_keys_from_branching(branching_tree)

    branching_schema = {
        "node_count": min_nodes,
        "dialogue_key_pattern": "{route}_{scene}_{seq}",
        "choice_schema": {
            "id": "string",
            "label": "string",
            "next_node": "string",
            "stat_delta": "dict (optional)",
        },
        "required_fields": ["root", "nodes", "edges", "routes"],
    }

    # --- dialogue schema ---
    dialogue_schema = {
        "format": "keyed",
        "required_keys": sorted(set(dialogue_keys)),
        "min_entries_per_key": 2,
    }

    # --- stats schema ---
    stat_names: list[str] = []
    range_defaults: dict[str, list] = {}
    stats_list = stat_system.get("stats", [])
    if isinstance(stats_list, list):
        for s in stats_list:
            if isinstance(s, dict) and "name" in s:
                stat_names.append(s["name"])
                rng = s.get("range", [0, 100])
                if isinstance(rng, list) and len(rng) == 2:
                    range_defaults[s["name"]] = rng
                else:
                    range_defaults[s["name"]] = [0, 100]

    stats_schema = {
        "stat_names": sorted(stat_names),
        "range_defaults": range_defaults,
    }

    # --- endings schema ---
    ending_keys: list[str] = []
    for ec in ending_conditions:
        if isinstance(ec, dict) and "name" in ec:
            ending_keys.append(ec["name"])

    endings_schema = {
        "ending_keys": sorted(ending_keys),
        "required_fields_per_ending": ["name", "trigger", "epilogue_key", "is_good_ending"],
    }

    # --- code interfaces ---
    code_interfaces = {
        "ChoiceSystem": VN_CODE_INTERFACES["ChoiceSystem"],
        "BranchingEngine": VN_CODE_INTERFACES["BranchingEngine"],
        "StatSystem": VN_CODE_INTERFACES["StatSystem"],
        "DialogueSystem": {
            "file_pattern": "DialogueSystem.ts",
            "required_methods": [
                "showDialogue",
                "setSpeakers",
                "advance",
                "isComplete",
            ],
        },
        "NovelScene": {
            "file_pattern": "NovelScene.ts",
            "required_methods": [
                "create",
                "update",
            ],
            "must_use": ["BranchingEngine", "StatSystem", "ChoiceSystem", "DialogueSystem"],
        },
    }

    return {
        "branching_schema": branching_schema,
        "dialogue_schema": dialogue_schema,
        "stats_schema": stats_schema,
        "endings_schema": endings_schema,
        "code_interfaces": code_interfaces,
    }


# ---------------------------------------------------------------------------
# validate_data_against_schema
# ---------------------------------------------------------------------------

def validate_data_against_schema(data: dict, schema: dict, data_type: str) -> list[str]:
    """Validate generated data files against their schema contract.

    ``data_type`` is one of: ``"branching"``, ``"dialogue"``, ``"stats"``,
    ``"endings"``.  Returns a list of error strings — empty means valid.
    """
    errors: list[str] = []

    if data_type == "branching":
        errors.extend(_validate_branching_data(data, schema))
    elif data_type == "dialogue":
        errors.extend(_validate_dialogue_data(data, schema))
    elif data_type == "stats":
        errors.extend(_validate_stats_data(data, schema))
    elif data_type == "endings":
        errors.extend(_validate_endings_data(data, schema))
    else:
        errors.append(f"Unknown data_type: '{data_type}'")

    return errors


def _validate_branching_data(data: dict, schema: dict) -> list[str]:
    """Validate branching.json against branching_schema."""
    errors: list[str] = []
    branching_schema = schema.get("branching_schema", {})

    # Required fields
    for field in branching_schema.get("required_fields", []):
        if field not in data:
            errors.append(f"branching.json missing required field: '{field}'")

    # Node count
    nodes = data.get("nodes", {})
    if isinstance(nodes, dict):
        min_count = branching_schema.get("node_count", 30)
        if len(nodes) < min_count:
            errors.append(
                f"branching.json has {len(nodes)} nodes, expected >= {min_count}"
            )

        # Root must be in nodes
        root = data.get("root", "")
        if root and root not in nodes:
            errors.append(f"branching.json root '{root}' not found in nodes")

        # Reachability check — no orphans
        reachable = _reachable_nodes(data)
        orphan_nodes = set(nodes.keys()) - reachable
        if orphan_nodes and root:
            errors.append(
                f"branching.json has {len(orphan_nodes)} orphan nodes unreachable from root: "
                f"{sorted(orphan_nodes)[:10]}"
            )

        required_choice_fields = {"id", "label", "next_node"}
        for node_id, node in nodes.items():
            if not isinstance(node, dict):
                continue
            choices = node.get("choices", [])
            if not isinstance(choices, list):
                continue
            for ci, choice in enumerate(choices):
                if not isinstance(choice, dict):
                    continue
                missing = required_choice_fields - set(choice.keys())
                if missing:
                    errors.append(
                        f"branching.json node '{node_id}' choice[{ci}] "
                        f"missing fields: {sorted(missing)}"
                    )

        # Check that stat_delta keys reference valid stat names
        valid_stat_names = set(schema.get("stats_schema", {}).get("stat_names", []))
        for node_id, node in nodes.items():
            if not isinstance(node, dict):
                continue
            for ci, choice in enumerate(node.get("choices", [])):
                if not isinstance(choice, dict):
                    continue
                delta = choice.get("stat_delta")
                if isinstance(delta, dict) and valid_stat_names:
                    invalid_stats = set(delta.keys()) - valid_stat_names
                    if invalid_stats:
                        errors.append(
                            f"branching.json node '{node_id}' choice[{ci}] stat_delta references "
                            f"unknown stats: {sorted(invalid_stats)}"
                        )

    return errors


def _validate_dialogue_data(data: dict, schema: dict) -> list[str]:
    """Validate dialogue.json against dialogue_schema."""
    errors: list[str] = []
    dialogue_schema = schema.get("dialogue_schema", {})

    required_keys = dialogue_schema.get("required_keys", [])
    min_entries = dialogue_schema.get("min_entries_per_key", 2)

    # If data is a dict with a top-level key like "dialogue", unwrap
    dialogue = data
    if isinstance(data, dict) and "dialogue" in data and isinstance(data["dialogue"], dict):
        dialogue = data["dialogue"]

    if not isinstance(dialogue, dict):
        errors.append("dialogue.json is not a keyed dict (expected {{key: [entries...]}})")
        return errors

    # Check required keys from branching exist in dialogue
    if required_keys:
        missing_keys = set(required_keys) - set(dialogue.keys())
        if missing_keys:
            errors.append(
                f"dialogue.json missing {len(missing_keys)} keys referenced in branching: "
                f"{sorted(missing_keys)[:10]}"
            )

    # Validate each dialogue entry
    for key, entries in dialogue.items():
        if not isinstance(entries, list):
            errors.append(f"dialogue.json key '{key}' is not an array")
            continue
        if len(entries) == 0:
            errors.append(f"dialogue.json key '{key}' has empty dialogue array")
            continue
        if len(entries) < min_entries:
            errors.append(
                f"dialogue.json key '{key}' has {len(entries)} entries, expected >= {min_entries}"
            )
        for ei, entry in enumerate(entries):
            if not isinstance(entry, dict):
                errors.append(f"dialogue.json key '{key}' entry[{ei}] is not a dict")
                continue
            if "speaker" not in entry:
                errors.append(f"dialogue.json key '{key}' entry[{ei}] missing 'speaker'")
            if "text" not in entry:
                errors.append(f"dialogue.json key '{key}' entry[{ei}] missing 'text'")

    return errors


def _validate_stats_data(data: dict, schema: dict) -> list[str]:
    """Validate stats.json against stats_schema."""
    errors: list[str] = []
    stats_schema = schema.get("stats_schema", {})

    # Unwrap if nested
    stats_data = data
    if isinstance(data, dict) and "stats" in data:
        stats_data = data.get("stats", data)

    expected_names = set(stats_schema.get("stat_names", []))

    if isinstance(stats_data, list):
        actual_names: set[str] = set()
        for si, stat in enumerate(stats_data):
            if not isinstance(stat, dict):
                errors.append(f"stats.json entry[{si}] is not a dict")
                continue
            name = stat.get("name")
            if not name or not isinstance(name, str):
                errors.append(f"stats.json entry[{si}] missing 'name'")
                continue
            actual_names.add(name)
            rng = stat.get("range")
            if not isinstance(rng, list) or len(rng) != 2:
                errors.append(f"stats.json stat '{name}' missing 'range' [min, max]")
        # Check that all expected stat names are present
        if expected_names:
            missing = expected_names - actual_names
            if missing:
                errors.append(
                    f"stats.json missing stats referenced in GDD: {sorted(missing)}"
                )
    elif isinstance(stats_data, dict):
        actual_names = set(stats_data.keys())
        if expected_names:
            missing = expected_names - actual_names
            if missing:
                errors.append(
                    f"stats.json missing stats referenced in GDD: {sorted(missing)}"
                )
    else:
        errors.append("stats.json is not a list or dict")

    return errors


def _validate_endings_data(data: dict, schema: dict) -> list[str]:
    """Validate endings.json against endings_schema."""
    errors: list[str] = []
    endings_schema = schema.get("endings_schema", {})

    # Unwrap endings data
    endings_list = data
    if isinstance(data, dict):
        if "endings" in data and isinstance(data["endings"], list):
            endings_list = data["endings"]
        else:
            errors.append("endings.json must be a list or have 'endings' key with a list")
            return errors

    if not isinstance(endings_list, list):
        errors.append("endings.json is not a list")
        return errors

    required_fields = endings_schema.get("required_fields_per_ending", [])
    expected_keys = set(endings_schema.get("ending_keys", []))

    actual_names: set[str] = set()
    for ei, ending in enumerate(endings_list):
        if not isinstance(ending, dict):
            errors.append(f"endings.json entry[{ei}] is not a dict")
            continue
        name = ending.get("name")
        if name:
            actual_names.add(str(name))
        for field in required_fields:
            if field not in ending:
                errors.append(
                    f"endings.json entry[{ei}] ({name or '?'}) missing field: '{field}'"
                )

    # Check that ending keys from branching exist in endings data
    if expected_keys:
        missing = expected_keys - actual_names
        if missing:
            errors.append(
                f"endings.json missing endings referenced in branching: {sorted(missing)}"
            )

    return errors


# ---------------------------------------------------------------------------
# validate_code_against_schema
# ---------------------------------------------------------------------------

def validate_code_against_schema(code_files: dict[str, str], interfaces: dict) -> list[str]:
    """Validate generated TypeScript code against interface contracts.

    Checks:
    * No forbidden imports (``fs``, ``path``, ``os``, ``child_process``, ``net``,
      ``http``, ``https``).
    * Each required interface method exists in the corresponding file.
    * No ``as any``, ``@ts-ignore``, ``@ts-expect-error`` in production code.
    * Game config has ``parent: 'game-container'``.

    Uses regex parsing — no AST needed.
    """
    errors: list[str] = []

    # --- Forbidden imports ---
    for file_path, content in code_files.items():
        if not file_path.endswith(".ts"):
            continue
        for forbidden in FORBIDDEN_BROWSER_IMPORTS:
            # Match: import ... from 'fs' or import ... from "fs"
            pattern = rf"""import\s+.*?\s+from\s+['"]({forbidden}.*?)['"]"""
            if re.search(pattern, content):
                errors.append(
                    f"{file_path}: forbidden import '{forbidden}' — will crash in browser"
                )
            # Also check require('fs') style
            if re.search(rf"""require\s*\(\s*['"]({forbidden}.*?)['"]\s*\)""", content):
                errors.append(
                    f"{file_path}: forbidden require('{forbidden}') — will crash in browser"
                )

    # --- Required methods per interface ---
    for iface_name, iface_spec in interfaces.items():
        if not isinstance(iface_spec, dict):
            continue
        file_pattern = iface_spec.get("file_pattern", "")
        required_methods = iface_spec.get("required_methods", [])

        if not file_pattern or not required_methods:
            continue

        # Find the matching file
        matching_file: str | None = None
        matching_content: str | None = None
        for fp, content in code_files.items():
            if file_pattern in fp:
                matching_file = fp
                matching_content = content
                break

        if matching_file is None or matching_content is None:
            errors.append(
                f"Missing file for interface '{iface_name}': expected '{file_pattern}'"
            )
            continue

        for method in required_methods:
            # Match method definitions: methodName( or methodName <generic> (
            # Covers: method(), method(param), async method(), method = (, etc.
            method_pattern = rf"""\b{re.escape(method)}\s*[<(]"""
            if not re.search(method_pattern, matching_content):
                errors.append(
                    f"{matching_file}: interface '{iface_name}' "
                    f"missing required method '{method}()'"
                )

    # --- Type safety anti-patterns ---
    for file_path, content in code_files.items():
        if not file_path.endswith(".ts"):
            continue
        if re.search(r"\bas\s+any\b", content):
            errors.append(f"{file_path}: uses 'as any' — unsafe type cast")
        if re.search(r"//\s*@ts-ignore", content):
            errors.append(f"{file_path}: uses '@ts-ignore' — suppresses type checking")
        if re.search(r"//\s*@ts-expect-error", content):
            errors.append(f"{file_path}: uses '@ts-expect-error' — suppresses type checking")

    # --- Game container parent ---
    has_game_container = False
    for file_path, content in code_files.items():
        if not file_path.endswith(".ts"):
            continue
        if re.search(r"""parent\s*:\s*['"`]game-container['"`]""", content):
            has_game_container = True
            break
    if not has_game_container and code_files:
        errors.append("No TypeScript file sets parent: 'game-container' in Phaser config")

    return errors

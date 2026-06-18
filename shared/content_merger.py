from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


def dedup_by_id(
    existing_items: list[dict[str, Any]],
    new_items: list[dict[str, Any]],
    id_field: str = "id",
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in existing_items:
        key = str(item.get(id_field, ""))
        merged[key] = item
    for item in new_items:
        key = str(item.get(id_field, ""))
        merged[key] = item
    return list(merged.values())


def merge_json_data(
    existing: dict[str, Any],
    new_entries: dict[str, Any],
    id_field: str = "id",
) -> dict[str, Any]:
    result = deepcopy(existing)
    for key, new_value in new_entries.items():
        if key not in result:
            result[key] = deepcopy(new_value)
            continue
        existing_value = result[key]
        if isinstance(existing_value, list) and isinstance(new_value, list):
            result[key] = dedup_by_id(existing_value, new_value, id_field)
        elif isinstance(existing_value, dict) and isinstance(new_value, dict):
            result[key] = merge_json_data(existing_value, new_value, id_field)
        else:
            result[key] = deepcopy(new_value)
    return result


def merge_data_file(
    file_path: Path,
    new_entries: dict[str, Any],
    id_field: str = "id",
) -> None:
    if not file_path.exists():
        file_path.write_text(json.dumps(new_entries, indent=2))
        return
    existing = json.loads(file_path.read_text())
    merged = merge_json_data(existing, new_entries, id_field)
    file_path.write_text(json.dumps(merged, indent=2))

from __future__ import annotations

import json
from pathlib import Path


def extract_content_summary(game_dir: Path) -> dict[str, list[str]]:
    summary: dict[str, list[str]] = {}

    for data_dir in [
        game_dir / "src" / "game" / "data",
        game_dir / "data",
        game_dir / "src" / "data",
    ]:
        if not data_dir.exists():
            continue
        for json_file in sorted(data_dir.glob("*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            ids = _extract_ids(data)
            if ids:
                summary[json_file.name] = ids
        break

    return summary


def _extract_ids(data: dict) -> list[str]:
    ids: list[str] = []
    for value in data.values():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and "id" in item:
                    ids.append(str(item["id"]))
        elif isinstance(value, dict):
            for v2 in value.values():
                if isinstance(v2, list):
                    for item in v2:
                        if isinstance(item, dict) and "id" in item:
                            ids.append(str(item["id"]))
    return ids

"""TypeScript source extractor for VN localization.

Parses ``.ts`` files inside a game's ``src/`` directory to extract
translatable strings that the existing HTML/JS extractor would miss:

* ``this.add.text(x, y, "translatable", ...)`` Phaser text calls
* ``const LABEL = "translatable"`` const string declarations
* ``dialogue: [{ id: "l01", text: "translatable", speaker: "Alice" }]``
  data records (branches/dialogue)
* ``name: "Alice"`` (and similar identifier-shaped strings)

Returns a dict mapping ``ts_<index>`` keys to the original string.
Idempotent across re-extraction; no state is stored.
"""

from __future__ import annotations

import re
from pathlib import Path


PHASER_TEXT_RE = re.compile(
    r'this\.add\.text\s*\([^,]+,\s*[^,]+,\s*["\']([^"\']+)["\']',
    re.MULTILINE,
)
CONST_STRING_RE = re.compile(
    r"^\s*const\s+[A-Z_][A-Z0-9_]*\s*=\s*['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)
DIALOGUE_TEXT_RE = re.compile(
    r"\btext\s*:\s*['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)
SPEAKER_NAME_RE = re.compile(
    r"\bspeaker\s*:\s*['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)
NAME_FIELD_RE = re.compile(
    r"\bname\s*:\s*['\"]([A-Z][a-zA-Z0-9_]*)['\"]",
    re.MULTILINE,
)


def extract_from_typescript(src_path: str | Path) -> dict[str, str]:
    """Extract translatable strings from a single TypeScript file."""
    path = Path(src_path)
    if not path.exists():
        return {}
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}

    out: dict[str, str] = {}
    counter = 0

    seen: set[str] = set()

    for pattern in (PHASER_TEXT_RE, CONST_STRING_RE, DIALOGUE_TEXT_RE, SPEAKER_NAME_RE, NAME_FIELD_RE):
        for match in pattern.finditer(content):
            text = match.group(1).strip()
            if not text or len(text) < 2:
                continue
            if text in seen:
                continue
            seen.add(text)
            out[f"ts_{counter:04d}"] = text
            counter += 1

    return out


def extract_from_project(src_dir: str | Path) -> dict[str, str]:
    """Walk a project's ``src/`` tree and extract from every ``.ts`` file.

    Returns combined dict with globally unique keys (``ts_NNNN``).
    """
    src = Path(src_dir)
    if not src.exists():
        return {}

    combined: dict[str, str] = {}
    next_idx = 0
    for ts_file in sorted(src.rglob("*.ts")):
        file_strings = extract_from_typescript(ts_file)
        for key, value in file_strings.items():
            new_key = f"ts_{next_idx:04d}"
            combined[new_key] = value
            next_idx += 1
    return combined


def extract_from_data_json(data_dir: str | Path) -> dict[str, dict]:
    """Read ``src/game/data/`` JSON files and extract character names.

    Returns a dict with keys ``characters``, ``dialogue``, ``endings`` —
    each value is a dict of extracted items. Used to build a translation
    table specifically for proper nouns (character names).
    """
    import json as _json

    data_path = Path(data_dir)
    out: dict[str, dict] = {"characters": {}, "dialogue": {}, "endings": {}}

    chars_file = data_path / "characters.json"
    if chars_file.exists():
        try:
            data = _json.loads(chars_file.read_text(encoding="utf-8"))
            for c in data.get("characters", []):
                if isinstance(c, dict) and c.get("name"):
                    out["characters"][c["name"]] = c.get("role", "npc")
        except (ValueError, OSError):
            pass

    dialogue_file = data_path / "dialogue.json"
    if dialogue_file.exists():
        try:
            data = _json.loads(dialogue_file.read_text(encoding="utf-8"))
            for line in data.get("lines", []):
                if isinstance(line, dict) and line.get("speaker"):
                    out["dialogue"][line["speaker"]] = line.get("text", "")
        except (ValueError, OSError):
            pass

    endings_file = data_path / "endings.json"
    if endings_file.exists():
        try:
            data = _json.loads(endings_file.read_text(encoding="utf-8"))
            for e in data.get("endings", []):
                if isinstance(e, dict) and e.get("name"):
                    out["endings"][e["name"]] = e.get("epilogue_key", "")
        except (ValueError, OSError):
            pass

    return out

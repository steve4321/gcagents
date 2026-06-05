from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

from loguru import logger

from shared.config import AppConfig
from shared.constants import DEFAULT_ANALYSIS_MODEL, DEFAULT_CODE_MODEL, TRUNC_LLM_PROMPT_ERROR
from shared.llm_client import llm
from shared.memory import get_memory_store
from shared.vn_schema import is_visual_novel, validate_gdd

MAX_SELF_VERIFY_RETRIES = 2
MAX_SOURCE_CHARS_IN_PROMPT = 12000

GRID_GENRES = {
    "puzzle", "match-3", "match3", "merge", "sudoku", "tile",
    "grid", "bejeweled", "tetris", "candy", "2048",
}


def is_grid_genre(genre: str) -> bool:
    lower = genre.lower().replace("_", "-").replace(" ", "-")
    return lower in GRID_GENRES or any(g in lower for g in GRID_GENRES)


_PROMPT_CACHE: dict[str, str] = {}


def _load_prompt(name: str) -> str:
    """Load a prompt template from config/prompts/<name>.yaml.

    Returns the 'system' field. Caches per-name for performance.
    """
    if name in _PROMPT_CACHE:
        return _PROMPT_CACHE[name]
    from pathlib import Path
    import yaml as _yaml
    path = Path(__file__).resolve().parents[3] / "config" / "prompts" / f"{name}.yaml"
    with open(path) as _f:
        data = _yaml.safe_load(_f)
    _PROMPT_CACHE[name] = data["system"]
    return _PROMPT_CACHE[name]


PROGRAMMER_SYSTEM_PROMPT = _load_prompt("programmer")


def _read_existing_source(
    project_dir: Path, max_chars: int = MAX_SOURCE_CHARS_IN_PROMPT
) -> dict[str, str]:
    """Read existing .ts source files from project_dir/src/ for inclusion in retry prompt."""
    files: dict[str, str] = {}
    total = 0
    for f in sorted(project_dir.glob("src/**/*.ts")):
        rel = str(f.relative_to(project_dir))
        content = f.read_text(encoding="utf-8", errors="replace")
        files[rel] = content
        total += len(content)
        if total >= max_chars:
            break
    return files


async def generate_game_code(
    gdd: dict,
    project_dir: Path,
    config: AppConfig,
    build_error: str = "",
    art_assets_path: str = "",
) -> Path:
    logger.info(f"Generating Phaser 4 game code for: {gdd.get('title', 'unknown')}")

    project_dir.mkdir(parents=True, exist_ok=True)

    _scaffold_project(project_dir, gdd)

    if art_assets_path:
        _copy_art_assets(art_assets_path, project_dir)

    model = DEFAULT_CODE_MODEL
    max_tokens = 16384
    if not config.minimax_api_key:
        logger.error("No AI API key configured")
        return project_dir

    if is_visual_novel(gdd):
        vn_errors = validate_gdd(gdd)
        if vn_errors:
            logger.warning(
                f"VN GDD validation issues ({len(vn_errors)}): {vn_errors[:3]} — proceeding with code generation anyway"
            )
        code_path = await _generate_visual_novel(
            gdd, project_dir, config, model, max_tokens, art_assets_path
        )
        vn_verify_err = _vn_post_gen_verify(code_path)
        if vn_verify_err:
            logger.warning(f"VN post-gen verify failed: {vn_verify_err[:300]}")
    else:
        mechanics = gdd.get("mechanics")
        if mechanics and not build_error:
            code_path = await _generate_by_mechanics(
                gdd, project_dir, config, model, max_tokens, art_assets_path
            )
        else:
            code_path = await _generate_all_at_once(
                gdd, project_dir, config, model, max_tokens, build_error, art_assets_path
            )

    build_err = _install_and_build(code_path)
    self_verify_attempt = 0
    while build_err and self_verify_attempt < MAX_SELF_VERIFY_RETRIES:
        self_verify_attempt += 1
        logger.warning(
            f"Self-verify build failed (attempt {self_verify_attempt}/{MAX_SELF_VERIFY_RETRIES}): {build_err[:200]}"
        )

        existing_files = _read_existing_source(code_path)
        existing_block = ""
        if existing_files:
            parts = []
            for path, content in existing_files.items():
                parts.append(f"### {path}\n```typescript\n{content}\n```")
            existing_block = "\n\n## Current source files:\n\n" + "\n\n".join(parts)

        messages = [
            {"role": "system", "content": PROGRAMMER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"""Build FAILED with this error:

{build_err[:TRUNC_LLM_PROMPT_ERROR]}
{existing_block}

Fix the TypeScript/build errors. Return a JSON object with ONLY the files you modified. Keep the response under 4000 tokens — do NOT include unchanged files.""",
            },
        ]
        response = await llm.chat_completion(
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=16384,
            agent_name="programmer",
            project_name=gdd.get("title", "unknown"),
        )
        try:
            files = _parse_code_files(response[0])
        except ValueError:
            logger.warning("Self-verify fix parse failed, retrying with deepseek-v4-flash")
            response = await llm.chat_completion(
                model="deepseek-v4-flash",
                messages=messages,
                temperature=0.1,
                max_tokens=16384,
                agent_name="programmer",
                project_name=gdd.get("title", "unknown"),
            )
            files = _parse_code_files(response[0])
        for fp, content in files.items():
            if not _validate_file_path(code_path, fp):
                continue
            full_path = code_path / fp
            await asyncio.to_thread(full_path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(full_path.write_text, content, encoding='utf-8')
        logger.info(f"Self-verify fix #{self_verify_attempt}: {len(files)} files")
        build_err = _install_and_build(code_path)

    if build_err:
        logger.error(
            f"Build still failing after {MAX_SELF_VERIFY_RETRIES} self-verify attempts: {build_err[:200]}"
        )

    runtime_err = _runtime_verify(code_path)
    runtime_attempt = 0
    while runtime_err and runtime_attempt < MAX_SELF_VERIFY_RETRIES:
        runtime_attempt += 1
        logger.warning(
            f"Self-verify runtime failed (attempt {runtime_attempt}): {runtime_err[:200]}"
        )

        existing_files = _read_existing_source(code_path)
        existing_block = ""
        if existing_files:
            parts = []
            for path, content in existing_files.items():
                parts.append(f"### {path}\n```typescript\n{content}\n```")
            existing_block = "\n\n## Current source files:\n\n" + "\n\n".join(parts)

        messages = [
            {"role": "system", "content": PROGRAMMER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"""The game builds successfully but FAILS at runtime:

{runtime_err[:TRUNC_LLM_PROMPT_ERROR]}
{existing_block}

The HTML template has `<div id="game-container"></div>`. Your Phaser config MUST use `parent: 'game-container'`.
Fix the runtime errors. Return a JSON object with ONLY the files you modified.""",
            },
        ]
        response = await llm.chat_completion(
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=8192,
            agent_name="programmer",
            project_name=gdd.get("title", "unknown"),
        )
        try:
            files = _parse_code_files(response[0])
        except ValueError:
            logger.warning("Runtime fix parse failed, retrying with deepseek-v4-flash")
            response = await llm.chat_completion(
                model="deepseek-v4-flash",
                messages=messages,
                temperature=0.1,
                max_tokens=8192,
                agent_name="programmer",
                project_name=gdd.get("title", "unknown"),
            )
            files = _parse_code_files(response[0])
        for fp, content in files.items():
            if not _validate_file_path(code_path, fp):
                continue
            full_path = code_path / fp
            await asyncio.to_thread(full_path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(full_path.write_text, content, encoding='utf-8')

        build_err = _install_and_build(code_path)
        if build_err:
            logger.warning(f"Runtime fix broke build: {build_err[:200]}")
            break
        runtime_err = _runtime_verify(code_path)

    return code_path


async def _generate_by_mechanics(
    gdd: dict,
    project_dir: Path,
    config: AppConfig,
    model: str,
    max_tokens: int,
    art_assets_path: str = "",
) -> Path:
    mechanics = gdd["mechanics"]
    game_title = gdd.get("title", "game")
    logger.info(f"Generating code mechanic-by-mechanic: {len(mechanics)} mechanics")

    accumulated_files: dict[str, str] = {}

    for i, mechanic in enumerate(mechanics):
        dep_names = mechanic.get("dependencies", [])
        relevant_existing = {
            k: v
            for k, v in accumulated_files.items()
            if any(d in k.lower().replace("/", "_").replace(".", "_") for d in dep_names)
        }
        existing_summary = (
            "\n".join(
                f"- {path} ({len(content)} chars)" for path, content in relevant_existing.items()
            )
            if relevant_existing
            else "None yet."
        )

        art_instruction = ""
        if art_assets_path and i == 0:
            art_instruction = f"""
IMPORTANT: Art assets are available at: {art_assets_path}
In BootScene, load images from this path using this.load.image(). Copy image files to public/assets/ and reference them as 'assets/filename.png'.
In game scenes, use the loaded image sprites instead of placeholder shapes.
"""
        mechanic_prompt = f"""You are building a Phaser 4 + TypeScript game incrementally, mechanic by mechanic.

Game: {game_title}
Genre: {gdd.get("genre", "unknown")}
Summary: {gdd.get("summary", "")}

Current mechanic ({i + 1}/{len(mechanics)}): {json.dumps(mechanic, indent=2)}

Already implemented files (for context):
{existing_summary}

Implement this mechanic now. Return a JSON object mapping file paths to file contents.
- For the FIRST mechanic (order 0), include src/main.ts, src/game/config.ts, and any scene/entity files needed.
- For later mechanics, ADD new files or RETURN UPDATED versions of existing files.
- Use `import * as Phaser from 'phaser';`
- Use Phaser shapes/text for visuals. Make visuals POLISHED: use gradients, glow effects, scale animations, color transitions. Do NOT use plain unstyled rectangles.
- Include window.__TEST__ = {{ ready: false, state: () => ({{...}}) }} in GameScene.
- Include analytics: navigator.sendBeacon on game_start and game_over events.

Return ONLY a JSON object of file paths to contents."""

        if art_instruction:
            mechanic_prompt += f"\n\n{art_instruction}"

        response = await llm.chat_completion(
            model=model,
            messages=[
                {"role": "system", "content": PROGRAMMER_SYSTEM_PROMPT},
                {"role": "user", "content": mechanic_prompt},
            ],
            temperature=0.4,
            max_tokens=max_tokens,
            agent_name="programmer",
            project_name=game_title,
        )

        new_files = _parse_code_files(response[0])
        accumulated_files.update(new_files)
        logger.info(
            f"Mechanic '{mechanic.get('name', '?')}' → {len(new_files)} files (total: {len(accumulated_files)})"
        )

    src_dir = project_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    for file_path, content in accumulated_files.items():
        if not _validate_file_path(project_dir, file_path):
            continue
        full_path = project_dir / file_path
        await asyncio.to_thread(full_path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(full_path.write_text, content, encoding='utf-8')

    logger.info(f"Generated {len(accumulated_files)} total files from {len(mechanics)} mechanics")
    return project_dir


def _try_direct_json_parse(text: str) -> dict[str, str] | None:
    clean = text.strip()
    if clean.startswith("```"):
        first_nl = clean.index("\n") + 1 if "\n" in clean else 3
        last_fence = clean.rfind("```")
        if last_fence > first_nl:
            clean = clean[first_nl:last_fence].strip()
    # Try finding JSON object boundaries
    start = clean.find("{")
    if start >= 0:
        brace_count = 0
        for i in range(start, len(clean)):
            if clean[i] == "{":
                brace_count += 1
            elif clean[i] == "}":
                brace_count -= 1
            if brace_count == 0:
                clean = clean[start:i + 1]
                break
    try:
        parsed = json.loads(clean)
        if isinstance(parsed, dict):
            return {k: json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
                    for k, v in parsed.items()}
    except (json.JSONDecodeError, TypeError) as e:
        logger.debug(f"Direct JSON parse failed: {e}, text[:100]={clean[:100]}")
    return None


async def _vn_llm_round(
    prompt: str,
    model: str,
    max_tokens: int,
    game_title: str,
    round_label: str,
) -> dict[str, str]:
    """Execute one VN generation LLM round with DeepSeek fallback on parse failure."""
    response = await llm.chat_completion(
        model=model,
        messages=[
            {"role": "system", "content": PROGRAMMER_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
        max_tokens=max_tokens,
        agent_name="programmer",
        project_name=game_title,
    )
    try:
        return _parse_code_files(response[0])
    except ValueError:
        direct = _try_direct_json_parse(response[0])
        if direct is not None:
            return direct
        logger.warning(f"VN round '{round_label}' parse failed, retrying with deepseek-v4-flash")
        retry = await llm.chat_completion(
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": PROGRAMMER_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=max_tokens,
            agent_name="programmer",
            project_name=game_title,
        )
        try:
            return _parse_code_files(retry[0])
        except ValueError:
            direct = _try_direct_json_parse(retry[0])
            if direct is not None:
                return direct
            raise


def _extract_partial_data(result: dict[str, str]) -> dict:
    """Extract branching and dialogue dicts from a route round's LLM response.

    The response may contain "branching" and "dialogue" as top-level keys,
    or they may be JSON-encoded strings within the dict.
    """
    branching: dict = {}
    dialogue: dict = {}

    if "branching" in result:
        raw = result["branching"]
        branching = json.loads(raw) if isinstance(raw, str) else raw
    if "dialogue" in result:
        raw = result["dialogue"]
        dialogue = json.loads(raw) if isinstance(raw, str) else raw

    # Fallback: if keys aren't present, the entire result might be the partial data
    if not branching and not dialogue:
        for key, val in result.items():
            if isinstance(val, str):
                try:
                    parsed = json.loads(val)
                    if isinstance(parsed, dict):
                        if "nodes" in parsed:
                            branching = parsed
                        elif not dialogue and any(
                            isinstance(v, dict) and "speaker" in v for v in parsed.values()
                        ):
                            dialogue = parsed
                except (json.JSONDecodeError, TypeError):
                    pass

    return {"branching": branching, "dialogue": dialogue}


def _count_nodes(result: dict) -> int:
    """Count branching nodes in a route round response."""
    for val in result.values():
        if isinstance(val, str):
            try:
                parsed = json.loads(val)
                if isinstance(parsed, dict) and "nodes" in parsed:
                    return len(parsed["nodes"])
            except (json.JSONDecodeError, TypeError):
                pass
        elif isinstance(val, dict) and "nodes" in val:
            return len(val["nodes"])
    return 0


def _add_round_summary(
    summaries: list[str], label: str, files: dict[str, str], node_count: int = 0,
) -> None:
    """Append a one-line summary of a completed round for cross-round context."""
    parts = [label]
    if files:
        parts.append(f"files: {', '.join(sorted(files.keys())[:6])}")
    if node_count:
        parts.append(f"nodes: {node_count}")
    summaries.append(" | ".join(parts))


def _merge_vn_data(
    partial_data_list: list[dict], gdd: dict,
) -> tuple[dict, dict]:
    """Merge multiple partial branching/dialogue dicts into unified files."""
    merged_branching: dict = {
        "root": "",
        "nodes": {},
        "edges": [],
        "routes": {},
    }
    merged_dialogue: dict = {}

    gdd_tree = gdd.get("branching_tree", {})
    gdd_root = gdd_tree.get("root", "")

    for partial in partial_data_list:
        branching = partial.get("branching", {})
        dialogue = partial.get("dialogue", {})

        if isinstance(branching, dict):
            nodes = branching.get("nodes", {})
            if isinstance(nodes, list):
                for n in nodes:
                    if isinstance(n, dict) and "id" in n:
                        merged_branching["nodes"][n["id"]] = n
            elif isinstance(nodes, dict):
                merged_branching["nodes"].update(nodes)
            edges = branching.get("edges", [])
            if isinstance(edges, list):
                merged_branching["edges"].extend(edges)

        if isinstance(dialogue, dict):
            merged_dialogue.update(dialogue)

    if gdd_root and gdd_root in merged_branching["nodes"]:
        merged_branching["root"] = gdd_root
    elif "common_start" in merged_branching["nodes"]:
        merged_branching["root"] = "common_start"
    elif merged_branching["nodes"]:
        merged_branching["root"] = next(iter(merged_branching["nodes"]))

    # Generate edges from node choices if edges are sparse
    if not merged_branching["edges"] and merged_branching["nodes"]:
        edge_set = set()
        for nid, node in merged_branching["nodes"].items():
            for choice in node.get("choices", []):
                target = choice.get("next_node", "")
                if target:
                    key = (nid, target)
                    if key not in edge_set:
                        edge_set.add(key)
                        merged_branching["edges"].append({"from": nid, "to": target})
            if node.get("next"):
                key = (nid, node["next"])
                if key not in edge_set:
                    edge_set.add(key)
                    merged_branching["edges"].append({"from": nid, "to": node["next"]})

    # Build routes metadata from node ID prefixes
    route_prefixes: dict[str, list[str]] = {}
    for node_id in merged_branching["nodes"]:
        prefix = node_id.rsplit("_", 1)[0] if "_" in node_id else "common"
        route_prefixes.setdefault(prefix, []).append(node_id)
    for prefix, node_ids in route_prefixes.items():
        merged_branching["routes"][prefix] = {
            "node_count": len(node_ids),
            "start_node": f"{prefix}_start" if f"{prefix}_start" in merged_branching["nodes"] else node_ids[0],
        }

    return merged_branching, merged_dialogue


def _validate_vn_data_consistency(project_dir: Path) -> list[str]:
    """Validate cross-file data consistency in generated VN project.

    Checks:
        - All next_node references in branching.json exist as nodes
        - All dialogue_refs in nodes exist in dialogue.json
        - All stat names in choices/endings match stats.json
    """
    errors: list[str] = []
    data_dir = project_dir / "src" / "game" / "data"

    branching = _load_json_safe(data_dir / "branching.json")
    dialogue = _load_json_safe(data_dir / "dialogue.json")
    stats = _load_json_safe(data_dir / "stats.json")
    endings = _load_json_safe(data_dir / "endings.json")

    if not branching:
        errors.append("branching.json missing or invalid")
        return errors

    nodes = branching.get("nodes", {})
    node_ids = set(nodes.keys())

    # Check next_node references
    for node_id, node in nodes.items():
        if not isinstance(node, dict):
            continue
        for choice in node.get("choices", []) or []:
            if not isinstance(choice, dict):
                continue
            nxt = choice.get("next_node", "")
            if nxt and nxt not in node_ids:
                errors.append(f"Node '{node_id}' references missing next_node '{nxt}'")

    # Check dialogue refs
    if dialogue:
        dialogue_ids = set(dialogue.keys()) if isinstance(dialogue, dict) else set()
        for node_id, node in nodes.items():
            if not isinstance(node, dict):
                continue
            for ref in node.get("dialogue_refs", []) or []:
                if ref and ref not in dialogue_ids:
                    errors.append(f"Node '{node_id}' references missing dialogue '{ref}'")

    # Check stat names in choices match stats.json
    if stats:
        stat_names = set()
        stats_list = stats.get("stats", stats) if isinstance(stats, dict) else stats
        if isinstance(stats_list, list):
            for s in stats_list:
                if isinstance(s, dict) and "name" in s:
                    stat_names.add(s["name"])

        if stat_names:
            for node_id, node in nodes.items():
                if not isinstance(node, dict):
                    continue
                for choice in node.get("choices", []) or []:
                    if not isinstance(choice, dict):
                        continue
                    deltas = choice.get("stat_deltas", {})
                    if isinstance(deltas, dict):
                        for stat_name in deltas:
                            if stat_name not in stat_names:
                                errors.append(
                                    f"Node '{node_id}' choice references unknown stat '{stat_name}'"
                                )

            # Check ending triggers
            endings_list = endings.get("endings", endings) if isinstance(endings, dict) else endings
            if isinstance(endings_list, list):
                for ending in endings_list:
                    if not isinstance(ending, dict):
                        continue
                    trigger = ending.get("trigger", {})
                    if isinstance(trigger, dict):
                        for stat_name in trigger:
                            if stat_name not in stat_names:
                                errors.append(
                                    f"Ending '{ending.get('name', '?')}' references unknown stat '{stat_name}'"
                                )

    return errors


def _load_json_safe(path: Path) -> dict | None:
    """Load a JSON file, returning None on any error."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


async def _vn_auto_fix_data(
    project_dir: Path, model: str, errors: list[str], game_title: str,
) -> bool:
    """Attempt one LLM round to fix data consistency issues."""
    data_dir = project_dir / "src" / "game" / "data"
    existing_data: dict[str, str] = {}

    for fname in ("branching.json", "dialogue.json", "stats.json", "endings.json", "characters.json"):
        fpath = data_dir / fname
        if fpath.exists():
            existing_data[fname] = fpath.read_text(encoding="utf-8")[:3000]

    fix_prompt = f"""The following Visual Novel data files have consistency errors.

Errors found:
{chr(10).join(f'- {e}' for e in errors)}

Current data files:
{chr(10).join(f'### {name}{chr(10)}{content}' for name, content in existing_data.items())}

Fix the errors. Return a JSON object mapping file paths (relative to project root, e.g. "src/game/data/branching.json") to the CORRECTED file contents.
Only return files that need changes.

Return ONLY a JSON object mapping file paths to file contents."""

    try:
        fixes = await _vn_llm_round(fix_prompt, model, 4096, game_title, "Data Fix")
        for fp, content in fixes.items():
            if not _validate_file_path(project_dir, fp):
                continue
            full_path = project_dir / fp
            text_content = content if isinstance(content, str) else json.dumps(content, indent=2, ensure_ascii=False)
            await asyncio.to_thread(full_path.write_text, text_content, encoding="utf-8")
        return bool(fixes)
    except Exception as e:
        logger.warning(f"VN auto-fix failed: {e}")
        return False


def _copy_vn_data_to_public(project_dir: Path) -> None:
    """Copy src/game/data/*.json to public/assets/data/ for runtime loading."""
    src_dir = project_dir / "src" / "game" / "data"
    dst_dir = project_dir / "public" / "assets" / "data"
    if not src_dir.exists():
        return
    dst_dir.mkdir(parents=True, exist_ok=True)
    for json_file in src_dir.glob("*.json"):
        shutil.copy2(json_file, dst_dir / json_file.name)
        logger.debug(f"Copied data to public: {json_file.name}")


async def _generate_all_at_once(
    gdd: dict,
    project_dir: Path,
    config: AppConfig,
    model: str,
    max_tokens: int,
    build_error: str,
    art_assets_path: str = "",
) -> Path:
    game_title = gdd.get("title", "game")
    art_instruction = ""
    if art_assets_path:
        art_instruction = f"""
IMPORTANT: Art assets are available at: {art_assets_path}
In BootScene, load images from this path using this.load.image(). Copy image files to public/assets/ and reference them as 'assets/filename.png'.
In game scenes, use the loaded image sprites instead of placeholder shapes.
"""

    # --- RETRY PATH: include existing source code in prompt ---
    if build_error:
        existing_files = _read_existing_source(project_dir)
        existing_block = ""
        if existing_files:
            parts = []
            for path, content in existing_files.items():
                parts.append(f"### {path}\n```typescript\n{content}\n```")
            existing_block = "\n\n## Current source files:\n\n" + "\n\n".join(parts)

        retry_max_tokens = min(max_tokens, 8192)
        messages = [
            {"role": "system", "content": PROGRAMMER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"""The previous build/QA FAILED with these specific issues:

{build_error[:TRUNC_LLM_PROMPT_ERROR]}
{existing_block}

Fix ONLY the files that need to change. Return a JSON object with ONLY the files you modified.
Do NOT return unchanged files.""",
            },
        ]

        response = await llm.chat_completion(
            model=model,
            messages=messages,
            temperature=0.3,
            max_tokens=retry_max_tokens,
            agent_name="programmer",
            project_name=game_title,
        )

        text = response[0]
        files = _parse_code_files(text)

        for file_path, content in files.items():
            if not _validate_file_path(project_dir, file_path):
                continue
            full_path = project_dir / file_path
            await asyncio.to_thread(full_path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(full_path.write_text, content, encoding='utf-8')
            logger.debug(f"Fixed: {file_path}")

        logger.info(f"Fix applied: {len(files)} files modified")
        return project_dir

    # --- MULTI-ROUND GENERATION PATH ---
    genre = gdd.get("genre", "arcade")
    tech_arch = gdd.get("technical_architecture", {})

    past_lessons = await _get_past_lessons(genre)

    code_path = await _generate_multi_round(
        gdd=gdd,
        project_dir=project_dir,
        model=model,
        max_tokens=max_tokens,
        art_instruction=art_instruction,
        past_lessons=past_lessons,
    )

    return code_path


async def _get_past_lessons(genre: str) -> str:
    memory = get_memory_store()
    try:
        lessons = await memory.search_long_term(
            query=f"programmer {genre} success failure pattern",
            category="lesson:programmer",
            limit=3,
        )
        if not lessons:
            return ""
        lines = []
        for lesson in lessons:
            summary = lesson.get("summary", lesson.get("content", ""))[:200]
            lines.append(f"- {summary}")
        return "\n## Past Experience ({genre} games):\n" + "\n".join(lines)
    except Exception as e:
        logger.debug(f"Could not fetch past lessons: {e}")
        return ""


async def _generate_multi_round(
    gdd: dict,
    project_dir: Path,
    model: str,
    max_tokens: int,
    art_instruction: str,
    past_lessons: str,
) -> Path:
    game_title = gdd.get("title", "game")
    genre = gdd.get("genre", "arcade")
    tech_arch = gdd.get("technical_architecture", {})
    data_files = tech_arch.get("data_driven", {})

    lessons_block = past_lessons if past_lessons else ""

    accumulated_files: dict[str, str] = {}

    # Round 1: Core engine — scenes, config, boot, player input
    round1_prompt = f"""You are building a Phaser 4 + TypeScript game. This is ROUND 1 of 4: Core Engine.

Game: {game_title}
Genre: {genre}
{lessons_block}

From the GDD:
- Scenes: {json.dumps(gdd.get('scenes', []))}
- Physics: {tech_arch.get('physics_engine', 'arcade')}
- Pattern: {tech_arch.get('game_pattern', 'state_machine')}
- Code Organization: {tech_arch.get('code_organization', 'scenes/entities/systems')}
{art_instruction}

Generate the core engine files:
1. src/main.ts - Entry point with Phaser config (parent: 'game-container')
2. src/game/config.ts - Game configuration
3. src/game/scenes/BootScene.ts - Asset loading (load images from assets/ if available)
4. src/game/scenes/MenuScene.ts - Main menu with START button
5. src/game/scenes/GameScene.ts - Main gameplay scene SKELETON with:
   - Player input handling (keyboard + mouse/touch)
   - Physics setup (if required)
   - The __TEST__ interface with full state: score, level, lives, isGameOver, enemyTypesSeen (array), powerupsUsed (number), sessionTime (seconds)
   - Basic update loop
   - Analytics: navigator.sendBeacon on game_start and game_over
6. src/game/scenes/GameOverScene.ts - Game over with score display and restart
7. src/game/entities/Player.ts - Player entity class (if entity-based)

Use `import * as Phaser from 'phaser';`
Set parent: 'game-container' in game config.
{lessons_block}

Return ONLY a JSON object mapping file paths to file contents."""

    r1_response = await llm.chat_completion(
        model=model,
        messages=[
            {"role": "system", "content": PROGRAMMER_SYSTEM_PROMPT},
            {"role": "user", "content": round1_prompt},
        ],
        temperature=0.4,
        max_tokens=max_tokens,
        agent_name="programmer",
        project_name=game_title,
    )
    r1_files = _parse_code_files(r1_response[0])
    accumulated_files.update(r1_files)
    logger.info(f"Round 1 (Core Engine): {len(r1_files)} files")

    # Round 2: Data layer — JSON data files
    if data_files:
        round2_prompt = f"""You are building a Phaser 4 + TypeScript game. This is ROUND 2 of 4: Data Layer.

Game: {game_title}, Genre: {genre}

The GDD specifies these data-driven files: {json.dumps(data_files)}
Mechanics: {json.dumps(gdd.get('mechanics', []))}
Balance: {json.dumps(gdd.get('balance', {}))}
Progression: {gdd.get('progression', '10 levels with increasing difficulty')}

Generate the data JSON files. Each file must contain realistic game content with enough depth for a commercial-quality game:
- Levels: at least 10 levels with increasing difficulty, each specifying enemies, obstacles, powerups, and difficulty_multiplier
- Enemies: at least 3-5 enemy types with distinct behavior patterns, speed, health, and attack patterns
- Powerups: at least 4-6 powerups with meaningful effects and duration
- Upgrades: if applicable, an upgrade tree with at least 6 upgrades at increasing costs

Return ONLY a JSON object mapping file paths to file contents. Files should go in src/game/data/."""

        r2_response = await llm.chat_completion(
            model=model,
            messages=[{"role": "user", "content": round2_prompt}],
            temperature=0.3,
            max_tokens=8192,
            agent_name="programmer",
            project_name=game_title,
        )
        r2_files = _parse_code_files(r2_response[0])
        accumulated_files.update(r2_files)
        logger.info(f"Round 2 (Data Layer): {len(r2_files)} files")

    # Round 3: Core gameplay — enemies, items, game systems
    existing_summary = _summarize_files(accumulated_files)
    round3_prompt = f"""You are building a Phaser 4 + TypeScript game. This is ROUND 3 of 4: Core Gameplay.

Game: {game_title}, Genre: {genre}
Entities: {json.dumps(gdd.get('entities', []))}
Core Loop: {json.dumps(gdd.get('core_loop', []))}

Already implemented files:
{existing_summary}

Now implement the core gameplay systems:
1. Enemy AI entities (src/game/entities/) — at least 3 distinct types with different behaviors
2. Projectile/weapon system (if shooter/action)
3. Collision/interaction handlers
4. Item/powerup pickup system
5. Level loading from data files (if Round 2 generated data/)
6. Score system with combos/multipliers

IMPORTANT: Update GameScene.ts to integrate ALL new entities and systems. Return the UPDATED GameScene.ts plus all new files.
Use `import * as Phaser from 'phaser';`

Return ONLY a JSON object mapping file paths to file contents. Include updated versions of any existing files that need changes."""

    r3_response = await llm.chat_completion(
        model=model,
        messages=[
            {"role": "system", "content": PROGRAMMER_SYSTEM_PROMPT},
            {"role": "user", "content": round3_prompt},
        ],
        temperature=0.4,
        max_tokens=max_tokens,
        agent_name="programmer",
        project_name=game_title,
    )
    r3_files = _parse_code_files(r3_response[0])
    accumulated_files.update(r3_files)
    logger.info(f"Round 3 (Core Gameplay): {len(r3_files)} files")

    # Round 4: Progression, polish, retention mechanics
    existing_summary = _summarize_files(accumulated_files)
    monetization = gdd.get("monetization", {})
    round4_prompt = f"""You are building a Phaser 4 + TypeScript game. This is ROUND 4 of 4: Progression & Polish.

Game: {game_title}, Genre: {genre}
Monetization: {json.dumps(monetization)}
Art Style: {json.dumps(gdd.get('art_style', {}))}
Audio: {json.dumps(gdd.get('audio', {}))}

Already implemented files:
{existing_summary}

Now add progression systems and polish:
1. Upgrade shop / skill tree (src/game/systems/UpgradeSystem.ts or similar)
2. Achievement system (if in monetization retention_hooks)
3. Visual polish: tween animations, particle effects, screen shake on impacts
4. UI polish: HUD styling, level transition effects
5. Pause menu with settings
6. Ad placeholder integration (between levels, rewarded video on game over)
7. Tutorial hint system (first level guidance)

Update GameScene.ts and any other files that need integration.
Use `import * as Phaser from 'phaser';`

Return ONLY a JSON object mapping file paths to file contents. Include updated versions of any existing files that need changes."""

    r4_response = await llm.chat_completion(
        model=model,
        messages=[
            {"role": "system", "content": PROGRAMMER_SYSTEM_PROMPT},
            {"role": "user", "content": round4_prompt},
        ],
        temperature=0.4,
        max_tokens=max_tokens,
        agent_name="programmer",
        project_name=game_title,
    )
    r4_files = _parse_code_files(r4_response[0])
    accumulated_files.update(r4_files)
    logger.info(f"Round 4 (Progression & Polish): {len(r4_files)} files")

    # Write all accumulated files
    src_dir = project_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    for file_path, content in accumulated_files.items():
        if not _validate_file_path(project_dir, file_path):
            continue
        full_path = project_dir / file_path
        await asyncio.to_thread(full_path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(full_path.write_text, content, encoding='utf-8')
        logger.debug(f"Generated: {file_path}")

    logger.info(
        f"Multi-round generation complete: {len(accumulated_files)} total files across 4 rounds"
    )
    return project_dir


def _summarize_files(files: dict[str, str], max_chars: int = 2000) -> str:
    lines = []
    total = 0
    for path, content in sorted(files.items()):
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        line_count = content.count("\n") + 1
        exports = []
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("export class ") or stripped.startswith("export interface "):
                exports.append(stripped.split("{")[0].replace("export ", "").strip())
        entry = f"  {path} ({line_count} lines"
        if exports:
            entry += f", exports: {', '.join(exports[:5])}"
        entry += ")"
        lines.append(entry)
        total += len(entry)
        if total >= max_chars:
            lines.append(f"  ... ({len(files)} files total)")
            break
    return "\n".join(lines)


def _scaffold_project(project_dir: Path, gdd: dict | None = None) -> None:
    package_json = {
        "name": project_dir.name,
        "version": "1.0.0",
        "type": "module",
        "scripts": {
            "dev": "vite",
            "build": "vite build",
            "preview": "vite preview",
        },
        "dependencies": {
            "phaser": "^4.0.0",
        },
        "devDependencies": {
            "typescript": "^5.5.0",
            "vite": "^6.0.0",
        },
    }

    tsconfig = {
        "compilerOptions": {
            "target": "ES2020",
            "module": "ESNext",
            "strict": True,
            "moduleResolution": "bundler",
            "esModuleInterop": True,
            "skipLibCheck": True,
            "outDir": "./dist",
            "rootDir": "./src",
        },
        "include": ["src/**/*"],
        "files": ["node_modules/phaser/types/phaser.d.ts"],
    }

    vite_config = """import { defineConfig } from 'vite';

export default defineConfig({
  base: './',
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
  },
  server: {
    port: 3000,
    open: true,
  },
});
"""

    target_platforms: list[str] = []
    if gdd:
        proposal = gdd.get("proposal", {})
        if isinstance(proposal, dict):
            target_platforms = proposal.get("target_platforms", [])
        if not target_platforms:
            target_platforms = gdd.get("target_platforms", [])

    from shared.ad_sdk import get_ad_helper_js, get_sdk_script_tags

    sdk_script_tags = get_sdk_script_tags(target_platforms)
    sdk_scripts_block = f"\n  {sdk_script_tags}" if sdk_script_tags else ""
    ad_helper_block = get_ad_helper_js(target_platforms)

    index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{gdd.get('title', 'Visual Novel') if gdd else 'Visual Novel'}</title>
  <style>
    body {{ margin: 0; background: #000; display: flex; justify-content: center; align-items: center; height: 100vh; font-family: 'Noto Sans CJK SC', 'Microsoft YaHei', 'PingFang SC', 'Hiragino Sans GB', sans-serif; overflow: hidden; }}
    #game-container {{ display: flex; justify-content: center; align-items: center; }}
    canvas {{ display: block; }}
  </style>{sdk_scripts_block}
</head>
<body>
  <div id="game-container"></div>
  {ad_helper_block}
  <script type="module" src="/src/main.ts"></script>
</body>
</html>
"""

    (project_dir / "package.json").write_text(json.dumps(package_json, indent=2))
    (project_dir / "tsconfig.json").write_text(json.dumps(tsconfig, indent=2))
    (project_dir / "vite.config.ts").write_text(vite_config)
    (project_dir / "index.html").write_text(index_html)

    public_dir = project_dir / "public"
    public_dir.mkdir(exist_ok=True)


def _copy_art_assets(art_assets_path: str, project_dir: Path) -> None:
    from shared.config import ROOT_DIR as _ROOT
    src = Path(art_assets_path)
    if not src.exists():
        logger.warning(f"Art assets path does not exist: {art_assets_path}")
        return
    try:
        src_resolved = src.resolve()
    except OSError as e:
        logger.warning(f"Art assets path could not be resolved: {art_assets_path}: {e}")
        return
    allowed_root = (_ROOT / "data" / "art").resolve()
    try:
        src_resolved.relative_to(allowed_root)
    except ValueError:
        logger.warning(
            f"Refusing to copy art assets from outside allowed root: {src_resolved} "
            f"(allowed: {allowed_root})"
        )
        return
    dst = project_dir / "public" / "assets"
    dst.mkdir(parents=True, exist_ok=True)
    for f in src_resolved.iterdir():
        if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"):
            shutil.copy2(f, dst / f.name)
            logger.debug(f"Copied art asset: {f.name}")


def _install_and_build(project_dir: Path) -> str:
    """Run npm install + build. Returns empty string on success, error message on failure."""
    try:
        subprocess.run(
            ["npm", "install"], cwd=str(project_dir), capture_output=True, timeout=120, check=True
        )
        logger.info("npm install completed")
        result = subprocess.run(
            ["npm", "run", "build"], cwd=str(project_dir), capture_output=True, timeout=120
        )
        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace")[:500]
            logger.warning(f"Build failed: {stderr}")
            return f"npm build failed: {stderr}"
        logger.info("Build succeeded")
        return ""
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors="replace")[:500] if e.stderr else str(e)
        return f"npm install failed: {stderr}"
    except FileNotFoundError:
        return "npm not found"
    except Exception as e:
        return f"Build error: {e}"
    finally:
        shutil.rmtree(project_dir / "node_modules", ignore_errors=True)


def _runtime_verify(project_dir: Path) -> str:
    """Open built game in headless Playwright, check canvas renders. Returns '' on success."""
    import asyncio

    from playwright.async_api import async_playwright

    dist_html = project_dir / "dist" / "index.html"
    if not dist_html.exists():
        return "dist/index.html not found"

    async def _check():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 800, "height": 600})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))

            url = f"file://{dist_html.resolve()}"
            await page.goto(url, wait_until="networkidle", timeout=15000)
            await page.wait_for_timeout(3000)

            canvas = await page.query_selector("canvas")
            container = await page.query_selector("#game-container canvas")
            has_canvas = canvas is not None or container is not None

            await browser.close()

            if errors:
                return f"Runtime JS errors: {'; '.join(e[:200] for e in errors[:3])}"
            if not has_canvas:
                body_html = await page.inner_text("body")
                return f"No canvas element found after 3s. Phaser failed to initialize. Body content: {body_html[:200] or '(empty)'}"
            return ""

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, _check())
        try:
            return future.result(timeout=30)
        except Exception as e:
            return f"Runtime verify error: {e}"


def _vn_post_gen_verify(project_dir: Path) -> str:
    """Run VN-specific schema checks on the generated code. Returns '' on success.

    Validates:
        * ``src/game/data/branching.json`` against ``validate_branching_tree``
        * ``src/game/data/endings.json`` against ``validate_ending_conditions``
    """
    from shared.vn_schema import validate_branching_tree, validate_ending_conditions

    errors: list[str] = []

    branching_path = project_dir / "src" / "game" / "data" / "branching.json"
    if branching_path.exists():
        try:
            with open(branching_path, encoding="utf-8") as f:
                data = json.load(f)
            errs = validate_branching_tree(data.get("branching_tree", {}))
            if errs:
                errors.extend([f"branching.json: {e}" for e in errs])
        except (json.JSONDecodeError, OSError) as e:
            errors.append(f"branching.json: parse/read error: {e}")

    endings_path = project_dir / "src" / "game" / "data" / "endings.json"
    if endings_path.exists():
        try:
            with open(endings_path, encoding="utf-8") as f:
                data = json.load(f)
            endings_list = data.get("endings", data) if isinstance(data, dict) else data
            errs = validate_ending_conditions(endings_list if isinstance(endings_list, list) else [])
            if errs:
                errors.extend([f"endings.json: {e}" for e in errs])
        except (json.JSONDecodeError, OSError) as e:
            errors.append(f"endings.json: parse/read error: {e}")

    return "; ".join(errors)


async def _generate_visual_novel(
    gdd: dict,
    project_dir: Path,
    config: AppConfig,
    model: str,
    max_tokens: int,
    art_assets_path: str = "",
) -> Path:
    """Generate a hybrid Visual Novel via route-by-route generation.

    Flow:
        Round 1:   Engine code (systems + skeleton scenes + config + main)
        Round 2:   Common route data (branching nodes + dialogue, ~12 nodes)
        Round 3-N: One character route per round (~8 nodes each)
        Round N+1: Endings + remaining data (stats.json, characters.json)
        Round N+2: Scene code (BootScene, TitleScene, MenuScene, update NovelScene)
        Merge:     Combine all partial data into unified branching.json + dialogue.json
        Validate:  Data consistency check + auto-fix if needed
    """
    game_title = gdd.get("title", "visual_novel")
    route_structure = gdd.get("route_structure", {})
    common_route = route_structure.get("common_route", {})
    character_routes = route_structure.get("character_routes", [])
    if not character_routes:
        # No explicit routes — synthesize 6 default routes for scale
        character_routes = [
            {"name": f"route_{i}", "heroine": f"heroine_{i}",
             "theme": f"path {i}", "nodes": 20}
            for i in range(6)
        ]
    total_rounds = 2 + len(character_routes) + 1 + 1  # engine + common + routes + endings + scenes
    logger.info(f"VN code gen route-by-route: {game_title} ({total_rounds} rounds, {len(character_routes)} character routes)")

    art_instruction = ""
    if art_assets_path:
        art_instruction = (
            f"\nArt assets available at: {art_assets_path}\n"
            "Load images via this.load.image() in BootScene. Reference as 'assets/<filename>'.\n"
        )

    accumulated: dict[str, str] = {}
    # Track partial data from each route round for later merging
    partial_data_list: list[dict] = []
    # Track round summaries for cross-round context
    round_summaries: list[str] = []

    char_summary = json.dumps(gdd.get("character_roster", []), indent=2)[:2000]
    stats_summary = json.dumps(gdd.get("stat_system", {}), indent=2)[:1000]

    # ── Round 1: Engine Code ──────────────────────────────────────────
    round_num = 1
    round1_prompt = f"""You are building a hybrid Visual Novel with Phaser 4 + TypeScript. ROUND {round_num} of {total_rounds}: ENGINE CODE.

Game: {game_title}
Narrative Premise: {gdd.get('narrative_premise', '')}
Player Protagonist: {json.dumps(gdd.get('player_protagonist', {}))}
Character Roster (truncated): {char_summary}
Stat System: {stats_summary}

Generate these files (return a JSON object mapping file paths to file contents):

1. src/game/config.ts — Phaser game config with parent:'game-container', scene list, scale settings
2. src/main.ts — Phaser entry, scene list [BootScene, TitleScene, MenuScene, NovelScene], window.__TEST__ with state() returning {{ currentScene, currentRoute, stats, flags, cgsUnlocked, routeProgress, endingReached, saveDataValid, visitedScenes, endingsReached }}
3. src/game/scenes/NovelScene.ts — SKELETON only: import systems, create() sets up containers, update() loop. The DialogueSystem/ChoiceSystem/Bran­chingEngine will be integrated in a later round.
4. src/game/systems/DialogueSystem.ts — typewriter-style dialogue renderer. MUST implement:
   showChoices(node: any), showAnimated(), hideAnimated(), destroy()
5. src/game/systems/BranchingEngine.ts — DAG traversal + condition evaluation + scene progression. MUST implement:
   getCurrentNode(), advance(choiceId: string), getVisitedNodes(), getActiveRoutes()
6. src/game/systems/ChoiceSystem.ts — choice UI panel with stat_delta application. MUST implement:
   showChoices(node: any), showAnimated(), hideAnimated(), destroy()
7. src/game/systems/StatSystem.ts — stat tracking with branching thresholds. MUST implement:
   get(name: string), set(name: string, value: number), applyDeltas(deltas: Record<string,number>), evaluateConditions(conditions: any): boolean

INTERFACE CONTRACTS (STRICT — these exact method signatures MUST exist):
- ChoiceSystem: showChoices(node), showAnimated(), hideAnimated(), destroy()
- BranchingEngine: getCurrentNode(), advance(choiceId), getVisitedNodes(), getActiveRoutes()
- StatSystem: get(name), set(name, value), applyDeltas(deltas), evaluateConditions(conditions)

FORBIDDEN: importing 'fs', 'path', 'os' — these crash in browser. This is a Phaser browser game.

Rules:
- `import * as Phaser from 'phaser';` (NOT `import Phaser from 'phaser'`)
- parent: 'game-container' in Phaser config
- TypeScript strict mode
- Real implementation, no TODOs or 'for simplicity' placeholders
{art_instruction}

Return ONLY a JSON object mapping file paths to file contents."""

    r1_files = await _vn_llm_round(
        round1_prompt, model, max_tokens, game_title, "Engine Code"
    )
    accumulated.update(r1_files)
    _add_round_summary(round_summaries, "Round 1 (Engine Code)", r1_files)
    logger.info(f"VN Round 1 (Engine Code): {len(r1_files)} files")

    # ── Round 2: Common Route Data ────────────────────────────────────
    round_num = 2
    common_nodes_expected = common_route.get("nodes", 30) if isinstance(common_route, dict) else 30
    common_theme = common_route.get("theme", "shared prologue and introduction") if isinstance(common_route, dict) else "shared prologue"
    existing_summary = _summarize_files(accumulated)
    past_rounds_ctx = "\n".join(round_summaries)

    round2_prompt = f"""You are building a hybrid Visual Novel. ROUND {round_num} of {total_rounds}: COMMON ROUTE DATA.

Game: {game_title}
Narrative Premise: {gdd.get('narrative_premise', '')}
Common Route Theme: {common_theme}
Expected nodes: ~{common_nodes_expected}

Past rounds summary:
{past_rounds_ctx}

Already implemented files:
{existing_summary}

Generate a JSON object with EXACTLY these two keys:
- "branching": A partial branching tree dict with "nodes" (dict of node_id -> node_obj) and "edges" (list).
  Each node MUST have: scene_key (str), dialogue_refs (list of dialogue IDs), and optionally choices (list of {{text, next_node, stat_deltas}}).
  Generate ~{common_nodes_expected} nodes for the common/shared route. Use IDs like "common_01", "common_02", etc.
  The first node ID should be "common_start".
- "dialogue": A dict mapping dialogue_id -> dialogue_obj.
  Each dialogue obj has: id, scene_id, speaker, text, and optional expression.
  Generate 10-20 dialogue entries for common route scenes.

Rules:
- All next_node references must point to node IDs that exist in this round OR will exist (use "common_*" pattern).
- The last common route node should have choices pointing to character route start nodes (e.g. "route_<name>_start").
- Keep total output concise but complete — do NOT truncate the JSON.

Return ONLY a JSON object with "branching" and "dialogue" keys."""

    r2_result = await _vn_llm_round(
        round2_prompt, model, 16384, game_title, "Common Route Data"
    )
    partial_data_list.append(_extract_partial_data(r2_result))
    _add_round_summary(round_summaries, f"Round {round_num} (Common Route)", {}, node_count=_count_nodes(r2_result))
    logger.info(f"VN Round {round_num} (Common Route): 2 keys in response")

    # ── Round 3..N: Character Routes ─────────────────────────────────────
    for idx, route in enumerate(character_routes):
        round_num = 3 + idx
        route_name = route.get("name", f"route_{idx}") if isinstance(route, dict) else f"route_{idx}"
        route_heroine = route.get("heroine", "") if isinstance(route, dict) else ""
        route_nodes = route.get("nodes", 20) if isinstance(route, dict) else 20
        route_theme = route.get("theme", "") if isinstance(route, dict) else ""
        past_rounds_ctx = "\n".join(round_summaries[-3:])

        route_prompt = f"""You are building a hybrid Visual Novel. ROUND {round_num} of {total_rounds}: CHARACTER ROUTE "{route_name}".

Game: {game_title}
Narrative Premise: {gdd.get('narrative_premise', '')}
Route: {route_name}
Heroine: {route_heroine}
Theme: {route_theme}
Expected nodes: ~{route_nodes}

Recent rounds summary:
{past_rounds_ctx}

Generate a JSON object with EXACTLY these two keys:
- "branching": Partial branching tree with "nodes" and "edges". Generate ~{route_nodes} nodes for this route.
  Use node IDs like "{route_name}_01", "{route_name}_02", etc. First node: "{route_name}_start".
  Each node has: scene_key, dialogue_refs, and optionally choices ({{text, next_node, stat_deltas}}).
  The route should branch from common route and eventually lead to an ending node.
  End choices should point to ending nodes like "ending_<type>".
- "dialogue": Dict of dialogue_id -> {{id, scene_id, speaker, text, expression?}}.
  Generate 30-50 dialogue entries specific to this route's story.
  Each dialogue "text" MUST be 200-400 Chinese characters of deep, literary prose.
  This is a NOVEL — dialogue should reveal character, advance plot, build tension.

Rules:
- All next_node references should use "{route_name}_*" or "ending_*" patterns.
- Include at least 3 meaningful choices that affect stats.
- Keep total output concise but complete — do NOT truncate the JSON.
- Deep, character-driven dialogue — Chinese literary prose, not shallow placeholder text.
- Each choice should also have "label" field (display text) and "id" field.

Return ONLY a JSON object with "branching" and "dialogue" keys."""

        route_result = await _vn_llm_round(
            route_prompt, model, 16384, game_title, f"Route: {route_name}"
        )
        partial_data_list.append(_extract_partial_data(route_result))
        _add_round_summary(round_summaries, f"Round {round_num} ({route_name})", {}, node_count=_count_nodes(route_result))
        logger.info(f"VN Round {round_num} ({route_name}): generated route data")

    # ── Round N+1: Endings + Data Files ───────────────────────────────
    round_num = 2 + len(character_routes) + 1
    endings_summary = json.dumps(gdd.get("ending_conditions", []), indent=2)[:1500]
    past_rounds_ctx = "\n".join(round_summaries[-3:])

    endings_prompt = f"""You are building a hybrid Visual Novel. ROUND {round_num} of {total_rounds}: ENDINGS & DATA FILES.

Game: {game_title}
Ending Conditions from GDD: {endings_summary}
Stat System: {stats_summary}
Character Roster (truncated): {char_summary}

Recent rounds summary:
{past_rounds_ctx}

Generate a JSON object mapping file paths to file contents:
1. src/game/data/endings.json — ending definitions. Each ending has: name, trigger (dict of stat conditions), epilogue_key, is_good_ending.
   At least 3 endings (one good, one normal, one bad). Trigger conditions must reference stat names from the stat system.
2. src/game/data/stats.json — stat definitions from the GDD. Each stat: name, range [min, max], decay, branching_thresholds.
   At least 5 stats.

Rules:
- Stat names must exactly match those referenced in branching choices.
- Trigger conditions use format: {{"stat_name": {{">=": value}}}}.
- Keep total output concise but complete — do NOT truncate the JSON.

Return ONLY a JSON object mapping file paths to file contents."""

    endings_files = await _vn_llm_round(
        endings_prompt, model, 16384, game_title, "Endings & Data"
    )
    accumulated.update(endings_files)
    _add_round_summary(round_summaries, f"Round {round_num} (Endings & Data)", endings_files)
    logger.info(f"VN Round {round_num} (Endings & Data): {len(endings_files)} files")

    # ── Round N+2: Scene Code ─────────────────────────────────────────
    round_num = 2 + len(character_routes) + 2
    existing_summary = _summarize_files(accumulated)
    past_rounds_ctx = "\n".join(round_summaries[-3:])

    scene_prompt = f"""You are building a hybrid Visual Novel. ROUND {round_num} of {total_rounds}: SCENE CODE.

Game: {game_title}

Already implemented files:
{existing_summary}

Past rounds summary:
{past_rounds_ctx}

Generate these scene files (return JSON mapping path -> content):
1. src/game/scenes/BootScene.ts — Load all data/*.json files via this.load.json() using RELATIVE path 'assets/data/<filename>.json' (NOT '/game/data/...' — that's the source path, build output is at assets/data/), transition to TitleScene.
2. src/game/scenes/TitleScene.ts — Title screen with game name in Chinese and English, press-to-start or click-to-start.
3. src/game/scenes/MenuScene.ts — NEW GAME / CONTINUE / GALLERY menu with visual polish.
4. src/game/scenes/NovelScene.ts — FULL implementation integrating BranchingEngine, StatSystem, ChoiceSystem, DialogueSystem.
   On create(): load branching.json and dialogue.json from this.cache.json, initialize systems, start at root node.
   On each node: display dialogue via DialogueSystem, then show choices via ChoiceSystem.
   On choice: apply stat deltas, advance BranchingEngine, check endings.
   If ending conditions met, transition to ending display.

Rules:
- `import * as Phaser from 'phaser';` (NOT `import Phaser from 'phaser'`)
- Access loaded JSON via this.cache.json.get('key') or scene.settings.data
- FORBIDDEN: importing 'fs', 'path', 'os' — browser crash
- TypeScript strict mode
- Real implementation, no TODOs
{art_instruction}

Return ONLY a JSON object mapping file paths to file contents."""

    scene_files = await _vn_llm_round(
        scene_prompt, model, max_tokens, game_title, "Scene Code"
    )
    accumulated.update(scene_files)
    _add_round_summary(round_summaries, f"Round {round_num} (Scene Code)", scene_files)
    logger.info(f"VN Round {round_num} (Scene Code): {len(scene_files)} files")

    # ── Merge all partial route data into unified files ───────────────
    logger.info(f"VN: Merging {len(partial_data_list)} partial route data sets")
    merged_branching, merged_dialogue = _merge_vn_data(partial_data_list, gdd)

    # Write merged data files
    data_dir = project_dir / "src" / "game" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    branching_path = data_dir / "branching.json"
    dialogue_path = data_dir / "dialogue.json"
    await asyncio.to_thread(
        branching_path.write_text,
        json.dumps(merged_branching, indent=2, ensure_ascii=False),
        "utf-8",
    )
    await asyncio.to_thread(
        dialogue_path.write_text,
        json.dumps(merged_dialogue, indent=2, ensure_ascii=False),
        "utf-8",
    )
    accumulated["src/game/data/branching.json"] = json.dumps(merged_branching, indent=2, ensure_ascii=False)
    accumulated["src/game/data/dialogue.json"] = json.dumps(merged_dialogue, indent=2, ensure_ascii=False)
    logger.info(
        f"VN: Merged branching.json ({len(merged_branching.get('nodes', {}))} nodes, "
        f"{len(merged_branching.get('edges', []))} edges) + dialogue.json ({len(merged_dialogue)} entries)"
    )

    # Copy data files to public/assets/data/ for runtime loading
    _copy_vn_data_to_public(project_dir)

    # ── Write all accumulated code files ──────────────────────────────
    src_dir = project_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    for file_path, content in accumulated.items():
        if not _validate_file_path(project_dir, file_path):
            continue
        full_path = project_dir / file_path
        await asyncio.to_thread(full_path.parent.mkdir, parents=True, exist_ok=True)
        text_content = content if isinstance(content, str) else json.dumps(content, indent=2, ensure_ascii=False)
        await asyncio.to_thread(full_path.write_text, text_content, encoding="utf-8")

    # ── Data consistency validation + auto-fix ────────────────────────
    consistency_errors = _validate_vn_data_consistency(project_dir)
    if consistency_errors:
        logger.warning(f"VN data consistency issues ({len(consistency_errors)}): {consistency_errors[:5]}")
        fixed = await _vn_auto_fix_data(project_dir, model, consistency_errors, game_title)
        if fixed:
            _copy_vn_data_to_public(project_dir)
            logger.info("VN: Auto-fix applied and data re-copied to public/")

    from shared.data_contract import extract_data_schemas, validate_data_against_schema, validate_code_against_schema

    schemas = extract_data_schemas(gdd)
    for data_type in ["branching", "dialogue", "stats", "endings"]:
        data_path = project_dir / "src" / "game" / "data" / f"{data_type}.json"
        if data_path.exists():
            with open(data_path, encoding="utf-8") as f:
                data = json.load(f)
            errs = validate_data_against_schema(data, schemas, data_type)
            if errs:
                logger.error(f"Schema contract violation ({data_type}): {errs[:5]}")

    code_errs = validate_code_against_schema(accumulated, schemas.get("code_interfaces", {}))
    if code_errs:
        logger.error(f"Code interface violations: {code_errs[:5]}")

    logger.info(f"VN generation complete: {len(accumulated)} files across {total_rounds} rounds")
    return project_dir


def _validate_file_path(project_dir: Path, rel_path: str) -> bool:
    """Validate that rel_path does not escape project_dir (path traversal defense)."""
    if ".." in Path(rel_path).parts:
        logger.warning(f"Skipping file with '..' in path: {rel_path}")
        return False
    resolved = (project_dir / rel_path).resolve()
    if not resolved.is_relative_to(project_dir.resolve()):
        logger.warning(
            f"Skipping file outside project directory: {rel_path} (resolved to {resolved})"
        )
        return False
    return True


def _parse_code_files(text: str) -> dict[str, str]:
    text = text.strip()

    # Case 1: wrapped in ```json ... ```
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    # Case 2: raw JSON
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Case 3: find first { ... } in text
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        result = json.loads(text[start:end])
        if isinstance(result, dict):
            return result
    except (ValueError, json.JSONDecodeError):
        pass

    # Case 4: multiple ```json blocks — concatenate
    import re

    blocks = re.findall(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if blocks:
        combined = {}
        for block in blocks:
            try:
                d = json.loads(block.strip())
                if isinstance(d, dict):
                    combined.update(d)
            except json.JSONDecodeError:
                continue
        if combined:
            return combined

    # Case 5: mixed JSON with code-fence values — extract file paths and contents
    # LLM may return {"path": "```ts\ncode\n```", ...} which is not valid JSON
    try:
        import re as _re
        file_pattern = _re.compile(
            r'"((?:src|public)[^"]+)"\s*:\s*`([^`]*(?:`[^`]*)*)`',
            _re.DOTALL,
        )
        if file_pattern.search(text):
            result = {}
            for match in file_pattern.finditer(text):
                result[match.group(1)] = match.group(2)
            if result:
                return result
    except Exception:
        pass

    raise ValueError(f"Failed to parse generated code files (text starts: {text[:200]})")

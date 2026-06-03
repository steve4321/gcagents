from __future__ import annotations

import json
import subprocess
import shutil
from pathlib import Path

from loguru import logger

from shared.config import AppConfig
from shared.constants import TRUNC_LLM_PROMPT_ERROR
from shared.llm_client import llm

MAX_SELF_VERIFY_RETRIES = 2
MAX_SOURCE_CHARS_IN_PROMPT = 12000


PROGRAMMER_SYSTEM_PROMPT = """You are an expert Phaser 4 + TypeScript game developer.
Given a GDD (Game Design Document), generate a complete, playable Phaser 4 game.

Generate the following files:
1. `src/main.ts` - Entry point
2. `src/game/config.ts` - Game configuration
3. `src/game/scenes/BootScene.ts` - Asset loading
4. `src/game/scenes/MenuScene.ts` - Main menu
5. `src/game/scenes/GameScene.ts` - Main gameplay (most important)
6. `src/game/scenes/GameOverScene.ts` - Game over screen
7. `src/game/entities/` - Game entities as needed
8. `src/game/systems/` - Game systems as needed

Rules:
- Use Phaser 4 API (not Phaser 3)
- All code must be valid TypeScript with strict mode
- CRITICAL: Use `import * as Phaser from 'phaser';` (NOT `import Phaser from 'phaser';` - Phaser ESM has no default export)
- If an art_assets_path is provided in the prompt, load images from that directory in BootScene using this.load.image() and use them in game scenes instead of placeholder shapes. Copy image files from art_assets_path into the project's public/assets/ directory. Use the actual sprite/background filenames from that path.
- If no art_assets_path is provided, use Phaser's built-in shape rendering for visuals (placeholder geometry)
- Implement ALL mechanics specified in the GDD — do not skip or simplify any mechanic
- Each mechanic must have real gameplay depth: state changes, visual feedback, player interaction
- Include at least 3 enemy/obstacle types with distinct behaviors (not just recolored copies)
- Implement a progression system across levels with increasing difficulty
- Add visual feedback for all player actions: tween animations, color changes, particle effects
- Include a scoring system with combos or multipliers when applicable
- Include basic game loop: start → play → end
- Add keyboard/mouse/touch controls
- Use window.__TEST__ = { ready: false, state: () => ({...}) } for test access
- Include basic gameplay analytics: call `navigator.sendBeacon('/api/analytics/event', new URLSearchParams({ game: '{game_name}', event: 'game_start' }))` when the game starts, and report 'game_over' with final score and 'play_time' in seconds when the game ends. This is non-blocking and should NOT impact gameplay.
- Audio files are loaded via `<script>` tags in index.html (assets/audio/bgm.js and assets/audio/sfx.js). They export `window.GameBGM` and `window.GameSFX`. Use `window.GameBGM.start()` to start background music, `window.GameBGM.stop()` to stop it. Use `window.GameSFX.jump()`, `window.GameSFX.collect()`, `window.GameSFX.hit()`, `window.GameSFX.gameover()`, or `window.GameSFX.click()` to play sound effects at appropriate moments.

Return a JSON object mapping file paths to file contents:
{"src/main.ts": "...", "src/game/scenes/GameScene.ts": "...", ...}"""


def _read_existing_source(project_dir: Path, max_chars: int = MAX_SOURCE_CHARS_IN_PROMPT) -> dict[str, str]:
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


async def generate_game_code(gdd: dict, project_dir: Path, config: AppConfig, build_error: str = "", art_assets_path: str = "") -> Path:
    logger.info(f"Generating Phaser 4 game code for: {gdd.get('title', 'unknown')}")

    project_dir.mkdir(parents=True, exist_ok=True)

    _scaffold_project(project_dir)

    if art_assets_path:
        _copy_art_assets(art_assets_path, project_dir)

    model = "deepseek-v4-flash"
    max_tokens = 16384
    if not config.deepseek_api_key:
        logger.error("No AI API key configured")
        return project_dir

    mechanics = gdd.get("mechanics")
    if mechanics and not build_error:
        code_path = await _generate_by_mechanics(gdd, project_dir, config, model, max_tokens, art_assets_path)
    else:
        code_path = await _generate_all_at_once(gdd, project_dir, config, model, max_tokens, build_error, art_assets_path)

    build_err = _install_and_build(code_path)
    self_verify_attempt = 0
    while build_err and self_verify_attempt < MAX_SELF_VERIFY_RETRIES:
        self_verify_attempt += 1
        logger.warning(f"Self-verify build failed (attempt {self_verify_attempt}/{MAX_SELF_VERIFY_RETRIES}): {build_err[:200]}")

        existing_files = _read_existing_source(code_path)
        existing_block = ""
        if existing_files:
            parts = []
            for path, content in existing_files.items():
                parts.append(f"### {path}\n```typescript\n{content}\n```")
            existing_block = "\n\n## Current source files:\n\n" + "\n\n".join(parts)

        messages = [
            {"role": "system", "content": PROGRAMMER_SYSTEM_PROMPT},
            {"role": "user", "content": f"""Build FAILED with this error:

{build_err[:TRUNC_LLM_PROMPT_ERROR]}
{existing_block}

Fix the TypeScript/build errors. Return a JSON object with ONLY the files you modified."""},
        ]
        response = await llm.chat_completion(
            model=model, messages=messages, temperature=0.2, max_tokens=8192,
            agent_name="programmer", project_name=gdd.get("title", "unknown"),
        )
        files = _parse_code_files(response[0])
        for fp, content in files.items():
            full_path = code_path / fp
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")
        logger.info(f"Self-verify fix #{self_verify_attempt}: {len(files)} files")
        build_err = _install_and_build(code_path)

    if build_err:
        logger.error(f"Build still failing after {MAX_SELF_VERIFY_RETRIES} self-verify attempts: {build_err[:200]}")

    return code_path


async def _generate_by_mechanics(
    gdd: dict, project_dir: Path, config: AppConfig, model: str, max_tokens: int, art_assets_path: str = "",
) -> Path:
    mechanics = gdd["mechanics"]
    game_title = gdd.get("title", "game")
    logger.info(f"Generating code mechanic-by-mechanic: {len(mechanics)} mechanics")

    accumulated_files: dict[str, str] = {}

    for i, mechanic in enumerate(mechanics):
        dep_names = mechanic.get("dependencies", [])
        relevant_existing = {k: v for k, v in accumulated_files.items()
                             if any(d in k.lower().replace("/", "_").replace(".", "_") for d in dep_names)}
        existing_summary = "\n".join(
            f"- {path} ({len(content)} chars)" for path, content in relevant_existing.items()
        ) if relevant_existing else "None yet."

        art_instruction = ""
        if art_assets_path and i == 0:
            art_instruction = f"""
IMPORTANT: Art assets are available at: {art_assets_path}
In BootScene, load images from this path using this.load.image(). Copy image files to public/assets/ and reference them as 'assets/filename.png'.
In game scenes, use the loaded image sprites instead of placeholder shapes.
"""
        mechanic_prompt = f"""You are building a Phaser 4 + TypeScript game incrementally, mechanic by mechanic.

Game: {game_title}
Genre: {gdd.get('genre', 'unknown')}
Summary: {gdd.get('summary', '')}

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
        logger.info(f"Mechanic '{mechanic.get('name', '?')}' → {len(new_files)} files (total: {len(accumulated_files)})")

    src_dir = project_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    for file_path, content in accumulated_files.items():
        full_path = project_dir / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

    logger.info(f"Generated {len(accumulated_files)} total files from {len(mechanics)} mechanics")
    return project_dir


async def _generate_all_at_once(
    gdd: dict, project_dir: Path, config: AppConfig, model: str, max_tokens: int, build_error: str, art_assets_path: str = "",
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
            {"role": "user", "content": f"""The previous build/QA FAILED with these specific issues:

{build_error[:TRUNC_LLM_PROMPT_ERROR]}
{existing_block}

Fix ONLY the files that need to change. Return a JSON object with ONLY the files you modified.
Do NOT return unchanged files."""},
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
            full_path = project_dir / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")
            logger.debug(f"Fixed: {file_path}")

        logger.info(f"Fix applied: {len(files)} files modified")
        return project_dir

    # --- NEW GENERATION PATH ---
    user_prompt = f"""Generate a complete Phaser 4 + TypeScript game based on this GDD:

{json.dumps(gdd, indent=2)}
{art_instruction}

Generate ALL source files as a JSON object mapping file paths to file contents.
The game must be playable, engaging, and have depth. Implement ALL mechanics from the GDD with real gameplay logic (not stubs). Use Phaser shapes/text with polished visuals — add tween animations, color transitions, and visual feedback for every player action. Plain unstyled rectangles are NOT acceptable.
Include the window.__TEST__ interface for automated testing.
Include basic gameplay analytics: call `navigator.sendBeacon('/api/analytics/event', new URLSearchParams({{ game: '{game_title}', event: 'game_start' }}))` on game start, and report 'game_over' with score and 'play_time' on game end. Keep analytics non-blocking."""

    messages = [
        {"role": "system", "content": PROGRAMMER_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    response = await llm.chat_completion(
        model=model,
        messages=messages,
        temperature=0.4,
        max_tokens=max_tokens,
        agent_name="programmer",
        project_name=gdd.get("title", "unknown"),
    )

    text = response[0]
    files = _parse_code_files(text)

    src_dir = project_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    for file_path, content in files.items():
        full_path = project_dir / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        logger.debug(f"Generated: {file_path}")

    logger.info(f"Generated {len(files)} source files")
    return project_dir


def _scaffold_project(project_dir: Path) -> None:
    """Create package.json, tsconfig.json, vite.config.ts, and index.html."""
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

    index_html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Game</title>
  <style>
    body { margin: 0; background: #000; display: flex; justify-content: center; align-items: center; height: 100vh; }
    canvas { display: block; }
  </style>
</head>
<body>
  <script src="assets/audio/bgm.js"></script>
  <script src="assets/audio/sfx.js"></script>
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
    src = Path(art_assets_path)
    if not src.exists():
        logger.warning(f"Art assets path does not exist: {art_assets_path}")
        return
    dst = project_dir / "public" / "assets"
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"):
            shutil.copy2(f, dst / f.name)
            logger.debug(f"Copied art asset: {f.name}")


def _install_and_build(project_dir: Path) -> str:
    """Run npm install + build. Returns empty string on success, error message on failure."""
    try:
        subprocess.run(["npm", "install"], cwd=str(project_dir), capture_output=True, timeout=120, check=True)
        logger.info("npm install completed")
        result = subprocess.run(["npm", "run", "build"], cwd=str(project_dir), capture_output=True, timeout=120)
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


def _parse_code_files(text: str) -> dict[str, str]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]

    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        result = json.loads(text[start:end])
        if isinstance(result, dict):
            return result
    except (ValueError, json.JSONDecodeError):
        pass

    raise ValueError("Failed to parse generated code files")

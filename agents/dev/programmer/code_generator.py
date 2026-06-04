from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from loguru import logger

from shared.config import AppConfig
from shared.constants import DEFAULT_ANALYSIS_MODEL, DEFAULT_CODE_MODEL, TRUNC_LLM_PROMPT_ERROR
from shared.llm_client import llm
from shared.memory import get_memory_store

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
- Use window.__TEST__ for test access. The __TEST__ interface MUST be declared in GameScene's create() method and expose rich game state for automated evaluation:
  ```typescript
  (window as any).__TEST__ = {
    ready: false,
    state: () => ({
      score: this.score,
      level: this.currentLevel,
      lives: this.lives,
      isGameOver: this.isGameOver,
      enemyTypesSeen: this.enemyTypesSeen,
      powerupsUsed: this.powerupsUsed,
      sessionTime: (Date.now() - this.sessionStart) / 1000,
    })
  };
  ```
  Where: enemyTypesSeen is a Set/array of distinct enemy type names encountered, powerupsUsed counts power-up activations, sessionStart is Date.now() at game start. These fields are REQUIRED for gameplay depth evaluation.
- Include basic gameplay analytics: call `navigator.sendBeacon('/api/analytics/event', new URLSearchParams({ game: '{game_name}', event: 'game_start' }))` when the game starts, and report 'game_over' with final score and 'play_time' in seconds when the game ends. This is non-blocking and should NOT impact gameplay.
- The HTML template has `<div id="game-container"></div>`. Set `parent: 'game-container'` in your Phaser game config so the canvas is rendered inside it.

Return a JSON object mapping file paths to file contents:
{"src/main.ts": "...", "src/game/scenes/GameScene.ts": "...", ...}

Additional requirements:
- MONETIZATION: Implement the monetization model from the GDD. For ad_supported: add placeholder ad slots (interstitial between levels, rewarded video on game over for extra life). For free_to_play: implement IAP-tier unlock mechanics. For premium: ensure a complete experience.
- RETENTION: Implement at least 2 retention features from the GDD (daily challenges, streak tracking, unlock progression, achievement notifications)
- ENGAGEMENT: Implement at least 1 engagement mechanic (power-up collection, combo system with visual feedback, social share button on game over with score)
- PROGRESSION DEPTH: Include a visible progression system (level unlock, score milestones, collectible unlocks) that gives players a reason to return
"""


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

Fix the TypeScript/build errors. Return a JSON object with ONLY the files you modified.""",
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
        files = _parse_code_files(response[0])
        for fp, content in files.items():
            if not _validate_file_path(code_path, fp):
                continue
            full_path = code_path / fp
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")
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
        files = _parse_code_files(response[0])
        for fp, content in files.items():
            if not _validate_file_path(code_path, fp):
                continue
            full_path = code_path / fp
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")

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
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

    logger.info(f"Generated {len(accumulated_files)} total files from {len(mechanics)} mechanics")
    return project_dir


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
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")
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
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        logger.debug(f"Generated: {file_path}")

    logger.info(
        f"Multi-round generation complete: {len(accumulated_files)} total files across 4 rounds"
    )
    return project_dir


def _summarize_files(files: dict[str, str], max_chars: int = 2000) -> str:
    lines = []
    total = 0
    for path, content in sorted(files.items()):
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

    sdk_scripts = ""
    platform_js_init = ""
    target_platforms = []
    if gdd:
        proposal = gdd.get("proposal", {})
        if isinstance(proposal, dict):
            target_platforms = proposal.get("target_platforms", [])
        if not target_platforms:
            target_platforms = gdd.get("target_platforms", [])

    from shared.constants import PLATFORM_SDK_SNIPPETS
    for platform in target_platforms:
        snippet = PLATFORM_SDK_SNIPPETS.get(platform)
        if snippet:
            sdk_scripts += f"\n  {snippet}"

    if sdk_scripts:
        platform_js_init = """
  <script>
    window.__PLATFORM_SDK__ = window.__PLATFORM_SDK__ || {};
  </script>
"""

    index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Game</title>
  <style>
    body {{ margin: 0; background: #000; display: flex; justify-content: center; align-items: center; height: 100vh; }}
    #game-container {{ display: flex; justify-content: center; align-items: center; }}
    canvas {{ display: block; }}
  </style>{platform_js_init}{sdk_scripts}
</head>
<body>
  <div id="game-container"></div>
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

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return (
                    loop.run_in_executor(pool, lambda: asyncio.run(_check())).result()
                    if False
                    else asyncio.run(_check())
                )
        return asyncio.run(_check())
    except Exception as e:
        return f"Runtime verify error: {e}"


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

    raise ValueError(f"Failed to parse generated code files (text starts: {text[:200]})")

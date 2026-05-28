from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from loguru import logger
from openai import AsyncOpenAI

from shared.config import AppConfig


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
- Include placeholder geometry for assets (no external images needed for MVP)
- Use Phaser's built-in shape rendering for visuals
- Keep the game simple but fun and complete
- Include basic game loop: start → play → end
- Add keyboard/mouse/touch controls
- Use window.__TEST__ = { ready: false, state: () => ({...}) } for test access

Return a JSON object mapping file paths to file contents:
{"src/main.ts": "...", "src/game/scenes/GameScene.ts": "...", ...}"""


async def generate_game_code(gdd: dict, project_dir: Path, config: AppConfig, build_error: str = "") -> Path:
    logger.info(f"Generating Phaser 4 game code for: {gdd.get('title', 'unknown')}")

    project_dir.mkdir(parents=True, exist_ok=True)

    _scaffold_project(project_dir)

    if config.deepseek_api_key:
        client = AsyncOpenAI(api_key=config.deepseek_api_key, base_url="https://api.deepseek.com")
        model = "deepseek-coder"
        max_tokens = 16384
    elif config.zhipu_api_key:
        client = AsyncOpenAI(api_key=config.zhipu_api_key, base_url="https://open.bigmodel.cn/api/paas/v4")
        model = "glm-4-flash"
        max_tokens = 8192
    else:
        logger.error("No AI API key configured")
        return project_dir

    user_prompt = f"""Generate a complete Phaser 4 + TypeScript game based on this GDD:

{json.dumps(gdd, indent=2)}

Generate ALL source files as a JSON object mapping file paths to file contents.
The game must be playable and fun. Use Phaser shapes/text for visuals (no external assets).
Include the window.__TEST__ interface for automated testing."""

    messages = [
        {"role": "system", "content": PROGRAMMER_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    if build_error:
        messages.append({
            "role": "user",
            "content": f"The previous build FAILED with this error. Fix the code:\n\n{build_error[:2000]}\n\nReturn ALL source files again with the fixes applied.",
        })

    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.4,
        max_tokens=max_tokens,
    )

    text = response.choices[0].message.content or ""
    files = _parse_code_files(text)

    src_dir = project_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    for file_path, content in files.items():
        full_path = project_dir / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        logger.debug(f"Generated: {file_path}")

    logger.info(f"Generated {len(files)} source files")

    _install_and_build(project_dir)

    return project_dir


def _scaffold_project(project_dir: Path) -> None:
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


def _install_and_build(project_dir: Path) -> None:
    import subprocess

    try:
        subprocess.run(["npm", "install"], cwd=str(project_dir), capture_output=True, timeout=120, check=True)
        logger.info("npm install completed")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.warning(f"npm install skipped: {e}")


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

    logger.error("Failed to parse generated code files")
    return {}

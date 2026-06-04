from __future__ import annotations

import subprocess
from pathlib import Path

from loguru import logger

from orchestrator.state import CompanyState, PipelinePhase


async def build_game(state: CompanyState) -> dict:
    game_code_path = state.game_code_path
    if not game_code_path:
        return {"phase": PipelinePhase.IDLE, "errors": ["No game code to build"]}

    project_dir = Path(game_code_path)
    logger.info(f"Building game: {project_dir.name}")

    try:
        install_result = subprocess.run(
            ["npm", "install"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if install_result.returncode != 0:
            logger.error(f"npm install failed:\n{install_result.stderr}")
            return {
                "phase": PipelinePhase.DEVELOPING,
                "errors": [f"npm install failed: {install_result.stderr[:500]}"],
            }

        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            logger.error(f"Build failed:\n{result.stderr}")
            return {
                "phase": PipelinePhase.DEVELOPING,
                "errors": [f"Build failed: {result.stderr[:500]}"],
                "retry_count": state.retry_count + 1,
            }

        dist_dir = project_dir / "dist"
        if not dist_dir.exists():
            return {"phase": PipelinePhase.DEVELOPING, "errors": ["Build produced no output"]}

        logger.info(f"Build successful: {dist_dir}")
        return {"phase": PipelinePhase.PUBLISHING, "build_path": str(dist_dir)}

    except subprocess.TimeoutExpired:
        logger.error("Build timed out")
        return {
            "phase": PipelinePhase.DEVELOPING,
            "errors": ["Build timeout"],
            "retry_count": state.retry_count + 1,
        }

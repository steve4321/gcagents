from __future__ import annotations

from pathlib import Path

from loguru import logger

from orchestrator.state import CompanyState, PipelinePhase
from shared import npm_runner


async def build_game(state: CompanyState) -> dict:
    game_code_path = state.game_code_path
    if not game_code_path:
        return {"phase": PipelinePhase.IDLE, "errors": ["No game code to build"]}

    project_dir = Path(game_code_path)
    logger.info(f"Building game: {project_dir.name}")

    try:
        err = await npm_runner.install_and_build(project_dir)
        if err:
            logger.error(f"Build failed: {err}")
            return {
                "phase": PipelinePhase.DEVELOPING,
                "errors": [err[:500]],
                "retry_count": state.retry_count + 1,
            }

        dist_dir = project_dir / "dist"
        if not dist_dir.exists():
            return {"phase": PipelinePhase.DEVELOPING, "errors": ["Build produced no output"]}

        logger.info(f"Build successful: {dist_dir}")
        return {"phase": PipelinePhase.PUBLISHING, "build_path": str(dist_dir)}

    except Exception as e:
        logger.error(f"Build error: {e}")
        return {
            "phase": PipelinePhase.DEVELOPING,
            "errors": [str(e)],
            "retry_count": state.retry_count + 1,
        }

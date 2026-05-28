from __future__ import annotations

from pathlib import Path

from loguru import logger

from orchestrator.state import CompanyState, PipelinePhase
from shared.config import load_config

from .code_generator import generate_game_code


async def develop_game(state: CompanyState) -> dict:
    gdd = state.gdd
    if not gdd:
        logger.error("No GDD to develop")
        return {"phase": PipelinePhase.IDLE, "errors": ["Missing GDD"]}

    config = load_config()
    project_name = gdd.get("title", "untitled").lower().replace(" ", "-")
    project_dir = config.games_output_dir / project_name

    code_path = await generate_game_code(gdd, project_dir, config)

    return {"phase": PipelinePhase.TESTING, "game_code_path": str(code_path)}

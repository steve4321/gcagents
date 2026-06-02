from __future__ import annotations

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
    base_name = gdd.get("title", "untitled").lower().replace(" ", "-")
    project_dir = config.games_output_dir / base_name

    if project_dir.exists():
        from datetime import datetime
        stamp = datetime.now().strftime("%m%d%H%M")
        project_dir = config.games_output_dir / f"{base_name}-{stamp}"

    build_error = ""
    if state.errors:
        build_error = state.errors[0] if isinstance(state.errors, list) else str(state.errors)

    code_path = await generate_game_code(
        gdd, project_dir, config,
        build_error=build_error,
        art_assets_path=state.art_assets_path or "",
    )

    return {"phase": PipelinePhase.TESTING, "game_code_path": str(code_path)}

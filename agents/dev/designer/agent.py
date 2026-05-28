from __future__ import annotations

from loguru import logger

from orchestrator.state import CompanyState, PipelinePhase
from shared.config import load_config

from ..designer.gdd_generator import generate_gdd


async def design_game(state: CompanyState) -> dict:
    proposal = state.current_proposal
    if not proposal:
        logger.error("No proposal to design")
        return {"phase": PipelinePhase.IDLE, "errors": ["Missing proposal"]}

    config = load_config()
    gdd = await generate_gdd(proposal, config)

    return {"phase": PipelinePhase.DEVELOPING, "gdd": gdd}

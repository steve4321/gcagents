from __future__ import annotations

from loguru import logger

from shared.config import load_config
from shared.models import GameProposal

from .state import CompanyState, PipelinePhase


async def ceo_evaluate(state: CompanyState) -> dict:
    """CEO reviews market insights and decides whether to greenlight a project."""
    if not state.market_insights:
        logger.info("CEO: No market insights, triggering scan")
        return {"phase": PipelinePhase.SCANNING}

    top_opportunity = max(state.market_insights, key=lambda x: x.get("score", 0))
    threshold = 0.6

    if top_opportunity.get("score", 0) < threshold:
        logger.info(f"CEO: Best opportunity score {top_opportunity.get('score')} below {threshold}, waiting")
        return {"phase": PipelinePhase.IDLE}

    proposal = GameProposal(
        name=top_opportunity["name"],
        genre=top_opportunity["genre"],
        description=top_opportunity["description"],
        target_platforms=["itch.io", "web"],
        estimated_dev_hours=top_opportunity.get("estimated_hours", 8),
        market_opportunity_score=top_opportunity["score"],
        differentiation=top_opportunity.get("differentiation", ""),
        reference_games=top_opportunity.get("reference_games", []),
    )

    logger.info(f"CEO: Greenlit project '{proposal.name}' ({proposal.genre}), score={proposal.market_opportunity_score}")
    return {"phase": PipelinePhase.DESIGNING, "current_proposal": proposal}


async def route_after_qa(state: CompanyState) -> str:
    """After QA, decide: pass → build, fail → fix or abort."""
    if not state.qa_results:
        return "build"

    passed = state.qa_results.get("passed", False)
    if passed:
        return "build"

    if state.retry_count >= 3:
        logger.error(f"CEO: Project failed QA {state.retry_count} times, aborting")
        return "abort"

    logger.warning(f"CEO: QA failed (attempt {state.retry_count}/3), sending back to dev")
    return "redevelop"


async def route_after_operating(state: CompanyState) -> str:
    """After a period of operation, decide: iterate, retire, or continue."""
    return "continue"

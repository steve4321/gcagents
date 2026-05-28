from __future__ import annotations

from loguru import logger

from shared.config import load_config
from shared.models import GameProposal

from orchestrator.state import CompanyState, PipelinePhase


async def _get_completed_genres() -> set[str]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from shared.config import load_config

    config = load_config()
    engine = create_async_engine(config.db_url, echo=False)
    genres = set()
    async with AsyncSession(engine) as db:
        rows = await db.execute(text("SELECT DISTINCT genre FROM game_projects"))
        for row in rows.fetchall():
            if row.genre:
                genres.add(row.genre.lower())
    await engine.dispose()
    return genres


async def ceo_evaluate(state: CompanyState) -> dict:
    if not state.market_insights:
        logger.info("CEO: No market insights, triggering scan")
        return {"phase": PipelinePhase.SCANNING}

    completed_genres = await _get_completed_genres()
    opportunities = state.market_insights

    novel = [o for o in opportunities if o.get("genre", "").lower() not in completed_genres]
    if not novel:
        logger.info("CEO: All top genres already produced, picking best anyway")
        novel = opportunities

    top_opportunity = max(novel, key=lambda x: x.get("market_opportunity_score", x.get("score", 0)))
    threshold = 0.6

    score = top_opportunity.get("market_opportunity_score") or top_opportunity.get("score", 0)
    if score < threshold:
        logger.info(f"CEO: Best opportunity score {score} below {threshold}, waiting")
        return {"phase": PipelinePhase.IDLE}

    proposal = GameProposal(
        name=top_opportunity["name"],
        genre=top_opportunity["genre"],
        description=top_opportunity["description"],
        target_platforms=["itch.io", "web"],
        estimated_dev_hours=top_opportunity.get("estimated_dev_hours") or top_opportunity.get("estimated_hours", 8),
        market_opportunity_score=score,
        differentiation=top_opportunity.get("differentiation", ""),
        reference_games=top_opportunity.get("reference_games", []),
    )

    logger.info(f"CEO: Greenlit project '{proposal.name}' ({proposal.genre}), score={proposal.market_opportunity_score}")
    return {"phase": PipelinePhase.DESIGNING, "current_proposal": proposal}


async def route_after_qa(state: CompanyState) -> str:
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

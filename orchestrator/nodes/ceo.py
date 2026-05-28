from __future__ import annotations

from loguru import logger

from shared.config import load_config
from shared.models import GameProposal

from orchestrator.state import CompanyState, PipelinePhase


async def _get_completed_genres() -> set[str]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

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


async def _find_project_to_update() -> dict | None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    config = load_config()
    engine = create_async_engine(config.db_url, echo=False)
    async with AsyncSession(engine) as db:
        rows = await db.execute(
            text("""
                SELECT p.id, p.name, p.itch_url,
                       COUNT(f.id) AS unprocessed_count
                FROM game_projects p
                JOIN game_feedback f ON f.project_id = p.id AND f.processed = 0
                WHERE p.status IN ('live', 'updating')
                AND f.category IN ('bug', 'feature')
                GROUP BY p.id
                HAVING unprocessed_count >= 2
                ORDER BY unprocessed_count DESC
                LIMIT 1
            """)
        )
        row = rows.fetchone()
    await engine.dispose()

    if row:
        return {"id": row.id, "name": row.name, "itch_url": row.itch_url, "unprocessed_count": row.unprocessed_count}
    return None


async def ceo_evaluate(state: CompanyState) -> dict:
    update_target = await _find_project_to_update()
    if update_target:
        logger.info(
            f"CEO: {update_target['unprocessed_count']} actionable feedback items for "
            f"'{update_target['name']}', routing to MODE_UPDATE"
        )
        return {
            "phase": PipelinePhase.UPDATING,
            "current_project_id": update_target["id"],
            "current_proposal": GameProposal(
                name=update_target["name"],
                genre="update",
                description=f"Update based on {update_target['unprocessed_count']} feedback items",
                target_platforms=["itch.io", "web"],
                estimated_dev_hours=4,
                market_opportunity_score=0.0,
            ),
        }

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

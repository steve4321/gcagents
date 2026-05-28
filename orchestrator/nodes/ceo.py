from __future__ import annotations

import json
from datetime import datetime, timezone

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


async def _process_ceo_instructions(state: CompanyState) -> dict:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from shared.llm_client import llm

    from orchestrator.persistence import get_pending_instructions, log_event

    instructions = await get_pending_instructions("ceo")
    if not instructions:
        return {}

    updates: dict = {}
    forced_genre: str | None = None

    for instruction in instructions[:5]:
        content = instruction.get("content", "")
        if not content:
            continue

        try:
            response, usage = await llm.chat_completion(
                model="glm-4-flash",
                messages=[
                    {"role": "system", "content": (
                        "You are processing user instructions for an autonomous game company CEO. "
                        "Classify the user's intent and extract key information. "
                        "Respond in JSON format:\n"
                        '{"intent": "direction" | "question" | "feedback" | "stop", '
                        '"genre": "extracted_genre_or_null", '
                        '"summary": "brief_summary"}'
                    )},
                    {"role": "user", "content": content},
                ],
                max_tokens=200,
                temperature=0.1,
                agent_name="ceo",
            )

            try:
                parsed = json.loads(response)
            except json.JSONDecodeError:
                parsed = {"intent": "feedback", "genre": None, "summary": content[:100]}

            intent = parsed.get("intent", "feedback")
            genre = parsed.get("genre")
            summary = parsed.get("summary", content[:100])

        except Exception as e:
            logger.warning(f"CEO: Failed to process instruction: {e}")
            intent = "feedback"
            genre = None
            summary = content[:100]

        if intent == "direction" and genre:
            config = load_config()
            engine = create_async_engine(config.db_url, echo=False)
            async with AsyncSession(engine) as db:
                await db.execute(
                    text("""
                        INSERT INTO company_memory (category, title, content, importance, created_at)
                        VALUES ('directive', 'user_genre_directive', :content, 0.9, :now)
                    """),
                    {
                        "content": json.dumps({"genre": genre, "instruction": content, "source": "user_chat"}),
                        "now": datetime.now(timezone.utc).isoformat(),
                    },
                )
                await db.commit()
            await engine.dispose()

            forced_genre = genre
            await log_event(
                "pipeline", "info",
                f"CEO received user directive: make {genre} game",
                detail=content[:200], source_agent="ceo",
            )

        elif intent == "stop":
            await log_event(
                "pipeline", "warning",
                "CEO received stop instruction from user",
                detail=content[:200], source_agent="ceo",
            )
            updates["phase"] = PipelinePhase.IDLE

        elif intent == "question":
            await log_event("system", "info", f"CEO question: {summary}", source_agent="ceo")

        else:
            await log_event("system", "info", f"CEO user feedback: {summary}", source_agent="ceo")

        config = load_config()
        engine = create_async_engine(config.db_url, echo=False)
        async with AsyncSession(engine) as db:
            metadata = json.loads(instruction.get("metadata_json", instruction.get("metadata", "{}")))
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            metadata["processed"] = True
            await db.execute(
                text("UPDATE chat_messages SET metadata_json = :meta WHERE id = :mid"),
                {"meta": json.dumps(metadata), "mid": instruction["id"]},
            )
            await db.commit()
        await engine.dispose()

    if forced_genre and not updates.get("phase"):
        updates["_forced_genre"] = forced_genre

    return updates


async def ceo_evaluate(state: CompanyState) -> dict:
    instruction_updates = await _process_ceo_instructions(state)

    if instruction_updates.get("phase") == PipelinePhase.IDLE:
        return {"phase": PipelinePhase.IDLE}

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

    forced_genre = instruction_updates.get("_forced_genre")
    if forced_genre:
        forced_matches = [o for o in novel if o.get("genre", "").lower() == forced_genre.lower()]
        if forced_matches:
            novel = forced_matches
            logger.info(f"CEO: User directed genre '{forced_genre}', filtering to {len(forced_matches)} matches")
        else:
            logger.info(f"CEO: User directed genre '{forced_genre}', but no matching opportunities found")

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

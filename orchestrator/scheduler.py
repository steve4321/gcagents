from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger

from orchestrator.decision_gate import create_decision, get_pending, resolve
from orchestrator.event_bus import emit
from orchestrator.persistence import (
    get_all_projects,
    get_pending_decisions,
    get_pending_instructions,
    get_project,
    save_project,
    save_chat_message,
    update_project_phase,
)
from orchestrator.state import CompanyState, PipelinePhase
from orchestrator.task_queue import enqueue, dequeue, complete_task, fail_task, update_progress
from shared.models import ProjectPhase, ProjectState

_TICK_COUNT = 0
MARKET_SCAN_INTERVAL = 10


async def scheduler_tick() -> dict | None:
    global _TICK_COUNT
    _TICK_COUNT += 1

    logger.info(f"Scheduler tick #{_TICK_COUNT}")

    await _process_instructions()
    await _resolve_answered_decisions()

    if _TICK_COUNT % MARKET_SCAN_INTERVAL == 0:
        await _periodic_market_scan()

    await _advance_projects()

    task_result = await _execute_one_task()
    if task_result:
        await _apply_task_result(task_result)

    await _generate_reports()

    return {"tick": _TICK_COUNT}


async def _process_instructions() -> None:
    instructions = await get_pending_instructions("scheduler")
    if not instructions:
        return

    for instruction in instructions[:5]:
        content = instruction.get("content", "")
        if not content:
            continue
        await emit(
            "scheduler", "Scheduler received instruction",
            detail=content[:200], source_agent="scheduler",
        )
        await _handle_instruction(content)


async def _handle_instruction(content: str) -> None:
    import json
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession
    from orchestrator.persistence import _get_engine

    content_lower = content.lower()

    if any(kw in content_lower for kw in ("new project", "create project", "start project")):
        await create_decision(
            "new_project",
            f"Create new project from instruction: {content[:200]}",
            context={"source": "chat", "instruction": content},
        )
        await save_chat_message("assistant", "I'll create a decision to start a new project. Please approve or reject.", agent_name="scheduler")
    elif any(kw in content_lower for kw in ("status", "report", "how are")):
        projects = await get_all_projects()
        lines = [f"- {p.name} ({p.phase.value}): {p.progress:.0%}" for p in projects]
        msg = "Current project status:\n" + "\n".join(lines) if lines else "No active projects."
        await save_chat_message("assistant", msg, agent_name="scheduler")
    elif any(kw in content_lower for kw in ("cancel", "stop")):
        projects = await get_all_projects()
        active = [p for p in projects if p.phase not in (ProjectPhase.BACKLOG, ProjectPhase.CANCELLED, ProjectPhase.LIVE)]
        for p in active[:1]:
            await create_decision("cancel", f"Cancel project '{p.name}'?", project_id=p.id)
            await save_chat_message("assistant", f"Created cancellation decision for '{p.name}'.", agent_name="scheduler")


async def _resolve_answered_decisions() -> None:
    decisions = await get_pending_decisions()
    for d in decisions:
        if d.status.value != "pending":
            continue
        if d.human_response:
            resolved = await resolve(d.id, d.human_response)
            if not resolved:
                continue
            response = (resolved.human_response or "").lower()
            if response in ("approve", "approved"):
                await _handle_approved_decision(resolved)
            elif response in ("reject", "rejected"):
                await _handle_rejected_decision(resolved)


async def _handle_approved_decision(decision) -> None:
    dtype = decision.decision_type.value
    pid = decision.project_id

    if dtype == "new_project":
        ctx = decision.context
        name = ctx.get("name", f"project-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}")
        project = ProjectState(
            id=pid or _new_id(),
            name=name,
            genre=ctx.get("genre", ""),
            phase=ProjectPhase.SCANNING,
            proposal=ctx,
        )
        await save_project(project)
        await emit("scheduler", f"New project approved: {name}", source_agent="scheduler", project_name=name)

    elif dtype == "publish" and pid:
        await update_project_phase(pid, "publishing")
        project = await get_project(pid)
        if project:
            await enqueue(pid, "deploy", {"project_name": project.name})
            await emit("scheduler", f"Publishing approved for {project.name}", source_agent="scheduler", project_name=project.name)

    elif dtype == "budget_overrun" and pid:
        project = await get_project(pid)
        if project:
            await update_project_phase(pid, "developing")
            await emit("scheduler", f"Budget overrun approved, continuing {project.name}", source_agent="scheduler", project_name=project.name)

    elif dtype == "direction_change" and pid:
        ctx = decision.context
        project = await get_project(pid)
        if project:
            await update_project_phase(pid, "designing")
            await emit("scheduler", f"Direction change for {project.name}", source_agent="scheduler", project_name=project.name)


async def _handle_rejected_decision(decision) -> None:
    dtype = decision.decision_type.value
    pid = decision.project_id

    if dtype == "new_project":
        await emit("scheduler", "New project rejected", source_agent="scheduler")

    elif dtype == "cancel" and pid:
        project = await get_project(pid)
        if project:
            await emit("scheduler", f"Cancellation rejected, continuing {project.name}", source_agent="scheduler", project_name=project.name)

    elif dtype == "publish" and pid:
        await update_project_phase(pid, "testing")
        await emit("scheduler", "Publish rejected, sending back to testing", source_agent="scheduler")


async def _periodic_market_scan() -> None:
    logger.info("Scheduler: periodic market scan")
    await enqueue("__system__", "market_scan")


async def _advance_projects() -> None:
    projects = await get_all_projects()
    for project in projects:
        if project.phase in (ProjectPhase.BACKLOG, ProjectPhase.CANCELLED, ProjectPhase.LIVE, ProjectPhase.PAUSED):
            continue
        if project.awaiting_decision:
            continue
        await _advance_project(project)


async def _advance_project(project: ProjectState) -> None:
    phase = project.phase
    pid = project.id

    if phase == ProjectPhase.SCANNING:
        await enqueue(pid, "market_scan", {"project_name": project.name})

    elif phase == ProjectPhase.DESIGNING:
        await enqueue(pid, "design_game", {"project_name": project.name, "genre": project.genre})

    elif phase == ProjectPhase.DEVELOPING:
        if project.art_status != "done":
            await enqueue(pid, "art_gen", {"project_name": project.name, "gdd": project.gdd})
        else:
            await enqueue(pid, "develop", {"project_name": project.name, "gdd": project.gdd})

    elif phase == ProjectPhase.TESTING:
        await enqueue(pid, "qa", {"project_name": project.name, "code_path": project.code_path})

    elif phase == ProjectPhase.BUILDING:
        await enqueue(pid, "build", {"project_name": project.name, "code_path": project.code_path})

    elif phase == ProjectPhase.PUBLISHING:
        decision = await create_decision(
            "publish",
            f"Ready to publish '{project.name}'?",
            project_id=pid,
            context={"project_name": project.name, "version": project.version},
        )
        from orchestrator.persistence import _get_engine
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import AsyncSession
        engine = _get_engine()
        async with AsyncSession(engine) as db:
            await db.execute(
                text("UPDATE projects SET awaiting_decision=:d WHERE id=:id"),
                {"d": decision.id, "id": pid},
            )
            await db.commit()


async def _execute_one_task() -> dict | None:
    import json

    task = await dequeue()
    if not task:
        return None

    await update_progress(task.id, 0.0)
    task_type = task.task_type
    pid = task.project_id
    params = task.params

    logger.info(f"Scheduler: executing task '{task_type}' for project {pid}")

    try:
        result = await _run_agent(task_type, pid, params)
        await complete_task(task.id, result)
        return {"task": task, "result": result, "status": "completed"}
    except Exception as e:
        logger.error(f"Scheduler: task '{task_type}' failed: {e}")
        await fail_task(task.id, str(e))
        return {"task": task, "error": str(e), "status": "failed"}


async def _run_agent(task_type: str, project_id: str, params: dict) -> dict:
    project = await get_project(project_id) if project_id != "__system__" else None

    state = CompanyState(
        phase=PipelinePhase.IDLE,
        current_project_id=project_id if project_id != "__system__" else None,
        gdd=project.gdd if project else None,
        current_proposal=_proposal_from_project(project) if project else None,
    )

    if task_type == "market_scan":
        from agents.research.scanner import scan_market
        return await scan_market(state)

    elif task_type == "design_game":
        from agents.dev.designer.agent import design_game
        return await design_game(state)

    elif task_type == "art_gen":
        from agents.dev.artist.art_node import generate_art
        return await generate_art(state)

    elif task_type == "develop":
        from agents.dev.programmer.agent import develop_game
        return await develop_game(state)

    elif task_type == "qa":
        from agents.dev.qa.qa_agent import run_qa
        return await run_qa(state)

    elif task_type == "build":
        from agents.dev.builder.build_agent import build_game
        return await build_game(state)

    elif task_type == "deploy":
        from agents.ops.deployer.itch_deployer import deploy_to_itch
        return await deploy_to_itch(state)

    else:
        logger.warning(f"Scheduler: unknown task type '{task_type}'")
        return {"error": f"unknown task type: {task_type}"}


def _proposal_from_project(project: ProjectState | None):
    if not project or not project.proposal:
        return None
    from shared.models import GameProposal
    p = project.proposal
    return GameProposal(
        name=p.get("name", project.name),
        genre=p.get("genre", project.genre),
        description=p.get("description", ""),
        target_platforms=p.get("target_platforms", ["itch.io", "web"]),
        estimated_dev_hours=p.get("estimated_dev_hours", 8),
        market_opportunity_score=p.get("market_opportunity_score", 0.5),
        differentiation=p.get("differentiation", ""),
        reference_games=p.get("reference_games", []),
    )


async def _apply_task_result(task_result: dict) -> None:
    import json
    from orchestrator.persistence import _get_engine
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession

    task = task_result["task"]
    status = task_result["status"]
    pid = task.project_id

    if pid == "__system__":
        return

    if status == "failed":
        await emit("scheduler", f"Task '{task.task_type}' failed for project {pid}", severity="warning", source_agent="scheduler")
        return

    result = task_result.get("result", {})
    task_type = task.task_type
    project = await get_project(pid)
    if not project:
        return

    engine = _get_engine()

    if task_type == "market_scan":
        insights = result.get("market_insights", [])
        if insights:
            top = max(insights, key=lambda x: x.get("market_opportunity_score", x.get("score", 0)))
            async with AsyncSession(engine) as db:
                proposal = {
                    "name": top.get("name", project.name),
                    "genre": top.get("genre", project.genre),
                    "description": top.get("description", ""),
                    "market_opportunity_score": top.get("market_opportunity_score", top.get("score", 0)),
                }
                await db.execute(
                    text("UPDATE projects SET phase='designing', proposal=:proposal, updated_at=:now WHERE id=:id"),
                    {"proposal": json.dumps(proposal), "now": datetime.now(timezone.utc).isoformat(), "id": pid},
                )
                await db.commit()
        else:
            await update_project_phase(pid, "backlog")

    elif task_type == "design_game":
        gdd = result.get("gdd")
        if gdd:
            async with AsyncSession(engine) as db:
                await db.execute(
                    text("UPDATE projects SET gdd=:gdd, updated_at=:now WHERE id=:id"),
                    {"gdd": json.dumps(gdd), "now": datetime.now(timezone.utc).isoformat(), "id": pid},
                )
                await db.commit()
            await update_project_phase(pid, "developing")

    elif task_type == "art_gen":
        art_path = result.get("art_assets_path")
        async with AsyncSession(engine) as db:
            await db.execute(
                text("UPDATE projects SET art_status='done', updated_at=:now WHERE id=:id"),
                {"now": datetime.now(timezone.utc).isoformat(), "id": pid},
            )
            await db.commit()

    elif task_type == "develop":
        code_path = result.get("game_code_path")
        if code_path:
            async with AsyncSession(engine) as db:
                await db.execute(
                    text("UPDATE projects SET code_path=:cp, updated_at=:now WHERE id=:id"),
                    {"cp": code_path, "now": datetime.now(timezone.utc).isoformat(), "id": pid},
                )
                await db.commit()
        await update_project_phase(pid, "testing")

    elif task_type == "qa":
        qa_results = result.get("qa_results", {})
        passed = qa_results.get("passed", False) if isinstance(qa_results, dict) else False
        async with AsyncSession(engine) as db:
            await db.execute(
                text("UPDATE projects SET qa_result=:qr, updated_at=:now WHERE id=:id"),
                {"qr": json.dumps(qa_results), "now": datetime.now(timezone.utc).isoformat(), "id": pid},
            )
            await db.commit()

        if passed:
            await update_project_phase(pid, "building")
        else:
            fail_count = project.qa_result.get("fail_count", 0) + 1 if project.qa_result else 1
            if fail_count >= 3:
                await create_decision(
                    "cancel",
                    f"Project '{project.name}' failed QA {fail_count} times. Cancel?",
                    project_id=pid,
                )
                async with AsyncSession(engine) as db:
                    await db.execute(
                        text("UPDATE projects SET awaiting_decision='qa_fail', updated_at=:now WHERE id=:id"),
                        {"now": datetime.now(timezone.utc).isoformat(), "id": pid},
                    )
                    await db.commit()
            else:
                await update_project_phase(pid, "developing")

    elif task_type == "build":
        build_path = result.get("build_path")
        if build_path:
            async with AsyncSession(engine) as db:
                await db.execute(
                    text("UPDATE projects SET code_path=:bp, updated_at=:now WHERE id=:id"),
                    {"bp": build_path, "now": datetime.now(timezone.utc).isoformat(), "id": pid},
                )
                await db.commit()
        await update_project_phase(pid, "publishing")

    elif task_type == "deploy":
        itch_url = result.get("itch_url")
        if itch_url:
            async with AsyncSession(engine) as db:
                await db.execute(
                    text("UPDATE projects SET itch_url=:url, phase='live', awaiting_decision=NULL, updated_at=:now WHERE id=:id"),
                    {"url": itch_url, "now": datetime.now(timezone.utc).isoformat(), "id": pid},
                )
                await db.commit()
            await emit("scheduler", f"Project '{project.name}' published to {itch_url}", source_agent="scheduler", project_name=project.name)
            await save_chat_message("assistant", f"🚀 Project '{project.name}' is now live at {itch_url}", agent_name="scheduler")


async def _generate_reports() -> None:
    if _TICK_COUNT % MARKET_SCAN_INTERVAL != 0:
        return

    projects = await get_all_projects()
    active = [p for p in projects if p.phase not in (ProjectPhase.BACKLOG, ProjectPhase.CANCELLED)]
    if not active:
        return

    lines = [f"• {p.name}: {p.phase.value} ({p.progress:.0%})" for p in active]
    report = f"Scheduler report (tick #{_TICK_COUNT}):\n" + "\n".join(lines)
    await save_chat_message("assistant", report, agent_name="scheduler")


def _new_id() -> str:
    import uuid
    return str(uuid.uuid4())

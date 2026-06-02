"""CEO multi-project tick scheduler.

Each tick processes human instructions, checks decision gates,
advances active projects through their lifecycle phases, executes
one task from the queue, and generates periodic reports.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from orchestrator.decision_gate import create_decision, resolve
from orchestrator.event_bus import emit
from orchestrator.persistence import (
    count_completed_tasks,
    get_all_projects,
    get_api_usage_summary,
    get_latest_market_report,
    get_pending_decisions,
    get_pending_instructions,
    get_project,
    get_recent_completed_tasks,
    save_project,
    save_chat_message,
    set_project_live,
    update_project_art_status,
    update_project_awaiting_decision,
    update_project_build_path,
    update_project_code_path,
    update_project_gdd,
    update_project_music_status,
    update_project_phase,
    update_project_proposal_and_phase,
    update_project_qa_result,
)
from orchestrator.state import CompanyState, PipelinePhase
from orchestrator.task_queue import enqueue, dequeue, complete_task, fail_task, update_progress, enqueue_retry
from shared.constants import LAYER1_MAX_RETRIES, MAX_INSTRUCTIONS_PER_TICK, QA_CANCEL_THRESHOLD
from shared.exceptions import SchedulerError, TaskExecutionError
from shared.memory import get_memory_store
from shared.models import ProjectPhase, ProjectState

_TICK_COUNT = 0


def _load_scheduler_config() -> dict:
    """Load scheduler config from agents.yaml, with fallback to defaults."""
    try:
        from shared.config import load_agents_config
        cfg = load_agents_config()
        return cfg.get("scheduler", {})
    except Exception as e:
        logger.warning(f"Failed to load scheduler config: {e}")
        return {}


_SCHED_CFG = _load_scheduler_config()
_default_phase_ticks = {"scanning": 3, "designing": 2, "developing": 10, "testing": 6, "building": 3, "publishing": 5}
PHASE_MAX_TICKS: dict[str, int] = _SCHED_CFG.get("phase_max_ticks", _default_phase_ticks)
MARKET_SCAN_INTERVAL = _SCHED_CFG.get("market_scan_interval", 10)
CEO_EVALUATE_INTERVAL = _SCHED_CFG.get("ceo_evaluate_interval", 1)
MAX_ACTIVE_PROJECTS = _SCHED_CFG.get("max_active_projects", 3)
REPORT_INTERVAL = _SCHED_CFG.get("report_interval", 5)

_PAUSE_FLAG_PATH = os.path.join(tempfile.gettempdir(), "gcagents_paused")


def is_paused() -> bool:
    return os.path.exists(_PAUSE_FLAG_PATH)


def set_paused(paused: bool) -> None:
    if paused:
        Path(_PAUSE_FLAG_PATH).touch()
    else:
        try:
            os.remove(_PAUSE_FLAG_PATH)
        except FileNotFoundError:
            pass


async def scheduler_tick() -> dict | None:
    """Execute one scheduler tick. Returns tick info dict or None if paused."""
    global _TICK_COUNT
    _TICK_COUNT += 1

    if is_paused():
        logger.debug(f"Scheduler tick #{_TICK_COUNT} skipped (paused)")
        return None

    logger.info(f"Scheduler tick #{_TICK_COUNT}")
    memory = get_memory_store()

    await _process_instructions()
    await _resolve_answered_decisions()

    if _TICK_COUNT % MARKET_SCAN_INTERVAL == 0:
        await _periodic_market_scan()

    if _TICK_COUNT % CEO_EVALUATE_INTERVAL == 0:
        await _ceo_evaluate_new_projects()

    await _advance_projects()

    task_result = await _execute_one_task()
    if task_result:
        await _apply_task_result(task_result)
        task = task_result["task"]
        pid = task.project_id
        if pid != "__system__":
            memory.store_short_term(
                "tick_result",
                f"Phase: {task.task_type}, Status: {task_result['status']}",
                pid,
                tick_id=str(_TICK_COUNT),
                importance=0.3,
            )

    await _generate_reports()

    return {"tick": _TICK_COUNT}


async def _process_instructions() -> None:
    """Read and handle up to MAX_INSTRUCTIONS_PER_TICK pending instructions from the chat."""
    instructions = await get_pending_instructions("ceo")
    if not instructions:
        return

    for instruction in instructions[:MAX_INSTRUCTIONS_PER_TICK]:
        content = instruction.get("content", "")
        if not content:
            continue
        await emit(
            "scheduler", "Scheduler received instruction",
            detail=content[:200], source_agent="scheduler",
        )
        await _handle_instruction(content)


async def _handle_instruction(content: str) -> None:
    content_lower = content.lower()

    if any(kw in content_lower for kw in ("new project", "create project", "start project", "新项目")):
        await create_decision(
            "new_project",
            f"Create new project from instruction: {content[:200]}",
            context={"source": "chat", "instruction": content},
        )
        await save_chat_message("assistant", "I'll create a decision to start a new project. Please approve or reject.", agent_name="ceo")
    elif any(kw in content_lower for kw in ("status", "report", "how are", "情况", "状态", "报告")):
        projects = await get_all_projects()
        lines = [f"- {p.name} ({p.phase.value}): {p.progress:.0%}" for p in projects]
        msg = "Current project status:\n" + "\n".join(lines) if lines else "No active projects."
        await save_chat_message("assistant", msg, agent_name="ceo")
    elif any(kw in content_lower for kw in ("cancel", "stop", "取消", "停止")):
        projects = await get_all_projects()
        active = [p for p in projects if p.phase not in (ProjectPhase.BACKLOG, ProjectPhase.CANCELLED, ProjectPhase.LIVE)]
        for p in active[:1]:
            await create_decision("cancel", f"Cancel project '{p.name}'?", project_id=p.id)
            await save_chat_message("assistant", f"Created cancellation decision for '{p.name}'.", agent_name="ceo")
    else:
        projects = await get_all_projects()
        active = [p for p in projects if p.phase not in (ProjectPhase.BACKLOG, ProjectPhase.CANCELLED)]
        summary = f"{len(projects)} projects total, {len(active)} active."
        await save_chat_message("assistant", f"收到。当前 {summary} 如需操作请说：状态、新项目、取消。", agent_name="ceo")


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


async def _ceo_evaluate_new_projects() -> None:
    """CEO evaluates latest market report and creates new projects for approved opportunities.
    
    This bridges the LangGraph CEO node into the scheduler tick flow. The CEO is the
    LLM-driven decision maker that picks which market opportunities to greenlight;
    the scheduler is the mechanical executor that advances projects through phases.
    """
    import json
    from orchestrator.nodes.ceo import ceo_evaluate
    from orchestrator.state import CompanyState, PipelinePhase

    latest_report = await get_latest_market_report()

    if not latest_report or not latest_report.get("opportunities_json"):
        logger.debug("CEO evaluate: no market report available yet")
        return

    try:
        opportunities = json.loads(latest_report["opportunities_json"])
    except Exception:
        logger.warning("CEO evaluate: failed to parse opportunities JSON")
        return

    if not opportunities:
        return

    state = CompanyState(
        phase=PipelinePhase.EVALUATING,
        market_insights=opportunities,
    )
    result = await ceo_evaluate(state)

    proposal = result.get("current_proposal")
    if not proposal:
        logger.info(f"CEO evaluate: no proposal approved (phase={result.get('phase')})")
        return

    proposal_name = proposal.name if hasattr(proposal, "name") else proposal.get("name", "unnamed")
    proposal_genre = proposal.genre if hasattr(proposal, "genre") else proposal.get("genre", "general")
    if hasattr(proposal, "model_dump"):
        proposal_dict = proposal.model_dump(mode="json")
    else:
        proposal_dict = proposal

    existing = await get_all_projects()
    if any(p.name.lower() == proposal_name.lower() for p in existing):
        logger.info(f"CEO evaluate: project '{proposal_name}' already exists, skipping")
        return

    project_id = f"ceo-{int(datetime.now(timezone.utc).timestamp())}"
    project = ProjectState(
        id=project_id,
        name=proposal_name,
        genre=proposal_genre,
        phase=ProjectPhase.BACKLOG,
        progress=0.0,
        proposal=proposal_dict,
        awaiting_decision="new_project",
    )
    await save_project(project)
    logger.info(f"CEO evaluate: greenlit new project '{proposal_name}' (id={project_id}, genre={proposal_genre})")

    decision = await create_decision(
        "new_project",
        f"CEO greenlit: '{proposal_name}' ({proposal_genre}). Approve to start development?",
        project_id=project_id,
        context={"proposal": proposal_dict, "source": "ceo_evaluate"},
    )
    await update_project_awaiting_decision(project_id, decision.id)
    await save_chat_message(
        "assistant",
        f"🎯 CEO greenlit new project: **{proposal_name}** ({proposal_genre}). Approve to start development?",
        agent_name="ceo",
        metadata={
            "type": "decision",
            "decision_id": decision.id,
            "decision_type": "new_project",
            "project_id": project_id,
            "proposal": proposal_dict,
        },
    )
    await emit(
        "ceo",
        f"New project greenlit: {proposal_name}",
        source_agent="ceo",
        project_name=proposal_name,
    )


async def _advance_projects() -> None:
    """Advance all active (non-blocked) projects by enqueueing their next task."""
    projects = await get_all_projects()
    active = [p for p in projects
              if p.phase not in (ProjectPhase.BACKLOG, ProjectPhase.CANCELLED, ProjectPhase.LIVE, ProjectPhase.PAUSED)
              and not p.awaiting_decision]

    if len(active) > MAX_ACTIVE_PROJECTS:
        active.sort(key=lambda p: p.progress or 0, reverse=True)
        for p in active[MAX_ACTIVE_PROJECTS:]:
            logger.debug(f"Scheduler: project {p.name} deferred ({len(active)} active, max {MAX_ACTIVE_PROJECTS})")
        active = active[:MAX_ACTIVE_PROJECTS]

    for project in active:
        await _advance_project(project)


async def _advance_project(project: ProjectState) -> None:
    phase = project.phase
    pid = project.id

    phase_key = phase.value if hasattr(phase, "value") else str(phase)
    max_ticks = PHASE_MAX_TICKS.get(phase_key, 10)
    phase_ticks = await _get_phase_ticks(pid)
    if phase_ticks >= max_ticks:
        logger.warning(f"Scheduler: project {pid} exceeded {max_ticks} ticks in {phase_key}, pausing")
        await create_decision(
            "direction_change",
            f"Project '{project.name}' stuck in {phase_key} for {phase_ticks} ticks (max {max_ticks}). Change direction?",
            project_id=pid,
        )
        await update_project_awaiting_decision(pid, "phase_timeout")
        await emit("scheduler", f"Phase timeout: {project.name} in {phase_key}", severity="warning", source_agent="scheduler", project_name=project.name)
        return

    if phase == ProjectPhase.SCANNING:
        await enqueue(pid, "market_scan", {"project_name": project.name})

    elif phase == ProjectPhase.DESIGNING:
        await enqueue(pid, "design_game", {"project_name": project.name, "genre": project.genre})

    elif phase == ProjectPhase.DEVELOPING:
        if project.art_status != "done":
            await enqueue(pid, "art_gen", {"project_name": project.name, "gdd": project.gdd})
        elif project.music_status != "done":
            await enqueue(pid, "generate_music", {"project_name": project.name, "gdd": project.gdd})
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
        await update_project_awaiting_decision(pid, decision.id)



async def _execute_one_task() -> dict | None:
    """Dequeue and execute one task with 3-layer error recovery."""
    task = await dequeue()
    if not task:
        return None

    await update_progress(task.id, 0.0)
    task_type = task.task_type
    pid = task.project_id
    params = task.params

    retry_count = params.get("retry_count", 0)
    layer = params.get("layer", 1)

    logger.info(f"Scheduler: executing task '{task_type}' for project {pid} (layer={layer}, retry={retry_count})")

    try:
        result = await _run_agent(task_type, pid, params)
        await complete_task(task.id, result)
        return {"task": task, "result": result, "status": "completed"}
    except TaskExecutionError:
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Scheduler: task '{task_type}' failed (layer={layer}, retry={retry_count}): {e}")
        await fail_task(task.id, error_msg)
        recovery = await _handle_retry_recovery(task, error_msg)
        if recovery:
            return recovery
        return {"task": task, "error": error_msg, "status": "failed"}


async def _handle_retry_recovery(task, error_msg: str) -> dict | None:
    params = task.params
    retry_count = params.get("retry_count", 0)
    layer = params.get("layer", 1)

    if layer == 1:
        if retry_count < LAYER1_MAX_RETRIES:
            return await _retry_layer1(task, error_msg, retry_count)
        else:
            return await _escalate_layer2(task, error_msg)

    elif layer == 2:
        return await _escalate_layer3(task, error_msg)

    return None


async def _retry_layer1(task, error_msg: str, retry_count: int) -> dict:
    pid = task.project_id
    task_type = task.task_type
    logger.info(f"Scheduler: Layer 1 retry #{retry_count + 1} for '{task_type}' (project {pid})")
    await enqueue_retry(
        pid, task_type, task.params,
        retry_count=retry_count + 1,
        retry_strategy="retry_with_feedback",
        layer=1,
        last_error=error_msg,
    )
    return {"task": task, "error": error_msg, "status": "failed", "recovery": "layer1_retry"}


async def _escalate_layer2(task, error_msg: str) -> dict:
    pid = task.project_id
    task_type = task.task_type
    alt_type = _fallback_task_type(task_type)

    if alt_type is None:
        logger.info(
            f"Scheduler: no Layer 2 fallback for '{task_type}', "
            f"escalating directly to Layer 3 (project {pid})"
        )
        return await _escalate_layer3(task, error_msg)

    alt_params = dict(task.params)
    alt_params["simplified"] = True
    alt_params["original_task_type"] = task_type
    logger.info(f"Scheduler: Layer 2 strategy change '{task_type}' -> '{alt_type}' (project {pid})")
    await enqueue_retry(
        pid, alt_type, alt_params,
        retry_count=0,
        retry_strategy="strategy_change",
        layer=2,
        last_error=error_msg,
    )
    return {"task": task, "error": error_msg, "status": "failed", "recovery": "layer2_strategy_change"}


async def _escalate_layer3(task, error_msg: str) -> dict:
    pid = task.project_id
    task_type = task.params.get("original_task_type", task.task_type)
    logger.warning(f"Scheduler: Layer 3 escalation for project {pid}, task '{task_type}'")
    context = {
        "failed_task_type": task_type,
        "layer2_task_type": task.task_type,
        "last_error": error_msg,
        "retry_metadata": {
            "retry_count": task.params.get("retry_count", 0),
            "retry_strategy": task.params.get("retry_strategy", ""),
            "layer": 2,
        },
    }
    await create_decision(
        "direction_change",
        f"Task '{task_type}' failed after retry and strategy change. Error: {error_msg[:200]}",
        project_id=pid,
        context=context,
    )
    await update_project_phase(pid, "paused")
    await emit("scheduler", f"Project {pid} paused — awaiting human decision after task failure", severity="warning", source_agent="scheduler")
    return {"task": task, "error": error_msg, "status": "failed", "recovery": "layer3_escalation"}


def _fallback_task_type(task_type: str) -> str | None:
    """Return a Layer 2 strategy-change alternative for the given task type.

    Returns ``None`` when no real fallback exists, signaling that the
    scheduler should escalate directly to Layer 3 (human decision) instead
    of re-queuing the same task type.
    """
    _FALLBACKS: dict[str, str] = {
        "develop": "develop_simple",
    }
    return _FALLBACKS.get(task_type)


async def _get_phase_ticks(project_id: str) -> int:
    return await count_completed_tasks(project_id)


async def _run_agent(task_type: str, project_id: str, params: dict) -> dict:
    project = await get_project(project_id) if project_id != "__system__" else None

    state = CompanyState(
        phase=PipelinePhase.IDLE,
        current_project_id=project_id if project_id != "__system__" else None,
        gdd=project.gdd if project else None,
        current_proposal=_proposal_from_project(project) if project else None,
    )

    if params.get("last_error"):
        state.retry_feedback = {
            "last_error": params["last_error"],
            "retry_count": params.get("retry_count", 0),
            "layer": params.get("layer", 1),
        }

    if task_type == "market_scan":
        from agents.research.scanner import scan_market
        return await scan_market(state)

    elif task_type == "design_game":
        from agents.dev.designer.agent import design_game
        return await design_game(state)

    elif task_type == "art_gen":
        from agents.dev.artist.art_node import generate_art
        return await generate_art(state)

    elif task_type == "generate_music":
        from agents.dev.music.music_generator import generate_music
        return await generate_music(state)

    elif task_type in ("develop", "develop_simple"):
        from agents.dev.programmer.agent import develop_game
        return await develop_game(state)

    elif task_type == "qa":
        from agents.dev.qa.qa_agent import run_qa
        return await run_qa(state)

    elif task_type == "build":
        from agents.dev.builder.build_agent import build_game
        return await build_game(state)

    elif task_type == "localize":
        from agents.dev.localize.string_extractor import extract_strings, inject_localization
        from agents.dev.localize.translator import translate_strings

        name = params.get("project_name", "")
        dist_dir = f"data/games/{name}/dist"
        strings = extract_strings(dist_dir)
        if strings:
            genre = ""
            if project and project.gdd:
                genre = project.gdd.get("genre", "")
            translations = await translate_strings(strings, game_genre=genre)
            result = inject_localization(dist_dir, translations)
        else:
            result = {"locales": [], "note": "no strings found"}
        return result

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
    """Update project state based on completed task result."""
    task = task_result["task"]
    status = task_result["status"]
    pid = task.project_id

    if pid == "__system__":
        return

    if status == "failed":
        recovery = task_result.get("recovery")
        if recovery:
            logger.info(f"Scheduler: task '{task.task_type}' failed, recovery action: {recovery}")
        else:
            await emit("scheduler", f"Task '{task.task_type}' failed for project {pid}", severity="warning", source_agent="scheduler")
        return

    result = task_result.get("result", {})
    task_type = task.task_type
    effective_type = task.params.get("original_task_type", task_type)
    project = await get_project(pid)
    if not project:
        return

    if effective_type == "market_scan":
        insights = result.get("market_insights", [])
        if insights:
            top = max(insights, key=lambda x: x.get("market_opportunity_score", x.get("score", 0)))
            proposal = {
                "name": top.get("name", project.name),
                "genre": top.get("genre", project.genre),
                "description": top.get("description", ""),
                "market_opportunity_score": top.get("market_opportunity_score", top.get("score", 0)),
            }
            await update_project_proposal_and_phase(pid, proposal)
        else:
            await update_project_phase(pid, "backlog")

    elif effective_type == "design_game":
        gdd = result.get("gdd")
        if gdd:
            await update_project_gdd(pid, gdd)
            await update_project_phase(pid, "developing")

    elif effective_type == "art_gen":
        await update_project_art_status(pid)

    elif effective_type == "generate_music":
        await update_project_music_status(pid)

    elif effective_type == "develop":
        code_path = result.get("game_code_path")
        if code_path:
            await update_project_code_path(pid, code_path)
        await update_project_phase(pid, "testing")

    elif effective_type == "qa":
        qa_results = result.get("qa_results", {})
        passed = qa_results.get("passed", False) if isinstance(qa_results, dict) else False

        prev_fail_count = 0
        if project.qa_result and isinstance(project.qa_result, dict):
            prev_fail_count = project.qa_result.get("fail_count", 0)
        new_fail_count = prev_fail_count + (0 if passed else 1)
        qa_results["fail_count"] = new_fail_count

        await update_project_qa_result(pid, qa_results)

        if passed:
            await update_project_phase(pid, "building")
        else:
            fail_count = new_fail_count
            if fail_count >= QA_CANCEL_THRESHOLD:
                await create_decision(
                    "cancel",
                    f"Project '{project.name}' failed QA {fail_count} times. Cancel?",
                    project_id=pid,
                )
                await update_project_awaiting_decision(pid, "qa_fail")
            else:
                await update_project_phase(pid, "developing")

    elif effective_type == "build":
        build_path = result.get("build_path")
        if build_path:
            await update_project_build_path(pid, build_path)
        await enqueue(pid, "localize", {"project_name": project.name})
        await update_project_phase(pid, "publishing")

    elif effective_type == "localize":
        locales = result.get("locales", [])
        if locales:
            await emit("scheduler", f"Localized '{project.name}' to {len(locales)} locales: {', '.join(locales)}", source_agent="scheduler", project_name=project.name)

    elif effective_type == "deploy":
        itch_url = result.get("itch_url")
        if itch_url:
            await set_project_live(pid, itch_url)
            await emit("scheduler", f"Project '{project.name}' published to {itch_url}", source_agent="scheduler", project_name=project.name)
            await save_chat_message("assistant", f"🚀 Project '{project.name}' is now live at {itch_url}", agent_name="scheduler")
            get_memory_store().consolidate(pid)


async def _generate_reports() -> None:
    """Generate periodic CEO report with project status and API usage."""
    if _TICK_COUNT % REPORT_INTERVAL != 0:
        return

    projects = await get_all_projects()
    active = [p for p in projects if p.phase not in (ProjectPhase.BACKLOG, ProjectPhase.CANCELLED, ProjectPhase.LIVE)]
    pending = await get_pending_decisions()
    total = len(projects)
    active_count = len(active)

    usage = await get_api_usage_summary()
    total_calls = usage["calls"]
    total_cost = usage["total_cost"]

    recent_rows = await get_recent_completed_tasks()

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "📋 公司经营报告",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🕐 {now_str}  |  Tick #{_TICK_COUNT}",
        "",
        f"📊 **概览**: {active_count} 个活跃项目 / {total} 个总计",
    ]

    if active:
        lines.append("")
        lines.append("🏗 **活跃项目**:")
        for p in active:
            phase_val = p.phase.value if hasattr(p.phase, "value") else str(p.phase)
            progress_str = f"{p.progress:.0%}" if p.progress is not None else "0%"
            lines.append(f"  • {p.name} — {phase_val} ({progress_str})")

    if recent_rows:
        lines.append("")
        lines.append("✅ **近期完成任务**:")
        for r in recent_rows:
            ts = r["completed_at"][:16] if r["completed_at"] else "?"
            lines.append(f"  • [{ts}] {r['task_type']} ({r['project_id'][:20]})")

    pending_count = len(pending) if pending else 0
    lines.append("")
    lines.append(f"⏳ **待决策**: {pending_count} 项")

    lines.append("")
    lines.append(f"💰 **API 使用**: {total_calls:,} 次调用  |  ${total_cost:.4f}")

    report = "\n".join(lines)
    await save_chat_message("assistant", report, agent_name="ceo", metadata={"type": "report"})


def _new_id() -> str:
    import uuid
    return str(uuid.uuid4())

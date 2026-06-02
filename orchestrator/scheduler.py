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
    count_completed_tasks_by_type,
    get_all_projects,
    get_api_usage_summary,
    get_company_policy,
    get_latest_market_report,
    get_pending_decisions,
    get_pending_instructions,
    get_project,
    get_recent_completed_tasks,
    has_active_task,
    resolve_decision,
    save_agent_log,
    save_game_version,
    save_project,
    save_chat_message,
    set_project_live,
    update_project_art_assets_path,
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

TASK_NODE_MAP = {
    "market_scan": "scan", "design_game": "design", "art_gen": "art",
    "generate_music": "music", "develop": "develop", "develop_simple": "develop",
    "qa": "qa", "build": "build", "localize": "build", "deploy": "deploy",
}

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

    policy = await get_company_policy()
    max_concurrent = policy.get("max_dev_projects", 3)

    for _ in range(max_concurrent):
        task_result = await _execute_one_task()
        if not task_result:
            break
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
    policy = await get_company_policy()
    timeout_hours = policy.get("decision_timeout_hours", 24)
    timeout_action = policy.get("timeout_action", "reject")

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
        else:
            created = d.created_at
            if created:
                now = datetime.now(timezone.utc)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                hours_elapsed = (now - created).total_seconds() / 3600
                if hours_elapsed >= timeout_hours:
                    logger.info(f"Decision {d.id} timed out after {hours_elapsed:.1f}h, applying default: {timeout_action}")
                    await resolve_decision(d.id, timeout_action)
                    if timeout_action == "approve":
                        await _handle_approved_decision(d)
                    else:
                        await _handle_rejected_decision(d)
                    await emit("scheduler", f"Decision timed out: {d.question[:50]}", severity="warning", source_agent="scheduler")


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
        await update_project_awaiting_decision(pid, None)
        project = await get_project(pid)
        if project:
            await enqueue(pid, "deploy", {"project_name": project.name})
            await emit("scheduler", f"Publishing approved for {project.name}", source_agent="scheduler", project_name=project.name)

    elif dtype == "budget_overrun" and pid:
        project = await get_project(pid)
        if project:
            await update_project_phase(pid, "developing")
            await update_project_awaiting_decision(pid, None)
            await emit("scheduler", f"Budget overrun approved, continuing {project.name}", source_agent="scheduler", project_name=project.name)

    elif dtype == "direction_change" and pid:
        ctx = decision.context
        project = await get_project(pid)
        if project:
            await update_project_phase(pid, "designing")
            await update_project_awaiting_decision(pid, None)
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
        await update_project_awaiting_decision(pid, None)
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

    policy = await get_company_policy()
    max_dev = policy.get("max_dev_projects", 3)
    dev_phases = {"scanning", "designing", "developing", "testing", "building", "publishing"}
    dev_count = sum(1 for p in existing if p.phase.value in dev_phases)
    if dev_count >= max_dev:
        logger.info(f"CEO evaluate: dev capacity reached ({dev_count}/{max_dev}), skipping '{proposal_name}'")
        return
    preferred_genres = policy.get("preferred_genres", [])
    genre_match = not preferred_genres or proposal_genre.lower() in [g.lower() for g in preferred_genres]
    auto_approve = True

    project_id = f"ceo-{int(datetime.now(timezone.utc).timestamp())}"
    project = ProjectState(
        id=project_id,
        name=proposal_name,
        genre=proposal_genre,
        phase=ProjectPhase.SCANNING,
        progress=0.0,
        proposal=proposal_dict,
        awaiting_decision=None,
    )
    await save_project(project)
    logger.info(f"CEO evaluate: greenlit new project '{proposal_name}' (id={project_id}, genre={proposal_genre}, auto=True)")

    await emit(
        "ceo",
        f"New project auto-approved by policy: {proposal_name}",
        source_agent="ceo",
        project_name=proposal_name,
    )
    await save_chat_message(
        "assistant",
        f"✅ 新项目 **{proposal_name}** ({proposal_genre}) 已自动批准。",
        agent_name="ceo",
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
    policy = await get_company_policy()
    max_dev = policy.get("max_dev_projects", 3)
    max_live = policy.get("max_live_projects", 5)

    dev_phases = {ProjectPhase.SCANNING, ProjectPhase.DESIGNING, ProjectPhase.DEVELOPING,
                  ProjectPhase.TESTING, ProjectPhase.BUILDING, ProjectPhase.PUBLISHING}

    dev_projects = [p for p in projects
                    if p.phase in dev_phases
                    and not p.awaiting_decision]

    live_projects = [p for p in projects
                     if p.phase == ProjectPhase.LIVE
                     and not p.awaiting_decision]

    if len(dev_projects) > max_dev:
        dev_projects.sort(key=lambda p: p.progress or 0, reverse=True)
        for p in dev_projects[max_dev:]:
            logger.debug(f"Scheduler: project {p.name} deferred ({len(dev_projects)} dev, max {max_dev})")
        dev_projects = dev_projects[:max_dev]

    if len(live_projects) > max_live:
        live_projects.sort(key=lambda p: p.progress or 0, reverse=True)
        for p in live_projects[max_live:]:
            logger.debug(f"Scheduler: project {p.name} deferred ({len(live_projects)} live, max {max_live})")
        live_projects = live_projects[:max_live]

    active = dev_projects + live_projects

    for project in active:
        await _advance_project(project)


async def _advance_project(project: ProjectState) -> None:
    phase = project.phase
    pid = project.id

    phase_key = phase.value if hasattr(phase, "value") else str(phase)
    max_ticks = PHASE_MAX_TICKS.get(phase_key, 10)
    phase_ticks = await _get_phase_ticks(pid)
    if phase_ticks >= max_ticks:
        logger.warning(f"Scheduler: project {pid} exceeded {max_ticks} ticks in {phase_key}, resetting and continuing")
        await save_chat_message("assistant", f"⚠️ 项目 **{project.name}** 在 {phase_key} 阶段停滞 ({phase_ticks}/{max_ticks} ticks)，自动重置继续", agent_name="ceo")
        await emit("scheduler", f"Phase timeout (auto-reset): {project.name} in {phase_key}", severity="warning", source_agent="scheduler", project_name=project.name)

    if phase == ProjectPhase.SCANNING:
        if not await has_active_task(pid, "market_scan"):
            await enqueue(pid, "market_scan", {"project_name": project.name})

    elif phase == ProjectPhase.DESIGNING:
        if not await has_active_task(pid, "design_game"):
            await enqueue(pid, "design_game", {"project_name": project.name, "genre": project.genre})

    elif phase == ProjectPhase.DEVELOPING:
        if project.art_status != "done":
            if not await has_active_task(pid, "art_gen"):
                await enqueue(pid, "art_gen", {"project_name": project.name, "gdd": project.gdd})
        elif project.music_status != "done":
            if not await has_active_task(pid, "generate_music"):
                await enqueue(pid, "generate_music", {"project_name": project.name, "gdd": project.gdd})
        else:
            if not await has_active_task(pid, "develop"):
                params = {"project_name": project.name, "gdd": project.gdd}
                if project.art_assets_path:
                    params["art_assets_path"] = project.art_assets_path
                if project.qa_result and isinstance(project.qa_result, dict):
                    params["last_qa_failure"] = project.qa_result
                await enqueue(pid, "develop", params)

    elif phase == ProjectPhase.TESTING:
        if not await has_active_task(pid, "qa"):
            await enqueue(pid, "qa", {"project_name": project.name, "code_path": project.code_path})

    elif phase == ProjectPhase.BUILDING:
        if not await has_active_task(pid, "build"):
            await enqueue(pid, "build", {"project_name": project.name, "code_path": project.code_path})

    elif phase == ProjectPhase.PUBLISHING:
        await update_project_phase(pid, "publishing")
        project = await get_project(pid)
        if project:
            await enqueue(pid, "deploy", {"project_name": project.name})
        await emit("scheduler", f"Publish auto-approved: {project.name}", source_agent="scheduler", project_name=project.name)
        await save_chat_message(
            "assistant",
            f"✅ 项目 **{project.name}** 自动发布。",
            agent_name="ceo",
        )



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

    project = await get_project(pid) if pid != "__system__" else None
    project_name = project.name if project else ""
    node_name = TASK_NODE_MAP.get(task_type, task_type)
    started_at = datetime.now(timezone.utc).isoformat()

    try:
        result = await _run_agent(task_type, pid, params)
        await complete_task(task.id, result)
        duration = int((datetime.now(timezone.utc) - datetime.fromisoformat(started_at)).total_seconds() * 1000)
        await save_agent_log(node_name, "completed", phase=task_type, duration_ms=duration,
                             started_at=started_at, project_name=project_name)
        return {"task": task, "result": result, "status": "completed"}
    except Exception as e:
        error_msg = str(e)
        duration = int((datetime.now(timezone.utc) - datetime.fromisoformat(started_at)).total_seconds() * 1000)
        await save_agent_log(node_name, "failed", phase=task_type, error=error_msg, duration_ms=duration,
                             started_at=started_at, project_name=project_name)
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
    logger.warning(f"Scheduler: Layer 3 auto-retry for project {pid}, task '{task_type}'")

    await save_chat_message("assistant", f"⚠️ 任务 **{task_type}** 失败，自动重新排队重试: {error_msg[:100]}", agent_name="ceo")

    # Auto-retry: re-enqueue the original task with layer reset
    await enqueue(pid, task_type, {
        "retry_count": 0,
        "layer": 1,
        "original_task_type": task_type,
    })
    await emit("scheduler", f"Project {pid} task '{task_type}' auto-retried after layer 3 failure", severity="warning", source_agent="scheduler")
    return {"task": task, "error": error_msg, "status": "failed", "recovery": "layer3_auto_retry"}


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
    project = await get_project(project_id)
    if not project:
        return 0

    phase = project.phase
    phase_key = phase.value if hasattr(phase, "value") else str(phase)

    if phase_key == "scanning":
        return await count_completed_tasks_by_type(project_id, "market_scan")
    elif phase_key == "designing":
        return await count_completed_tasks_by_type(project_id, "design_game")
    elif phase_key == "developing":
        art = await count_completed_tasks_by_type(project_id, "art_gen")
        music = await count_completed_tasks_by_type(project_id, "generate_music")
        code = await count_completed_tasks_by_type(project_id, "develop")
        return art + music + code
    elif phase_key == "testing":
        return await count_completed_tasks_by_type(project_id, "qa")
    elif phase_key == "building":
        return await count_completed_tasks_by_type(project_id, "build")
    elif phase_key == "publishing":
        return await count_completed_tasks_by_type(project_id, "deploy")
    else:
        return await count_completed_tasks(project_id)


async def _run_agent(task_type: str, project_id: str, params: dict) -> dict:
    project = await get_project(project_id) if project_id != "__system__" else None

    state = CompanyState(
        phase=PipelinePhase.IDLE,
        current_project_id=project_id if project_id != "__system__" else None,
        gdd=project.gdd if project else None,
        current_proposal=_proposal_from_project(project) if project else None,
        art_assets_path=params.get("art_assets_path") or (project.art_assets_path if project else None),
        game_code_path=params.get("code_path") or (project.code_path if project else None),
        build_path=params.get("build_path") or (
            str(Path(project.code_path) / "dist") if project and project.code_path else None
        ),
    )

    if params.get("last_qa_failure"):
        qa = params["last_qa_failure"]
        parts = []
        if qa.get("errors"):
            parts.extend(qa["errors"])
        checks = qa.get("checks", {})
        playtest = checks.get("playtest", {})
        for c in playtest.get("checks", []):
            if not c.get("passed"):
                parts.append(f"Playtest fail: {c['name']}" + (f" - {c.get('detail','')}" if c.get("detail") else ""))
        if not checks.get("project_structure", True):
            parts.append("Project structure check failed")
        if not checks.get("build_artifacts", True):
            parts.append("Build artifacts check failed")
        if parts:
            state.errors = parts[:10]

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
        art_status = result.get("art_status", "done")
        await update_project_art_status(pid, art_status)
        art_assets_path = result.get("art_assets_path", "")
        if art_assets_path:
            await update_project_art_assets_path(pid, art_assets_path)

    elif effective_type == "generate_music":
        music_status = result.get("music_status", "done")
        await update_project_music_status(pid, music_status)

    elif effective_type == "develop":
        code_path = result.get("game_code_path")
        version = result.get("version", "0.1.0")
        if code_path:
            await update_project_code_path(pid, code_path)
        await save_game_version(
            project_id=pid,
            version=version,
            gdd_snapshot=project.gdd if project else None,
            changelog="Code generated" if not project or not project.code_path else "Code regenerated after QA feedback",
        )
        await update_project_phase(pid, "testing")

    elif effective_type == "qa":
        qa_results = result.get("qa_results", {})
        passed = qa_results.get("passed", False) if isinstance(qa_results, dict) else False

        if passed:
            await update_project_qa_result(pid, qa_results)
            await update_project_phase(pid, "building")
        else:
            prev_fail_count = 0
            if project.qa_result and isinstance(project.qa_result, dict):
                prev_fail_count = project.qa_result.get("fail_count", 0)
            new_fail_count = prev_fail_count + 1
            qa_results["fail_count"] = new_fail_count
            await update_project_qa_result(pid, qa_results)

            if new_fail_count >= QA_CANCEL_THRESHOLD:
                await save_chat_message("assistant", f"🔴 项目 **{project.name}** QA 失败 {new_fail_count} 次，自动重试", agent_name="ceo")
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
    if _TICK_COUNT % REPORT_INTERVAL != 0:
        return

    projects = await get_all_projects()
    active = [p for p in projects if p.phase not in (ProjectPhase.BACKLOG, ProjectPhase.CANCELLED, ProjectPhase.LIVE)]
    live = [p for p in projects if p.phase == ProjectPhase.LIVE]
    pending = await get_pending_decisions()
    total = len(projects)
    active_count = len(active)

    usage = await get_api_usage_summary()
    total_calls = usage["calls"]
    total_cost = usage["total_cost"]

    recent_rows = await get_recent_completed_tasks()

    policy = await get_company_policy()
    budget_limit = policy.get("budget_limit_usd", 5.0)

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "📊 今日汇报",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🕐 {now_str}  |  Tick #{_TICK_COUNT}",
        "",
    ]

    if live:
        lines.append("✅ **已上线**:")
        for p in live:
            lines.append(f"  • {p.name}")
        lines.append("")

    if active:
        lines.append("🔄 **进行中**:")
        for p in active:
            phase_val = p.phase.value if hasattr(p.phase, "value") else str(p.phase)
            progress_str = f"{p.progress:.0%}" if p.progress is not None else "0%"
            lines.append(f"  • {p.name} — {phase_val} ({progress_str})")
        lines.append("")

    pending_count = len(pending) if pending else 0
    if pending_count > 0:
        lines.append(f"📋 **待决策**: {pending_count} 项")
        lines.append("")

    lines.append(f"💰 **本月支出**: ${total_cost:.2f} / ${budget_limit:.2f} ({total_cost/budget_limit*100:.0f}%)")

    report = "\n".join(lines)
    await save_chat_message("assistant", report, agent_name="ceo", metadata={"type": "report"})


def _new_id() -> str:
    import uuid
    return str(uuid.uuid4())

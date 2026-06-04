from __future__ import annotations

from datetime import UTC, datetime

from langgraph.graph import END, StateGraph
from loguru import logger

from agents.dev.artist.art_node import generate_art
from agents.dev.builder.build_agent import build_game
from agents.dev.designer.agent import design_game
from agents.dev.programmer.agent import develop_game
from agents.dev.qa.qa_agent import run_qa
from agents.ops.analytics.feedback_collector import collect_feedback
from agents.ops.deployer.itch_deployer import deploy_to_itch
from agents.research.scanner import scan_market
from orchestrator.nodes.ceo import ceo_evaluate, route_after_qa
from orchestrator.nodes.cfo import cfo_budget_check
from orchestrator.nodes.coo import coo_health_check
from orchestrator.persistence import (
    ensure_tables,
    get_latest_version,
    get_unprocessed_feedback,
    mark_feedback_processed,
    save_agent_log,
    save_game_version,
)
from orchestrator.state import CompanyState, PipelinePhase


def _logged_node(fn, node_name: str, phase: str):
    async def wrapper(state: CompanyState) -> dict:
        started_at = datetime.now(UTC).isoformat()
        project_name = (
            state.gdd.get("title")
            if state.gdd
            else state.current_proposal.name
            if state.current_proposal
            else None
        )
        try:
            result = await fn(state)
            duration_ms = int(
                (datetime.now(UTC) - datetime.fromisoformat(started_at)).total_seconds() * 1000
            )
            await save_agent_log(
                node_name,
                "completed",
                phase=phase,
                duration_ms=duration_ms,
                project_name=project_name,
                started_at=started_at,
            )
            return result
        except Exception as e:
            duration_ms = int(
                (datetime.now(UTC) - datetime.fromisoformat(started_at)).total_seconds() * 1000
            )
            await save_agent_log(
                node_name,
                "failed",
                phase=phase,
                error=str(e),
                duration_ms=duration_ms,
                project_name=project_name,
                started_at=started_at,
            )
            raise

    return wrapper


async def _save_version(state: CompanyState) -> dict:
    pid = state.current_project_id
    if not pid:
        return {}
    old_ver = await get_latest_version(pid)
    parts = old_ver.split(".")
    try:
        new_ver = f"{parts[0]}.{int(parts[1]) + 1}.0" if len(parts) >= 2 else "1.0.0"
    except (ValueError, IndexError):
        new_ver = "1.0.0"
    await save_game_version(
        project_id=pid,
        version=new_ver,
        gdd_snapshot=state.gdd or {},
        changelog=f"Auto-update to v{new_ver}",
        build_size=0,
    )
    return {}


async def _collect_feedback(state: CompanyState) -> dict:
    logger.info("Pipeline: collecting feedback from live projects")
    await collect_feedback()
    return {}


async def _update_from_feedback(state: CompanyState) -> dict:
    pid = state.current_project_id
    if not pid:
        state.phase = PipelinePhase.SCANNING
        return {"phase": PipelinePhase.SCANNING}

    feedback = await get_unprocessed_feedback(pid)
    if not feedback:
        state.phase = PipelinePhase.SCANNING
        return {"phase": PipelinePhase.SCANNING}

    fids = [f["id"] for f in feedback]
    bugs = [f for f in feedback if f.get("category") == "bug"]
    features = [f for f in feedback if f.get("category") == "feature"]

    summary = f"Feedback-driven update: {len(bugs)} bugs, {len(features)} features"
    logger.info(f"Updating project {pid}: {summary}")

    await mark_feedback_processed(fids)
    return {
        "phase": PipelinePhase.DEVELOPING,
        "gdd": state.gdd or {},
        "errors": [],
    }


def build_company_graph() -> StateGraph:
    graph = StateGraph(CompanyState)

    graph.add_node("coo_check", _logged_node(coo_health_check, "coo_check", "operating"))
    graph.add_node("collect_feedback", _collect_feedback)
    graph.add_node("scan", scan_market)
    graph.add_node("evaluate", _logged_node(ceo_evaluate, "evaluate", "evaluating"))
    graph.add_node("design", _logged_node(design_game, "design", "designing"))
    graph.add_node("art", _logged_node(generate_art, "art", "designing"))
    graph.add_node("cfo_check", _logged_node(cfo_budget_check, "cfo_check", "developing"))
    graph.add_node("develop", _logged_node(develop_game, "develop", "developing"))
    graph.add_node("qa", _logged_node(run_qa, "qa", "testing"))
    graph.add_node("build", _logged_node(build_game, "build", "building"))
    graph.add_node("deploy", _logged_node(deploy_to_itch, "deploy", "publishing"))
    graph.add_node("version", _save_version)
    graph.add_node("update", _update_from_feedback)

    graph.set_entry_point("coo_check")

    graph.add_edge("coo_check", "collect_feedback")

    graph.add_edge("collect_feedback", "scan")

    graph.add_edge("scan", "evaluate")

    graph.add_conditional_edges(
        "evaluate",
        _route_after_evaluation,
        {
            "scan": "scan",
            "design": "design",
            "update": "update",
            "idle": END,
        },
    )

    graph.add_conditional_edges(
        "update",
        _route_after_update,
        {
            "cfo_check": "cfo_check",
            "scan": "scan",
        },
    )

    graph.add_edge("design", "art")
    graph.add_edge("art", "cfo_check")
    graph.add_conditional_edges(
        "cfo_check",
        _route_after_cfo_check,
        {
            "develop": "develop",
            "abort": END,
        },
    )
    graph.add_edge("develop", "qa")

    graph.add_conditional_edges(
        "qa",
        route_after_qa,
        {
            "build": "build",
            "redevelop": "develop",
            "abort": END,
        },
    )

    graph.add_edge("build", "deploy")
    graph.add_edge("deploy", "version")
    graph.add_edge("version", END)

    return graph


def _route_after_evaluation(state: CompanyState) -> str:
    if state.phase == PipelinePhase.DESIGNING:
        return "design"
    if state.phase == PipelinePhase.UPDATING:
        return "update"
    if state.phase == PipelinePhase.SCANNING:
        return "scan"
    return "idle"


def _route_after_update(state: CompanyState) -> str:
    if state.phase == PipelinePhase.DEVELOPING:
        return "cfo_check"
    return "scan"


def _route_after_cfo_check(state: CompanyState) -> str:
    if state.errors and any("budget" in e.lower() for e in state.errors):
        return "abort"
    return "develop"


async def create_company_app():
    await ensure_tables()
    graph = build_company_graph()
    return graph.compile()

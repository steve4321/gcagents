from __future__ import annotations

from datetime import datetime, timezone

from langgraph.graph import END, StateGraph
from loguru import logger

from orchestrator.state import CompanyState, PipelinePhase
from orchestrator.nodes.ceo import ceo_evaluate, route_after_qa
from agents.research.scanner import scan_market
from agents.dev.designer.agent import design_game
from agents.dev.artist.art_node import generate_art
from agents.dev.programmer.agent import develop_game
from agents.dev.qa.qa_agent import run_qa
from agents.dev.builder.build_agent import build_game
from agents.ops.deployer.itch_deployer import deploy_to_itch
from orchestrator.persistence import save_pipeline_state, save_market_signals, save_agent_log, ensure_tables


def _logged_node(fn, node_name: str, phase: str):
    async def wrapper(state: CompanyState) -> dict:
        started_at = datetime.now(timezone.utc).isoformat()
        project_name = (
            state.gdd.get("title") if state.gdd
            else state.current_proposal.name if state.current_proposal
            else None
        )
        try:
            result = await fn(state)
            duration_ms = int((datetime.now(timezone.utc) - datetime.fromisoformat(started_at)).total_seconds() * 1000)
            await save_agent_log(node_name, "completed", phase=phase, duration_ms=duration_ms,
                                 project_name=project_name, started_at=started_at)
            return result
        except Exception as e:
            duration_ms = int((datetime.now(timezone.utc) - datetime.fromisoformat(started_at)).total_seconds() * 1000)
            await save_agent_log(node_name, "failed", phase=phase, error=str(e), duration_ms=duration_ms,
                                 project_name=project_name, started_at=started_at)
            raise
    return wrapper


def build_company_graph() -> StateGraph:
    graph = StateGraph(CompanyState)

    graph.add_node("scan", scan_market)
    graph.add_node("evaluate", _logged_node(ceo_evaluate, "evaluate", "evaluating"))
    graph.add_node("design", _logged_node(design_game, "design", "designing"))
    graph.add_node("art", _logged_node(generate_art, "art", "designing"))
    graph.add_node("develop", _logged_node(develop_game, "develop", "developing"))
    graph.add_node("qa", _logged_node(run_qa, "qa", "testing"))
    graph.add_node("build", _logged_node(build_game, "build", "building"))
    graph.add_node("deploy", _logged_node(deploy_to_itch, "deploy", "publishing"))

    graph.set_entry_point("scan")

    graph.add_edge("scan", "evaluate")

    graph.add_conditional_edges(
        "evaluate",
        _route_after_evaluation,
        {
            "scan": "scan",
            "design": "design",
            "idle": END,
        },
    )

    graph.add_edge("design", "art")
    graph.add_edge("art", "develop")
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
    graph.add_edge("deploy", END)

    return graph


def _route_after_evaluation(state: CompanyState) -> str:
    if state.phase == PipelinePhase.DESIGNING:
        return "design"
    if state.phase == PipelinePhase.SCANNING:
        return "scan"
    return "idle"


async def create_company_app():
    await ensure_tables()
    graph = build_company_graph()
    return graph.compile()

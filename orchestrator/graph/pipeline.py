from __future__ import annotations

from langgraph.graph import END, StateGraph

from orchestrator.state import CompanyState, PipelinePhase
from orchestrator.nodes.ceo import ceo_evaluate, route_after_qa
from agents.research.scanner import scan_market
from agents.dev.designer.agent import design_game
from agents.dev.artist.art_node import generate_art
from agents.dev.programmer.agent import develop_game
from agents.dev.qa.qa_agent import run_qa
from agents.dev.builder.build_agent import build_game
from agents.ops.deployer.itch_deployer import deploy_to_itch


def build_company_graph() -> StateGraph:
    graph = StateGraph(CompanyState)

    graph.add_node("scan", scan_market)
    graph.add_node("evaluate", ceo_evaluate)
    graph.add_node("design", design_game)
    graph.add_node("art", generate_art)
    graph.add_node("develop", develop_game)
    graph.add_node("qa", run_qa)
    graph.add_node("build", build_game)
    graph.add_node("deploy", deploy_to_itch)

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


def create_company_app():
    graph = build_company_graph()
    return graph.compile()

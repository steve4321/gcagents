from __future__ import annotations

import asyncio
import sys

from loguru import logger
from rich.console import Console

from orchestrator.graph.pipeline import create_company_app
from orchestrator.state import CompanyState, PipelinePhase
from shared.config import load_config


console = Console()


async def run_single_cycle() -> None:
    config = load_config()
    config.games_output_dir.mkdir(parents=True, exist_ok=True)
    config.build_dir.mkdir(parents=True, exist_ok=True)

    app = await create_company_app()

    console.print("\n[bold green]🎮 GCAgents - AI Game Company Starting...[/bold green]\n")

    initial_state = CompanyState(phase=PipelinePhase.IDLE)

    console.print("[bold cyan]Running full cycle: Scan → Evaluate → Design → Dev → QA → Build → Deploy[/bold cyan]\n")

    try:
        result = await app.ainvoke(initial_state.model_dump())

        final_phase = result.get("phase", "unknown")
        project_name = result.get("current_proposal", {})
        if isinstance(project_name, dict):
            project_name = project_name.get("name", "N/A")

        console.print(f"\n[bold]Cycle Complete[/bold]")
        console.print(f"  Final Phase: [yellow]{final_phase}[/yellow]")
        if project_name != "N/A":
            console.print(f"  Project: [cyan]{project_name}[/cyan]")
        if result.get("itch_url"):
            console.print(f"  Published: [link]{result['itch_url']}[/link]")
        if result.get("errors"):
            console.print(f"  Errors: [red]{result['errors']}[/red]")

    except Exception as e:
        console.print(f"\n[bold red]Cycle failed: {e}[/bold red]")
        logger.exception("Cycle execution failed")
        sys.exit(1)


def cli() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    if args.command == "run":
        asyncio.run(run_single_cycle())
    elif args.command == "scan":
        asyncio.run(_run_scan_only())
    else:
        parser.print_help()


async def _run_scan_only() -> None:
    from agents.research.scanner import scan_market
    from shared.config import load_sources

    state = CompanyState()
    result = await scan_market(state)
    console.print(f"\n[yellow]Phase: {result.get('phase')}[/yellow]")
    insights = result.get("market_insights", [])
    console.print(f"[cyan]Opportunities found: {len(insights)}[/cyan]\n")
    for opp in insights:
        score = opp.get("market_opportunity_score") or opp.get("score", 0)
        console.print(f"  • {opp.get('name', 'N/A')} ({opp.get('genre', 'N/A')}) score={score:.2f}")


def _build_arg_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="gcagents",
        description="AI Game Company - autonomous game research, development and operations",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="Run a full cycle (scan → design → dev → deploy)")
    sub.add_parser("scan", help="Run market scan only")
    return parser


if __name__ == "__main__":
    cli()

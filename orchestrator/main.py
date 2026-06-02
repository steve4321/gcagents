from __future__ import annotations

import asyncio

from loguru import logger
from rich.console import Console

from orchestrator.graph.pipeline import create_company_app
from orchestrator.state import CompanyState, PipelinePhase
from shared.config import load_config


console = Console()


async def run_single_cycle() -> dict | None:
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

        console.print("\n[bold]Cycle Complete[/bold]")
        console.print(f"  Final Phase: [yellow]{final_phase}[/yellow]")
        if project_name != "N/A":
            console.print(f"  Project: [cyan]{project_name}[/cyan]")
        if result.get("itch_url"):
            console.print(f"  Published: [link]{result['itch_url']}[/link]")
        if result.get("errors"):
            console.print(f"  Errors: [red]{result['errors']}[/red]")

        return result

    except Exception as e:
        console.print(f"\n[bold red]Cycle failed: {e}[/bold red]")
        logger.exception("Cycle execution failed")
        return None


async def run_forever(interval_seconds: int = 3600) -> None:
    config = load_config()
    config.games_output_dir.mkdir(parents=True, exist_ok=True)
    config.build_dir.mkdir(parents=True, exist_ok=True)

    console.print("\n[bold green]🎮 GCAgents - 24/7 Mode Starting...[/bold green]")
    console.print(f"[dim]Interval: {interval_seconds}s between cycles (Ctrl+C to stop)[/dim]\n")

    cycle = 0
    while True:
        cycle += 1
        console.print(f"\n[bold cyan]═══════ Cycle #{cycle} ═══════[/bold cyan]\n")

        result = await run_single_cycle()
        if result is None:
            console.print(f"[red]Cycle {cycle} failed, continuing...[/red]")

        console.print(f"\n[dim]Sleeping {interval_seconds}s before next cycle (Ctrl+C to stop)...[/dim]\n")
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            console.print("\n[bold yellow]24/7 mode stopped.[/bold yellow]")
            break


async def run_scheduler_tick() -> dict | None:
    from orchestrator.scheduler import scheduler_tick
    from orchestrator.persistence import ensure_tables

    await ensure_tables()
    return await scheduler_tick()


async def run_scheduler_forever(interval_seconds: int = 300) -> None:
    config = load_config()
    config.games_output_dir.mkdir(parents=True, exist_ok=True)
    config.build_dir.mkdir(parents=True, exist_ok=True)

    console.print("\n[bold green]🎮 GCAgents - Scheduler Mode Starting...[/bold green]")
    console.print(f"[dim]Tick interval: {interval_seconds}s (Ctrl+C to stop)[/dim]\n")

    while True:
        result = await run_scheduler_tick()
        tick_num = result.get("tick", "?") if result else "?"
        console.print(f"[dim]Tick #{tick_num} complete[/dim]")

        console.print(f"[dim]Sleeping {interval_seconds}s until next tick (Ctrl+C to stop)...[/dim]\n")
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            console.print("\n[bold yellow]Scheduler mode stopped.[/bold yellow]")
            break


def cli() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    if args.command == "run":
        asyncio.run(run_single_cycle())
    elif args.command == "run-forever":
        asyncio.run(run_forever(interval_seconds=args.interval))
    elif args.command == "run-scheduler":
        asyncio.run(run_scheduler_forever(interval_seconds=args.interval))
    elif args.command == "scan":
        asyncio.run(_run_scan_only())
    elif args.command == "run-prototype":
        asyncio.run(_run_prototype(args.concept))
    else:
        parser.print_help()


async def _run_scan_only() -> None:
    from agents.research.scanner import scan_market

    state = CompanyState()
    result = await scan_market(state)
    console.print(f"\n[yellow]Phase: {result.get('phase')}[/yellow]")
    insights = result.get("market_insights", [])
    console.print(f"[cyan]Opportunities found: {len(insights)}[/cyan]\n")
    for opp in insights:
        score = opp.get("market_opportunity_score") or opp.get("score", 0)
        console.print(f"  • {opp.get('name', 'N/A')} ({opp.get('genre', 'N/A')}) score={score:.2f}")


async def _run_prototype(concept: str) -> None:
    from orchestrator.prototype_mode import run_prototype

    console.print(f"\n[bold cyan]🚀 Quick Prototype: {concept}[/bold cyan]\n")
    result = await run_prototype(concept)
    console.print(f"[bold green]✓ Prototype built in {result['duration_seconds']}s[/bold green]")
    console.print(f"  Name: [cyan]{result['project_name']}[/cyan]")
    console.print(f"  Path: [dim]{result['dist_path']}[/dim]")
    console.print(f"  Preview: [link]{result['preview_url']}[/link]\n")


def _build_arg_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="gcagents",
        description="AI Game Company - autonomous game research, development and operations",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="Run a full cycle (scan → design → dev → deploy)")
    forever_parser = sub.add_parser("run-forever", help="Run in 24/7 mode — loop forever with interval")
    forever_parser.add_argument("--interval", type=int, default=3600,
                                help="Seconds between cycles (default: 3600)")
    sub.add_parser("scan", help="Run market scan only")
    sched_parser = sub.add_parser("run-scheduler", help="Run tick-based multi-project scheduler")
    sched_parser.add_argument("--interval", type=int, default=300,
                              help="Seconds between ticks (default: 300)")
    proto_parser = sub.add_parser("run-prototype", help="Generate a quick playable prototype (~5 min)")
    proto_parser.add_argument("concept", help='Game concept, e.g. "space shooter with powerups"')
    return parser


if __name__ == "__main__":
    cli()

"""CLI entry point for GCAgents.

Subcommands:
  - run-scheduler: tick-based multi-project scheduler (recommended)
  - scan: market scan only
  - run-prototype: quick playable prototype (~5 min)
"""

from __future__ import annotations

import asyncio
import os
import sys

from loguru import logger
from rich.console import Console

from orchestrator.state import CompanyState
from shared.config import load_config

console = Console()


def _configure_logging() -> None:
    """Configure loguru based on environment.

    GCAGENTS_LOG_FORMAT=text|json (default: text)
    GCAGENTS_LOG_LEVEL=DEBUG|INFO|WARNING|ERROR (default: INFO)
    """
    from loguru import logger as _log

    _log.remove()
    fmt = (
        "<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan> — <level>{message}</level>"
    )
    if os.environ.get("GCAGENTS_LOG_FORMAT", "text").lower() == "json":
        _log.add(sys.stderr, serialize=True, level=os.environ.get("GCAGENTS_LOG_LEVEL", "INFO"))
    else:
        _log.add(sys.stderr, format=fmt, level=os.environ.get("GCAGENTS_LOG_LEVEL", "INFO"))


async def run_scheduler_tick() -> dict | None:
    from orchestrator.persistence import ensure_tables
    from orchestrator.scheduler import scheduler_tick

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

        console.print(
            f"\n[dim]Sleeping {interval_seconds}s until next tick (Ctrl+C to stop)...[/dim]\n"
        )
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            console.print("\n[bold yellow]Scheduler mode stopped.[/bold yellow]")
            break


def cli() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    if args.command == "run-scheduler":
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
    console.print(f"[cyan]Opportunities found: {len(insights)}[/cyan>\n")
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
    console.print(f"  Preview: [link]{result['preview_url']}[/link>\n")


def _build_arg_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="gcagents",
        description="AI Game Company - autonomous game research, development and operations",
    )
    sub = parser.add_subparsers(dest="command")
    sched_parser = sub.add_parser(
        "run-scheduler", help="Run tick-based multi-project scheduler (recommended)"
    )
    sched_parser.add_argument(
        "--interval", type=int, default=300, help="Seconds between ticks (default: 300)"
    )
    sub.add_parser("scan", help="Run market scan only")
    proto_parser = sub.add_parser(
        "run-prototype", help="Generate a quick playable prototype (~5 min)"
    )
    proto_parser.add_argument("concept", help='Game concept, e.g. "space shooter with powerups"')
    return parser


if __name__ == "__main__":
    _configure_logging()
    cli()

"""
End-to-end integration test for the full GCAgents pipeline.

Runs: Market Scan → CEO Evaluate → Game Design → Code Gen → QA → Build → Deploy (simulated)

Usage:
    python scripts/e2e_test.py              # full pipeline with live APIs
    python scripts/e2e_test.py --mock       # mock all external API calls
    python scripts/e2e_test.py --scan-only  # only test market scanning
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from shared.config import load_config, AppConfig
from shared.models import GameProposal

console = Console()


async def test_market_scan(config: AppConfig, mock: bool = False) -> list[dict]:
    console.print("\n[bold cyan]━━━ Phase 1: Market Scan ━━━[/bold cyan]")

    if mock:
        console.print("[yellow]Using mock data[/yellow]")
        return [
            {
                "name": "Cosmic Clicker",
                "genre": "idle-clicker",
                "description": "An idle clicker set in space where you mine asteroids and build a galactic empire.",
                "target_platforms": ["itch.io", "web"],
                "estimated_dev_hours": 12,
                "market_opportunity_score": 0.85,
                "differentiation": "Space theme with asteroid mining mechanics not commonly seen in idle games",
                "reference_games": ["Cookie Clicker", "Adventure Capitalist", "Idle Planet Miner"],
            },
            {
                "name": "Match Quest",
                "genre": "puzzle-match",
                "description": "A match-3 puzzle game with RPG progression and unique power-up combinations.",
                "target_platforms": ["itch.io", "web"],
                "estimated_dev_hours": 20,
                "market_opportunity_score": 0.72,
                "differentiation": "RPG stat system layered on match-3 base creates deeper engagement",
                "reference_games": ["Candy Crush", "Bejeweled", "Puzzle Quest"],
            },
            {
                "name": "Tower Frontier",
                "genre": "tower-defense",
                "description": "Minimalist tower defense with procedural maps and roguelike tower upgrades.",
                "target_platforms": ["itch.io", "web"],
                "estimated_dev_hours": 30,
                "market_opportunity_score": 0.68,
                "differentiation": "Roguelike upgrade system adds replayability to tower defense",
                "reference_games": ["Kingdom Rush", "Bloons TD", "Plants vs Zombies"],
            },
        ]

    from agents.research.scanner import scan_market
    from orchestrator.state import CompanyState

    state = CompanyState()
    result = await scan_market(state)
    opportunities = result.get("market_insights", [])

    if not opportunities:
        console.print("[red]No opportunities found. Check API keys and network.[/red]")
        return []

    _print_opportunities(opportunities)
    return opportunities


async def test_game_design(proposal_data: dict, config: AppConfig, mock: bool = False) -> dict:
    console.print("\n[bold cyan]━━━ Phase 2: Game Design ━━━[/bold cyan]")

    proposal = GameProposal(**proposal_data)
    console.print(f"Designing: [green]{proposal.name}[/green] ({proposal.genre})")

    if mock:
        console.print("[yellow]Using mock GDD[/yellow]")
        return _mock_gdd(proposal.name, proposal.genre)

    from agents.dev.designer.gdd_generator import generate_gdd

    gdd = await generate_gdd(proposal, config)

    if gdd.get("title"):
        console.print(f"GDD generated: [green]{gdd['title']}[/green]")
        console.print(f"  Scenes: {len(gdd.get('scenes', []))}")
        console.print(f"  Entities: {len(gdd.get('entities', []))}")
        console.print(f"  Mechanics: {list(gdd.get('mechanics', {}).keys())}")
    else:
        console.print("[red]GDD generation failed[/red]")

    return gdd


async def test_code_generation(gdd: dict, config: AppConfig, mock: bool = False) -> Path:
    console.print("\n[bold cyan]━━━ Phase 3: Code Generation ━━━[/bold cyan]")

    project_name = gdd.get("title", "test-game").lower().replace(" ", "-")
    project_dir = config.games_output_dir / project_name

    if mock:
        console.print("[yellow]Using mock code (copying idle-clicker template)[/yellow]")
        return _mock_game_code(project_dir)

    from agents.dev.programmer.code_generator import generate_game_code

    code_path = await generate_game_code(gdd, project_dir, config)

    ts_files = [f for f in code_path.rglob("*.ts") if "node_modules" not in f.parts]
    console.print(f"Generated {len(ts_files)} TypeScript files in src/:")
    for f in sorted(ts_files):
        console.print(f"  {f.relative_to(code_path)}")

    return code_path


async def test_qa(project_dir: Path) -> dict:
    console.print("\n[bold cyan]━━━ Phase 4: QA ━━━[/bold cyan]")

    from agents.dev.qa.qa_agent import _check_project_structure

    ok, errors = _check_project_structure(project_dir)
    console.print(f"Structure check: {'[green]PASS[/green]' if ok else '[red]FAIL[/red]'}")
    for e in errors:
        console.print(f"  [red]✗ {e}[/red]")

    return {"passed": ok, "errors": errors}


async def test_build(project_dir: Path) -> bool:
    console.print("\n[bold cyan]━━━ Phase 5: Build ━━━[/bold cyan]")

    import subprocess

    try:
        if not (project_dir / "node_modules").exists():
            console.print("Running npm install...")
            subprocess.run(["npm", "install"], cwd=str(project_dir), capture_output=True, timeout=120, check=True)

        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            console.print("[green]Build successful![/green]")
            dist = project_dir / "dist"
            if dist.exists():
                files = list(dist.rglob("*"))
                console.print(f"  Output: {len(files)} files in dist/")
            return True
        else:
            console.print(f"[red]Build failed:[/red]\n{result.stderr[:500]}")
            return False
    except FileNotFoundError:
        console.print("[yellow]npm not found, skipping build[/yellow]")
        return False
    except subprocess.TimeoutExpired:
        console.print("[red]Build timed out[/red]")
        return False


async def run_full_pipeline(mock: bool = False) -> None:
    config = load_config()
    config.games_output_dir.mkdir(parents=True, exist_ok=True)

    console.print(Panel.fit(
        "[bold]GCAgents End-to-End Integration Test[/bold]\n"
        f"Mode: {'MOCK' if mock else 'LIVE'}",
        border_style="green",
    ))

    # Phase 1: Scan
    opportunities = await test_market_scan(config, mock)
    if not opportunities:
        console.print("[red]Pipeline stopped: no opportunities[/red]")
        return

    # Phase 2: Design (use top opportunity)
    top = max(opportunities, key=lambda x: x.get("market_opportunity_score", 0))
    gdd = await test_game_design(top, config, mock=mock)
    if not gdd.get("title"):
        console.print("[red]Pipeline stopped: GDD generation failed[/red]")
        return

    # Phase 3: Code
    try:
        project_dir = await test_code_generation(gdd, config, mock=mock)
    except Exception as e:
        console.print(f"[red]Code generation failed: {e}[/red]")
        logger.exception("Code generation error")
        return

    # Phase 4: QA
    qa_result = await test_qa(project_dir)
    if not qa_result["passed"]:
        console.print("[red]Pipeline stopped: QA failed[/red]")
        return

    # Phase 5: Build
    build_ok = await test_build(project_dir)

    # Summary
    console.print("\n" + "═" * 60)
    console.print(Panel.fit(
        f"[bold]Pipeline Result[/bold]\n\n"
        f"  Game: [cyan]{gdd.get('title', 'N/A')}[/cyan]\n"
        f"  Genre: {gdd.get('genre', 'N/A')}\n"
        f"  QA: {'[green]PASS[/green]' if qa_result['passed'] else '[red]FAIL[/red]'}\n"
        f"  Build: {'[green]PASS[/green]' if build_ok else '[red]FAIL[/red]'}\n"
        f"  Project: {project_dir}",
        border_style="green" if build_ok else "red",
    ))


def _print_opportunities(opportunities: list[dict]) -> None:
    table = Table(title="Market Opportunities")
    table.add_column("Game", style="cyan")
    table.add_column("Genre", style="magenta")
    table.add_column("Score", style="green")
    table.add_column("Est. Hours", style="yellow")

    for opp in opportunities:
        table.add_row(
            opp.get("name", "N/A"),
            opp.get("genre", "N/A"),
            f"{opp.get('market_opportunity_score', 0):.2f}",
            str(opp.get("estimated_dev_hours", "?")),
        )

    console.print(table)


def main() -> None:
    parser = argparse.ArgumentParser(description="GCAgents E2E Integration Test")
    parser.add_argument("--mock", action="store_true", help="Use mock data instead of live APIs")
    parser.add_argument("--scan-only", action="store_true", help="Only test market scanning")
    args = parser.parse_args()

    if args.scan_only:
        config = load_config()
        asyncio.run(test_market_scan(config, mock=args.mock))
    else:
        asyncio.run(run_full_pipeline(mock=args.mock))


def _mock_gdd(name: str, genre: str) -> dict:
    return {
        "title": name,
        "genre": genre,
        "summary": f"A {genre} game with engaging mechanics.",
        "core_loop": ["click", "earn", "upgrade", "repeat"],
        "mechanics": {"click": "Click to earn points", "upgrade": "Spend points to earn faster"},
        "progression": "Unlock upgrades over time",
        "win_condition": "Reach highest score",
        "art_style": {"theme": "pixel-art", "color_palette": ["#1a1a2e", "#00ff88", "#ffaa00"], "reference": "retro arcade"},
        "audio": {"bgm_mood": "upbeat chiptune", "sfx_list": ["click", "upgrade", "level_up"]},
        "scenes": [
            {"name": "Boot", "description": "Loading"},
            {"name": "Menu", "description": "Main menu"},
            {"name": "Game", "description": "Main gameplay"},
            {"name": "GameOver", "description": "Game over"},
        ],
        "entities": [
            {"name": "Player", "type": "sprite", "behaviors": ["click", "upgrade"]},
            {"name": "Background", "type": "tilemap", "behaviors": ["scroll"]},
        ],
        "ui_layout": {"hud": ["score", "level"], "menus": ["pause", "settings"]},
        "balance": {"starting_lives": 3, "difficulty_curve": "gradual"},
        "estimated_play_session_minutes": 5,
    }


def _mock_game_code(project_dir: Path) -> Path:
    import shutil
    template_dir = Path(__file__).resolve().parent.parent / "game-templates" / "idle-clicker"
    if project_dir.exists():
        shutil.rmtree(project_dir)
    shutil.copytree(str(template_dir), str(project_dir))
    console.print(f"Copied template to: {project_dir}")
    ts_files = list(project_dir.rglob("*.ts"))
    console.print(f"  {len(ts_files)} TypeScript files")
    return project_dir


if __name__ == "__main__":
    main()

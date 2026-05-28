"""One-time setup: create SQLite database, directories, and verify dependencies."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from rich.console import Console

console = Console()

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"

INIT_SQL = Path(ROOT_DIR / "infra" / "db" / "init.sql")


async def setup() -> None:
    console.print("[bold green]GCAgents - Local Setup (No Docker)[/bold green]\n")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "games").mkdir(exist_ok=True)
    (DATA_DIR / "builds").mkdir(exist_ok=True)
    (DATA_DIR / "market").mkdir(exist_ok=True)
    (DATA_DIR / "reports").mkdir(exist_ok=True)
    console.print("[green]✓[/green] Data directories created")

    db_path = DATA_DIR / "gcagents.db"
    if db_path.exists():
        console.print(f"[yellow]⚠[/yellow] Database already exists: {db_path}")
    else:
        await _init_db(db_path)
        console.print(f"[green]✓[/green] SQLite database created: {db_path}")

    console.print("\n[bold]Dependency Check:[/bold]")
    _check_import("sqlalchemy", "SQLAlchemy")
    _check_import("aiosqlite", "aiosqlite (SQLite async)")
    _check_import("langgraph", "LangGraph")
    _check_import("httpx", "httpx")
    _check_import("feedparser", "feedparser")
    _check_import("yaml", "PyYAML")
    _check_import("pydantic", "Pydantic")
    _check_import("pydantic_settings", "pydantic-settings")
    _check_import("openai", "openai (DeepSeek API)")

    missing = [
        ("fastapi", "FastAPI (dashboard)"),
        ("uvicorn", "uvicorn (dashboard server)"),
        ("jinja2", "Jinja2 (templates)"),
    ]
    for mod, name in missing:
        _check_import(mod, name, required=False)

    console.print("\n[bold]Next Steps:[/bold]")
    console.print("  1. [cyan]cp .env.example .env[/cyan] then edit .env with your API keys")
    console.print("  2. [cyan]pip install -e .[/cyan] to install all dependencies")
    console.print("  3. [cyan]python scripts/e2e_test.py --mock[/cyan] to test the pipeline")
    console.print("  4. [cyan]python -m orchestrator.main run[/cyan] to run full cycle")


async def _init_db(db_path: Path) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")

    sql = INIT_SQL.read_text()
    statements = [s.strip() for s in sql.split(";") if s.strip()]

    async with engine.begin() as conn:
        for stmt in statements:
            s = stmt.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
            s = s.replace("TIMESTAMPTZ", "TEXT")
            s = s.replace("FLOAT", "REAL")
            s = s.replace("JSONB", "TEXT")
            s = s.replace("DEFAULT NOW()", "DEFAULT (datetime('now'))")
            await conn.execute(text(s))

    await engine.dispose()
    logger.info(f"Database initialized with {len(statements)} statements")


def _check_import(module: str, name: str, required: bool = True) -> None:
    try:
        __import__(module)
        console.print(f"  [green]✓[/green] {name}")
    except ImportError:
        tag = "[red]✗[/red]" if required else "[yellow]?[/yellow]"
        console.print(f"  {tag} {name} - pip install {module}")


if __name__ == "__main__":
    asyncio.run(setup())

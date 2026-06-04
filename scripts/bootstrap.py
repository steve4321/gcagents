#!/usr/bin/env python3
"""GCAgents bootstrap: one-shot setup combining local DB + itch.io credentials.

Replaces scripts/setup_local.py + scripts/setup_itch.sh with a single entry point.
Run via: `python scripts/bootstrap.py` or `make install`.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from loguru import logger
from rich.console import Console

console = Console()
DATA_DIR = ROOT_DIR / "data"
INIT_SQL = ROOT_DIR / "infra" / "db" / "init.sql"


async def setup_local() -> None:
    console.print("[bold green]GCAgents - Local Setup[/bold green]\n")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for sub in ("games", "builds", "market", "reports"):
        (DATA_DIR / sub).mkdir(exist_ok=True)
    console.print("[green]✓[/green] Data directories created")

    db_path = DATA_DIR / "gcagents.db"
    if db_path.exists():
        console.print(f"[yellow]⚠[/yellow] Database already exists: {db_path}")
    else:
        await _init_db(db_path)
        console.print(f"[green]✓[/green] SQLite database created: {db_path}")

    console.print("\n[bold]Dependency Check:[/bold]")
    for mod, name in [
        ("sqlalchemy", "SQLAlchemy"),
        ("aiosqlite", "aiosqlite"),
        ("httpx", "httpx"),
        ("yaml", "PyYAML"),
        ("pydantic", "Pydantic"),
        ("openai", "openai (LLM client)"),
    ]:
        _check_import(mod, name)
    for mod, name in [
        ("fastapi", "FastAPI (dashboard)"),
        ("uvicorn", "uvicorn"),
    ]:
        _check_import(mod, name, required=False)


def setup_itch() -> None:
    env_file = ROOT_DIR / ".env"
    if env_file.exists():
        console.print("[green]✓[/green] .env already present")
    elif (ROOT_DIR / ".env.example").exists():
        shutil.copy(ROOT_DIR / ".env.example", env_file)
        console.print(f"[green]✓[/green] Created {env_file} from .env.example")
    else:
        console.print(f"[yellow]⚠[/yellow] No .env.example found — create {env_file} manually")

    if shutil.which("butler"):
        console.print(f"[green]✓[/green] butler CLI installed: {subprocess.run(['butler', '--version'], capture_output=True, text=True).stdout.strip()}")
    else:
        console.print(
            "[yellow]⚠[/yellow] butler CLI not found — install from "
            "https://itchio.itch.io/butler then run `butler login`"
        )

    try:
        username = input("  itch.io username (or Enter to skip): ").strip()
        api_key = input("  Butler API key (or Enter to skip): ").strip()
    except EOFError:
        username = api_key = ""

    if username and api_key and env_file.exists():
        _update_env(env_file, "BUTLER_USERNAME", username)
        _update_env(env_file, "BUTLER_API_KEY", api_key)
        console.print("[green]✓[/green] Credentials saved to .env")
    else:
        console.print("[yellow]⚠[/yellow] Edit .env manually later")


async def _init_db(db_path: Path) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    sql = INIT_SQL.read_text()
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    async with engine.begin() as conn:
        for stmt in statements:
            s = stmt.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
            s = s.replace("TIMESTAMPTZ", "TEXT").replace("FLOAT", "REAL")
            s = s.replace("JSONB", "TEXT").replace("DEFAULT NOW()", "DEFAULT (datetime('now'))")
            await conn.execute(text(s))
    await engine.dispose()


def _update_env(path: Path, key: str, value: str) -> None:
    text = path.read_text()
    if f"{key}=" in text:
        lines = text.splitlines()
        lines = [f"{key}={value}" if l.startswith(f"{key}=") else l for l in lines]
        path.write_text("\n".join(lines) + "\n")
    else:
        with path.open("a") as f:
            f.write(f"{key}={value}\n")


def _check_import(module: str, name: str, required: bool = True) -> None:
    try:
        __import__(module)
        console.print(f"  [green]✓[/green] {name}")
    except ImportError:
        tag = "[red]✗[/red]" if required else "[yellow]?[/yellow]"
        console.print(f"  {tag} {name} - pip install {module}")


def main() -> None:
    asyncio.run(setup_local())
    console.print()
    setup_itch()
    console.print("\n[bold green]✓ Bootstrap complete![/bold green]")
    console.print("  Next: edit .env with your API keys, then `make run-scheduler`")


if __name__ == "__main__":
    main()

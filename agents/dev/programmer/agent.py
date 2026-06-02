from __future__ import annotations

import subprocess
from pathlib import Path

from loguru import logger

from orchestrator.state import CompanyState, PipelinePhase
from shared.config import load_config

from .code_generator import generate_game_code


def _git_init(project_dir: Path) -> None:
    """Initialize a git repo in the project directory if not already one."""
    if (project_dir / ".git").exists():
        return
    subprocess.run(["git", "init"], cwd=str(project_dir), capture_output=True, timeout=10, check=True)
    subprocess.run(["git", "config", "user.email", "bot@gcagents.local"], cwd=str(project_dir), capture_output=True, timeout=5)
    subprocess.run(["git", "config", "user.name", "GCAgents Bot"], cwd=str(project_dir), capture_output=True, timeout=5)
    (project_dir / ".gitignore").write_text("node_modules/\ndist/\n*.log\n")


def _git_commit(project_dir: Path, message: str) -> None:
    """Stage all files and commit."""
    subprocess.run(["git", "add", "-A"], cwd=str(project_dir), capture_output=True, timeout=30)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", message],
        cwd=str(project_dir), capture_output=True, timeout=30,
    )


async def develop_game(state: CompanyState) -> dict:
    gdd = state.gdd
    if not gdd:
        logger.error("No GDD to develop")
        return {"phase": PipelinePhase.IDLE, "errors": ["Missing GDD"]}

    config = load_config()
    project_id = state.current_project_id or "unknown"

    # Use project_id as fixed directory name — no more timestamp-suffix sprawl
    project_dir = config.games_output_dir / project_id

    _git_init(project_dir)

    build_error = ""
    if state.errors:
        build_error = state.errors[0] if isinstance(state.errors, list) else str(state.errors)

    is_retry = bool(build_error) or bool(state.retry_feedback)
    commit_msg = f"fix: retry build after error" if is_retry else f"feat: initial code generation"

    code_path = await generate_game_code(
        gdd, project_dir, config,
        build_error=build_error,
        art_assets_path=state.art_assets_path or "",
    )

    _git_commit(project_dir, commit_msg)

    result = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=str(project_dir), capture_output=True, text=True, timeout=10,
    )
    commit_count = int(result.stdout.strip()) if result.returncode == 0 else 1

    return {
        "phase": PipelinePhase.TESTING,
        "game_code_path": str(code_path),
        "version": f"0.{commit_count}.0",
    }

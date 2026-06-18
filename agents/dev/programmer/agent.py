from __future__ import annotations

import asyncio
from pathlib import Path

from loguru import logger

from orchestrator.state import CompanyState, PipelinePhase
from shared.config import load_config

from .code_generator import generate_game_code


async def _run_cmd(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        return -1, "", f"Command timed out: {' '.join(cmd)}"
    return (
        proc.returncode if proc.returncode is not None else -1,
        stdout.decode(errors="replace"),
        stderr.decode(errors="replace"),
    )


async def _git_init(project_dir: Path) -> None:
    if (project_dir / ".git").exists():
        return
    rc, _, err = await _run_cmd(["git", "init"], project_dir, 10)
    if rc != 0:
        raise RuntimeError(f"git init failed: {err}")
    rc, _, err = await _run_cmd(
        ["git", "config", "user.email", "bot@gcagents.local"], project_dir, 5
    )
    if rc != 0:
        raise RuntimeError(f"git config email failed: {err}")
    rc, _, err = await _run_cmd(["git", "config", "user.name", "GCAgents Bot"], project_dir, 5)
    if rc != 0:
        raise RuntimeError(f"git config name failed: {err}")
    (project_dir / ".gitignore").write_text("node_modules/\ndist/\n*.log\n")


async def _git_commit(project_dir: Path, message: str) -> None:
    rc, _, err = await _run_cmd(["git", "add", "-A"], project_dir, 30)
    if rc != 0:
        raise RuntimeError(f"git add failed: {err}")
    rc, _, err = await _run_cmd(["git", "commit", "--allow-empty", "-m", message], project_dir, 30)
    if rc != 0:
        raise RuntimeError(f"git commit failed: {err}")


async def develop_game(state: CompanyState) -> dict:
    gdd = state.gdd
    if not gdd:
        logger.error("No GDD to develop")
        return {"phase": PipelinePhase.IDLE, "errors": ["Missing GDD"]}

    config = load_config()
    project_id = state.current_project_id or "unknown"

    project_dir = config.games_output_dir / project_id

    project_dir.mkdir(parents=True, exist_ok=True)
    await _git_init(project_dir)

    build_error = ""
    if state.errors:
        if isinstance(state.errors, list):
            build_error = "\n".join(state.errors[:10])
        else:
            build_error = str(state.errors)

    is_retry = bool(build_error) or bool(state.retry_feedback)
    commit_msg = "fix: retry build after error" if is_retry else "feat: initial code generation"

    code_path = await generate_game_code(
        gdd,
        project_dir,
        config,
        build_error=build_error,
        art_assets_path=state.art_assets_path or "",
    )

    await _git_commit(project_dir, commit_msg)

    rc, stdout, stderr = await _run_cmd(["git", "rev-list", "--count", "HEAD"], project_dir, 10)
    commit_count = int(stdout.strip()) if rc == 0 else 1

    return {
        "phase": PipelinePhase.TESTING,
        "game_code_path": str(code_path),
        "version": f"0.{commit_count}.0",
    }

"""Shared npm install + build runner for game projects.

Uses ``asyncio.create_subprocess_exec`` so the event loop is not blocked
while npm runs.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from loguru import logger


NPM_INSTALL_TIMEOUT = 300
NPM_BUILD_TIMEOUT = 180


async def _run(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, str, str]:
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
        try:
            await proc.communicate()
        except Exception:
            pass
        return -1, "", f"Command timed out after {timeout}s: {' '.join(cmd)}"
    return (
        proc.returncode if proc.returncode is not None else -1,
        stdout.decode(errors="replace"),
        stderr.decode(errors="replace"),
    )


async def install(project_dir: Path, timeout: int = NPM_INSTALL_TIMEOUT) -> str:
    """Run ``npm install`` in *project_dir*. Return '' on success, error msg on failure."""
    code, _out, err = await _run(["npm", "install"], project_dir, timeout)
    if code != 0:
        logger.warning(f"npm install failed: {err[:500]}")
        return f"npm install failed: {err[:500]}"
    logger.info("npm install completed")
    return ""


async def build(project_dir: Path, timeout: int = NPM_BUILD_TIMEOUT) -> str:
    """Run ``npm run build`` in *project_dir*. Return '' on success, error msg on failure."""
    code, _out, err = await _run(["npm", "run", "build"], project_dir, timeout)
    if code != 0:
        logger.warning(f"npm build failed: {err[:500]}")
        return f"npm build failed: {err[:500]}"
    logger.info("npm build succeeded")
    return ""


async def install_and_build(
    project_dir: Path,
    install_timeout: int = NPM_INSTALL_TIMEOUT,
    build_timeout: int = NPM_BUILD_TIMEOUT,
) -> str:
    """Run install + build. Return '' on success, error message on first failure.

    Always cleans up ``node_modules`` afterwards to keep the data dir small.
    """
    try:
        if not shutil.which("npm"):
            return "npm not found on PATH"
        err = await install(project_dir, install_timeout)
        if err:
            return err
        return await build(project_dir, build_timeout)
    finally:
        shutil.rmtree(project_dir / "node_modules", ignore_errors=True)

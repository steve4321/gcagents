"""Subprocess-based sandbox for isolated code execution."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from shared.constants import NPM_BUILD_TIMEOUT, NPM_INSTALL_TIMEOUT

# ── Data classes ────────────────────────────────────────────────────────────


@dataclass
class CommandResult:
    """Result of a sandboxed command execution."""

    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False


@dataclass
class SandboxConfig:
    """Configuration for the subprocess sandbox."""

    working_dir: str = "."
    timeout_secs: int = 120
    max_output_bytes: int = 1_000_000  # 1 MB
    env_vars: dict[str, str] = field(default_factory=dict)


# ── SubprocessSandbox ──────────────────────────────────────────────────────


class SubprocessSandbox:
    """Isolated code execution via subprocess with resource limits."""

    def __init__(self, config: SandboxConfig | None = None) -> None:
        self.config = config or SandboxConfig()

    # ── core execution ──────────────────────────────────────────────────

    async def execute(
        self,
        command: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> CommandResult:
        """Run *command* in a sandboxed subprocess."""
        work_dir = cwd or self.config.working_dir
        effective_timeout = timeout or self.config.timeout_secs

        merged_env = dict(os.environ)
        merged_env.update(self.config.env_vars)
        if env:
            merged_env.update(env)

        start = time.monotonic()
        timed_out = False

        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
                env=merged_env,
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=effective_timeout,
            )
            exit_code = proc.returncode if proc.returncode is not None else -1

        except TimeoutError:
            timed_out = True
            try:
                proc.kill()  # type: ignore[possibly-undefined]
                await proc.communicate()  # type: ignore[possibly-undefined]
            except (ProcessLookupError, OSError) as e:
                logger.debug(f"Process kill after timeout: {e}")
            stdout_bytes = b""
            stderr_bytes = f"Command timed out after {effective_timeout}s".encode()
            exit_code = -1

        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.error("Sandbox execution failed: {}", exc)
            return CommandResult(
                exit_code=-1,
                stdout="",
                stderr=str(exc),
                duration_ms=elapsed_ms,
            )

        elapsed_ms = int((time.monotonic() - start) * 1000)

        max_bytes = self.config.max_output_bytes
        stdout = stdout_bytes[:max_bytes].decode(errors="replace")
        stderr = stderr_bytes[:max_bytes].decode(errors="replace")

        return CommandResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=elapsed_ms,
            timed_out=timed_out,
        )

    # ── script execution ────────────────────────────────────────────────

    async def execute_script(
        self,
        script_content: str,
        language: str = "bash",
        cwd: str | None = None,
    ) -> CommandResult:
        """Write *script_content* to a temp file and execute it."""
        suffix = {"bash": ".sh", "python": ".py", "node": ".js"}.get(language, ".sh")
        tmp_path = Path(cwd or self.config.working_dir) / f"_sandbox_tmp{suffix}"
        tmp_path.write_text(script_content)

        try:
            if language == "python":
                cmd = ["python3", str(tmp_path)]
            elif language == "node":
                cmd = ["node", str(tmp_path)]
            else:
                cmd = ["bash", str(tmp_path)]
            return await self.execute(cmd, cwd=cwd)
        finally:
            tmp_path.unlink(missing_ok=True)

    # ── file helpers ────────────────────────────────────────────────────

    async def file_exists(self, path: str) -> bool:
        """Check if *path* exists relative to the working dir."""
        full = Path(self.config.working_dir) / path
        return full.exists()

    async def read_file(self, path: str, limit: int = 2000) -> str | None:
        """Read up to *limit* lines from *path*."""
        full = Path(self.config.working_dir) / path
        if not full.exists():
            return None
        text = full.read_text(errors="replace")
        lines = text.splitlines()
        if len(lines) > limit:
            lines = lines[:limit]
            lines.append(f"... truncated ({limit}/{len(text.splitlines())} lines)")
        return "\n".join(lines)

    async def write_file(self, path: str, content: str) -> None:
        """Write *content* to *path* inside the sandbox working dir."""
        full = Path(self.config.working_dir) / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
        logger.debug("Sandbox wrote {} bytes to {}", len(content), path)

    async def snapshot_working_dir(self, path: str | None = None) -> list[str]:
        """List all files under *path* (recursively) for change detection."""
        base = Path(path or self.config.working_dir)
        if not base.exists():
            return []
        return sorted(str(p.relative_to(base)) for p in base.rglob("*") if p.is_file())


# ── ProjectSandbox ─────────────────────────────────────────────────────────


class ProjectSandbox:
    """Higher-level API for game-project build operations."""

    def __init__(self, sandbox: SubprocessSandbox | None = None) -> None:
        self.sandbox = sandbox or SubprocessSandbox()

    async def npm_install(self, project_path: str) -> CommandResult:
        """Run ``npm install`` in *project_path*."""
        logger.info("npm install — {}", project_path)
        return await self.sandbox.execute(
            ["npm", "install"],
            cwd=project_path,
            timeout=NPM_INSTALL_TIMEOUT,
        )

    async def npm_build(self, project_path: str) -> CommandResult:
        """Run ``npm run build`` in *project_path*."""
        logger.info("npm run build — {}", project_path)
        return await self.sandbox.execute(
            ["npm", "run", "build"],
            cwd=project_path,
            timeout=NPM_BUILD_TIMEOUT,
        )

    async def type_check(self, project_path: str) -> CommandResult:
        """Run ``tsc --noEmit`` in *project_path*."""
        logger.info("tsc --noEmit — {}", project_path)
        return await self.sandbox.execute(
            ["npx", "tsc", "--noEmit"],
            cwd=project_path,
            timeout=NPM_BUILD_TIMEOUT,
        )

    async def list_artifacts(self, project_path: str) -> list[str]:
        """List files in ``dist/`` after build."""
        return await self.sandbox.snapshot_working_dir(
            str(Path(project_path) / "dist"),
        )


# ── Singleton ───────────────────────────────────────────────────────────────

_sandbox: SubprocessSandbox | None = None


def get_sandbox() -> SubprocessSandbox:
    """Return (and lazily create) the global :class:`SubprocessSandbox`."""
    global _sandbox
    if _sandbox is None:
        _sandbox = SubprocessSandbox()
    return _sandbox

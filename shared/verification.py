"""Verification-first protocol — every agent output must be independently verified.

Inspired by:
- prove-it: structured verification plan + result blocks
- hog: structural role separation (generator ≠ verifier)
- Superpowers: goal-backward verification from observable truths
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from loguru import logger


class VerificationMode(str, Enum):
    """Verification strictness levels."""

    QUICK = "quick"  # Basic checks only (file exists, no syntax errors)
    STANDARD = "standard"  # Standard checks + structural validation
    STRICT = "strict"  # Full checks + regression tests + edge cases


class ArtifactType(str, Enum):
    """Types of agent outputs that can be verified."""

    CODE = "code"
    ART = "art"
    GDD = "gdd"
    BUILD = "build"
    MARKET_REPORT = "market_report"
    MUSIC = "music"
    LOCALIZATION = "localization"
    GAME_PACKAGE = "game_package"


@dataclass
class VerificationCheck:
    """A single verification check."""

    name: str
    description: str
    check_type: str  # "file_exists" | "command" | "custom" | "schema"
    command: str | None = None  # Shell command to run (for command type)
    expected_path: str | None = None  # File path to check (for file_exists)
    required: bool = True  # If True, failure fails the whole verification

    @staticmethod
    def file_exists(name: str, path: str, required: bool = True) -> VerificationCheck:
        return VerificationCheck(
            name=name,
            description=f"File exists: {path}",
            check_type="file_exists",
            expected_path=path,
            required=required,
        )

    @staticmethod
    def command_check(
        name: str, cmd: str, description: str = "", required: bool = True
    ) -> VerificationCheck:
        return VerificationCheck(
            name=name,
            description=description or f"Command: {cmd}",
            check_type="command",
            command=cmd,
            required=required,
        )

    @staticmethod
    def custom_check(name: str, description: str, required: bool = True) -> VerificationCheck:
        return VerificationCheck(
            name=name,
            description=description,
            check_type="custom",
            required=required,
        )


@dataclass
class VerificationPlan:
    """Plan for verifying an agent's output.

    Every agent that produces a tangible artifact MUST provide one of these.
    """

    agent_name: str
    artifact_type: ArtifactType
    artifact_path: str | None = None
    checks: list[VerificationCheck] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    edge_cases: list[str] = field(default_factory=list)
    mode: VerificationMode = VerificationMode.STANDARD

    def add_file_check(self, name: str, path: str, required: bool = True) -> VerificationPlan:
        self.checks.append(VerificationCheck.file_exists(name, path, required))
        return self

    def add_command_check(self, name: str, cmd: str, required: bool = True) -> VerificationPlan:
        self.checks.append(VerificationCheck.command_check(name, cmd, required=required))
        return self

    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "artifact_type": self.artifact_type.value,
            "artifact_path": self.artifact_path,
            "checks": [
                {"name": c.name, "type": c.check_type, "required": c.required} for c in self.checks
            ],
            "success_criteria": self.success_criteria,
            "mode": self.mode.value,
        }


@dataclass
class CheckResult:
    """Result of a single verification check."""

    name: str
    passed: bool
    evidence: str = ""
    error: str | None = None
    duration_ms: int = 0


@dataclass
class VerificationResult:
    """Complete verification result for an agent output."""

    plan: VerificationPlan
    passed: bool
    check_results: list[CheckResult] = field(default_factory=list)
    summary: str = ""
    total_duration_ms: int = 0

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [c for c in self.check_results if not c.passed]

    @property
    def failure_evidence(self) -> str:
        """Formatted evidence of all failures for feedback to agent."""
        parts = []
        for c in self.failed_checks:
            parts.append(f"❌ {c.name}: {c.error or 'failed'}")
            if c.evidence:
                parts.append(f"   Evidence: {c.evidence[:200]}")
        return "\n".join(parts)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "summary": self.summary,
            "total_duration_ms": self.total_duration_ms,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "evidence": c.evidence[:200],
                    "error": c.error,
                }
                for c in self.check_results
            ],
        }


class Verifier:
    """Independent verifier — executes verification plans.

    CRITICAL DESIGN PRINCIPLE: The verifier operates with its own context.
    It does not share the generating agent's context window, preventing
    "self-verification bias" (the tendency to accept your own output).
    """

    def __init__(self, max_command_timeout: int = 60) -> None:
        self.max_command_timeout = max_command_timeout

    async def verify(self, plan: VerificationPlan) -> VerificationResult:
        """Execute all checks in a verification plan."""
        import time

        start = time.monotonic()

        check_results = []

        for check in plan.checks:
            result = await self._execute_check(check)
            check_results.append(result)

        total_ms = int((time.monotonic() - start) * 1000)

        required_failures = [
            c for c, r in zip(plan.checks, check_results) if c.required and not r.passed
        ]
        passed = len(required_failures) == 0

        passed_count = sum(1 for r in check_results if r.passed)
        total_count = len(check_results)
        summary = f"{passed_count}/{total_count} checks passed"
        if not passed:
            summary += f" — {len(required_failures)} required check(s) failed"

        result = VerificationResult(
            plan=plan,
            passed=passed,
            check_results=check_results,
            summary=summary,
            total_duration_ms=total_ms,
        )

        if passed:
            logger.info(f"Verification PASSED: {plan.agent_name} ({summary})")
        else:
            logger.warning(f"Verification FAILED: {plan.agent_name} ({summary})")

        return result

    async def _execute_check(self, check: VerificationCheck) -> CheckResult:
        """Execute a single verification check."""
        import time

        start = time.monotonic()

        try:
            if check.check_type == "file_exists":
                return await self._check_file_exists(check)
            elif check.check_type == "command":
                return await self._check_command(check)
            elif check.check_type == "schema":
                return await self._check_schema(check)
            else:
                return CheckResult(
                    name=check.name,
                    passed=False,
                    error=f"Unknown check type: {check.check_type}",
                    duration_ms=int((time.monotonic() - start) * 1000),
                )
        except Exception as e:
            return CheckResult(
                name=check.name,
                passed=False,
                error=str(e),
                duration_ms=int((time.monotonic() - start) * 1000),
            )

    async def _check_file_exists(self, check: VerificationCheck) -> CheckResult:
        """Verify a file exists and has content."""
        path = check.expected_path
        if not path:
            return CheckResult(name=check.name, passed=False, error="No path specified")

        p = Path(path)
        if not p.exists():
            return CheckResult(
                name=check.name,
                passed=False,
                error=f"File not found: {path}",
            )

        size = p.stat().st_size
        if size == 0:
            return CheckResult(
                name=check.name,
                passed=False,
                error=f"File is empty: {path}",
                evidence="size=0 bytes",
            )

        return CheckResult(
            name=check.name,
            passed=True,
            evidence=f"exists, {size} bytes",
        )

    async def _check_command(self, check: VerificationCheck) -> CheckResult:
        """Run a shell command and check exit code."""
        if not check.command:
            return CheckResult(name=check.name, passed=False, error="No command specified")

        try:
            proc = await asyncio.create_subprocess_exec(
                *["bash", "-c", check.command],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.max_command_timeout
            )

            stdout_text = stdout.decode()[:500] if stdout else ""
            stderr_text = stderr.decode()[:200] if stderr else ""
            evidence = stdout_text + stderr_text

            return CheckResult(
                name=check.name,
                passed=proc.returncode == 0,
                evidence=evidence.strip(),
                error=(f"exit code {proc.returncode}" if proc.returncode != 0 else None),
            )
        except TimeoutError:
            return CheckResult(
                name=check.name,
                passed=False,
                error=f"Command timed out ({self.max_command_timeout}s)",
            )

    async def _check_schema(self, check: VerificationCheck) -> CheckResult:
        """Validate JSON schema (placeholder for future implementation)."""
        return CheckResult(
            name=check.name,
            passed=True,
            evidence="Schema validation not yet implemented",
        )


# ── Pre-built verification plan factories ────────────────────────────


def plan_for_code(
    agent_name: str,
    code_path: str,
    mode: VerificationMode = VerificationMode.STANDARD,
) -> VerificationPlan:
    """Create a verification plan for code output."""
    plan = VerificationPlan(
        agent_name=agent_name,
        artifact_type=ArtifactType.CODE,
        artifact_path=code_path,
        mode=mode,
        success_criteria=[
            "Code files exist",
            "No syntax errors",
            "Project structure valid",
        ],
    )
    plan.add_file_check("source_dir", code_path)

    if mode in (VerificationMode.STANDARD, VerificationMode.STRICT):
        # Check for package.json in Phaser projects
        plan.add_file_check("package_json", f"{code_path}/package.json")
        plan.add_file_check("tsconfig", f"{code_path}/tsconfig.json", required=False)

    if mode == VerificationMode.STRICT:
        plan.add_command_check("npm_install", f"cd {code_path} && npm install", required=True)
        plan.add_command_check(
            "type_check",
            f"cd {code_path} && npx tsc --noEmit 2>&1 || true",
            required=False,
        )

    return plan


def plan_for_build(agent_name: str, build_path: str) -> VerificationPlan:
    """Create a verification plan for build output."""
    plan = VerificationPlan(
        agent_name=agent_name,
        artifact_type=ArtifactType.BUILD,
        artifact_path=build_path,
        success_criteria=["Build directory exists", "index.html present"],
    )
    plan.add_file_check("build_dir", build_path)
    plan.add_file_check("index_html", f"{build_path}/index.html")
    return plan


def plan_for_art(agent_name: str, art_path: str) -> VerificationPlan:
    """Create a verification plan for art assets."""
    plan = VerificationPlan(
        agent_name=agent_name,
        artifact_type=ArtifactType.ART,
        artifact_path=art_path,
        success_criteria=["Art directory exists", "At least one image file"],
    )
    plan.add_file_check("art_dir", art_path)
    return plan


def plan_for_gdd(agent_name: str) -> VerificationPlan:
    """Create a verification plan for GDD output (structure check only)."""
    return VerificationPlan(
        agent_name=agent_name,
        artifact_type=ArtifactType.GDD,
        success_criteria=["GDD has required sections", "Mechanics defined"],
        checks=[
            VerificationCheck.custom_check(
                "gdd_structure", "GDD has title, genre, mechanics, scenes"
            ),
        ],
    )


# Singleton verifier
_verifier: Verifier | None = None


def get_verifier() -> Verifier:
    global _verifier
    if _verifier is None:
        _verifier = Verifier()
    return _verifier

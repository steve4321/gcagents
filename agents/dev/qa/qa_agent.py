"""QA agent — validates game builds and runs automated Playwright playtests.

Checks: project structure, build artifacts, and 8-point automated verification.
Failing QA feeds back to the developer for retry.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from loguru import logger

from orchestrator.state import CompanyState, PipelinePhase

from .auto_playtest import run_auto_playtest


async def run_qa(state: CompanyState) -> dict:
    game_code_path = state.game_code_path
    if not game_code_path:
        return {"phase": PipelinePhase.IDLE, "errors": ["No game code to test"]}

    project_dir = Path(game_code_path)
    logger.info(f"Running QA on: {project_dir.name}")

    build_ok = _check_build_exists(project_dir)
    build_error = ""
    if not build_ok:
        logger.warning("No build found, attempting build first")
        build_ok, build_error = _try_build(project_dir)
        if not build_ok:
            return {
                "phase": PipelinePhase.DEVELOPING,
                "qa_results": {"passed": False, "errors": [build_error[:500]]},
                "retry_count": state.retry_count + 1,
                "errors": [build_error[:500]],
            }

    structure_ok, structure_errors = _check_project_structure(project_dir)

    playtest_results = None
    dist_dir = project_dir / "dist"
    if build_ok and dist_dir.exists():
        logger.info("Running automated playtest...")
        playtest_results = await run_auto_playtest(dist_dir, game_dir=project_dir)
        logger.info(
            f"Playtest: passed={playtest_results['passed']}, "
            f"score={playtest_results['score']}, "
            f"duration={playtest_results.get('duration_ms', 0)}ms"
        )

    code_review_result = None
    if build_ok and project_dir.exists():
        code_review_result = await _run_code_review(project_dir)
        if code_review_result:
            logger.info(
                f"Code review: score={code_review_result.get('score', '?')}, "
                f"issues={len(code_review_result.get('issues', []))}"
            )

    checks = {
        "project_structure": structure_ok,
        "build_artifacts": build_ok,
    }
    if playtest_results is not None:
        checks["playtest"] = playtest_results
    if code_review_result is not None:
        checks["code_review"] = code_review_result

    playtest_passed = playtest_results["passed"] if playtest_results else False
    all_passed = structure_ok and build_ok and playtest_passed

    qa_results = {
        "passed": all_passed,
        "errors": structure_errors,
        "checks": checks,
    }

    logger.info(f"QA results: passed={qa_results['passed']}, errors={len(structure_errors)}")

    if qa_results["passed"]:
        return {"phase": PipelinePhase.BUILDING, "qa_results": qa_results}
    else:
        return {
            "phase": PipelinePhase.DEVELOPING,
            "qa_results": qa_results,
            "retry_count": state.retry_count + 1,
        }


async def _run_code_review(project_dir: Path) -> dict | None:
    try:
        from skills.base import SkillContext
        from skills.code_review import CodeReviewSkill

        skill = CodeReviewSkill()
        ctx = SkillContext(
            task_type="develop",
            artifact_path=str(project_dir),
        )
        if not skill.should_activate(ctx):
            return None
        result = await skill.execute(ctx)
        if result.success and result.output:
            return result.output
    except Exception as e:
        from loguru import logger
        logger.debug(f"Code review skill skipped: {e}")
    return None


def _check_build_exists(project_dir: Path) -> bool:
    return (project_dir / "dist" / "index.html").exists()


def _try_build(project_dir: Path) -> tuple[bool, str]:
    import shutil

    try:
        install = subprocess.run(
            ["npm", "install"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if install.returncode != 0:
            return False, install.stderr or "npm install failed"
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            return True, ""
        return False, result.stderr or result.stdout or "Build failed with no output"
    except Exception as e:
        return False, str(e)
    finally:
        shutil.rmtree(project_dir / "node_modules", ignore_errors=True)


def _check_project_structure(project_dir: Path) -> tuple[bool, list[str]]:
    errors = []
    required = [
        "package.json",
        "index.html",
        "src/main.ts",
    ]
    for f in required:
        if not (project_dir / f).exists():
            errors.append(f"Missing required file: {f}")

    return len(errors) == 0, errors

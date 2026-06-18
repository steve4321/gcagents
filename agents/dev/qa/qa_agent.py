"""QA agent — validates game builds and runs automated Playwright playtests.

Checks: project structure, build artifacts, and 8-point automated verification.
Failing QA feeds back to the developer for retry.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from orchestrator.state import CompanyState, PipelinePhase
from shared import npm_runner

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
        build_ok, build_error = await _try_build(project_dir)
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

    quality_gate_result = None
    if build_ok and playtest_results and playtest_results["passed"]:
        try:
            from shared.quality_gate import run_quality_gate

            gdd = state.gdd or {}
            gate_report = await run_quality_gate(project_dir, gdd)
            quality_gate_result = gate_report.to_dict()
            logger.info(
                f"Quality gate: passed={quality_gate_result['overall_passed']}, "
                f"hard_fails={len(quality_gate_result['hard_failures'])}"
            )
            for hf in quality_gate_result["hard_failures"]:
                structure_errors.append(f"Gate[{hf['name']}]: {hf['evidence']}")
        except Exception as e:
            logger.warning(f"Quality gate error: {e}")

    checks = {
        "project_structure": structure_ok,
        "build_artifacts": build_ok,
    }
    if playtest_results is not None:
        checks["playtest"] = playtest_results
    if code_review_result is not None:
        checks["code_review"] = code_review_result
    if quality_gate_result is not None:
        checks["quality_gate"] = quality_gate_result

    playtest_passed = playtest_results["passed"] if playtest_results else False
    gate_passed = quality_gate_result["overall_passed"] if quality_gate_result else True
    all_passed = structure_ok and build_ok and playtest_passed and gate_passed

    qa_results = {
        "passed": all_passed,
        "errors": structure_errors,
        "checks": checks,
    }

    logger.info(f"QA results: passed={qa_results['passed']}, errors={len(structure_errors)}")

    _record_production_metric(state, project_dir, qa_results)

    if qa_results["passed"]:
        return {"phase": PipelinePhase.BUILDING, "qa_results": qa_results}
    else:
        return {
            "phase": PipelinePhase.DEVELOPING,
            "qa_results": qa_results,
            "retry_count": state.retry_count + 1,
        }


def _record_production_metric(
    state: CompanyState,
    project_dir: Path,
    qa_results: dict,
) -> None:
    try:
        from shared.production_metrics import get_recorder

        gdd = state.gdd or {}
        genre = gdd.get("genre", "unknown")
        theme = gdd.get("theme", "")

        gate = qa_results.get("checks", {}).get("quality_gate", {})
        hard_fails = [f["name"] for f in gate.get("hard_failures", [])]
        soft_warns = [w["name"] for w in gate.get("soft_warnings", [])]
        if not hard_fails and not qa_results["passed"]:
            hard_fails = qa_results.get("errors", [])[:5]

        get_recorder().record(
            project_id=project_dir.name,
            genre=genre,
            theme=theme,
            passed=qa_results["passed"],
            hard_failures=hard_fails,
            soft_warnings=soft_warns,
            template_used=genre if genre == "tower-defense" else "",
        )
    except Exception as e:
        logger.debug(f"Metrics recording skipped: {e}")


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


async def _try_build(project_dir: Path) -> tuple[bool, str]:
    try:
        err = await npm_runner.install_and_build(project_dir)
        if err:
            return False, err
        return True, ""
    except Exception as e:
        return False, str(e)


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

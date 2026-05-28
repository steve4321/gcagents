from __future__ import annotations

import subprocess
from pathlib import Path

from loguru import logger

from orchestrator.state import CompanyState, PipelinePhase


async def run_qa(state: CompanyState) -> dict:
    game_code_path = state.game_code_path
    if not game_code_path:
        return {"phase": PipelinePhase.IDLE, "errors": ["No game code to test"]}

    project_dir = Path(game_code_path)
    logger.info(f"Running QA on: {project_dir.name}")

    build_ok = _check_build_exists(project_dir)
    if not build_ok:
        logger.warning("No build found, attempting build first")
        build_result = _try_build(project_dir)
        if not build_result:
            return {
                "phase": PipelinePhase.DEVELOPING,
                "qa_results": {"passed": False, "errors": ["Build failed"]},
                "retry_count": state.retry_count + 1,
            }

    structure_ok, structure_errors = _check_project_structure(project_dir)

    qa_results = {
        "passed": structure_ok,
        "errors": structure_errors,
        "checks": {
            "project_structure": structure_ok,
            "build_artifacts": build_ok,
        },
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


def _check_build_exists(project_dir: Path) -> bool:
    return (project_dir / "dist" / "index.html").exists()


def _try_build(project_dir: Path) -> bool:
    try:
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.returncode == 0
    except Exception:
        return False


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

from __future__ import annotations

import subprocess
from pathlib import Path

from loguru import logger

from orchestrator.state import CompanyState, PipelinePhase
from shared.config import load_config


async def deploy_to_itch(state: CompanyState) -> dict:
    build_path = state.build_path
    if not build_path:
        return {"phase": PipelinePhase.IDLE, "errors": ["No build to deploy"]}

    config = load_config()

    if not config.butler_api_key or not config.butler_username:
        logger.warning("itch.io credentials not configured, simulating deploy")
        return {
            "phase": PipelinePhase.OPERATING,
            "itch_url": f"https://{config.butler_username or 'placeholder'}.itch.io/{Path(state.game_code_path or '').name}",
        }

    project_name = Path(state.game_code_path or "game").name
    channel = "html"

    logger.info(f"Deploying {project_name} to itch.io...")

    try:
        env = {"BUTLER_API_KEY": config.butler_api_key}

        result = subprocess.run(
            [
                "butler", "push",
                str(build_path),
                f"{config.butler_username}/{project_name}:{channel}",
            ],
            env={**subprocess.os.environ, **env},
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[:500]
            logger.error(f"Deploy failed: {detail}")
            return {"phase": PipelinePhase.BUILDING, "errors": [f"Deploy failed: {detail}"]}

        itch_url = f"https://{config.butler_username}.itch.io/{project_name}"
        logger.info(f"Deployed to: {itch_url}")

        return {"phase": PipelinePhase.OPERATING, "itch_url": itch_url}

    except subprocess.TimeoutExpired:
        logger.error("Deploy timed out")
        return {"phase": PipelinePhase.BUILDING, "errors": ["Deploy timeout"]}
    except FileNotFoundError:
        logger.error("butler CLI not found - install from https://itchio.itch.io/butler")
        return {"phase": PipelinePhase.BUILDING, "errors": ["butler CLI not installed"]}

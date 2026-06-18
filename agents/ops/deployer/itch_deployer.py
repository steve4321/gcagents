from __future__ import annotations

import asyncio
import os
from pathlib import Path

from loguru import logger

from agents.ops.deployer.base import PlatformAdapter
from orchestrator.state import CompanyState, PipelinePhase
from shared.config import load_config


class ItchAdapter(PlatformAdapter):
    platform_name = "itch.io"

    def is_configured(self) -> bool:
        config = load_config()
        return bool(config.butler_api_key and config.butler_username)

    async def deploy(
        self,
        build_path: str,
        project_name: str,
        title: str = "",
        **kwargs,
    ) -> dict:
        dist = self._validate_build(build_path)
        if not dist:
            return {"error": f"Invalid build for {self.platform_name}"}

        config = load_config()
        if not config.butler_api_key or not config.butler_username:
            logger.warning("itch.io credentials not configured, simulating deploy")
            return {
                "platform": self.platform_name,
                "url": f"https://{config.butler_username or 'placeholder'}.itch.io/{project_name}",
                "simulated": True,
            }

        slug = self._slug(title) if title else project_name
        channel = "html"

        logger.info(f"Deploying {slug} to itch.io...")

        try:
            env = {"BUTLER_API_KEY": config.butler_api_key}
            proc = await asyncio.create_subprocess_exec(
                "butler",
                "push",
                str(dist),
                f"{config.butler_username}/{slug}:{channel}",
                env={**os.environ, **env},
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
            except TimeoutError:
                proc.kill()
                await proc.communicate()
                logger.error("Deploy timed out")
                return {"error": "Deploy timeout"}

            if proc.returncode != 0:
                detail = (
                    stderr.decode(errors="replace") or stdout.decode(errors="replace") or ""
                ).strip()[:500]
                logger.error(f"Deploy failed: {detail}")
                return {"error": f"Deploy failed: {detail}"}

            itch_url = f"https://{config.butler_username}.itch.io/{slug}"
            logger.info(f"Deployed to: {itch_url}")
            return {"platform": self.platform_name, "url": itch_url}

        except FileNotFoundError:
            logger.error("butler CLI not found - install from https://itchio.itch.io/butler")
            return {"error": "butler CLI not installed"}


async def deploy_to_itch(state: CompanyState) -> dict:
    build_path = state.build_path
    if not build_path:
        return {"phase": PipelinePhase.IDLE, "errors": ["No build to deploy"]}

    adapter = ItchAdapter()
    result = await adapter.deploy(
        build_path=build_path,
        project_name=Path(state.game_code_path or "game").name,
        title=state.project_name or "",
    )

    if "error" in result:
        return {"phase": PipelinePhase.BUILDING, "errors": [result["error"]]}

    itch_url = result.get("url", "")
    return {"phase": PipelinePhase.OPERATING, "itch_url": itch_url}

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from loguru import logger

from agents.ops.deployer.base import PlatformAdapter
from shared.config import load_config


class CrazyGamesAdapter(PlatformAdapter):
    platform_name = "crazygames"

    def is_configured(self) -> bool:
        config = load_config()
        return bool(config.crazygames_api_key)

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
        if not config.crazygames_api_key:
            logger.warning("CrazyGames API key not configured, simulating deploy")
            return {
                "platform": self.platform_name,
                "url": f"https://www.crazygames.com/game/{self._slug(title or project_name)}",
                "simulated": True,
            }

        slug = self._slug(title or project_name)

        try:
            archive_path = await self._create_zip(dist, slug)
            result = self._upload_to_crazygames(archive_path, slug, config.crazygames_api_key)

            if result.get("success"):
                url = result.get("url", f"https://www.crazygames.com/game/{slug}")
                logger.info(f"Deployed to CrazyGames: {url}")
                return {"platform": self.platform_name, "url": url}
            else:
                logger.error(f"CrazyGames deploy failed: {result.get('error', 'unknown')}")
                return {"error": f"CrazyGames deploy failed: {result.get('error', 'unknown')}"}

        except Exception as e:
            logger.error(f"CrazyGames deploy error: {e}")
            return {"error": str(e)}

    async def _create_zip(self, dist: Path, slug: str) -> Path:
        import asyncio
        import tempfile

        zip_path = Path(tempfile.mkdtemp()) / f"{slug}.zip"
        proc = await asyncio.create_subprocess_exec(
            "zip", "-r", str(zip_path), ".",
            cwd=str(dist),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return zip_path

    def _upload_to_crazygames(self, archive_path: Path, slug: str, api_key: str) -> dict:
        url = "https://developer-api.crazygames.com/v2/games"
        req = urllib.request.Request(
            url,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps({"slug": slug, "zipUrl": str(archive_path)}).encode(),
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            return {"success": False, "error": str(e)}

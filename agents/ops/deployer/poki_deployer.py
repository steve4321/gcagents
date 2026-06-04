from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from loguru import logger

from agents.ops.deployer.base import PlatformAdapter
from shared.config import load_config


class PokiAdapter(PlatformAdapter):
    platform_name = "poki"

    def is_configured(self) -> bool:
        config = load_config()
        return bool(config.poki_api_key)

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
        if not config.poki_api_key:
            logger.warning("Poki API key not configured, simulating deploy")
            return {
                "platform": self.platform_name,
                "url": f"https://poki.com/en/g/{self._slug(title or project_name)}",
                "simulated": True,
            }

        slug = self._slug(title or project_name)

        try:
            result = self._submit_to_poki(dist, slug, config.poki_api_key)
            if result.get("success"):
                url = result.get("url", f"https://poki.com/en/g/{slug}")
                logger.info(f"Deployed to Poki: {url}")
                return {"platform": self.platform_name, "url": url}
            else:
                logger.error(f"Poki deploy failed: {result.get('error', 'unknown')}")
                return {"error": f"Poki deploy failed: {result.get('error', 'unknown')}"}
        except Exception as e:
            logger.error(f"Poki deploy error: {e}")
            return {"error": str(e)}

    def _submit_to_poki(self, dist: Path, slug: str, api_key: str) -> dict:
        url = "https://api.poki.com/v1/games"
        req = urllib.request.Request(
            url,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps({"gameSlug": slug, "buildPath": str(dist)}).encode(),
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            return {"success": False, "error": str(e)}

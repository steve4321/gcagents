from __future__ import annotations

import asyncio
from loguru import logger

from agents.ops.deployer.base import PlatformAdapter
from agents.ops.deployer.crazygames_deployer import CrazyGamesAdapter
from agents.ops.deployer.itch_deployer import ItchAdapter
from agents.ops.deployer.poki_deployer import PokiAdapter

_ADAPTERS: dict[str, type[PlatformAdapter]] = {
    "itch.io": ItchAdapter,
    "crazygames": CrazyGamesAdapter,
    "poki": PokiAdapter,
}


def get_adapter(platform: str) -> PlatformAdapter | None:
    cls = _ADAPTERS.get(platform)
    if cls:
        return cls()
    logger.warning(f"No adapter for platform: {platform}")
    return None


def configured_platforms() -> list[str]:
    result = []
    for name, cls in _ADAPTERS.items():
        adapter = cls()
        if adapter.is_configured():
            result.append(name)
    return result


async def deploy_to_all(
    build_path: str,
    project_name: str,
    title: str = "",
    target_platforms: list[str] | None = None,
) -> dict[str, dict]:
    if target_platforms is None:
        target_platforms = list(_ADAPTERS.keys())

    results: dict[str, dict] = {}
    tasks = []

    for platform in target_platforms:
        adapter = get_adapter(platform)
        if not adapter:
            results[platform] = {"error": f"No adapter for {platform}"}
            continue
        if not adapter.is_configured():
            results[platform] = {
                "platform": platform,
                "url": "",
                "simulated": True,
                "note": "credentials not configured",
            }
            continue
        tasks.append((platform, adapter))

    async def _run(platform: str, adapter: PlatformAdapter) -> tuple[str, dict]:
        try:
            return platform, await adapter.deploy(build_path, project_name, title)
        except Exception as e:
            logger.error(f"Deploy to {platform} failed: {e}")
            return platform, {"error": str(e)}

    if tasks:
        task_results = await asyncio.gather(*[_run(p, a) for p, a in tasks])
        for platform, result in task_results:
            results[platform] = result

    logger.info(f"Multi-platform deploy complete: {list(results.keys())}")
    return results

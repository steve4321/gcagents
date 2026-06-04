from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from loguru import logger


class PlatformAdapter(ABC):
    platform_name: str = ""

    @abstractmethod
    async def deploy(
        self,
        build_path: str,
        project_name: str,
        title: str = "",
        **kwargs,
    ) -> dict:
        ...

    def is_configured(self) -> bool:
        return True

    def _slug(self, title: str) -> str:
        import re
        slug = title.lower()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        return slug.strip("-")

    def _validate_build(self, build_path: str) -> Path | None:
        dist = Path(build_path)
        if not dist.exists():
            logger.error(f"Build path does not exist: {dist}")
            return None
        if not (dist / "index.html").exists():
            logger.error(f"No index.html in build: {dist}")
            return None
        return dist

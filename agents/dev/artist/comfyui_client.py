from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from loguru import logger


class ComfyUIClient:
    def __init__(self, base_url: str = "http://localhost:8188"):
        self.base_url = base_url.rstrip("/")

    async def queue_prompt(self, workflow: dict) -> str:
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.post(f"{self.base_url}/prompt", json={"prompt": workflow})
                resp.raise_for_status()
                data = resp.json()
                prompt_id = data["prompt_id"]
                logger.info(f"Queued ComfyUI prompt: {prompt_id}")
                return prompt_id
            except httpx.ConnectError:
                logger.error(f"Cannot connect to ComfyUI at {self.base_url}")
                raise
            except httpx.TimeoutException:
                logger.error("ComfyUI prompt queue timed out")
                raise

    async def wait_for_completion(self, prompt_id: str, timeout: int = 120) -> dict:
        start = asyncio.get_event_loop().time()
        async with httpx.AsyncClient(timeout=10) as client:
            while True:
                elapsed = asyncio.get_event_loop().time() - start
                if elapsed > timeout:
                    raise TimeoutError(f"ComfyUI prompt {prompt_id} timed out after {timeout}s")

                try:
                    resp = await client.get(f"{self.base_url}/history/{prompt_id}")
                    if resp.status_code == 200:
                        data = resp.json()
                        if prompt_id in data:
                            history = data[prompt_id]
                            if history.get("status", {}).get("completed"):
                                logger.info(f"ComfyUI prompt completed: {prompt_id}")
                                return history
                except httpx.ConnectError:
                    logger.warning("ComfyUI connection lost while polling, retrying...")
                except httpx.TimeoutException:
                    logger.warning("ComfyUI poll timed out, retrying...")

                await asyncio.sleep(1)

    async def get_output_images(self, prompt_id: str, output_dir: Path | None = None) -> list[Path]:
        history = await self.wait_for_completion(prompt_id)
        outputs = history.get("outputs", {})
        images: list[Path] = []

        async with httpx.AsyncClient(timeout=30) as client:
            for node_output in outputs.values():
                for img_data in node_output.get("images", []):
                    filename = img_data["filename"]
                    subfolder = img_data.get("subfolder", "")
                    resp = await client.get(
                        f"{self.base_url}/view",
                        params={"filename": filename, "subfolder": subfolder, "type": "output"},
                    )
                    resp.raise_for_status()

                    if output_dir:
                        output_dir.mkdir(parents=True, exist_ok=True)
                        img_path = output_dir / filename
                        img_path.write_bytes(resp.content)
                        images.append(img_path)
                        logger.debug(f"Downloaded image: {img_path}")
                    else:
                        images.append(Path(filename))

        return images

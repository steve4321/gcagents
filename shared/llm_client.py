from __future__ import annotations

import asyncio

from loguru import logger
from openai import APIStatusError, AsyncOpenAI

from shared.config import load_config

MODEL_PRICING: dict[str, dict[str, float]] = {
    "deepseek-coder": {"input_per_1k": 0.0015, "output_per_1k": 0.002},
    "deepseek-chat": {"input_per_1k": 0.0015, "output_per_1k": 0.002},
    "glm-4-flash": {"input_per_1k": 0.0, "output_per_1k": 0.0},
}

_MODEL_PROVIDER: dict[str, dict[str, str]] = {
    "deepseek-coder": {"key_attr": "deepseek_api_key", "base_url": "https://api.deepseek.com"},
    "deepseek-chat": {"key_attr": "deepseek_api_key", "base_url": "https://api.deepseek.com"},
    "glm-4-flash": {"key_attr": "zhipu_api_key", "base_url": "https://open.bigmodel.cn/api/paas/v4"},
}

_RETRYABLE_CODES = {429, 500, 502, 503}


class LLMClient:
    """Centralized LLM client with token tracking and cost logging."""

    def __init__(self) -> None:
        self._config = load_config()
        self._clients: dict[str, AsyncOpenAI] = {}

    def _get_client(self, model: str) -> AsyncOpenAI:
        if model in self._clients:
            return self._clients[model]
        provider = _MODEL_PROVIDER.get(model)
        if not provider:
            raise ValueError(f"Unknown model: {model}")
        api_key = getattr(self._config, provider["key_attr"])
        if not api_key:
            raise ValueError(
                f"No API key for model {model} (missing {provider['key_attr']})"
            )
        client = AsyncOpenAI(api_key=api_key, base_url=provider["base_url"])
        self._clients[model] = client
        return client

    async def chat_completion(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        agent_name: str = "",
        project_name: str = "",
    ) -> tuple[str, dict]:
        """Call LLM with retry/backoff, token tracking, and cost logging.

        Returns (response_text, usage_info) where usage_info has tokens + cost.
        """
        client = self._get_client(model)

        response = None
        for attempt in range(3):
            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                break
            except APIStatusError as e:
                if e.status_code not in _RETRYABLE_CODES or attempt == 2:
                    raise
                delay = min(2 ** attempt, 30)
                logger.warning(
                    f"LLM retry {attempt + 1}/3 for model={model}: "
                    f"status={e.status_code}, waiting {delay}s"
                )
                await asyncio.sleep(delay)

        assert response is not None  # guaranteed by retry logic

        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        total_tokens = usage.total_tokens if usage else 0

        pricing = MODEL_PRICING.get(model, {"input_per_1k": 0.0, "output_per_1k": 0.0})
        cost_usd = (
            prompt_tokens / 1000 * pricing["input_per_1k"]
            + completion_tokens / 1000 * pricing["output_per_1k"]
        )

        usage_info: dict = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost_usd": cost_usd,
        }

        try:
            from orchestrator.persistence import log_api_usage

            await log_api_usage(
                model=model,
                agent_name=agent_name,
                project_name=project_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                estimated_cost_usd=cost_usd,
            )
        except Exception as e:
            logger.warning(f"Failed to log API usage: {e}")

        response_text = response.choices[0].message.content or ""

        logger.info(
            f"LLM call: model={model}, agent={agent_name}, "
            f"tokens={total_tokens}, cost=${cost_usd:.6f}"
        )

        return response_text, usage_info


llm = LLMClient()

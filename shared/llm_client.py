from __future__ import annotations

import asyncio

from loguru import logger
from openai import APIStatusError, AsyncOpenAI

from shared.config import load_config
from shared.constants import LLM_BACKOFF_MAX_SECONDS, LLM_MAX_RETRIES
from shared.exceptions import LLMApiError

MODEL_PRICING: dict[str, dict[str, float]] = {
    "deepseek-v4-flash": {"input_per_1k": 0.00014, "output_per_1k": 0.00028},
    "deepseek-v4-pro": {"input_per_1k": 0.00218, "output_per_1k": 0.00872},
    "deepseek-coder": {"input_per_1k": 0.0015, "output_per_1k": 0.002},
    "MiniMax-M3": {"input_per_1k": 0.00030, "output_per_1k": 0.00120},
    "MiniMax-M2.7": {"input_per_1k": 0.00030, "output_per_1k": 0.00120},
    "MiniMax-M2.1": {"input_per_1k": 0.00030, "output_per_1k": 0.00120},
}

_MODEL_PROVIDER: dict[str, dict[str, str]] = {
    "deepseek-v4-flash": {"key_attr": "deepseek_api_key", "base_url": "https://api.deepseek.com"},
    "deepseek-v4-pro": {"key_attr": "deepseek_api_key", "base_url": "https://api.deepseek.com"},
    "deepseek-coder": {"key_attr": "deepseek_api_key", "base_url": "https://api.deepseek.com"},
    "MiniMax-M3": {"key_attr": "minimax_api_key", "base_url": "https://api.minimaxi.com/v1"},
    "MiniMax-M2.7": {"key_attr": "minimax_api_key", "base_url": "https://api.minimaxi.com/v1"},
    "MiniMax-M2.1": {"key_attr": "minimax_api_key", "base_url": "https://api.minimaxi.com/v1"},
}

_MODEL_FALLBACKS: dict[str, list[str]] = {
    "deepseek-v4-pro": ["deepseek-v4-flash"],
    "deepseek-coder": ["deepseek-v4-flash"],
    "MiniMax-M3": ["MiniMax-M2.7", "MiniMax-M2.1"],
    "MiniMax-M2.7": ["MiniMax-M2.1"],
    "deepseek-v4-flash": [],
    "MiniMax-M2.1": [],
}

_RETRYABLE_CODES = {429, 500, 502, 503}


class LLMClient:
    """Centralized LLM client with token tracking and cost logging."""

    def __init__(self) -> None:
        self._config = None
        self._clients: dict[str, AsyncOpenAI] = {}

    def _ensure_config(self) -> None:
        if self._config is None:
            self._config = load_config()

    def _get_client(self, model: str) -> AsyncOpenAI:
        self._ensure_config()
        if model in self._clients:
            return self._clients[model]
        provider = _MODEL_PROVIDER.get(model)
        if not provider:
            raise ValueError(f"Unknown model: {model}")
        api_key = getattr(self._config, provider["key_attr"])
        if not api_key:
            raise ValueError(f"No API key for model {model} (missing {provider['key_attr']})")
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
        """Call LLM with retry/backoff, token tracking, cost logging, and fallback chain.

        Returns (response_text, usage_info) where usage_info has tokens + cost.
        """
        tried: list[str] = []
        current = model
        while True:
            tried.append(current)
            try:
                return await self._call_single(
                    current, messages, max_tokens, temperature, agent_name, project_name,
                )
            except LLMApiError as e:
                fallbacks = _MODEL_FALLBACKS.get(current, [])
                remaining = [f for f in fallbacks if f not in tried]
                if not remaining:
                    raise
                logger.warning(
                    f"LLM model {current} failed ({e.status_code}), "
                    f"falling back to {remaining[0]}"
                )
                current = remaining[0]

    async def _call_single(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        agent_name: str,
        project_name: str,
    ) -> tuple[str, dict]:
        client = self._get_client(model)

        pricing = MODEL_PRICING.get(model, {"input_per_1k": 0.0, "output_per_1k": 0.0})
        estimated_input = sum(len(str(m).split()) for m in messages)
        estimated_cost = (
            estimated_input / 1000 * pricing["input_per_1k"]
            + max_tokens / 1000 * pricing["output_per_1k"]
        )

        budget_exceeded = False
        try:
            from orchestrator.persistence import check_budget_available

            budget_ok = await check_budget_available("monthly", estimated_cost)
            if not budget_ok:
                budget_exceeded = True
                logger.warning(
                    f"Budget exceeded for monthly (est ${estimated_cost:.6f}), "
                    f"proceeding anyway (soft enforcement)"
                )
        except Exception as e:
            logger.warning(f"Budget check failed, skipping enforcement: {e}")

        response = None
        for attempt in range(LLM_MAX_RETRIES):
            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                break
            except APIStatusError as e:
                if e.status_code not in _RETRYABLE_CODES or attempt == LLM_MAX_RETRIES - 1:
                    raise LLMApiError(model=model, status_code=e.status_code, detail=str(e)) from e
                delay = min(2**attempt, LLM_BACKOFF_MAX_SECONDS)
                logger.warning(
                    f"LLM retry {attempt + 1}/3 for model={model}: "
                    f"status={e.status_code}, waiting {delay}s"
                )
                await asyncio.sleep(delay)

        if response is None:
            raise RuntimeError(f"LLM call failed for model={model} after retries")

        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        total_tokens = usage.total_tokens if usage else 0

        cost_usd = (
            prompt_tokens / 1000 * pricing["input_per_1k"]
            + completion_tokens / 1000 * pricing["output_per_1k"]
        )

        usage_info: dict = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost_usd": cost_usd,
            "budget_exceeded": budget_exceeded,
        }

        try:
            from orchestrator.persistence import log_api_usage, record_spend

            await log_api_usage(
                model=model,
                agent_name=agent_name,
                project_name=project_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                estimated_cost_usd=cost_usd,
            )

            if cost_usd > 0:
                await record_spend("monthly", cost_usd)
                if project_name:
                    await record_spend(project_name, cost_usd)
        except (RuntimeError, ValueError, OSError) as e:
            logger.warning(f"Failed to log API usage: {e}")

        response_text = response.choices[0].message.content or ""

        logger.info(
            f"LLM call: model={model}, agent={agent_name}, "
            f"tokens={total_tokens}, cost=${cost_usd:.6f}"
        )

        return response_text, usage_info


llm = LLMClient()

"""Tests for shared/llm_client.py — cost estimation and retry behavior.

All tests mock the OpenAI client — NO real network calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openai import APIStatusError

from shared.llm_client import LLMClient, MODEL_PRICING


def test_estimate_cost_deepseek():
    pricing = MODEL_PRICING["deepseek-coder"]
    prompt_tokens = 10_000
    completion_tokens = 5_000
    cost = (
        prompt_tokens / 1000 * pricing["input_per_1k"]
        + completion_tokens / 1000 * pricing["output_per_1k"]
    )
    assert cost == pytest.approx(0.025, abs=1e-6)


def test_estimate_cost_zhipu():
    pricing = MODEL_PRICING["glm-4-flash"]
    assert pricing["input_per_1k"] == 0.0
    assert pricing["output_per_1k"] == 0.0


@pytest.mark.asyncio
async def test_client_retries_on_429(tmp_db):
    """On HTTP 429 the client must retry up to 3 times before giving up."""
    await __import__("orchestrator.persistence", fromlist=["ensure_tables"]).ensure_tables()

    mock_response_429 = MagicMock()
    mock_response_429.status_code = 429
    mock_response_429.headers = {}
    mock_response_429.body = MagicMock()

    error_429 = APIStatusError(
        message="rate limited",
        response=mock_response_429,
        body=None,
    )

    mock_success = MagicMock()
    mock_success.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    mock_choice = MagicMock()
    mock_choice.message.content = "hello"
    mock_success.choices = [mock_choice]

    mock_create = AsyncMock(side_effect=[error_429, error_429, mock_success])
    mock_completions = MagicMock(create=mock_create)
    mock_chat = MagicMock(completions=mock_completions)
    mock_client_instance = MagicMock(chat=mock_chat)

    with patch.object(LLMClient, "_get_client", return_value=mock_client_instance), \
         patch("shared.llm_client.load_config"), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        client = LLMClient()
        client._config = MagicMock()
        text_result, usage = await client.chat_completion(
            model="deepseek-coder",
            messages=[{"role": "user", "content": "test"}],
        )

        assert mock_create.call_count == 3
        assert text_result == "hello"
        assert usage["total_tokens"] == 15

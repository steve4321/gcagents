"""Context window manager — 4-layer progressive compression for LLM conversations.

Manages the context window budget to prevent overflow while preserving critical information.
Inspired by Claude Code's 5-layer compaction strategy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from loguru import logger


class CompactionLevel(str, Enum):
    """Progressive compaction levels."""

    NONE = "none"
    SNIP = "snip"  # Layer 1: Clear old tool results
    SEGMENT = "segment"  # Layer 2: Summarize conversation segments
    FULL = "full"  # Layer 3: Full conversation compaction


@dataclass
class ContextBudget:
    """Token budget configuration."""

    max_tokens: int = 128_000
    soft_threshold: float = 0.70  # Trigger background compaction
    hard_threshold: float = 0.85  # Trigger immediate compaction
    critical_threshold: float = 0.95  # Trigger emergency compaction
    reserved_tokens: int = 4_000  # Reserved for system prompt + response

    @property
    def available_tokens(self) -> int:
        return self.max_tokens - self.reserved_tokens

    def usage_ratio(self, token_count: int) -> float:
        return token_count / self.available_tokens if self.available_tokens > 0 else 1.0

    def should_compact(self, token_count: int) -> CompactionLevel:
        """Determine compaction level based on current token usage."""
        ratio = self.usage_ratio(token_count)
        if ratio >= self.critical_threshold:
            return CompactionLevel.FULL
        if ratio >= self.hard_threshold:
            return CompactionLevel.SEGMENT
        if ratio >= self.soft_threshold:
            return CompactionLevel.SNIP
        return CompactionLevel.NONE


@dataclass
class ConversationSummary:
    """Structured summary of a conversation segment."""

    segment_start: int  # message index
    segment_end: int  # message index
    decisions_made: list[str] = field(default_factory=list)
    key_findings: list[str] = field(default_factory=list)
    tasks_completed: list[str] = field(default_factory=list)
    pending_items: list[str] = field(default_factory=list)
    errors_encountered: list[str] = field(default_factory=list)
    token_count_approx: int = 0
    summary_text: str = ""


class ContextManager:
    """4-layer progressive context management for LLM conversations.

    Layer 0: Tool result budget — estimate token cost before execution
    Layer 1: Snip compression — clear old tool results
    Layer 2: Segment compression — summarize conversation segments
    Layer 3: Full compaction — summarize entire conversation
    """

    def __init__(self, budget: ContextBudget | None = None) -> None:
        self.budget = budget or ContextBudget()
        self._summaries: list[ConversationSummary] = []
        self._current_token_count: int = 0

    def estimate_token_count(self, text: str) -> int:
        """Rough token count estimation (~4 chars per token for English, ~2 for Chinese)."""
        if not text:
            return 0
        # Simple heuristic: average between char/4 and char/2
        # This is a rough estimate — actual tokenizer varies by model
        chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        other_chars = len(text) - chinese_chars
        return int(chinese_chars / 1.5 + other_chars / 4) + 1

    def estimate_messages_tokens(self, messages: list[dict]) -> int:
        """Estimate total token count for a list of messages."""
        total = 0
        for msg in messages:
            # Message overhead (role, formatting)
            total += 4
            content = msg.get("content", "")
            if isinstance(content, str):
                total += self.estimate_token_count(content)
            elif isinstance(content, list):
                # Multimodal content
                for part in content:
                    if isinstance(part, dict):
                        text = part.get("text", "")
                        total += self.estimate_token_count(text)
            # Tool calls/results have overhead
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    total += self.estimate_token_count(
                        json.dumps(tc.get("function", {}).get("arguments", ""))
                    )
                    total += 10  # overhead per tool call
            if msg.get("tool_result") or msg.get("name"):
                result_content = msg.get("content", "")
                if isinstance(result_content, str):
                    total += self.estimate_token_count(result_content)
                total += 10
        return total

    # ── Layer 0: Tool Result Budget ──────────────────────────────────────

    def estimate_tool_cost(
        self, tool_name: str, args: dict, estimated_output_chars: int = 0
    ) -> int:
        """Estimate token cost of a tool call before execution.

        Returns estimated total tokens (input + output).
        """
        input_tokens = self.estimate_token_count(json.dumps(args)) + 20
        output_tokens = (
            self.estimate_token_count(" " * estimated_output_chars)
            if estimated_output_chars
            else 500
        )
        return input_tokens + output_tokens

    def can_execute_tool(
        self, tool_name: str, args: dict, current_tokens: int, estimated_output_chars: int = 0
    ) -> bool:
        """Check if there's enough context budget for a tool call."""
        cost = self.estimate_tool_cost(tool_name, args, estimated_output_chars)
        return (current_tokens + cost) < self.budget.available_tokens

    # ── Layer 1: Snip Compression ────────────────────────────────────────

    def snip_old_results(self, messages: list[dict], keep_last_n: int = 3) -> list[dict]:
        """Clear old tool results to free context space.

        Replaces old tool result content with a compact placeholder
        while preserving the message structure.
        """
        snipped = []
        tool_result_indices = [
            i for i, m in enumerate(messages) if m.get("role") == "tool" or m.get("tool_result")
        ]

        # Keep the last N tool results intact, snip the rest
        snip_indices = (
            set(tool_result_indices[:-keep_last_n])
            if len(tool_result_indices) > keep_last_n
            else set()
        )

        for i, msg in enumerate(messages):
            if i in snip_indices:
                snipped_msg = dict(msg)
                original_len = len(str(msg.get("content", "")))
                snipped_msg["content"] = f"[旧工具结果已清除 — 原始 {original_len} 字符]"
                snipped.append(snipped_msg)
            else:
                snipped.append(msg)

        snipped_count = len(snip_indices)
        if snipped_count:
            logger.info(f"Context: snipped {snipped_count} old tool results")

        return snipped

    # ── Layer 2: Segment Compression ─────────────────────────────────────

    async def summarize_segment(
        self, messages: list[dict], llm_client: Any = None
    ) -> ConversationSummary:
        """Generate a structured summary of a conversation segment.

        If llm_client is provided, uses it for summarization.
        Otherwise, uses rule-based extraction.
        """
        # Extract key information from messages without LLM
        decisions = []
        findings = []
        tasks = []
        pending = []
        errors = []

        for msg in messages:
            content = str(msg.get("content", ""))

            # Extract decisions
            if "approved" in content.lower() or "rejected" in content.lower():
                if len(content) < 200:
                    decisions.append(content[:100])

            # Extract errors
            if "error" in content.lower() or "failed" in content.lower():
                errors.append(content[:100])

            # Extract task completions
            if "completed" in content.lower() or "done" in content.lower():
                tasks.append(content[:100])

            # Extract pending items
            if "pending" in content.lower() or "waiting" in content.lower():
                pending.append(content[:100])

        # If LLM client available, generate proper summary
        summary_text = ""
        if llm_client is not None:
            try:
                conversation_text = "\n".join(
                    f"{m.get('role', '?')}: {str(m.get('content', ''))[:200]}"
                    for m in messages[-10:]
                )
                response, _ = await llm_client.chat_completion(
                    model="MiniMax-M3",
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Summarize this conversation segment in 2-3 sentences. "
                                "Focus on: decisions made, key findings, pending work. "
                                "Respond in Chinese."
                            ),
                        },
                        {"role": "user", "content": conversation_text[:2000]},
                    ],
                    max_tokens=200,
                    temperature=0.3,
                    agent_name="context_manager",
                )
                summary_text = response
            except Exception as e:
                logger.warning(f"Context: LLM summarization failed: {e}")

        return ConversationSummary(
            segment_start=0,
            segment_end=len(messages) - 1,
            decisions_made=decisions[:5],
            key_findings=findings[:5],
            tasks_completed=tasks[:5],
            pending_items=pending[:5],
            errors_encountered=errors[:5],
            token_count_approx=self.estimate_messages_tokens(messages),
            summary_text=summary_text,
        )

    # ── Layer 3: Full Compaction ─────────────────────────────────────────

    async def compact_full(self, messages: list[dict], llm_client: Any = None) -> list[dict]:
        """Full conversation compaction — replace history with structured summary.

        Keeps: system prompt + recent messages + summary of everything else.
        """
        if len(messages) <= 4:
            return messages

        # Keep system prompt (first message)
        system_msgs = [m for m in messages if m.get("role") == "system"]
        # Keep last 2 messages for continuity
        recent = messages[-2:]
        # Summarize everything in between
        middle = messages[len(system_msgs) : -2]

        if not middle:
            return messages

        summary = await self.summarize_segment(middle, llm_client)

        # Create summary message
        summary_parts = []
        if summary.summary_text:
            summary_parts.append(f"对话摘要: {summary.summary_text}")
        if summary.decisions_made:
            summary_parts.append(f"已做决策: {'; '.join(summary.decisions_made[:3])}")
        if summary.key_findings:
            summary_parts.append(f"关键发现: {'; '.join(summary.key_findings[:3])}")
        if summary.pending_items:
            summary_parts.append(f"待处理: {'; '.join(summary.pending_items[:3])}")
        if summary.errors_encountered:
            summary_parts.append(f"遇到错误: {'; '.join(summary.errors_encountered[:3])}")

        summary_content = "\n".join(summary_parts) if summary_parts else "[对话历史已压缩]"

        compacted = [
            *system_msgs,
            {"role": "assistant", "content": f"📝 **上下文压缩摘要**\n{summary_content}"},
            *recent,
        ]

        logger.info(
            f"Context: full compaction {len(messages)} → {len(compacted)} messages "
            f"(saved ~{summary.token_count_approx} tokens)"
        )

        return compacted

    # ── Main Entry Point ─────────────────────────────────────────────────

    async def manage_context(
        self,
        messages: list[dict],
        current_tokens: int | None = None,
        llm_client: Any = None,
    ) -> list[dict]:
        """Apply appropriate compression level based on context usage.

        This is the main entry point. Call before each LLM call.
        """
        if current_tokens is None:
            current_tokens = self.estimate_messages_tokens(messages)

        self._current_token_count = current_tokens
        level = self.budget.should_compact(current_tokens)

        if level == CompactionLevel.NONE:
            return messages

        logger.info(
            f"Context: applying {level.value} compaction (usage: {self.budget.usage_ratio(current_tokens):.1%})"
        )

        if level == CompactionLevel.SNIP:
            return self.snip_old_results(messages)

        elif level == CompactionLevel.SEGMENT:
            # First snip, then summarize if still over budget
            snipped = self.snip_old_results(messages)
            new_count = self.estimate_messages_tokens(snipped)
            if self.budget.should_compact(new_count) != CompactionLevel.NONE:
                return await self.compact_full(snipped, llm_client)
            return snipped

        elif level == CompactionLevel.FULL:
            return await self.compact_full(messages, llm_client)

        return messages

    def get_status(self) -> dict:
        """Get current context status."""
        return {
            "current_tokens": self._current_token_count,
            "max_tokens": self.budget.max_tokens,
            "usage_ratio": f"{self.budget.usage_ratio(self._current_token_count):.1%}",
            "compaction_level": self.budget.should_compact(self._current_token_count).value,
            "summaries_count": len(self._summaries),
        }

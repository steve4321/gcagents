"""Tool registry — centralized tool management with self-registration."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolSpec:
    """Specification for a registered tool."""

    name: str
    description: str
    # file_ops | code_gen | art | deploy | analysis | memory | verification
    category: str
    handler: Callable[..., Coroutine[Any, Any, dict]]
    input_schema: dict[str, Any] = field(default_factory=dict)
    # 1=read, 2=write, 3=execute, 4=admin
    permission_level: int = 1
    is_concurrency_safe: bool = True
    # low | medium | high
    cost_estimate: str = "low"
    # Which agent roles can use this (empty = all)
    agent_roles: list[str] = field(default_factory=list)


class ToolRegistry:
    """Global tool registry — tools self-register on import."""

    _tools: dict[str, ToolSpec] = {}

    @classmethod
    def register(
        cls,
        name: str,
        category: str,
        description: str = "",
        permission_level: int = 1,
        is_concurrency_safe: bool = True,
        cost_estimate: str = "low",
        agent_roles: list[str] | None = None,
        input_schema: dict | None = None,
    ) -> Callable:
        """Decorator to register a function as a tool.

        Usage::

            @ToolRegistry.register(
                "read_file", category="file_ops", permission_level=1
            )
            async def read_file(path: str, ...) -> dict:
                ...
        """

        def decorator(
            func: Callable[..., Coroutine[Any, Any, dict]],
        ) -> Callable[..., Coroutine[Any, Any, dict]]:
            cls._tools[name] = ToolSpec(
                name=name,
                description=description or func.__doc__ or "",
                category=category,
                handler=func,
                input_schema=input_schema or {},
                permission_level=permission_level,
                is_concurrency_safe=is_concurrency_safe,
                cost_estimate=cost_estimate,
                agent_roles=agent_roles or [],
            )
            return func

        return decorator

    @classmethod
    def get_tool(cls, name: str) -> ToolSpec | None:
        """Get a tool spec by name."""
        return cls._tools.get(name)

    @classmethod
    def get_all_tools(cls) -> dict[str, ToolSpec]:
        """Get all registered tools."""
        return dict(cls._tools)

    @classmethod
    def get_tools_by_category(cls, category: str) -> list[ToolSpec]:
        """Get all tools in a given category."""
        return [t for t in cls._tools.values() if t.category == category]

    @classmethod
    def get_tools_for_agent(
        cls,
        agent_role: str,
        declared_tools: list[str] | None = None,
    ) -> list[ToolSpec]:
        """Get tools available to an agent.

        If declared_tools is provided, returns only those tools.
        Otherwise returns all tools where agent_role is in
        agent_roles OR agent_roles is empty (available to all).
        """
        if declared_tools:
            return [cls._tools[t] for t in declared_tools if t in cls._tools]

        return [t for t in cls._tools.values() if not t.agent_roles or agent_role in t.agent_roles]

    @classmethod
    def get_concurrent_safe_tools(cls, tool_names: list[str]) -> list[ToolSpec]:
        """Filter to only concurrency-safe tools from a list."""
        return [
            cls._tools[t]
            for t in tool_names
            if t in cls._tools and cls._tools[t].is_concurrency_safe
        ]

    @classmethod
    def tool_exists(cls, name: str) -> bool:
        return name in cls._tools

    @classmethod
    def count(cls) -> int:
        return len(cls._tools)

    @classmethod
    def list_tool_names(cls) -> list[str]:
        return sorted(cls._tools.keys())

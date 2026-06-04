"""File operation tools — reading, writing, searching files."""

from __future__ import annotations

from shared.tools import ToolRegistry  # noqa: F401


# Tools will be migrated from agents/dev/programmer/agent.py and related modules.
# Example:
# @ToolRegistry.register("read_file", category="file_ops", permission_level=1)
# async def read_file(path: str, offset: int = 0, limit: int = 2000) -> dict:
#     """Read content from a file."""
#     ...

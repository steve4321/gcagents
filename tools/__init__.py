"""GCAgents tool implementations.

Tool modules are imported here to trigger self-registration via ToolRegistry.register().
Each tool file should use the @ToolRegistry.register() decorator.

Planned tool categories:
    - file_ops: File reading, writing, glob, grep
    - code_gen: Code generation, editing
    - art: ComfyUI art generation
    - music: Music generation
    - analysis: Market analysis, opportunity scoring
    - deploy: itch.io deployment
    - verification: Build verification, QA checks
    - memory: Memory store/retrieve operations

Tools are currently being migrated from agent modules.
Import tool modules here as they are created:
    from tools.file_ops import *  # noqa: F401,F403
"""

# Tool registration will happen as tools are migrated from agent modules
# into this package. For now, the registry is populated on-demand.

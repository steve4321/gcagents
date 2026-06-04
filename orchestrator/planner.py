"""DAG-based execution planner with wave-based parallel execution.

Plans are versioned and immutable — each modification creates a new version.
Execution proceeds in waves: tasks within a wave run in parallel,
waves execute sequentially to respect dependencies.

Inspired by Graph Harness (arxiv 2604.11378) and PIVOT frameworks.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from loguru import logger


class PlanNodeStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"  # All dependencies completed
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class RecoveryLevel(str, Enum):
    """Three-level recovery protocol."""

    RETRY = "retry"  # Level 1: Transient error, just retry
    STRATEGY_CHANGE = "strategy"  # Level 2: Change approach
    REPLAN = "replan"  # Level 3: Full replan needed


@dataclass
class PlanNode:
    """A single node in the execution plan DAG."""

    node_id: str
    task_type: str  # e.g., "market_scan", "design_game", "develop"
    agent_role: str  # e.g., "scanner", "designer", "programmer"
    dependencies: list[str] = field(default_factory=list)  # node_ids
    params: dict = field(default_factory=dict)
    status: PlanNodeStatus = PlanNodeStatus.PENDING
    result: dict | None = None
    error: str | None = None
    retry_count: int = 0
    max_retries: int = 2

    @staticmethod
    def new(
        task_type: str,
        agent_role: str,
        dependencies: list[str] | None = None,
        params: dict | None = None,
        node_id: str | None = None,
    ) -> PlanNode:
        return PlanNode(
            node_id=node_id or str(uuid.uuid4())[:8],
            task_type=task_type,
            agent_role=agent_role,
            dependencies=dependencies or [],
            params=params or {},
        )

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "task_type": self.task_type,
            "agent_role": self.agent_role,
            "dependencies": self.dependencies,
            "status": self.status.value,
            "retry_count": self.retry_count,
        }


@dataclass
class ExecutionPlan:
    """Immutable execution plan — versioned DAG of tasks.

    Once created, the plan structure (nodes and edges) should not change.
    Only node statuses are mutable. For structural changes, create a new version.
    """

    plan_id: str
    version: int
    project_id: str
    goal: str  # High-level description of what this plan achieves
    nodes: list[PlanNode] = field(default_factory=list)
    created_at: str = ""
    parent_plan_id: str | None = None  # For replan tracking

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()

    @staticmethod
    def new(
        project_id: str,
        goal: str,
        nodes: list[PlanNode] | None = None,
        plan_id: str | None = None,
    ) -> ExecutionPlan:
        return ExecutionPlan(
            plan_id=plan_id or str(uuid.uuid4())[:12],
            version=1,
            project_id=project_id,
            goal=goal,
            nodes=nodes or [],
        )

    def get_node(self, node_id: str) -> PlanNode | None:
        for n in self.nodes:
            if n.node_id == node_id:
                return n
        return None

    def get_ready_nodes(self) -> list[PlanNode]:
        """Return all pending nodes whose dependencies are done."""
        done_ids = {n.node_id for n in self.nodes if n.status == PlanNodeStatus.DONE}
        return [
            n
            for n in self.nodes
            if n.status == PlanNodeStatus.PENDING and all(dep in done_ids for dep in n.dependencies)
        ]

    def get_running_nodes(self) -> list[PlanNode]:
        return [n for n in self.nodes if n.status == PlanNodeStatus.RUNNING]

    def get_failed_nodes(self) -> list[PlanNode]:
        return [n for n in self.nodes if n.status == PlanNodeStatus.FAILED]

    def is_complete(self) -> bool:
        """Check if all nodes are done (or skipped)."""
        terminal = {PlanNodeStatus.DONE, PlanNodeStatus.SKIPPED}
        return all(n.status in terminal for n in self.nodes)

    def progress(self) -> float:
        """Return completion percentage."""
        if not self.nodes:
            return 0.0
        done = sum(
            1 for n in self.nodes if n.status in (PlanNodeStatus.DONE, PlanNodeStatus.SKIPPED)
        )
        return done / len(self.nodes)

    def get_waves(self) -> list[list[PlanNode]]:
        """Compute execution waves via topological sort.

        Tasks in the same wave can run in parallel.
        Waves execute sequentially.
        """
        waves: list[list[PlanNode]] = []
        completed = set()
        remaining = [n for n in self.nodes if n.status == PlanNodeStatus.PENDING]

        while remaining:
            # Find nodes whose dependencies are all in completed set
            wave = [n for n in remaining if all(dep in completed for dep in n.dependencies)]
            if not wave:
                # Circular dependency or deadlock
                logger.warning(
                    f"Plan {self.plan_id}: cannot compute next wave, {len(remaining)} nodes stuck"
                )
                break
            waves.append(wave)
            for n in wave:
                completed.add(n.node_id)
            remaining = [n for n in remaining if n not in wave]

        return waves

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "version": self.version,
            "project_id": self.project_id,
            "goal": self.goal,
            "progress": f"{self.progress():.0%}",
            "is_complete": self.is_complete(),
            "nodes": [n.to_dict() for n in self.nodes],
            "waves": len(self.get_waves()),
        }


class Planner:
    """DAG planning engine — creates and manages execution plans."""

    # ── Pre-built plan templates ─────────────────────────────────────────

    @staticmethod
    def plan_full_game(
        project_id: str, project_name: str, genre: str, gdd: dict | None = None
    ) -> ExecutionPlan:
        """Create a full game development plan.

        DAG structure:
            scan → design → [art || music] → develop → qa → build → deploy

        art and music can run in parallel.
        """
        scan = PlanNode.new("market_scan", "scanner", params={"project_name": project_name})
        design = PlanNode.new(
            "design_game",
            "designer",
            dependencies=[scan.node_id],
            params={"project_name": project_name, "genre": genre},
        )
        art = PlanNode.new(
            "art_gen",
            "artist",
            dependencies=[design.node_id],
            params={"project_name": project_name},
        )
        music = PlanNode.new(
            "generate_music",
            "musician",
            dependencies=[design.node_id],
            params={"project_name": project_name},
        )
        develop = PlanNode.new(
            "develop",
            "programmer",
            dependencies=[art.node_id, music.node_id],
            params={"project_name": project_name, "genre": genre},
        )
        qa = PlanNode.new(
            "qa", "qa_agent", dependencies=[develop.node_id], params={"project_name": project_name}
        )
        build = PlanNode.new(
            "build", "builder", dependencies=[qa.node_id], params={"project_name": project_name}
        )
        deploy = PlanNode.new(
            "deploy",
            "deployer",
            dependencies=[build.node_id],
            params={"project_name": project_name},
        )

        return ExecutionPlan.new(
            project_id=project_id,
            goal=f"Full game development: {project_name} ({genre})",
            nodes=[scan, design, art, music, develop, qa, build, deploy],
        )

    @staticmethod
    def plan_prototype(project_id: str, project_name: str, genre: str) -> ExecutionPlan:
        """Create a quick prototype plan (skip art and music).

        scan → design → develop_simple → qa → build
        """
        design = PlanNode.new(
            "design_game", "designer", params={"project_name": project_name, "genre": genre}
        )
        develop = PlanNode.new(
            "develop_simple",
            "programmer",
            dependencies=[design.node_id],
            params={"project_name": project_name, "genre": genre, "simplified": True},
        )
        qa = PlanNode.new(
            "qa", "qa_agent", dependencies=[develop.node_id], params={"project_name": project_name}
        )
        build = PlanNode.new(
            "build", "builder", dependencies=[qa.node_id], params={"project_name": project_name}
        )

        return ExecutionPlan.new(
            project_id=project_id,
            goal=f"Quick prototype: {project_name} ({genre})",
            nodes=[design, develop, qa, build],
        )

    @staticmethod
    def plan_market_scan() -> ExecutionPlan:
        """Simple plan for periodic market scanning."""
        scan = PlanNode.new("market_scan", "scanner")
        return ExecutionPlan.new(
            project_id="__system__",
            goal="Periodic market intelligence scan",
            nodes=[scan],
        )

    @staticmethod
    def plan_update(project_id: str, project_name: str, feedback_count: int) -> ExecutionPlan:
        """Plan for updating a live game based on feedback."""
        develop = PlanNode.new(
            "develop", "programmer", params={"project_name": project_name, "is_update": True}
        )
        qa = PlanNode.new(
            "qa", "qa_agent", dependencies=[develop.node_id], params={"project_name": project_name}
        )
        build = PlanNode.new(
            "build", "builder", dependencies=[qa.node_id], params={"project_name": project_name}
        )
        deploy = PlanNode.new(
            "deploy",
            "deployer",
            dependencies=[build.node_id],
            params={"project_name": project_name},
        )

        return ExecutionPlan.new(
            project_id=project_id,
            goal=f"Update {project_name} based on {feedback_count} feedback items",
            nodes=[develop, qa, build, deploy],
        )

    # ── Recovery ─────────────────────────────────────────────────────────

    @staticmethod
    def determine_recovery(node: PlanNode, error: str, attempt: int = 0) -> RecoveryLevel:
        """Determine recovery level based on failure characteristics.

        Level 1 (RETRY): Transient errors — timeouts, rate limits, temp failures
        Level 2 (STRATEGY_CHANGE): Logic errors — wrong output, failed checks
        Level 3 (REPLAN): Structural failures — dependencies broken, fundamental issues
        """
        transient_signals = ["timeout", "rate limit", "503", "502", "connection", "temporary"]
        logic_signals = ["assertion", "validation", "check failed", "qa failed", "build failed"]
        structural_signals = ["dependency", "not found", "missing", "circular"]

        error_lower = error.lower()

        if any(s in error_lower for s in transient_signals):
            return RecoveryLevel.RETRY

        if any(s in error_lower for s in structural_signals):
            return RecoveryLevel.REPLAN

        if attempt >= 2:
            return RecoveryLevel.REPLAN

        if any(s in error_lower for s in logic_signals):
            return RecoveryLevel.STRATEGY_CHANGE

        return RecoveryLevel.RETRY if attempt < 1 else RecoveryLevel.STRATEGY_CHANGE

    @staticmethod
    def replan(
        original: ExecutionPlan, failed_node: PlanNode, strategy: str = "simplified"
    ) -> ExecutionPlan:
        """Create a new plan version from a failed execution.

        Preserves completed nodes, replaces failed portion.
        """
        # Keep completed nodes, reset the rest
        new_nodes = []
        for node in original.nodes:
            if node.status == PlanNodeStatus.DONE:
                new_nodes.append(node)
            elif node.node_id == failed_node.node_id:
                # Replace with alternative task
                alt_type = "develop_simple" if node.task_type == "develop" else node.task_type
                new_node = PlanNode.new(
                    task_type=alt_type,
                    agent_role=node.agent_role,
                    dependencies=node.dependencies,
                    params={**node.params, "retry_from": node.node_id, "strategy": strategy},
                    node_id=f"{node.node_id}_v{original.version + 1}",
                )
                new_nodes.append(new_node)
            elif node.status == PlanNodeStatus.PENDING:
                # Keep pending nodes but reset
                reset_node = PlanNode(
                    node_id=node.node_id,
                    task_type=node.task_type,
                    agent_role=node.agent_role,
                    dependencies=node.dependencies,
                    params=node.params,
                )
                new_nodes.append(reset_node)

        return ExecutionPlan(
            plan_id=original.plan_id,
            version=original.version + 1,
            project_id=original.project_id,
            goal=f"{original.goal} (replan v{original.version + 1}: {strategy})",
            nodes=new_nodes,
            parent_plan_id=original.plan_id,
        )


# Singleton
_planner: Planner | None = None


def get_planner() -> Planner:
    global _planner
    if _planner is None:
        _planner = Planner()
    return _planner

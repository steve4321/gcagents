"""Adaptive orchestration topology selector.

Analyzes task DAGs and selects the optimal orchestration pattern based on
structural characteristics. Inspired by AdaptOrch (arxiv 2602.16873).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

import networkx as nx
from loguru import logger

if TYPE_CHECKING:
    import networkx as nx

    from orchestrator.planner import ExecutionPlan


class TopologyType(str, Enum):
    """Orchestration topology patterns."""

    PARALLEL = "parallel"  # Wide-shallow, low coupling
    SEQUENTIAL = "sequential"  # Chain-like, high coupling
    HIERARCHICAL = "hierarchical"  # Deep-narrow, lead delegates
    HYBRID = "hybrid"  # Diamond / fan-out + fan-in


@dataclass(frozen=True)
class DAGMetrics:
    """Structural metrics computed from a task DAG."""

    node_count: int
    edge_count: int
    max_depth: int
    avg_fan_out: float
    coupling_score: float  # edges / (nodes * (nodes-1)), 0-1
    parallelism_potential: float  # 1 - (longest_path / total_nodes), 0-1


class TopologySelector:
    """Analyzes DAG structure and selects the optimal orchestration topology."""

    # ── Public API ────────────────────────────────────────────────────────

    def analyze(self, plan_or_dag: ExecutionPlan | nx.DiGraph) -> DAGMetrics:
        """Analyze DAG structure and return computed metrics."""
        graph = self._to_graph(plan_or_dag)
        return self._compute_metrics(graph)

    def select_topology(self, plan_or_dag: ExecutionPlan | nx.DiGraph) -> TopologyType:
        """Select optimal topology based on DAG characteristics.

        Selection rules (from AdaptOrch research):
        - PARALLEL (62% of tasks): wide-shallow, low coupling
        - SEQUENTIAL (14%): chain-like, high coupling
        - HIERARCHICAL (14%): deep-narrow, lead delegates
        - HYBRID (remaining): diamond / fan-out + fan-in
        """
        graph = self._to_graph(plan_or_dag)
        metrics = self._compute_metrics(graph)

        max_out_degree = max((d for _, d in graph.out_degree()), default=0)

        if metrics.node_count <= 1:
            return TopologyType.SEQUENTIAL

        # Sequential: linear chain (max fan-out == 1, path spans all nodes)
        if max_out_degree <= 1 and metrics.max_depth == metrics.node_count - 1:
            logger.debug("Topology: SEQUENTIAL (chain-like, fan_out={:.1f})", metrics.avg_fan_out)
            return TopologyType.SEQUENTIAL

        # Parallel: wide-shallow (max fan-out > 2, depth <= 2)
        if max_out_degree > 2 and metrics.max_depth <= 2:
            logger.debug(
                "Topology: PARALLEL (wide-shallow, max_out={}, depth={})",
                max_out_degree,
                metrics.max_depth,
            )
            return TopologyType.PARALLEL

        # Hierarchical: deep-narrow (depth > 3, max fan-out <= 2)
        if metrics.max_depth > 3 and max_out_degree <= 2:
            logger.debug(
                "Topology: HIERARCHICAL (deep-narrow, depth={}, max_out={})",
                metrics.max_depth,
                max_out_degree,
            )
            return TopologyType.HIERARCHICAL

        # Hybrid: everything else (diamond, fan-out + fan-in)
        logger.debug(
            "Topology: HYBRID (fan_out={:.1f}, depth={}, coupling={:.2f})",
            metrics.avg_fan_out,
            metrics.max_depth,
            metrics.coupling_score,
        )
        return TopologyType.HYBRID

    def recommend_parallelism(self, plan_or_dag: ExecutionPlan | nx.DiGraph) -> int:
        """Recommend max concurrent tasks based on DAG structure."""
        graph = self._to_graph(plan_or_dag)

        if graph.number_of_nodes() == 0:
            return 1

        # Max width across all layers = max number of concurrent tasks possible
        max_width = max(
            (len(generation) for generation in nx.topological_generations(graph)),
            default=1,
        )

        # Cap by parallelism potential
        metrics = self._compute_metrics(graph)
        recommended = max(1, int(max_width * metrics.parallelism_potential))

        logger.debug(
            "Recommended parallelism: {} (max_width={}, potential={:.2f})",
            recommended,
            max_width,
            metrics.parallelism_potential,
        )
        return recommended

    def estimate_speedup(
        self, plan_or_dag: ExecutionPlan | nx.DiGraph, max_workers: int = 3
    ) -> float:
        """Estimate speedup over sequential execution.

        Sequential time = total nodes (1 unit per node).
        Parallel time = critical path length (longest path through DAG).
        Speedup = sequential / parallel, capped at max_workers.
        """
        graph = self._to_graph(plan_or_dag)
        n = graph.number_of_nodes()

        if n <= 1:
            return 1.0

        # Longest path = critical path
        critical_path = self._longest_path_length(graph)
        sequential_time = float(n)
        parallel_time = float(max(critical_path, 1))

        speedup = min(sequential_time / parallel_time, float(max_workers))

        logger.debug(
            "Estimated speedup: {:.1f}x (seq={}, parallel={}, workers={})",
            speedup,
            sequential_time,
            parallel_time,
            max_workers,
        )
        return speedup

    # ── Internal helpers ──────────────────────────────────────────────────

    @staticmethod
    def _to_graph(plan_or_dag: ExecutionPlan | nx.DiGraph) -> nx.DiGraph:
        """Convert input to a networkx DiGraph."""
        if isinstance(plan_or_dag, nx.DiGraph):
            return plan_or_dag

        # Build from ExecutionPlan
        graph = nx.DiGraph()
        for node in plan_or_dag.nodes:
            graph.add_node(node.node_id)
            for dep in node.dependencies:
                graph.add_edge(dep, node.node_id)
        return graph

    def _compute_metrics(self, graph: nx.DiGraph) -> DAGMetrics:
        """Compute structural metrics from a DAG."""
        n = graph.number_of_nodes()
        e = graph.number_of_edges()

        if n == 0:
            return DAGMetrics(
                node_count=0,
                edge_count=0,
                max_depth=0,
                avg_fan_out=0.0,
                coupling_score=0.0,
                parallelism_potential=1.0,
            )

        max_depth = self._longest_path_length(graph)
        avg_fan_out = e / n

        # Graph density as coupling measure (0 = uncoupled, 1 = fully connected)
        coupling_score = e / (n * (n - 1)) if n > 1 else 0.0

        # Parallelism: 1 if all tasks can run concurrently, 0 if fully sequential
        parallelism_potential = 1.0 - (max_depth / n) if n > 0 else 1.0

        return DAGMetrics(
            node_count=n,
            edge_count=e,
            max_depth=max_depth,
            avg_fan_out=round(avg_fan_out, 3),
            coupling_score=round(coupling_score, 4),
            parallelism_potential=round(max(0.0, parallelism_potential), 3),
        )

    @staticmethod
    def _longest_path_length(graph: nx.DiGraph) -> int:
        """Compute longest path length (critical path) in a DAG.

        Returns the number of edges on the longest path.
        Uses dynamic programming on topological order.
        """
        if graph.number_of_nodes() == 0:
            return 0

        # dist[v] = longest path ending at v (in edges)
        dist: dict[str, int] = {node: 0 for node in graph.nodes}

        for node in nx.topological_sort(graph):
            for successor in graph.successors(node):
                dist[successor] = max(dist[successor], dist[node] + 1)

        return max(dist.values()) if dist else 0


# ── Singleton ─────────────────────────────────────────────────────────────

_selector: TopologySelector | None = None


def get_topology_selector() -> TopologySelector:
    """Return the singleton TopologySelector instance."""
    global _selector
    if _selector is None:
        _selector = TopologySelector()
    return _selector

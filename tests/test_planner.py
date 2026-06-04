"""Tests for orchestrator/planner.py — DAG construction, waves, recovery."""

from __future__ import annotations

import pytest

from orchestrator.planner import (
    ExecutionPlan,
    Planner,
    PlanNode,
    PlanNodeStatus,
    RecoveryLevel,
)


def _node(nid: str, deps: list[str] | None = None, status: PlanNodeStatus = PlanNodeStatus.PENDING) -> PlanNode:
    return PlanNode(
        node_id=nid,
        task_type="develop",
        agent_role="developer",
        dependencies=deps or [],
        status=status,
    )


class TestPlanNodeBasics:
    def test_node_new_generates_id(self):
        n = PlanNode.new(task_type="qa", agent_role="tester")
        assert n.node_id and len(n.node_id) >= 4
        assert n.status == PlanNodeStatus.PENDING
        assert n.max_retries == 2

    def test_node_to_dict_round_trip(self):
        n = PlanNode.new(task_type="build", agent_role="builder", dependencies=["n1"])
        d = n.to_dict()
        assert d["node_id"] == n.node_id
        assert d["task_type"] == "build"
        assert d["dependencies"] == ["n1"]
        assert d["status"] == "pending"


class TestExecutionPlanReadyNodes:
    def test_empty_plan_no_ready(self):
        plan = ExecutionPlan.new(project_id="p1", goal="x")
        assert plan.get_ready_nodes() == []
        assert plan.get_running_nodes() == []
        assert plan.is_complete()

    def test_root_nodes_ready(self):
        a = _node("a")
        b = _node("b")
        plan = ExecutionPlan.new(project_id="p1", goal="x", nodes=[a, b])
        ready = plan.get_ready_nodes()
        assert {n.node_id for n in ready} == {"a", "b"}

    def test_dependent_blocked_until_dep_done(self):
        a = _node("a", status=PlanNodeStatus.PENDING)
        b = _node("b", deps=["a"], status=PlanNodeStatus.PENDING)
        plan = ExecutionPlan.new(project_id="p1", goal="x", nodes=[a, b])
        assert {n.node_id for n in plan.get_ready_nodes()} == {"a"}

        a.status = PlanNodeStatus.DONE
        assert {n.node_id for n in plan.get_ready_nodes()} == {"b"}

    def test_running_and_failed_nodes(self):
        a = _node("a", status=PlanNodeStatus.RUNNING)
        b = _node("b", status=PlanNodeStatus.FAILED)
        plan = ExecutionPlan.new(project_id="p1", goal="x", nodes=[a, b])
        assert {n.node_id for n in plan.get_running_nodes()} == {"a"}
        assert {n.node_id for n in plan.get_failed_nodes()} == {"b"}

    def test_get_node_lookup(self):
        a = _node("a")
        b = _node("b")
        plan = ExecutionPlan.new(project_id="p1", goal="x", nodes=[a, b])
        assert plan.get_node("a") is a
        assert plan.get_node("missing") is None


class TestWaveComputation:
    def test_single_wave_independent_nodes(self):
        nodes = [_node(f"n{i}") for i in range(3)]
        plan = ExecutionPlan.new(project_id="p1", goal="x", nodes=nodes)
        waves = plan.get_waves()
        assert len(waves) == 1
        assert len(waves[0]) == 3

    def test_sequential_chains_emit_one_node_per_wave(self):
        nodes = [
            _node("a"),
            _node("b", deps=["a"]),
            _node("c", deps=["b"]),
        ]
        plan = ExecutionPlan.new(project_id="p1", goal="x", nodes=nodes)
        waves = plan.get_waves()
        assert len(waves) == 3
        assert [w[0].node_id for w in waves] == ["a", "b", "c"]

    def test_diamond_dag(self):
        a = _node("a")
        b = _node("b", deps=["a"])
        c = _node("c", deps=["a"])
        d = _node("d", deps=["b", "c"])
        plan = ExecutionPlan.new(project_id="p1", goal="x", nodes=[a, b, c, d])
        waves = plan.get_waves()
        assert waves[0][0].node_id == "a"
        assert {n.node_id for n in waves[1]} == {"b", "c"}
        assert waves[2][0].node_id == "d"

    def test_progress_and_is_complete(self):
        nodes = [_node("a"), _node("b")]
        plan = ExecutionPlan.new(project_id="p1", goal="x", nodes=nodes)
        assert plan.progress() == 0.0
        assert not plan.is_complete()

        nodes[0].status = PlanNodeStatus.DONE
        assert plan.progress() == 0.5
        assert not plan.is_complete()

        nodes[1].status = PlanNodeStatus.SKIPPED
        assert plan.is_complete()


class TestRecoveryLevel:
    @pytest.mark.parametrize(
        "error,expected",
        [
            ("Connection timeout after 30s", RecoveryLevel.RETRY),
            ("Rate limit exceeded (HTTP 429)", RecoveryLevel.RETRY),
            ("HTTP 503 unavailable", RecoveryLevel.RETRY),
            ("Dependency missing: package x", RecoveryLevel.REPLAN),
            ("File not found", RecoveryLevel.REPLAN),
            ("Build failed: syntax error", RecoveryLevel.STRATEGY_CHANGE),
            ("QA failed: assertion mismatch", RecoveryLevel.STRATEGY_CHANGE),
            ("Random unknown issue", RecoveryLevel.RETRY),
        ],
    )
    def test_classify(self, error: str, expected: RecoveryLevel):
        n = _node("n")
        assert Planner.determine_recovery(n, error, attempt=0) == expected

    def test_high_attempt_promotes_to_replan(self):
        n = _node("n")
        result = Planner.determine_recovery(n, "Some logic error", attempt=3)
        assert result == RecoveryLevel.REPLAN


class TestReplan:
    def test_replan_preserves_completed_nodes(self):
        a = _node("a", status=PlanNodeStatus.DONE)
        b = _node("b", deps=["a"], status=PlanNodeStatus.FAILED)
        plan = ExecutionPlan.new(project_id="p1", goal="x", nodes=[a, b])
        new_plan = Planner.replan(plan, b, strategy="simplified")
        assert new_plan.version == plan.version + 1
        assert new_plan.plan_id == plan.plan_id
        a_new = new_plan.get_node("a")
        assert a_new is not None and a_new.status == PlanNodeStatus.DONE

    def test_replan_replaces_failed_with_alternative(self):
        a = _node("a", status=PlanNodeStatus.DONE)
        b = _node("b", deps=["a"], status=PlanNodeStatus.FAILED)
        plan = ExecutionPlan.new(project_id="p1", goal="x", nodes=[a, b])
        new_plan = Planner.replan(plan, b)
        replanned = next(
            (n for n in new_plan.nodes if n.params.get("retry_from") == b.node_id),
            None,
        )
        assert replanned is not None
        assert replanned.task_type == "develop_simple"
        assert replanned.params.get("strategy") == "simplified"

    def test_replan_resets_pending_nodes(self):
        a = _node("a", status=PlanNodeStatus.DONE)
        b = _node("b", deps=["a"], status=PlanNodeStatus.FAILED)
        c = _node("c", deps=["b"], status=PlanNodeStatus.PENDING)
        plan = ExecutionPlan.new(project_id="p1", goal="x", nodes=[a, b, c])
        new_plan = Planner.replan(plan, b)
        c_new = new_plan.get_node("c")
        assert c_new is not None
        assert c_new.status == PlanNodeStatus.PENDING


class TestPlannerTemplates:
    def test_plan_full_game_has_correct_dag(self):
        plan = Planner.plan_full_game("p1", "TestGame", "puzzle")
        types = {n.task_type for n in plan.nodes}
        assert {
            "market_scan",
            "design_game",
            "art_gen",
            "generate_music",
            "develop",
            "qa",
            "build",
            "deploy",
        }.issubset(types)
        develop = next((n for n in plan.nodes if n.task_type == "develop"), None)
        assert develop is not None
        dep_types = {
            plan.get_node(d).task_type
            for d in develop.dependencies
            if plan.get_node(d) is not None
        }
        assert dep_types == {"art_gen", "generate_music"}

    def test_plan_prototype_skips_art_and_music(self):
        plan = Planner.plan_prototype("p1", "Proto", "puzzle")
        ids = {n.node_id for n in plan.nodes}
        assert "art_gen" not in ids
        assert "generate_music" not in ids

    def test_plan_to_dict_has_summary(self):
        plan = Planner.plan_full_game("p1", "G", "puzzle")
        d = plan.to_dict()
        assert d["plan_id"] == plan.plan_id
        assert d["version"] == 1
        assert d["waves"] >= 1
        assert d["progress"] == "0%"


class TestPlanVersioning:
    def test_new_plan_has_version_one(self):
        plan = ExecutionPlan.new(project_id="p1", goal="x")
        assert plan.version == 1
        assert plan.created_at

    def test_plan_post_init_sets_created_at(self):
        plan = ExecutionPlan(plan_id="abc", version=1, project_id="p1", goal="g")
        assert plan.created_at

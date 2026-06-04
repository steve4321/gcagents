"""Tests for feedback_collector → scheduler tick → update routing loop."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_collect_feedback_called_on_tick_30(tmp_db):
    from orchestrator.persistence import ensure_tables

    await ensure_tables()

    with (
        patch(
            "agents.ops.analytics.feedback_collector.collect_feedback",
            new_callable=AsyncMock,
            return_value={"feedback_collected": 3},
        ) as mock_collect,
        patch("orchestrator.scheduler.emit", new_callable=AsyncMock),
        patch("orchestrator.scheduler.enqueue", new_callable=AsyncMock),
        patch("orchestrator.scheduler._process_instructions", new_callable=AsyncMock),
        patch("orchestrator.scheduler._resolve_answered_decisions", new_callable=AsyncMock),
        patch("orchestrator.scheduler._periodic_market_scan", new_callable=AsyncMock),
        patch("orchestrator.scheduler._ceo_evaluate_new_projects", new_callable=AsyncMock),
        patch("orchestrator.scheduler._fetch_itch_stats", new_callable=AsyncMock),
        patch("orchestrator.scheduler._advance_projects", new_callable=AsyncMock),
        patch("orchestrator.scheduler._execute_one_task", new_callable=AsyncMock, return_value=None),
        patch("orchestrator.scheduler._generate_reports", new_callable=AsyncMock),
        patch(
            "orchestrator.persistence.get_live_projects",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "orchestrator.persistence.get_pending_feedback",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        import orchestrator.scheduler as sched

        sched._TICK_COUNT = 9
        await sched.scheduler_tick()
        mock_collect.assert_not_awaited()

        sched._TICK_COUNT = 29
        await sched.scheduler_tick()
        mock_collect.assert_awaited_once()


@pytest.mark.asyncio
async def test_feedback_routes_update_on_two_bug_feature(tmp_db):
    from orchestrator.persistence import ensure_tables

    await ensure_tables()

    proj = {"id": "proj-1", "name": "TestGame"}
    feedback_items = [
        {"id": 1, "category": "bug", "text": "crash"},
        {"id": 2, "category": "feature", "text": "add levels"},
        {"id": 3, "category": "praise", "text": "great"},
    ]

    with (
        patch(
            "agents.ops.analytics.feedback_collector.collect_feedback",
            new_callable=AsyncMock,
            return_value={"feedback_collected": 3},
        ),
        patch("orchestrator.scheduler.emit", new_callable=AsyncMock),
        patch("orchestrator.scheduler.enqueue", new_callable=AsyncMock) as mock_enqueue,
        patch("orchestrator.scheduler.save_chat_message", new_callable=AsyncMock),
        patch("orchestrator.scheduler._process_instructions", new_callable=AsyncMock),
        patch("orchestrator.scheduler._resolve_answered_decisions", new_callable=AsyncMock),
        patch("orchestrator.scheduler._periodic_market_scan", new_callable=AsyncMock),
        patch("orchestrator.scheduler._ceo_evaluate_new_projects", new_callable=AsyncMock),
        patch("orchestrator.scheduler._fetch_itch_stats", new_callable=AsyncMock),
        patch("orchestrator.scheduler._advance_projects", new_callable=AsyncMock),
        patch("orchestrator.scheduler._execute_one_task", new_callable=AsyncMock, return_value=None),
        patch("orchestrator.scheduler._generate_reports", new_callable=AsyncMock),
        patch(
            "orchestrator.persistence.get_live_projects",
            new_callable=AsyncMock,
            return_value=[proj],
        ),
        patch(
            "orchestrator.persistence.get_pending_feedback",
            new_callable=AsyncMock,
            return_value=feedback_items,
        ),
    ):
        import orchestrator.scheduler as sched

        sched._TICK_COUNT = 29
        await sched.scheduler_tick()

        mock_enqueue.assert_any_await(
            "proj-1",
            "develop",
            {
                "project_name": "TestGame",
                "mode": "update",
                "feedback_count": 2,
            },
        )


@pytest.mark.asyncio
async def test_feedback_no_route_when_fewer_than_two(tmp_db):
    from orchestrator.persistence import ensure_tables

    await ensure_tables()

    proj = {"id": "proj-2", "name": "SmallGame"}
    feedback_items = [
        {"id": 10, "category": "bug", "text": "typo"},
    ]

    with (
        patch(
            "agents.ops.analytics.feedback_collector.collect_feedback",
            new_callable=AsyncMock,
            return_value={"feedback_collected": 1},
        ),
        patch("orchestrator.scheduler.emit", new_callable=AsyncMock),
        patch("orchestrator.scheduler.enqueue", new_callable=AsyncMock) as mock_enqueue,
        patch("orchestrator.scheduler._process_instructions", new_callable=AsyncMock),
        patch("orchestrator.scheduler._resolve_answered_decisions", new_callable=AsyncMock),
        patch("orchestrator.scheduler._periodic_market_scan", new_callable=AsyncMock),
        patch("orchestrator.scheduler._ceo_evaluate_new_projects", new_callable=AsyncMock),
        patch("orchestrator.scheduler._fetch_itch_stats", new_callable=AsyncMock),
        patch("orchestrator.scheduler._advance_projects", new_callable=AsyncMock),
        patch("orchestrator.scheduler._execute_one_task", new_callable=AsyncMock, return_value=None),
        patch("orchestrator.scheduler._generate_reports", new_callable=AsyncMock),
        patch(
            "orchestrator.persistence.get_live_projects",
            new_callable=AsyncMock,
            return_value=[proj],
        ),
        patch(
            "orchestrator.persistence.get_pending_feedback",
            new_callable=AsyncMock,
            return_value=feedback_items,
        ),
    ):
        import orchestrator.scheduler as sched

        sched._TICK_COUNT = 29
        await sched.scheduler_tick()

        for call in mock_enqueue.call_args_list:
            if call.args[1] == "develop" and call.args[2].get("mode") == "update":
                pytest.fail("update task enqueued with < 2 bug/feature items")


@pytest.mark.asyncio
async def test_feedback_summary_endpoint(tmp_db):
    from httpx import ASGITransport, AsyncClient

    from orchestrator.persistence import ensure_tables, save_feedback

    await ensure_tables()

    await save_feedback(
        project_id=1, post_id="p1", body="crash", category="bug", author="a"
    )
    await save_feedback(
        project_id=1, post_id="p2", body="want levels", category="feature", author="b"
    )
    await save_feedback(
        project_id=1, post_id="p3", body="nice", category="praise", author="c"
    )

    live_projects = [
        {"id": 1, "name": "TestGame", "genre": "puzzle", "status": "live", "itch_url": "https://x.itch.io/t"},
    ]

    with (
        patch("orchestrator.persistence._get_engine", return_value=tmp_db),
        patch(
            "orchestrator.persistence.get_live_projects",
            new_callable=AsyncMock,
            return_value=live_projects,
        ),
    ):
        from dashboard.web.api_server import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/feedback/summary")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_pending"] == 3
    assert len(data["games"]) == 1
    assert data["games"][0]["by_category"]["bug"] == 1
    assert data["games"][0]["by_category"]["feature"] == 1
    assert data["games"][0]["by_category"]["praise"] == 1


@pytest.mark.asyncio
async def test_collect_feedback_failure_does_not_crash_tick(tmp_db):
    from orchestrator.persistence import ensure_tables

    await ensure_tables()

    with (
        patch(
            "agents.ops.analytics.feedback_collector.collect_feedback",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network error"),
        ),
        patch("orchestrator.scheduler.emit", new_callable=AsyncMock),
        patch("orchestrator.scheduler._process_instructions", new_callable=AsyncMock),
        patch("orchestrator.scheduler._resolve_answered_decisions", new_callable=AsyncMock),
        patch("orchestrator.scheduler._periodic_market_scan", new_callable=AsyncMock),
        patch("orchestrator.scheduler._ceo_evaluate_new_projects", new_callable=AsyncMock),
        patch("orchestrator.scheduler._fetch_itch_stats", new_callable=AsyncMock),
        patch("orchestrator.scheduler._advance_projects", new_callable=AsyncMock),
        patch("orchestrator.scheduler._execute_one_task", new_callable=AsyncMock, return_value=None),
        patch("orchestrator.scheduler._generate_reports", new_callable=AsyncMock),
    ):
        import orchestrator.scheduler as sched

        sched._TICK_COUNT = 29
        result = await sched.scheduler_tick()
        assert result is not None
        assert result["tick"] == 30

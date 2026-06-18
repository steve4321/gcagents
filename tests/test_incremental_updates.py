from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from shared.content_merger import dedup_by_id, merge_data_file, merge_json_data
from shared.content_summary import extract_content_summary
from shared.models import ProjectState


class TestContentMerger:
    def test_dedup_preserves_all_unique(self):
        result = dedup_by_id(
            [{"id": "a", "n": "A"}],
            [{"id": "b", "n": "B"}],
        )
        assert len(result) == 2

    def test_dedup_replaces_same_id(self):
        result = dedup_by_id(
            [{"id": "a", "n": "Old"}],
            [{"id": "a", "n": "New"}],
        )
        assert len(result) == 1
        assert result[0]["n"] == "New"

    def test_merge_appends_new_entries(self):
        merged = merge_json_data(
            {"towers": [{"id": "arrow", "damage": 10}]},
            {"towers": [{"id": "laser", "damage": 25}]},
        )
        assert len(merged["towers"]) == 2
        ids = {t["id"] for t in merged["towers"]}
        assert ids == {"arrow", "laser"}

    def test_merge_preserves_missing_keys(self):
        merged = merge_json_data(
            {"waves": [1, 2]},
            {"towers": [{"id": "x"}]},
        )
        assert "waves" in merged
        assert merged["waves"] == [1, 2]

    def test_merge_no_mutation(self):
        existing = {"towers": [{"id": "a"}]}
        new = {"towers": [{"id": "b"}]}
        merge_json_data(existing, new)
        assert len(existing["towers"]) == 1
        assert len(new["towers"]) == 1

    def test_merge_data_file_creates(self, tmp_path):
        fp = tmp_path / "data.json"
        merge_data_file(fp, {"items": [{"id": "first"}]})
        data = json.loads(fp.read_text())
        assert data["items"] == [{"id": "first"}]

    def test_merge_data_file_appends(self, tmp_path):
        fp = tmp_path / "data.json"
        fp.write_text(json.dumps({"items": [{"id": "a"}]}))
        merge_data_file(fp, {"items": [{"id": "b"}]})
        data = json.loads(fp.read_text())
        assert len(data["items"]) == 2


class TestContentSummary:
    def test_template_layout(self, tmp_path):
        data_dir = tmp_path / "src" / "game" / "data"
        data_dir.mkdir(parents=True)
        (data_dir / "towers.json").write_text(
            json.dumps({"towers": [{"id": "arrow"}, {"id": "cannon"}]})
        )
        result = extract_content_summary(tmp_path)
        assert result == {"towers.json": ["arrow", "cannon"]}

    def test_flat_data_dir(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "enemies.json").write_text(
            json.dumps({"enemies": [{"id": "grunt"}]})
        )
        result = extract_content_summary(tmp_path)
        assert result == {"enemies.json": ["grunt"]}

    def test_empty_dir(self, tmp_path):
        assert extract_content_summary(tmp_path) == {}

    def test_invalid_json_skipped(self, tmp_path):
        data_dir = tmp_path / "src" / "game" / "data"
        data_dir.mkdir(parents=True)
        (data_dir / "bad.json").write_text("not json{")
        (data_dir / "good.json").write_text(
            json.dumps({"items": [{"id": "ok"}]})
        )
        result = extract_content_summary(tmp_path)
        assert "bad.json" not in result
        assert result.get("good.json") == ["ok"]


class TestProjectStateFields:
    def test_defaults(self):
        p = ProjectState(id="t", name="t")
        assert p.content_version == 0
        assert p.last_content_update is None
        assert p.update_mode == ""

    def test_round_trip(self):
        p = ProjectState(
            id="t", name="t",
            content_version=3,
            last_content_update=datetime(2026, 1, 1, tzinfo=UTC),
            update_mode="content_update",
        )
        d = p.model_dump()
        p2 = ProjectState(**d)
        assert p2.content_version == 3
        assert p2.update_mode == "content_update"


class TestScaffoldGuard:
    def test_skip_preserves_existing_ts(self, tmp_path):
        from agents.dev.programmer.code_generator import _scaffold_project

        src_dir = tmp_path / "src"
        src_dir.mkdir()
        marker = src_dir / "main.ts"
        marker.write_text("// MY CUSTOM CODE")

        result = _scaffold_project(
            tmp_path,
            {"genre": "tower-defense"},
            skip_if_exists=True,
        )
        assert result is True
        assert marker.read_text() == "// MY CUSTOM CODE"

    def test_no_skip_overwrites(self, tmp_path):
        from agents.dev.programmer.code_generator import _scaffold_project

        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "main.ts").write_text("// OLD")

        _scaffold_project(
            tmp_path,
            {"genre": "tower-defense"},
            skip_if_exists=False,
        )
        assert (src_dir / "main.ts").read_text() != "// OLD"


class TestIncrementalValidation:
    def test_merge_valid_when_ids_preserved(self):
        from agents.dev.programmer.code_generator import _validate_incremental_merge

        old = {"towers.json": json.dumps({"towers": [{"id": "a"}]})}
        new = {"towers.json": json.dumps({"towers": [{"id": "a"}, {"id": "b"}]})}
        assert _validate_incremental_merge(old, new) == []

    def test_merge_fails_when_id_missing(self):
        from agents.dev.programmer.code_generator import _validate_incremental_merge

        old = {"towers.json": json.dumps({"towers": [{"id": "a"}, {"id": "b"}]})}
        new = {"towers.json": json.dumps({"towers": [{"id": "a"}]})}
        errors = _validate_incremental_merge(old, new)
        assert len(errors) >= 1
        assert "b" in errors[0]

    def test_extract_ids_nested(self):
        from agents.dev.programmer.code_generator import _extract_entry_ids

        data = {
            "towers": [{"id": "arrow"}, {"id": "cannon"}],
            "enemies": [{"id": "grunt"}],
        }
        ids = _extract_entry_ids(data)
        assert ids == {"arrow", "cannon", "grunt"}


@pytest.mark.asyncio
class TestContentExpansion:
    async def test_returns_valid_spec(self):
        from agents.dev.designer.gdd_generator import generate_content_expansion
        from shared.config import load_config

        mock_response = json.dumps({
            "rationale": "Add variety",
            "target_files": ["towers.json"],
            "new_content": {
                "towers.json": {
                    "add_entries": [{"id": "laser", "damage": 25}]
                }
            },
            "balance_notes": "Balanced",
        })

        config = load_config()
        with patch("agents.dev.designer.gdd_generator.llm") as mock_llm:
            mock_llm.chat_completion = AsyncMock(
                return_value=(mock_response, {})
            )
            result = await generate_content_expansion(
                {"title": "TD", "genre": "tower-defense"},
                {"towers.json": ["arrow"]},
                config,
            )

        assert "rationale" in result
        assert "towers.json" in result["new_content"]
        assert "target_files" in result

    async def test_inventory_in_prompt(self):
        from agents.dev.designer.gdd_generator import generate_content_expansion
        from shared.config import load_config

        mock_response = json.dumps({
            "rationale": "x",
            "target_files": [],
            "new_content": {},
            "balance_notes": "",
        })

        config = load_config()
        with patch("agents.dev.designer.gdd_generator.llm") as mock_llm:
            mock_llm.chat_completion = AsyncMock(
                return_value=(mock_response, {})
            )
            await generate_content_expansion(
                {"title": "TD", "genre": "tower-defense"},
                {"towers.json": ["arrow", "cannon"]},
                config,
            )

        call_args = mock_llm.chat_completion.call_args
        user_msg = call_args.kwargs["messages"][1]["content"]
        assert "arrow" in user_msg
        assert "cannon" in user_msg


class TestSchedulerHelpers:
    def test_update_interval_known(self):
        from orchestrator.scheduler import _get_update_interval

        assert _get_update_interval("tower-defense") == 30
        assert _get_update_interval("visual-novel") == 7

    def test_update_interval_unknown(self):
        from orchestrator.scheduler import _get_update_interval

        assert _get_update_interval("racing") == 14

    def test_trigger_no_history(self):
        from orchestrator.scheduler import _should_trigger_update

        assert _should_trigger_update(None, 7) is True

    def test_trigger_recent(self):
        from orchestrator.scheduler import _should_trigger_update

        recent = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        assert _should_trigger_update(recent, 7) is False

    def test_trigger_old(self):
        from orchestrator.scheduler import _should_trigger_update

        old = (datetime.now(UTC) - timedelta(days=30)).isoformat()
        assert _should_trigger_update(old, 7) is True

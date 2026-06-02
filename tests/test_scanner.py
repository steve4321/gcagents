"""Tests for market scanner and analyzer with mocked HTTP responses."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.research.analyzer import (
    _build_analysis_prompt,
    _normalize_opportunities,
    _parse_opportunities,
)
from shared.models import MarketSignal


@pytest.fixture
def sample_signals():
    """Create a list of sample MarketSignal objects for testing."""
    from datetime import datetime
    return [
        MarketSignal(source="itch_rss", signal_type="new_game", genre="puzzle",
                     title="Puzzle Quest", data={"url": "http://example.com"}, score=0.8,
                     captured_at=datetime.now()),
        MarketSignal(source="reddit", signal_type="community_hot", genre="puzzle",
                     title="Cool Puzzle Game", data={"url": "http://example.com"}, score=0.6,
                     captured_at=datetime.now()),
        MarketSignal(source="steam_spy", signal_type="steam_popularity", genre="idle",
                     title="Idle Clicker Pro", data={"url": "http://example.com"}, score=0.9,
                     captured_at=datetime.now()),
    ]


class TestBuildAnalysisPrompt:
    def test_includes_genre_counts(self, sample_signals):
        from collections import Counter
        genre_counts = Counter(s.genre for s in sample_signals if s.genre)
        prompt = _build_analysis_prompt(sample_signals, genre_counts)
        assert "puzzle" in prompt.lower()
        assert "2" in prompt  # puzzle appears twice

    def test_includes_cross_source_correlation(self, sample_signals):
        from collections import Counter
        genre_counts = Counter(s.genre for s in sample_signals if s.genre)
        prompt = _build_analysis_prompt(sample_signals, genre_counts)
        assert "Cross-Source" in prompt

    def test_empty_signals(self):
        from collections import Counter
        prompt = _build_analysis_prompt([], Counter())
        assert "Total signals: 0" in prompt


class TestParseOpportunities:
    def test_parse_valid_json(self):
        text = json.dumps([
            {"name": "Test Game", "genre": "puzzle", "market_opportunity_score": 0.8}
        ])
        result = _parse_opportunities(text)
        assert len(result) == 1
        assert result[0]["name"] == "Test Game"

    def test_parse_json_in_code_block(self):
        text = '```json\n[{"name": "Game", "genre": "idle"}]\n```'
        result = _parse_opportunities(text)
        assert len(result) == 1

    def test_parse_invalid_text_returns_empty(self):
        result = _parse_opportunities("not json at all no brackets")
        assert result == []


class TestNormalizeOpportunities:
    def test_normalizes_field_names(self):
        opps = [{"estimated_hours": 10, "score": 0.8, "game_name": "Test"}]
        result = _normalize_opportunities(opps)
        assert "estimated_dev_hours" in result[0]
        assert "market_opportunity_score" in result[0]
        assert "name" in result[0]

    def test_adds_defaults(self):
        result = _normalize_opportunities([{"name": "X", "genre": "puzzle"}])
        assert result[0]["target_platforms"] == ["itch.io", "web"]
        assert result[0]["competition_analysis"] == "medium"
        assert result[0]["trend_direction"] == "stable"


class TestScanMarket:
    @pytest.mark.asyncio
    async def test_scan_returns_insights(self, sample_signals):
        """Test scan_market returns market insights when signals are collected."""
        with patch("agents.research.scanner.scan_all_sources", new_callable=AsyncMock) as mock_scan, \
             patch("agents.research.scanner.analyze_signals", new_callable=AsyncMock) as mock_analyze, \
             patch("agents.research.scanner.save_agent_log", new_callable=AsyncMock), \
             patch("agents.research.scanner.save_market_report", new_callable=AsyncMock):
            mock_scan.return_value = sample_signals
            mock_analyze.return_value = (
                [{"name": "Test", "genre": "puzzle", "market_opportunity_score": 0.8}],
                "raw analysis"
            )

            from agents.research.scanner import scan_market
            from orchestrator.state import CompanyState
            state = CompanyState()
            result = await scan_market(state)

            assert "market_insights" in result
            assert len(result["market_insights"]) == 1

    @pytest.mark.asyncio
    async def test_scan_handles_no_signals(self):
        """Test scan_market handles empty signal list gracefully."""
        with patch("agents.research.scanner.scan_all_sources", new_callable=AsyncMock) as mock_scan, \
             patch("agents.research.scanner.save_agent_log", new_callable=AsyncMock):
            mock_scan.return_value = []

            from agents.research.scanner import scan_market
            from orchestrator.state import CompanyState
            state = CompanyState()
            result = await scan_market(state)

            assert result["market_insights"] == []

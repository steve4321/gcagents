"""Tests for configuration loading."""

from __future__ import annotations

from shared.config import AppConfig, SourceConfig, load_config


class TestAppConfig:
    def test_load_config_returns_app_config(self):
        config = load_config()
        assert isinstance(config, AppConfig)

    def test_default_values(self):
        config = load_config()
        assert config.dashboard_port == 8080
        assert isinstance(config.deepseek_api_key, str)
        assert config.comfyui_url == "http://localhost:8188"

    def test_games_output_dir_is_path(self):
        from pathlib import Path

        config = load_config()
        assert isinstance(config.games_output_dir, Path)

    def test_db_url_contains_sqlite(self):
        config = load_config()
        assert "sqlite" in config.db_url


class TestSourceConfig:
    def test_source_config_defaults(self):
        sc = SourceConfig(type="rss", base_url="https://example.com")
        assert sc.auth_type == "none"
        assert sc.rate_limit_per_second == 5
        assert sc.cache_ttl_seconds == 300
        assert sc.feeds == []

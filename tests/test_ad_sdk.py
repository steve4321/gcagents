"""Tests for shared.ad_sdk module."""
from __future__ import annotations

import json

import pytest

from shared.ad_sdk import (
    get_ad_break_js,
    get_ad_helper_js,
    get_all_platforms,
    get_happytime_js,
    get_sdk_init_js,
    get_sdk_script_tags,
)


class TestGetSdkScriptTags:
    def test_crazygames_returns_script_tag(self):
        result = get_sdk_script_tags(["crazygames"])
        assert "crazygames-sdk-v1.js" in result
        assert "<script" in result

    def test_poki_returns_script_tag(self):
        result = get_sdk_script_tags(["poki"])
        assert "poki-sdk.js" in result
        assert "<script" in result

    def test_empty_list_returns_empty(self):
        assert get_sdk_script_tags([]) == ""

    def test_unknown_platform_returns_empty(self):
        assert get_sdk_script_tags(["steam"]) == ""

    def test_multiple_platforms_combined(self):
        result = get_sdk_script_tags(["crazygames", "poki"])
        assert "crazygames-sdk-v1.js" in result
        assert "poki-sdk.js" in result


class TestGetSdkInitJs:
    def test_crazygames_init(self):
        result = get_sdk_init_js(["crazygames"])
        assert "CrazySDK" in result
        assert "init()" in result

    def test_poki_init(self):
        result = get_sdk_init_js(["poki"])
        assert "PokiSDK" in result
        assert "init()" in result

    def test_empty_list_returns_empty(self):
        assert get_sdk_init_js([]) == ""

    def test_multiple_platforms_combined(self):
        result = get_sdk_init_js(["crazygames", "poki"])
        assert "CrazySDK" in result
        assert "PokiSDK" in result


class TestGetAdBreakJs:
    def test_crazygames_adbreak(self):
        result = get_ad_break_js(["crazygames"])
        assert "requestAd" in result
        assert "midgame" in result

    def test_poki_adbreak(self):
        result = get_ad_break_js(["poki"])
        assert "commercialBreak" in result

    def test_empty_list_returns_empty(self):
        assert get_ad_break_js([]) == ""

    def test_multiple_platforms_includes_comments(self):
        result = get_ad_break_js(["crazygames", "poki"])
        assert "// crazygames" in result
        assert "// poki" in result
        assert "requestAd" in result
        assert "commercialBreak" in result


class TestGetHappytimeJs:
    def test_crazygames_happytime(self):
        result = get_happytime_js(["crazygames"])
        assert "happytime" in result

    def test_poki_happytime(self):
        result = get_happytime_js(["poki"])
        assert "levelComplete" in result

    def test_empty_list_returns_empty(self):
        assert get_happytime_js([]) == ""

    def test_multiple_platforms_combined(self):
        result = get_happytime_js(["crazygames", "poki"])
        assert "happytime" in result
        assert "levelComplete" in result


class TestGetAllPlatforms:
    def test_returns_supported_platforms(self):
        platforms = get_all_platforms()
        assert "crazygames" in platforms
        assert "poki" in platforms

    def test_returns_list(self):
        assert isinstance(get_all_platforms(), list)


class TestGetAdHelperJs:
    def test_no_platforms_returns_stubs(self):
        result = get_ad_helper_js([])
        assert "__AD_CONFIG__" in result
        assert "__triggerAdBreak" in result
        assert "__triggerHappyTime" in result

    def test_with_platforms_includes_config(self):
        result = get_ad_helper_js(["crazygames", "poki"])
        assert "__AD_CONFIG__" in result
        config_json = json.dumps(["crazygames", "poki"])
        assert config_json in result
        assert "CrazyGames" in result
        assert "PokiSDK" in result

    def test_with_platforms_includes_trigger_functions(self):
        result = get_ad_helper_js(["crazygames"])
        assert "__triggerAdBreak" in result
        assert "__triggerHappyTime" in result
        assert "requestAd" in result
        assert "happytime" in result

    def test_crazygames_only_no_poki_script_tag(self):
        result = get_ad_helper_js(["crazygames"])
        assert "poki-sdk.js" not in result


class TestScaffoldWithAdSdk:
    def test_scaffold_includes_ad_config_for_platforms(self, tmp_path):
        from agents.dev.programmer.code_generator import _scaffold_project

        project_dir = tmp_path / "ad-game"
        project_dir.mkdir()
        gdd = {
            "title": "Ad Game",
            "target_platforms": ["crazygames", "poki"],
        }
        _scaffold_project(project_dir, gdd)

        html = (project_dir / "index.html").read_text()
        assert "crazygames-sdk-v1.js" in html
        assert "poki-sdk.js" in html
        assert "__AD_CONFIG__" in html
        assert "__triggerAdBreak" in html
        assert "__triggerHappyTime" in html

    def test_scaffold_no_platforms_no_sdk_scripts(self, tmp_path):
        from agents.dev.programmer.code_generator import _scaffold_project

        project_dir = tmp_path / "no-ad-game"
        project_dir.mkdir()
        _scaffold_project(project_dir)

        html = (project_dir / "index.html").read_text()
        assert "crazygames" not in html.lower() or "__AD_CONFIG__" in html
        assert "__AD_CONFIG__ = []" in html

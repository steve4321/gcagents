"""Tests for api_server — POST endpoints, API key auth, WebSocket."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from dashboard.web import api_server
from dashboard.web.api_server import app


@pytest.fixture
def auth_client(monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_KEY", "test-secret-key")
    api_server._DASHBOARD_API_KEY = "test-secret-key"
    with TestClient(app) as client:
        yield client
    api_server._DASHBOARD_API_KEY = ""


@pytest.fixture
def no_auth_client():
    api_server._DASHBOARD_API_KEY = ""
    with TestClient(app) as client:
        yield client


class TestApiKeyAuth:
    def test_protected_post_requires_key(self, no_auth_client):
        api_server._DASHBOARD_API_KEY = "secret"
        try:
            r = no_auth_client.post("/api/pipeline/stop")
            assert r.status_code == 401
        finally:
            api_server._DASHBOARD_API_KEY = ""

    def test_protected_post_with_wrong_key_401(self):
        api_server._DASHBOARD_API_KEY = "secret"
        try:
            with TestClient(app) as c:
                r = c.post(
                    "/api/pipeline/stop",
                    headers={"X-API-Key": "wrong"},
                )
                assert r.status_code == 401
        finally:
            api_server._DASHBOARD_API_KEY = ""

    def test_protected_post_with_correct_key_ok(self):
        api_server._DASHBOARD_API_KEY = "secret"
        try:
            with TestClient(app) as c:
                r = c.post(
                    "/api/projects/some-id/pause",
                    headers={"X-API-Key": "secret"},
                )
                assert r.status_code in (200, 404, 500)
        finally:
            api_server._DASHBOARD_API_KEY = ""

    def test_get_endpoints_no_key_required(self):
        api_server._DASHBOARD_API_KEY = "secret"
        try:
            with TestClient(app) as c:
                r = c.get("/api/status")
                assert r.status_code == 200
        finally:
            api_server._DASHBOARD_API_KEY = ""


class TestInvalidProjectId:
    def test_path_validation_rejects_bad_chars(self):
        api_server._DASHBOARD_API_KEY = ""
        try:
            with TestClient(app) as c:
                r = c.get("/api/gdd/bad!@#chars")
                assert r.status_code in (400, 404, 422)
        finally:
            api_server._DASHBOARD_API_KEY = ""


class TestMetricsEndpoint:
    def test_metrics_returns_prometheus_text(self):
        api_server._DASHBOARD_API_KEY = ""
        try:
            with TestClient(app) as c:
                r = c.get("/metrics")
                assert r.status_code == 200
                assert "gcagents_projects_total" in r.text or "scrape_error" in r.text
        finally:
            api_server._DASHBOARD_API_KEY = ""


class TestChatSend:
    def test_chat_send_requires_key(self):
        api_server._DASHBOARD_API_KEY = "secret"
        try:
            with TestClient(app) as c:
                r = c.post(
                    "/api/chat/send",
                    json={"content": "hi"},
                )
                assert r.status_code == 401
        finally:
            api_server._DASHBOARD_API_KEY = ""

    def test_chat_send_rejects_empty_content(self):
        api_server._DASHBOARD_API_KEY = "secret"
        try:
            with TestClient(app) as c:
                r = c.post(
                    "/api/chat/send",
                    json={"content": ""},
                    headers={"X-API-Key": "secret"},
                )
                assert r.status_code == 400
        finally:
            api_server._DASHBOARD_API_KEY = ""

    def test_chat_send_rejects_non_ceo(self):
        api_server._DASHBOARD_API_KEY = "secret"
        try:
            with TestClient(app) as c:
                r = c.post(
                    "/api/chat/send",
                    json={"content": "hi", "target_agent": "cfo"},
                    headers={"X-API-Key": "secret"},
                )
                assert r.status_code == 400
        finally:
            api_server._DASHBOARD_API_KEY = ""


class TestDecisionRespond:
    def test_decision_respond_404_for_missing(self):
        api_server._DASHBOARD_API_KEY = "secret"
        try:
            with TestClient(app) as c:
                r = c.post(
                    "/api/decisions/nonexistent-id/respond",
                    params={"response": "approve"},
                    headers={"X-API-Key": "secret"},
                )
                assert r.status_code == 404
        finally:
            api_server._DASHBOARD_API_KEY = ""


class TestFinanceBudget:
    def test_budget_rejects_negative(self):
        api_server._DASHBOARD_API_KEY = "secret"
        try:
            with TestClient(app) as c:
                r = c.post(
                    "/api/finance/budget",
                    json={"budget_limit_usd": -1},
                    headers={"X-API-Key": "secret"},
                )
                assert r.status_code == 400
        finally:
            api_server._DASHBOARD_API_KEY = ""


class TestPolicy:
    def test_get_policy_no_auth(self):
        api_server._DASHBOARD_API_KEY = ""
        try:
            with TestClient(app) as c:
                r = c.get("/api/policy")
                assert r.status_code == 200
        finally:
            api_server._DASHBOARD_API_KEY = ""

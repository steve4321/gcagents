"""Smoke tests for shared/npm_runner.py — install/build helpers."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from shared import npm_runner


class _AsyncProcMock:
    def __init__(self, returncode: int, stderr: bytes = b""):
        self.returncode = returncode
        self._stderr = stderr

    async def communicate(self):
        return b"", self._stderr

    def kill(self):
        pass


def _run(coro):
    return asyncio.run(coro)


def test_install_and_build_missing_npm(tmp_path):
    with patch("shared.npm_runner.shutil.which", return_value=None):
        assert "npm not found" in _run(npm_runner.install_and_build(tmp_path))


def test_install_fails_on_nonzero_exit(tmp_path):
    fake = _AsyncProcMock(returncode=1, stderr=b"network error")
    with patch(
        "shared.npm_runner.asyncio.create_subprocess_exec", return_value=fake
    ):
        err = _run(npm_runner.install(tmp_path))
    assert "npm install failed" in err
    assert "network error" in err


def test_install_succeeds_on_zero(tmp_path):
    fake = _AsyncProcMock(returncode=0)
    with patch(
        "shared.npm_runner.asyncio.create_subprocess_exec", return_value=fake
    ):
        assert _run(npm_runner.install(tmp_path)) == ""


def test_build_fails_on_nonzero(tmp_path):
    fake = _AsyncProcMock(returncode=2, stderr=b"tsc error")
    with patch(
        "shared.npm_runner.asyncio.create_subprocess_exec", return_value=fake
    ):
        err = _run(npm_runner.build(tmp_path))
    assert "npm build failed" in err
    assert "tsc error" in err


def test_build_succeeds_on_zero(tmp_path):
    fake = _AsyncProcMock(returncode=0)
    with patch(
        "shared.npm_runner.asyncio.create_subprocess_exec", return_value=fake
    ):
        assert _run(npm_runner.build(tmp_path)) == ""


def test_install_handles_timeout(tmp_path):
    async def hang_communicate(*_args, **_kwargs):
        raise TimeoutError

    fake = _AsyncProcMock(returncode=0)
    with patch(
        "shared.npm_runner.asyncio.create_subprocess_exec", return_value=fake
    ), patch.object(
        fake, "communicate", side_effect=hang_communicate
    ):
        assert "timed out" in _run(npm_runner.install(tmp_path))


def test_install_and_build_stops_on_install_failure(tmp_path):
    install_fake = _AsyncProcMock(returncode=1, stderr=b"bad")
    with patch("shared.npm_runner.shutil.which", return_value="/usr/bin/npm"), patch(
        "shared.npm_runner.asyncio.create_subprocess_exec", return_value=install_fake
    ):
        err = _run(npm_runner.install_and_build(tmp_path))
    assert "install failed" in err

"""Tests for subactor-procache integration in monag."""
from __future__ import annotations

import json
import os
import subprocess
from unittest import mock

import pytest

from monag.cache import (
    get_cache_runner,
    reset_cache_runner,
)
from monag.monitor import command
from monag.prs import github_open_prs


@pytest.fixture(autouse=True)
def clean_cache_state(tmp_path):
    """Ensure a fresh cache database and clean environment for each test."""
    reset_cache_runner()
    cache_db = tmp_path / "test_subactor_github.sqlite3"
    old_env = dict(os.environ)
    os.environ["XDG_CACHE_HOME"] = str(tmp_path)
    os.environ["MONAG_GITHUB_READ_TTL"] = "60"
    yield cache_db
    reset_cache_runner()
    os.environ.clear()
    os.environ.update(old_env)


class TestProcacheIntegration:
    def test_read_command_is_cached_in_sqlite(self, tmp_path):
        """Repeated read commands must hit cache and invoke subprocess only once."""
        call_count = 0
        fake_prs = [
            {"number": 42, "title": "Test PR", "state": "OPEN", "headRefName": "feat"}
        ]

        def fake_run(args, **kwargs):
            nonlocal call_count
            call_count += 1
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps(fake_prs),
                stderr="",
            )

        with mock.patch("subprocess.run", side_effect=fake_run):
            # First call: executes subprocess and writes to SQLite cache
            prs1, errs1 = github_open_prs("semcod/test-repo", state="open")
            assert errs1 == []
            assert prs1 == fake_prs
            assert call_count == 1

            # Second call: served directly from SQLite cache!
            prs2, errs2 = github_open_prs("semcod/test-repo", state="open")
            assert errs2 == []
            assert prs2 == fake_prs
            assert call_count == 1, "Expected second call to be served from procache without calling subprocess"

    def test_mutating_command_never_cached(self, tmp_path):
        """Mutating commands such as `gh pr merge` must never be cached."""
        call_count = 0

        def fake_run(args, **kwargs):
            nonlocal call_count
            call_count += 1
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="Merged PR #42",
                stderr="",
            )

        with mock.patch("subprocess.run", side_effect=fake_run):
            out1, err1 = command(["gh", "pr", "merge", "42", "--repo", "semcod/test-repo", "--squash"])
            assert err1 is None
            assert "Merged" in out1
            assert call_count == 1

            out2, err2 = command(["gh", "pr", "merge", "42", "--repo", "semcod/test-repo", "--squash"])
            assert err2 is None
            assert call_count == 2, "Mutating command must not be cached"

    def test_rate_limit_triggers_cooldown(self, tmp_path):
        """HTTP 429 / secondary rate limits must trigger cooldown and prevent request storm."""
        call_count = 0

        def fake_run(args, **kwargs):
            nonlocal call_count
            call_count += 1
            return subprocess.CompletedProcess(
                args=args,
                returncode=1,
                stdout="",
                stderr="HTTP 429: You have exceeded a secondary rate limit. Please wait a few minutes.",
            )

        with mock.patch("subprocess.run", side_effect=fake_run):
            # First call triggers 429 error and activates cooldown
            out1, err1 = command(["gh", "pr", "list", "--repo", "semcod/test-repo", "--json", "number"])
            assert out1 == ""
            assert "secondary rate limit" in err1 or "429" in err1
            assert call_count == 1

            # Second call during cooldown fails locally without issuing new network request
            out2, err2 = command(["gh", "pr", "list", "--repo", "semcod/test-repo", "--json", "number"])
            assert out2 == ""
            assert "cooling down" in err2 or "failed" in err2
            assert call_count == 1, "Subprocess must not be called during provider cooldown"

    def test_disable_procache_environment_override(self, tmp_path):
        """Setting MONAG_DISABLE_PROCACHE=1 disables caching and falls back to normal subprocess."""
        os.environ["MONAG_DISABLE_PROCACHE"] = "1"
        call_count = 0

        def fake_run(args, **kwargs):
            nonlocal call_count
            call_count += 1
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="[]",
                stderr="",
            )

        with mock.patch("subprocess.run", side_effect=fake_run):
            command(["gh", "pr", "list", "--repo", "semcod/test-repo", "--json", "number"])
            command(["gh", "pr", "list", "--repo", "semcod/test-repo", "--json", "number"])
            assert call_count == 2, "When procache is disabled, every call goes to subprocess"


@pytest.mark.parametrize("value", ["invalid", "nan", "inf", "-1"])
def test_invalid_ttl_uses_bounded_default(value, monkeypatch):
    monkeypatch.setenv("MONAG_GITHUB_READ_TTL", value)
    runner = get_cache_runner()
    assert runner is not None
    assert runner.ttl == 30.0


def test_timeout_is_reported_without_reexecuting_provider():
    args = ["gh", "pr", "list", "--repo", "semcod/test-repo", "--json", "number"]
    with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(args, .5)) as run:
        out, error = command(args, timeout=.5)
    assert out == ""
    assert "TimeoutExpired" in error
    assert run.call_count == 1
    assert run.call_args.kwargs["timeout"] == .5


def test_cache_failure_after_success_does_not_repeat_provider():
    from procache import SQLiteResponseCache
    args = ["gh", "pr", "list", "--repo", "semcod/test-repo", "--json", "number"]
    def load_then_fail(self, key, loader, **kwargs):
        loader()
        raise OSError("simulated cache write failure")
    with mock.patch.object(SQLiteResponseCache, "get_or_set", load_then_fail):
        with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess(args, 0, "[]", "")) as run:
            out, error = command(args)
    assert out == ""
    assert "OSError" in error
    assert run.call_count == 1


def test_explicit_cooldown_exception_never_falls_back():
    from procache import ProviderCooldownError
    runner = get_cache_runner()
    with mock.patch.object(runner, "run", side_effect=ProviderCooldownError("fixture", 30)):
        with mock.patch("subprocess.run") as run:
            out, error = command(["gh", "pr", "list", "--repo", "semcod/test-repo"])
    assert out == ""
    assert "ProviderCooldownError" in error
    run.assert_not_called()

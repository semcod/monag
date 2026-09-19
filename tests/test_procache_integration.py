"""Tests for subactor-procache integration in monag."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from monag.cache import (
    PROCACHE_AVAILABLE,
    get_cache_runner,
    reset_cache_runner,
    run_cached_gh,
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


@pytest.mark.skipif(not PROCACHE_AVAILABLE, reason="subactor-procache is not installed")
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

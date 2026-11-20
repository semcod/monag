"""ticket-153: opt-in explicit keyring identity for procache-shared gh reads."""

from __future__ import annotations

import sys
import types

import pytest

from monag import cache


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    cache.reset_cache_runner()
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN", "GH_HOST"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("MONAG_GITHUB_IDENTITY", raising=False)
    yield
    cache.reset_cache_runner()


def _procache_with_github_env(monkeypatch, *, token="test-keyring-token", fail=False):
    calls = []

    def github_env(host="github.com", env=None):
        calls.append((host, dict(env or {})))
        if fail:
            raise RuntimeError("gh missing")
        result = dict(env or {})
        result["GH_HOST"] = host
        if token:
            result["GH_TOKEN" if host == "github.com" else "GH_ENTERPRISE_TOKEN"] = token
        return result

    module = types.ModuleType("procache")
    module.github_env = github_env
    monkeypatch.setitem(sys.modules, "procache", module)
    return calls


def test_identity_is_opt_in(monkeypatch):
    calls = _procache_with_github_env(monkeypatch)
    env = {"PATH": "/usr/bin"}
    assert cache.with_github_identity(env) is env
    assert calls == []


def test_opt_in_adds_host_and_keyring_token(monkeypatch):
    monkeypatch.setenv("MONAG_GITHUB_IDENTITY", "1")
    calls = _procache_with_github_env(monkeypatch)
    env = {"PATH": "/usr/bin", "GH_PROMPT_DISABLED": "1"}
    result = cache.with_github_identity(env)
    assert result == {**env, "GH_HOST": "github.com", "GH_TOKEN": "test-keyring-token"}
    assert env == {"PATH": "/usr/bin", "GH_PROMPT_DISABLED": "1"}
    assert calls[0][0] == "github.com"


def test_existing_gh_host_is_respected(monkeypatch):
    monkeypatch.setenv("MONAG_GITHUB_IDENTITY", "1")
    _procache_with_github_env(monkeypatch)
    result = cache.with_github_identity({"GH_HOST": "Enterprise.Example"})
    assert result["GH_HOST"] == "enterprise.example"
    assert result["GH_ENTERPRISE_TOKEN"] == "test-keyring-token"
    assert "GH_TOKEN" not in result


@pytest.mark.parametrize("name", ["GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"])
def test_explicit_tokens_are_left_alone(monkeypatch, name):
    monkeypatch.setenv("MONAG_GITHUB_IDENTITY", "1")
    calls = _procache_with_github_env(monkeypatch)
    env = {name: "test-credential-a"}
    assert cache.with_github_identity(env) is env and calls == []


@pytest.mark.parametrize("kwargs", [{"token": ""}, {"fail": True}])
def test_unresolved_identity_leaves_environment_untouched(monkeypatch, kwargs):
    monkeypatch.setenv("MONAG_GITHUB_IDENTITY", "1")
    _procache_with_github_env(monkeypatch, **kwargs)
    env = {"PATH": "/usr/bin"}
    assert cache.with_github_identity(env) is env


def test_older_procache_without_github_env(monkeypatch):
    monkeypatch.setenv("MONAG_GITHUB_IDENTITY", "1")
    monkeypatch.setitem(sys.modules, "procache", types.ModuleType("procache"))
    env = {"PATH": "/usr/bin"}
    assert cache.with_github_identity(env) is env


def test_identity_is_reused_then_refreshed(monkeypatch):
    monkeypatch.setenv("MONAG_GITHUB_IDENTITY", "1")
    calls = _procache_with_github_env(monkeypatch)
    times = iter([0.0, 5.0, cache.IDENTITY_REFRESH_SECONDS + 1])
    for _ in range(3):
        cache.with_github_identity({}, clock=lambda: next(times))
    assert len(calls) == 2


def test_run_cached_gh_passes_identity_to_runner(monkeypatch):
    monkeypatch.setenv("MONAG_GITHUB_IDENTITY", "1")
    _procache_with_github_env(monkeypatch)
    seen = []

    class Runner:
        @staticmethod
        def is_read(args):
            return True

        def run(self, args, *, timeout=None, env=None):
            seen.append(env)
            return types.SimpleNamespace(returncode=0, stdout="[]", stderr="")

    monkeypatch.setattr(cache, "get_cache_runner", lambda: Runner())
    out = cache.run_cached_gh(["gh", "pr", "list", "--repo", "acme/demo"], env={"PATH": "/usr/bin"})
    assert out == ("[]", None)
    assert seen[0]["GH_TOKEN"] == "test-keyring-token" and seen[0]["GH_HOST"] == "github.com"


def test_without_opt_in_run_cached_gh_never_resolves_identity(monkeypatch):
    calls = _procache_with_github_env(monkeypatch)
    seen = []

    class Runner:
        @staticmethod
        def is_read(args):
            return True

        def run(self, args, *, timeout=None, env=None):
            seen.append(env)
            return types.SimpleNamespace(returncode=0, stdout="[]", stderr="")

    monkeypatch.setattr(cache, "get_cache_runner", lambda: Runner())
    env = {"PATH": "/usr/bin"}
    assert cache.run_cached_gh(["gh", "pr", "list", "--repo", "acme/demo"], env=env) == ("[]", None)
    assert calls == [] and seen == [env] and "GH_TOKEN" not in seen[0]

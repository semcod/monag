"""Integration with subactor-procache for read-side GitHub API caching."""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Sequence, Tuple, Optional

from procache import CachedReadCommand, SQLiteResponseCache

PROCACHE_AVAILABLE = True

_runner: Optional[CachedReadCommand] = None
_cache_path: Optional[Path] = None


def get_cache_runner(
    ttl: float | None = None,
    cache_path: Path | str | None = None,
) -> Optional[CachedReadCommand]:
    """Return a shared CachedReadCommand runner or None if unavailable/disabled."""
    global _runner, _cache_path
    if os.environ.get("MONAG_DISABLE_PROCACHE") == "1":
        return None

    if _runner is not None and ttl is None and cache_path is None:
        return _runner

    path = Path(cache_path) if cache_path else _cache_path
    if path is None:
        cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        path = cache_root / "subactor" / "github.sqlite3"

    # Bad environment input must not crash the CLI or create infinite entries.
    try:
        effective_ttl = float(ttl if ttl is not None else os.environ.get(
            "MONAG_GITHUB_READ_TTL", os.environ.get("SUBACTOR_GITHUB_READ_TTL", "30.0")
        ))
        if not math.isfinite(effective_ttl) or effective_ttl < 0:
            effective_ttl = 30.0
    except (TypeError, ValueError, OverflowError):
        effective_ttl = 30.0

    try:
        cache = SQLiteResponseCache(path, namespace="github-user")
        runner = CachedReadCommand(cache, ttl=effective_ttl)
        _runner = runner
        _cache_path = path
        return runner
    except Exception:
        return None


def reset_cache_runner() -> None:
    """Reset the cached runner (useful for tests and reinitialization)."""
    global _runner, _cache_path
    _runner = None
    _cache_path = None


def run_cached_gh(
    args: Sequence[str],
    cwd: Path | str | None = None,
    timeout: int | float = 8,
    env: dict[str, str] | None = None,
) -> Optional[Tuple[str, Optional[str]]]:
    """Attempt to execute a read-only gh command through procache.

    Returns (stdout, error) if handled by procache, or None if the command
    should be executed directly by the caller.
    """
    if not args or args[0] != "gh":
        return None

    runner = get_cache_runner()
    if runner is None or not runner.is_read(args):
        return None

    # If cwd is set and --repo is not explicitly specified, direct execution is safer
    if cwd is not None and "--repo" not in args:
        return None

    try:
        res = runner.run(args, timeout=timeout, env=env)
        if res.returncode != 0:
            operation = " ".join(args[:2]) if len(args) > 1 else args[0]
            err_msg = res.stderr.strip() or f"{operation} failed (exit {res.returncode})"
            return "", err_msg
        return res.stdout, None
    except Exception as error:
        # The provider may already have executed. Returning None would cause
        # monitor.command to repeat the request and bypass cooldown/failure.
        return "", f"gh cache: {type(error).__name__}"

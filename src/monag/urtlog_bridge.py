"""Opt-in bridge emitting Monag agent observation snapshots into a local uritime-urtlog store.

Activated strictly when ``URTLOG_STATE_DIR`` (or an explicit ``state_dir``) is
provided and ``urtlog`` is importable. Zero mandatory dependencies; all bridge
failures degrade silently so Monag observations are never interrupted.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import re
from typing import Any, Mapping

_TICKET_RE = re.compile(r"(ticket-[0-9]{3,})")


def resolve_state_dir(explicit: Path | str | None = None) -> Path | None:
    """Return configured urtlog state directory, or None when opt-in is inactive."""
    raw = str(explicit).strip() if explicit is not None else os.environ.get("URTLOG_STATE_DIR", "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def normalize_monag_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a Monag snapshot dict for urtlog.adapters.adapt_monag_snapshot."""
    pid_to_repo: dict[int, str] = {}
    for repo in snapshot.get("repositories") or ():
        if not isinstance(repo, Mapping):
            continue
        repo_name = str(repo.get("github") or repo.get("name") or Path(str(repo.get("path") or "")).name or "").strip()
        if not repo_name:
            continue
        for pid in repo.get("agents") or ():
            if isinstance(pid, int):
                pid_to_repo[pid] = repo_name

    normalized_agents: list[dict[str, Any]] = []
    for agent in snapshot.get("agents") or ():
        if not isinstance(agent, Mapping):
            continue
        pid = int(agent.get("pid") or 0)
        cwd = str(agent.get("cwd") or "")
        task_text = str(agent.get("task") or "")
        match = _TICKET_RE.search(cwd) or _TICKET_RE.search(task_text)
        ticket = match.group(1) if match else (agent.get("ticket") or f"pid-{pid}")
        repo = (
            agent.get("repository")
            or agent.get("repo")
            or pid_to_repo.get(pid)
            or (Path(cwd).name if cwd else "workspace/local")
        )
        proc_state = str(agent.get("status") or agent.get("state") or "running").lower()
        status = "failed" if proc_state in {"z", "zombie", "failed"} else "running"
        normalized_agents.append(
            {
                "pid": pid,
                "agent": str(agent.get("agent") or agent.get("kind") or "agent"),
                "repository": str(repo),
                "ticket": str(ticket),
                "status": status,
                "cwd": cwd,
                "summary": str(agent.get("summary") or task_text or f"{agent.get('kind', 'agent')} pid={pid}"),
            }
        )
    return {
        "observed_at": snapshot.get("observed_at") or snapshot.get("timestamp"),
        "agents": normalized_agents,
    }


def record_monag_snapshot(
    snapshot: Mapping[str, Any],
    *,
    state_dir: Path | str | None = None,
    sensitivity: str = "internal",
) -> int:
    """Persist a Monag observation snapshot into urtlog when opt-in is active; returns recorded count."""
    target_dir = resolve_state_dir(state_dir)
    if target_dir is None:
        return 0
    normalized = normalize_monag_snapshot(snapshot)
    if not normalized["agents"]:
        return 0
    try:
        adapters_mod = importlib.import_module("urtlog.adapters")
        sdk_mod = importlib.import_module("urtlog.sdk")
    except Exception:
        return 0
    try:
        records = adapters_mod.adapt_monag_snapshot(normalized, sensitivity=sensitivity)
        if not records:
            return 0
        client = sdk_mod.UrtClient(state_dir=target_dir, source="monag", repository="semcod/monag")
        try:
            recorded = 0
            for record in records:
                client.store.append(record)
                recorded += 1
            return recorded
        finally:
            client.close()
    except Exception:
        return 0

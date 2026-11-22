"""Tests for semcod/monag#185: live P0 autonomy probes, --budget-seconds, and usage warnings."""
from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import patch

from monag import autonomy_probes, triage, usage


def test_autonomy_probes_rank_p0_above_worktrees(tmp_path: Path) -> None:
    repo = tmp_path / "heyasa"
    (repo / ".git").mkdir(parents=True)

    w_db = tmp_path / "projects.sqlite"
    with sqlite3.connect(w_db) as conn:
        conn.execute("CREATE TABLE jobs (id TEXT, phase TEXT)")
        conn.execute("INSERT INTO jobs VALUES ('j1', 'uncertain')")

    h_plans = tmp_path / "plans.json"
    h_plans.write_text(json.dumps({"plans": [{"id": "p1", "status": "paused"}]}), encoding="utf-8")

    def fake_http(url: str, timeout: float):
        if "7655" in url:
            return 503, {"ready": False, "reason": "WILLMAN-RESOURCE-BLOCKED"}
        if "8765" in url:
            return 503, {"error": "ticket_index_stale"}
        return 200, {"status": "ok"}

    def fake_systemctl(argv):
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout="heyasa-planfile-watchdog.service loaded failed failed watchdog\n",
            stderr="",
        )

    with patch("monag.autonomy_probes._http_probe", side_effect=fake_http):
        blockers = autonomy_probes.probe_live_autonomy_blockers(
            include_runtime_probes=True,
            willman_db=w_db,
            heyasa_plans=h_plans,
            systemctl_runner=fake_systemctl,
        )
    assert len(blockers) >= 4
    report = triage.run_holistic_triage(
        tmp_path,
        depth=1,
        limit=10,
        extra_candidates=[
            {"origin": "worktree-observed", "repo": "heyasa/heyasa", "path": "/tmp/wt1", "title": "wt1", "priority": "medium"},
            *blockers,
        ],
    )
    assert report["guidance_steps"]
    assert report["guidance_steps"][0]["category"] == triage.CATEGORY_IMMEDIATE_BLOCKER
    assert "P0 Autonomy Blocker" in report["guidance_steps"][0]["title"]


def test_triage_budget_seconds_returns_partial_coverage(tmp_path: Path) -> None:
    for idx in range(5):
        (tmp_path / f"repo-{idx}" / ".git").mkdir(parents=True)
    res = triage.run_holistic_triage(tmp_path, depth=1, budget_seconds=0.0, include_runtime_probes=False)
    assert res["timed_out"] is True
    assert res["partial_coverage"] is True
    assert res["budget_seconds"] == 0.0


def test_usage_flags_stale_ledger_and_idle_long_running_agent(tmp_path: Path) -> None:
    now_ts = 1_800_000_000.0
    expired_10d = now_ts - 10 * 86400
    ledger_dir = tmp_path / "ledgers"
    ledger_dir.mkdir()
    (ledger_dir / "api-budget-codex.json").write_text(
        json.dumps({
            "schema": usage.LEDGER_SCHEMA,
            "provider": "codex",
            "remaining": 100,
            "observed_at": now_ts - 100,
            "reset_at": expired_10d,
        }),
        encoding="utf-8",
    )
    fake_proc = [{"pid": 4242, "kind": "codex", "state": "S", "cpu_seconds_tree": 2.0, "children": 0, "cwd": "/tmp", "start": "0", "descendants": []}]
    with (
        patch("monag.usage.processes", return_value=(fake_proc, 0)),
        patch("monag.usage.resident_bytes", return_value=1024),
        patch("monag.usage.uptime_seconds", return_value=2 * 86400 + 3600),
    ):
        res = usage.scan(tmp_path, ledgers=(str(ledger_dir),), proc=tmp_path / "proc", home=tmp_path, now=now_ts)

    assert "STALE_LEDGER" in res["ledgers"][0]["warnings"]
    assert "IDLE_LONG_RUNNING_AGENT" in res["agents"][0]["warnings"]
    assert res["warnings"]["stale_ledger_count"] == 1
    assert res["warnings"]["idle_long_running_agent_count"] == 1
    rendered = usage.render(res)
    assert "STALE_LEDGER" in rendered
    assert "IDLE_LONG_RUNNING_AGENT" in rendered

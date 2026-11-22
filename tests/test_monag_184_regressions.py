"""Regression tests for semcod/monag#184: advise issue number, doctor budget, and summary/day fixes."""
from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from monag.advise import advise as generate_advice
from monag.doctor import diagnose
from monag.export import audit_candidates
from monag import summary


def test_audit_candidates_preserves_issue_number_for_advise(tmp_path: Path) -> None:
    report = {
        "repositories": [
            {
                "name": "heyasa",
                "repo": "heyasa/heyasa",
                "path": str(tmp_path / "heyasa"),
                "untracked_issues": [
                    {
                        "number": 1008,
                        "title": "Fix health metrics",
                        "state": "OPEN",
                        "url": "https://github.com/heyasa/heyasa/issues/1008",
                    }
                ],
                "planfile": {"status": "present", "active_tickets": []},
                "local_tickets": [],
                "worktrees": [],
            }
        ]
    }
    candidates = audit_candidates(report)
    untracked = [c for c in candidates if c.get("origin") == "audit-untracked-issue"]
    assert len(untracked) == 1
    assert untracked[0]["issue_number"] == 1008

    with patch("monag.export.scan", return_value={"candidates": candidates}), patch(
        "monag.advise.collect_reflex_patterns", return_value={"available": False, "patterns": []}
    ):
        advice = generate_advice(tmp_path, limit=5)
    text = json.dumps(advice, ensure_ascii=False)
    assert "#1008" in text
    assert "# w" not in text


def test_doctor_agent_storage_uses_remaining_budget_and_reports_phase_cap(tmp_path: Path) -> None:
    seen_deadlines: list[float | None] = []
    now_t = [100.0]

    def fake_clock() -> float:
        return now_t[0]

    def fake_storage(home=None, deadline=None, clock=fake_clock):
        seen_deadlines.append(deadline)
        now_t[0] = 105.0
        return {"status": "PARTIAL_TIMEOUT", "corrupted_sessions": [], "detected_panics": [], "timed_out": True}

    with (
        patch("monag.doctor.audit_agent_storage_health", side_effect=fake_storage),
        patch("monag.ecosystem.audit_ecosystem_tools", return_value={}),
        patch("monag.doctor.find_git_repositories", return_value=[]),
    ):
        # Without explicit phase_budgets['agent_storage'], uses full 60s overall budget (not capped to 10s).
        res = diagnose(tmp_path, home=tmp_path, budget_seconds=60.0, clock=lambda: 100.0)
        assert seen_deadlines[-1] == 160.0

        # With explicit phase_budgets['agent_storage']=2.0 while elapsed < budget_seconds, names phase cap.
        now_t[0] = 100.0
        res2 = diagnose(
            tmp_path,
            home=tmp_path,
            budget_seconds=60.0,
            phase_budgets={"agent_storage": 2.0},
            clock=fake_clock,
        )
        assert any("phase budget cap (agent_storage=2.0s)" in rec for rec in res2["recommendations"])


def test_summary_splits_live_and_expired_leases_marks_truncated_prs_and_day_telemetry(tmp_path: Path) -> None:
    leases_dir = tmp_path / ".subactor" / "leases"
    leases_dir.mkdir(parents=True)
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (leases_dir / "ticket-1--live.json").write_text(json.dumps({"phase": "claimed", "expiresAt": future}), encoding="utf-8")
    (leases_dir / "ticket-2--exp.json").write_text(json.dumps({"phase": "claimed", "expiresAt": past}), encoding="utf-8")
    (leases_dir / "ticket-3--rel.json").write_text(json.dumps({"phase": "released", "expiresAt": past}), encoding="utf-8")

    snap = summary._scan_active_leases_snapshot(tmp_path, depth=0)
    assert snap["active_leases_count"] == 2
    assert snap["active_live_leases_count"] == 1
    assert snap["expired_non_terminal_leases_count"] == 1
    assert snap["terminal_leases_count"] == 1

    # Mock gh search prs returning exactly 50 open PRs -> truncated
    prs_50 = [{"number": i, "title": f"PR {i}", "repository": {"nameWithOwner": "o/r"}, "url": f"u/{i}", "state": "OPEN"} for i in range(50)]

    def fake_run(argv, **_):
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(prs_50), stderr="")

    with patch("monag.summary.shutil.which", return_value="/usr/bin/gh"), patch("monag.summary.subprocess.run", side_effect=fake_run):
        gh_res = summary.query_github_pr_metrics()
    assert gh_res["open_prs_count"] == 50
    assert gh_res["open_prs_truncated"] is True
    assert gh_res["merged_prs_truncated"] is False

    # Optional read-only runtime telemetry adapters for monag day
    willman_db = tmp_path / "projects.sqlite"
    with sqlite3.connect(willman_db) as conn:
        conn.execute("CREATE TABLE jobs (id TEXT, phase TEXT, updated REAL)")
        conn.execute("INSERT INTO jobs VALUES ('j1', 'uncertain', ?)", (datetime.now(timezone.utc).timestamp(),))
    heyasa_plans = tmp_path / "plans.json"
    heyasa_plans.write_text(json.dumps({"plans": [{"id": "p1", "status": "paused"}]}), encoding="utf-8")

    day = summary.gather_summary(
        tmp_path,
        github=False,
        mode="day",
        state_dir=tmp_path,
        telemetry_paths={"willman_db": willman_db, "heyasa_plans": heyasa_plans},
    )
    rt = day["delta_24h"]["runtime_telemetry_24h"]
    assert rt["enabled"] is True
    assert rt["willman_jobs_24h"] == 1
    assert rt["willman_uncertain_jobs"] == 1
    assert rt["heyasa_paused_plans"] == 1

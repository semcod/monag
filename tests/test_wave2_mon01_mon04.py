"""Comprehensive unit tests for Wave 2 (`MON-01`..`MON-04`, issues #162..#165)."""
from __future__ import annotations

from datetime import date, datetime, timezone
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from monag import autodiagnosis, cli, doctor, summary, triage, worktrees


class Mon01AutonomyStallProbeTests(unittest.TestCase):
    """MON-01 (#162): Deterministic autonomy stall probes & top ranking in autodiagnose."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _init_hygiene_repo(self, rel_path: str) -> Path:
        repo = self.root / rel_path
        repo.mkdir(parents=True)
        subprocess.run(["git", "-C", str(repo), "init", "-b", "main"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
        # Leave missing LICENSE & README + raw git+ URL + dirty file to create floor & hygiene defects
        (repo / "pyproject.toml").write_text('[project]\ndependencies = ["x @ git+https://example.invalid/x.git"]\n', encoding="utf-8")
        (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
        return repo

    def test_systemd_daemon_status_and_load_stall_probes_rank_above_repo_hygiene(self) -> None:
        self._init_hygiene_repo("semcod/noisy-repo")

        systemctl_stdout = "\n\n".join(
            [
                "Id=subactor-coding-agent.service\nLoadState=loaded\nActiveState=failed\nSubState=failed\nResult=exit-code\nExecMainStatus=1",
                "Id=subactor-pr-controller.service\nLoadState=loaded\nActiveState=failed\nSubState=failed\nResult=exit-code\nExecMainStatus=2",
                "Id=subactor-repair-agent.service\nLoadState=loaded\nActiveState=failed\nSubState=failed\nResult=exit-code\nExecMainStatus=1",
                "Id=subactor-autonom-user.service\nLoadState=loaded\nActiveState=failed\nSubState=failed\nResult=exit-code\nExecMainStatus=1",
                "Id=heyasa.service\nLoadState=loaded\nActiveState=active\nSubState=running\nResult=success\nExecMainStatus=0",
            ]
        )

        heyasa_payload = {
            "schema": "heyasa.daemon-status/v1",
            "velocity_status": {
                "is_degraded": True,
                "completed_count": 0,
                "target_capacity": 12,
                "open_candidates_count": 71,
                "summary": "DEGRADED: 0 completed vs 12 target with 71 open candidates",
            },
            "last_result": {
                "willman": {
                    "flowguard": {
                        "eligible_projects": 0,
                        "admitted_slots": 0,
                        "blocked_candidates": 63,
                        "blocked_reasons": {"active_lease_fenced": 63},
                        "project_exclusions": {"semcod/monag": "active_lease"},
                    }
                }
            },
        }

        def fake_systemctl(cmd, **kwargs):
            self.assertEqual(cmd[:3], ["systemctl", "--user", "show"])
            self.assertLessEqual(kwargs.get("timeout", 99), 3.0)
            return subprocess.CompletedProcess(cmd, 0, systemctl_stdout, "")

        stall_anomalies = autodiagnosis.probe_autonomy_health(
            self.root,
            systemctl_runner=fake_systemctl,
            heyasa_payload=heyasa_payload,
            load_fn=lambda: (43.6, 38.0, 29.5),
            cpu_count_fn=lambda: 16,
        )
        codes = [a["code"] for a in stall_anomalies]
        self.assertEqual(codes.count("AUTONOMY_UNIT_FAILED"), 4)
        self.assertIn("AUTONOMY_ELIGIBLE_PROJECTS_ZERO", codes)
        self.assertIn("AUTONOMY_ADMISSION_STALL", codes)
        self.assertIn("AUTONOMY_VELOCITY_STALL", codes)
        self.assertIn("HOST_LOAD_SATURATION", codes)
        self.assertEqual(len(stall_anomalies), 8)

        with patch("monag.autodiagnosis.probe_autonomy_health", return_value=stall_anomalies):
            diag = autodiagnosis.diagnose_fleet(self.root, depth=2, use_cache=False)
            tickets = autodiagnosis.synthesize_tickets_with_subllm(diag, runner=None)

        # Every single operational stall anomaly & ticket MUST rank strictly above repo defects/hygiene
        top_8_codes = [a["code"] for a in diag["anomalies"][:8]]
        for code in top_8_codes:
            self.assertNotIn(code, {"NO_LICENSE", "NO_README", "HIGH_WORKTREE_COUNT", "DIRTY_WORKTREE", "DEPENDENCY_GIT_URL_FOUND"})

        top_8_tickets = tickets[:8]
        self.assertTrue(all(t.get("autonomy_probe") is True for t in top_8_tickets))
        self.assertTrue(all(t.get("weight", 0) >= 850 for t in top_8_tickets))
        repo_tickets = tickets[8:]
        self.assertGreaterEqual(len(repo_tickets), 3)
        self.assertTrue(all(t.get("autonomy_probe") is False for t in repo_tickets))

    def test_host_load_warning_threshold_and_graceful_degradation(self) -> None:
        # Warning threshold: 1.5x < 26.0 / 16 <= 2.0x
        warn_findings = autodiagnosis.probe_autonomy_health(
            self.root,
            systemctl_runner=lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError("no systemctl")),
            http_opener=lambda *a, **kw: (_ for _ in ()).throw(OSError("connection refused")),
            load_fn=lambda: (26.0, 20.0, 15.0),
            cpu_count_fn=lambda: 16,
        )
        self.assertEqual(len(warn_findings), 1)
        self.assertEqual(warn_findings[0]["code"], "HOST_LOAD_SATURATION")
        self.assertEqual(warn_findings[0]["severity"], "WARNING")
        self.assertGreater(warn_findings[0]["weight"], 0)

        # Healthy host + missing systemctl + unreachable daemon => 0 findings, no crash
        healthy = autodiagnosis.probe_autonomy_health(
            self.root,
            systemctl_runner=lambda *a, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired("systemctl", 2.5)),
            http_opener=lambda *a, **kw: (_ for _ in ()).throw(TimeoutError("timed out")),
            load_fn=lambda: (4.0, 3.0, 2.0),
            cpu_count_fn=lambda: 16,
        )
        self.assertEqual(healthy, [])

    def test_non_loopback_heyasa_url_is_refused_without_network_io(self) -> None:
        called = []

        def forbidden_opener(*args, **kwargs):
            called.append(args)
            raise AssertionError("external URL must never be opened")

        findings = autodiagnosis.probe_autonomy_health(
            self.root,
            units=(),
            heyasa_status_url="https://example.com/v1/daemon/status",
            http_opener=forbidden_opener,
            load_fn=lambda: (1.0, 1.0, 1.0),
            cpu_count_fn=lambda: 8,
        )
        self.assertEqual(findings, [])
        self.assertEqual(called, [])


class Mon02DoctorBudgetAndLeaseHoistTests(unittest.TestCase):
    """MON-02 (#163): O(1) lease reading per repo & monotonic time budget partial output."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _make_repo(self, rel_path: str) -> Path:
        repo = self.root / rel_path
        repo.mkdir(parents=True)
        subprocess.run(["git", "-C", str(repo), "init", "-b", "main"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
        (repo / "README.md").write_text("seed\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "seed"], check=True, capture_output=True)
        return repo

    def test_audit_worktrees_reads_repo_leases_once_for_many_worktrees(self) -> None:
        repo = self._make_repo("org/multi-wt")
        leases_dir = repo / ".subactor" / "leases"
        leases_dir.mkdir(parents=True)

        for idx in range(1, 9):
            wt_dir = repo / ".worktrees" / f"ticket-{idx:03d}--slice"
            subprocess.run(
                ["git", "-C", str(repo), "worktree", "add", "-b", f"ticket/{idx:03d}-slice", str(wt_dir), "main"],
                check=True,
                capture_output=True,
            )
            (leases_dir / f"ticket-{idx:03d}--slice.json").write_text(
                json.dumps(
                    {
                        "schema": "wellmanifest.change-lease/v1",
                        "ticketId": f"ticket-{idx:03d}",
                        "worktreeId": f"ticket-{idx:03d}--slice",
                        "branchRef": f"refs/heads/ticket/{idx:03d}-slice",
                        "phase": "editing",
                    }
                ),
                encoding="utf-8",
            )

        with (
            patch("monag.worktrees.get_repo_leases", wraps=worktrees.get_repo_leases) as spy_leases,
            patch("monag.worktrees.resolve_default_target_branch", wraps=worktrees.resolve_default_target_branch) as spy_target,
        ):
            audited = doctor.audit_worktrees(repo)

        secondary = [w for w in audited if not w["is_primary"]]
        self.assertEqual(len(secondary), 8)
        self.assertTrue(all(not w["stale"] for w in secondary))
        self.assertEqual(spy_leases.call_count, 1)
        self.assertEqual(spy_target.call_count, 1)

    def test_diagnose_returns_structured_partial_report_when_budget_expires(self) -> None:
        for idx in range(1, 5):
            self._make_repo(f"org/repo-{idx}")

        fake_now = [100.0]

        def fake_clock() -> float:
            return fake_now[0]

        orig_audit_wt = doctor.audit_worktrees

        def slow_audit_wt(repo: Path, **kwargs):
            res = orig_audit_wt(repo, **kwargs)
            # Advance monotonic clock past budget after auditing first repository
            fake_now[0] += 0.6
            return res

        fake_home = self.root / "empty_home"
        fake_home.mkdir()

        with patch("monag.doctor.audit_worktrees", side_effect=slow_audit_wt):
            report = doctor.diagnose(
                self.root,
                home=fake_home,
                budget_seconds=0.5,
                clock=fake_clock,
            )

        self.assertTrue(report["timed_out"])
        self.assertEqual(report["budget_seconds"], 0.5)
        self.assertIn("environment", report["completed_phases"])
        self.assertIn("ecosystem_tools", report["completed_phases"])
        self.assertIn("repositories", report["timed_out_phases"])
        self.assertIn("agent_storage", report["skipped_phases"])
        self.assertEqual(report["repositories_checked"], 1)
        self.assertEqual(len(report["skipped_repositories"]), 3)
        self.assertEqual(report["errors"], [])

    def test_cli_doctor_timeout_flag_outputs_valid_json(self) -> None:
        repo = self._make_repo("org/cli-doc")
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            rc = cli.main(["doctor", "--root", str(repo), "--timeout", "15", "--json"])
        self.assertEqual(rc, 0)
        parsed = json.loads(buf.getvalue())
        self.assertEqual(parsed["budget_seconds"], 15.0)
        self.assertIn("timed_out", parsed)
        self.assertIn("completed_phases", parsed)
        self.assertIn("skipped_repositories", parsed)


class Mon03DayVsSummarySeparationTests(unittest.TestCase):
    """MON-03 (#164): Distinct `day` (24h delta) vs `summary` (portfolio snapshot) + source labels."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state_dir = self.root / ".state"
        (self.state_dir / "tasks").mkdir(parents=True)

        repo = self.root / "semcod" / "monag"
        sprints = repo / ".planfile" / "sprints"
        sprints.mkdir(parents=True)
        leases = repo / ".subactor" / "leases"
        leases.mkdir(parents=True)

        self.today = date(2026, 11, 14)
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        now_epoch = datetime.now(timezone.utc).timestamp()

        current_sprint = {
            "data": {
                "sprint": {
                    "tickets": {
                        "PLF-101": {
                            "name": "Completed today feature",
                            "status": "done",
                            "updated_at": f"{self.today.isoformat()}T09:00:00Z",
                        },
                        "PLF-102": {
                            "name": "Queued open work",
                            "status": "open",
                            "priority": "high",
                            "estimated_duration_seconds": 900,
                        },
                        "PLF-103": {
                            "name": "In-progress ticket",
                            "status": "in_progress",
                            "priority": "critical",
                            "estimated_duration_seconds": 600,
                        },
                        "PLF-104": {
                            "name": "Blocked on upstream dependency",
                            "status": "blocked",
                            "updated_at": now_iso,
                            "blocked_reason": "waiting on validator pin",
                        },
                    }
                }
            }
        }
        (sprints / "current.yaml.fast.json").write_text(json.dumps(current_sprint), encoding="utf-8")

        (leases / "ticket-137--active.json").write_text(
            json.dumps(
                {
                    "schema": "wellmanifest.change-lease/v1",
                    "ticketId": "ticket-137",
                    "phase": "editing",
                }
            ),
            encoding="utf-8",
        )

        # Agent run records in <state_dir>/tasks/*.json
        (self.state_dir / "tasks" / "run-ok.json").write_text(
            json.dumps(
                {
                    "pid": 12345,
                    "start": "100",
                    "cwd": str(repo),
                    "task": "Implement MON-03",
                    "ticket": "ticket-137",
                    "status": "completed",
                    "updated": now_epoch - 120,
                }
            ),
            encoding="utf-8",
        )
        (self.state_dir / "tasks" / "run-fail.json").write_text(
            json.dumps(
                {
                    "pid": 12346,
                    "start": "101",
                    "cwd": str(repo),
                    "task": "Broken executor run",
                    "ticket": "ticket-136",
                    "status": "failed",
                    "updated": now_epoch - 60,
                }
            ),
            encoding="utf-8",
        )

    def test_day_and_summary_produce_distinct_json_and_markdown_with_source_labels(self) -> None:
        mock_prs = {
            "open_prs_count": 4,
            "merged_prs_count": 2,
            "opened_prs_count": 3,
            "open_prs": [{"repo": "semcod/monag", "number": 170, "title": "Open PR", "url": "https://x/170"}],
            "merged_prs": [{"repo": "semcod/monag", "number": 169, "title": "Merged PR", "url": "https://x/169"}],
            "opened_prs": [{"repo": "semcod/monag", "number": 170, "title": "Open PR", "state": "OPEN", "url": "https://x/170"}],
        }
        with patch("monag.summary.query_github_pr_metrics", return_value=mock_prs):
            day_data = summary.gather_day(
                self.root,
                hours=24,
                github=True,
                target_date=self.today,
                depth=2,
                state_dir=self.state_dir,
            )
            sum_data = summary.gather_summary(
                self.root,
                hours=24,
                github=True,
                target_date=self.today,
                depth=2,
                state_dir=self.state_dir,
                mode="summary",
            )

        self.assertEqual(day_data["mode"], "day")
        self.assertEqual(day_data["report_kind"], "day_24h_delta")
        self.assertEqual(sum_data["mode"], "summary")
        self.assertEqual(sum_data["report_kind"], "portfolio_queue_snapshot")

        # Day captures 24h operational delta (agent runs, new blockers, merged/opened PRs)
        self.assertIn("delta_24h", day_data)
        self.assertNotIn("portfolio_snapshot", day_data)
        self.assertEqual(day_data["delta_24h"]["agent_runs_completed"], 1)
        self.assertEqual(day_data["delta_24h"]["agent_runs_failed"], 1)
        self.assertEqual(day_data["delta_24h"]["new_blockers_count"], 1)
        self.assertEqual(day_data["delta_24h"]["merged_prs_count"], 2)
        self.assertEqual(day_data["delta_24h"]["opened_prs_count"], 3)

        # Summary captures current portfolio/queue snapshot (queued, blocked, all entries, active leases, open PRs)
        self.assertIn("portfolio_snapshot", sum_data)
        self.assertNotIn("delta_24h", sum_data)
        self.assertEqual(sum_data["portfolio_snapshot"]["queued_actionable"], 2)
        self.assertEqual(sum_data["portfolio_snapshot"]["in_progress"], 1)
        self.assertEqual(sum_data["portfolio_snapshot"]["blocked_total"], 1)
        self.assertEqual(sum_data["portfolio_snapshot"]["all_current_sprint_entries"], 4)
        self.assertEqual(sum_data["portfolio_snapshot"]["active_leases_count"], 1)
        self.assertEqual(sum_data["portfolio_snapshot"]["open_prs_count"], 4)

        # Every count in both modes MUST carry explicit source, scope, and filter labels
        for payload in (day_data, sum_data):
            self.assertTrue(payload["counts_labeled"])
            for metric_name, meta in payload["counts_labeled"].items():
                self.assertIn("value", meta, metric_name)
                self.assertTrue(meta.get("source"), f"{metric_name} missing source")
                self.assertTrue(meta.get("scope"), f"{metric_name} missing scope")
                self.assertTrue(meta.get("filter"), f"{metric_name} missing filter")

        day_md = summary.format_markdown(day_data)
        sum_md = summary.format_markdown(sum_data)
        self.assertNotEqual(day_md, sum_md)
        self.assertIn("MONAG 24h Operational Delta", day_md)
        self.assertIn("MONAG Portfolio & Queue Summary", sum_md)
        self.assertIn("źródło:", day_md)
        self.assertIn("filtr:", day_md)
        self.assertIn("źródło:", sum_md)
        self.assertIn("filtr:", sum_md)

    def test_cli_day_and_summary_commands_emit_distinct_reports(self) -> None:
        day_buf = io.StringIO()
        sum_buf = io.StringIO()
        with patch("sys.stdout", day_buf):
            rc_day = cli.main(
                ["--root", str(self.root), "--state-dir", str(self.state_dir), "day", "--no-github", "--markdown"]
            )
        with patch("sys.stdout", sum_buf):
            rc_sum = cli.main(
                ["--root", str(self.root), "--state-dir", str(self.state_dir), "summary", "--no-github", "--markdown"]
            )
        self.assertEqual(rc_day, 0)
        self.assertEqual(rc_sum, 0)
        self.assertNotEqual(day_buf.getvalue(), sum_buf.getvalue())
        self.assertIn("24h Operational Delta", day_buf.getvalue())
        self.assertIn("Portfolio & Queue Summary", sum_buf.getvalue())


class Mon04TriageDeduplicationAndImpactSortTests(unittest.TestCase):
    """MON-04 (#165): Collapse repeated `(repo, cause)` findings & sort by unblock impact descending."""

    def test_collapses_fifteen_duplicate_repo_worktree_rows_and_sorts_by_unblock_impact(self) -> None:
        raw_candidates = [
            # Single low-impact code smell in repo-smell
            {
                "repo": "semcod/tagi",
                "origin": "audit-untracked-issue",
                "title": "Address code smell: dead code in legacy adapter",
                "priority": "low",
            },
            # Single worktree observation in small-repo
            {
                "repo": "other/small-repo",
                "origin": "worktree-observed",
                "path": "/workspace/other/small-repo/.worktrees/ticket-001--minor",
                "title": "Registered worktree to inspect: ticket-001--minor",
                "priority": "medium",
            },
        ]
        # 15 identical worktree-observed rows in forge (reproducing the incident report)
        for idx in range(1, 16):
            raw_candidates.append(
                {
                    "repo": "heyasa/forge",
                    "origin": "worktree-observed",
                    "path": f"/workspace/heyasa/forge/.worktrees/ticket-{idx:03d}--task",
                    "title": f"Registered worktree to inspect: ticket-{idx:03d}--task",
                    "priority": "medium",
                }
            )
        # 1 critical immediate blocker in subactor/coding-agent
        raw_candidates.append(
            {
                "repo": "subactor/coding-agent",
                "origin": "diagnostics",
                "title": "Critical blocker: executor service crashed on startup",
                "priority": "critical",
            }
        )

        ranked = triage.deduplicate_and_rank_candidates(raw_candidates, collisions_by_repo={})
        # 18 raw candidates collapse into 4 unique (repo, cause) groups!
        self.assertEqual(len(ranked), 4)

        # Verify descending unblock impact order:
        # 1. Critical immediate blocker (subactor/coding-agent)
        # 2. 15-worktree bottleneck (heyasa/forge, affected_count=15)
        # 3. Single worktree observation (other/small-repo, affected_count=1)
        # 4. Single code smell (semcod/tagi, affected_count=1)
        repos_in_order = [item["repo"] for item in ranked]
        self.assertEqual(
            repos_in_order,
            ["subactor/coding-agent", "heyasa/forge", "other/small-repo", "semcod/tagi"],
        )

        impacts = [item["estimated_unblock_impact"] for item in ranked]
        self.assertEqual(impacts, sorted(impacts, reverse=True))

        forge_entry = ranked[1]
        self.assertEqual(forge_entry["affected_count"], 15)
        self.assertEqual(forge_entry["cause"], "worktree-observed")
        self.assertEqual(len(forge_entry["sample_items"]), 5)
        self.assertEqual(forge_entry["sample_items"][0], "ticket-001--task")
        self.assertNotIn("active", forge_entry["title"].lower())
        self.assertIn("15 observed", forge_entry["title"])

    def test_run_holistic_triage_propagates_grouped_fields_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "heyasa" / "forge"
            repo.mkdir(parents=True)
            subprocess.run(["git", "-C", str(repo), "init", "-b", "main"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "seed"],
                check=True,
                capture_output=True,
            )
            for idx in range(1, 5):
                wt = repo / ".worktrees" / f"ticket-{idx:03d}--dup"
                subprocess.run(
                    ["git", "-C", str(repo), "worktree", "add", "-b", f"ticket/{idx:03d}-dup", str(wt), "main"],
                    check=True,
                    capture_output=True,
                )

            with patch("monag.triage.audit_active_fleet_processes", return_value=[]):
                report = triage.run_holistic_triage(root, depth=2, limit=15)

            self.assertEqual(report["total_candidates"], 4)
            self.assertEqual(report["deduplicated_candidates_count"], 1)
            self.assertEqual(len(report["guidance_steps"]), 1)

            step = report["guidance_steps"][0]
            self.assertEqual(step["repo"], "heyasa/forge")
            self.assertEqual(step["affected_count"], 4)
            self.assertEqual(len(step["sample_items"]), 4)
            self.assertGreater(step["estimated_unblock_impact"], 0)

            md = triage.triage_markdown(report)
            self.assertIn("Deduplicated Action Groups", md)
            self.assertIn("Affected**: `4`", md)
            self.assertIn("Sample Items (4/4)", md)


if __name__ == "__main__":
    unittest.main()

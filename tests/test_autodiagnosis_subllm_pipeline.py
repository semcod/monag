import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import yaml

from monag import autodiagnosis, cli


class TestAutodiagnosisFleetInspection(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_inspect_repository_anomalies_detects_defects(self):
        # Create a mock git repository with multiple defects
        repo = self.root / "org" / "test-repo"
        repo.mkdir(parents=True)
        subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)

        # Missing README, LICENSE, Planfile
        anomalies = autodiagnosis.inspect_repository_anomalies(repo)
        codes = {a["code"] for a in anomalies}
        self.assertIn("NO_README", codes)
        self.assertIn("NO_LICENSE", codes)
        self.assertIn("PLANFILE_UNINITIALIZED", codes)

        # Add README and LICENSE
        (repo / "README.md").write_text("# Test Repo")
        (repo / "LICENSE").write_text("Apache-2.0")
        (repo / ".planfile" / "sprints").mkdir(parents=True)

        anomalies_after = autodiagnosis.inspect_repository_anomalies(repo)
        codes_after = {a["code"] for a in anomalies_after}
        self.assertNotIn("NO_README", codes_after)
        self.assertNotIn("NO_LICENSE", codes_after)
        self.assertNotIn("PLANFILE_UNINITIALIZED", codes_after)
        self.assertIn("PLANFILE_GITHUB_SYNC_MISSING", codes_after)

    def test_inspect_dependency_git_url(self):
        repo = self.root / "org" / "py-repo"
        repo.mkdir(parents=True)
        subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
        (repo / "pyproject.toml").write_text('[project]\ndependencies = ["pkg @ git+https://github.com/foo/bar"]\n')

        anomalies = autodiagnosis.inspect_repository_anomalies(repo)
        codes = {a["code"] for a in anomalies}
        self.assertIn("DEPENDENCY_GIT_URL_FOUND", codes)

    def test_diagnose_fleet_discovers_workspace_repositories(self):
        r1 = self.root / "org1" / "repo-a"
        r2 = self.root / "org2" / "repo-b"
        r1.mkdir(parents=True)
        r2.mkdir(parents=True)
        subprocess.run(["git", "-C", str(r1), "init"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(r2), "init"], check=True, capture_output=True)

        report = autodiagnosis.diagnose_fleet(self.root, depth=2)
        self.assertEqual(report["schema"], autodiagnosis.SCHEMA)
        self.assertEqual(report["repositories_checked"], 2)
        self.assertGreater(report["anomalies_count"], 0)

    def test_diagnose_fleet_with_sqlite_caching(self):
        r1 = self.root / "org1" / "cached-repo"
        r1.mkdir(parents=True)
        subprocess.run(["git", "-C", str(r1), "init"], check=True, capture_output=True)

        state_dir = self.root / "state"
        # First diagnostic pass: cache miss, saves to SQLite
        rep1 = autodiagnosis.diagnose_fleet(self.root, depth=2, state_dir=state_dir)
        self.assertEqual(rep1["repositories_cached"], 0)

        # Synthesize so tickets and snapshots are committed to SQLite cache
        autodiagnosis.synthesize_tickets_with_subllm(rep1)

        # Second diagnostic pass on unchanged repo: cache hit!
        rep2 = autodiagnosis.diagnose_fleet(self.root, depth=2, state_dir=state_dir)
        self.assertEqual(rep2["repositories_cached"], 1)


class TestSubLLMTicketSynthesis(unittest.TestCase):
    def test_synthesize_tickets_with_mock_subllm_runner(self):
        anomaly = {
            "code": "NO_README",
            "tier": autodiagnosis.TIER_HYGIENE,
            "severity": "WARNING",
            "target": "subactor/core",
            "summary": "Repository is missing a README.md file.",
            "evidence": "No README found in repository root.",
        }

        mock_llm_json = json.dumps({
            "title": "[subactor/core] docs: add comprehensive project README and architecture overview",
            "target_repo": "subactor/core",
            "tier": "hygiene",
            "priority": "medium",
            "action": "Author standard README.md with quickstart, test instructions, and architecture boundaries.",
            "acceptance_criteria": [
                "AC-01: README.md is created with installation and verification steps.",
                "AC-02: Document conforms to wellmanifest.docs standard."
            ],
            "verification_command": "test -f README.md && npm test",
            "satisfied_when": "README.md exists and documentation checks pass.",
            "labels": ["monag", "autodiagnosis", "docs", "koru-autonomous"]
        })

        def fake_runner(prompt):
            self.assertIn("subactor/core", prompt)
            return mock_llm_json

        tickets = autodiagnosis.synthesize_tickets_with_subllm([anomaly], runner=fake_runner)
        self.assertEqual(len(tickets), 1)
        t = tickets[0]

        self.assertEqual(t["target_repo"], "subactor/core")
        self.assertEqual(t["priority"], "medium")
        self.assertIn("AC-01: README.md is created", t["description"])
        self.assertIn("AC-02: Document conforms", t["description"])
        self.assertIn("## Planfile & Koru Autonomous Handoff", t["description"])
        self.assertIn("planfile ticket done", t["description"])
        self.assertIn("npm test", t["verification_command"])

    def test_synthesize_tickets_fallback_without_subllm(self):
        anomaly = {
            "code": "DEPENDENCY_GIT_URL_FOUND",
            "tier": autodiagnosis.TIER_FLOOR,
            "severity": "WARNING",
            "target": "semcod/diagit",
            "summary": "Repository contains raw Git URL dependency.",
            "evidence": "pyproject.toml has git+ URL.",
        }

        # Runner returns empty/error, triggering deterministic fallback
        def failing_runner(prompt):
            raise ConnectionError("No API route")

        tickets = autodiagnosis.synthesize_tickets_with_subllm([anomaly], runner=failing_runner)
        self.assertEqual(len(tickets), 1)
        t = tickets[0]
        self.assertEqual(t["target_repo"], "semcod/diagit")
        self.assertEqual(t["priority"], "critical")
        self.assertIn("AC-01: Repository contains raw Git URL dependency", t["description"])
        self.assertIn("AC-02: Verification checks", t["description"])
        self.assertIn("## Empirical Resource Estimation (semcod/estimation)", t["description"])
        self.assertIn("estimation", t)
        self.assertGreater(t["estimation"]["duration_p90_seconds"], 0)
        self.assertIn("planfile ticket done", t["description"])


class TestPlanfileDispatchAndKoruIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_dispatch_tickets_to_planfile_creates_sprint_yaml(self):
        repo_dir = self.root / "subactor" / "runtime"
        repo_dir.mkdir(parents=True)
        subprocess.run(["git", "-C", str(repo_dir), "init"], check=True, capture_output=True)

        tickets = [
            {
                "title": "[subactor/runtime] fix: resolve uncommitted artifacts",
                "description": "## Context\nTest\n\n## Acceptance Criteria\n- [ ] AC-01: Clean repo",
                "target_repo": "subactor/runtime",
                "tier": "floor",
                "priority": "critical",
                "labels": ["monag", "autodiagnosis"],
                "satisfied_when": "Clean git status",
                "created_at": "2026-09-25T14:00:00Z",
            }
        ]

        res = autodiagnosis.dispatch_tickets_to_planfile(tickets, root=self.root, sprint="current")
        self.assertEqual(res["dispatched"], 1)
        self.assertEqual(len(res["errors"]), 0)

        sprint_file = repo_dir / ".planfile" / "sprints" / "current.yaml"
        self.assertTrue(sprint_file.is_file())

        sprint_data = yaml.safe_load(sprint_file.read_text())
        self.assertEqual(sprint_data["schema"], "planfile.sprint/v1")
        self.assertEqual(len(sprint_data["tasks"]), 1)
        task = sprint_data["tasks"][0]
        self.assertEqual(task["title"], "[subactor/runtime] fix: resolve uncommitted artifacts")
        self.assertEqual(task["status"], "todo")
        self.assertEqual(task["priority"], "critical")

        # Test idempotency - running dispatch again must not duplicate existing task
        res2 = autodiagnosis.dispatch_tickets_to_planfile(tickets, root=self.root, sprint="current")
        self.assertEqual(res2["dispatched"], 0)
        sprint_data2 = yaml.safe_load(sprint_file.read_text())
        self.assertEqual(len(sprint_data2["tasks"]), 1)

    def test_planfile_github_sync_and_koru_queue_contracts(self):
        repo_dir = self.root / "semcod" / "mcp"
        repo_dir.mkdir(parents=True)
        subprocess.run(["git", "-C", str(repo_dir), "init"], check=True, capture_output=True)

        ticket = {
            "title": "[semcod/mcp] chore(deps): upgrade vulnerable dependencies",
            "description": (
                "## Context\nObserved outdated libraries.\n\n"
                "## Acceptance Criteria\n- [ ] AC-01: Bump version\n- [ ] AC-02: Tests pass\n\n"
                "## Planfile & Koru Autonomous Handoff\n"
                "- When checks pass, run: `planfile ticket done task_123`"
            ),
            "target_repo": "semcod/mcp",
            "tier": "hygiene",
            "priority": "medium",
            "labels": ["monag", "autodiagnosis", "tier:hygiene"],
            "satisfied_when": "All dependencies up to date.",
            "created_at": "2026-09-25T14:30:00Z",
        }

        autodiagnosis.dispatch_tickets_to_planfile([ticket], root=self.root, sprint="current")
        sprint_file = repo_dir / ".planfile" / "sprints" / "current.yaml"
        data = yaml.safe_load(sprint_file.read_text())
        saved_task = data["tasks"][0]

        # 1. Compatibility with planfile sync github
        self.assertIn("id", saved_task)
        self.assertIn("title", saved_task)
        self.assertIn("description", saved_task)
        self.assertIn("priority", saved_task)
        self.assertIn("labels", saved_task)

        # 2. Compatibility with koru autonomous queue handoff
        self.assertIn("AC-01", saved_task["description"])
        self.assertIn("planfile ticket done", saved_task["description"])


class TestCLIAutodiagnose(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        # Create a repo inside root
        repo = self.root / "test-project"
        repo.mkdir()
        subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cli_autodiagnose_emit_planfile(self):
        ret = cli.main(["--root", str(self.root), "autodiagnose", "--no-subllm", "--emit-planfile"])
        self.assertEqual(ret, 0)

    def test_cli_autodiagnose_feed_planfile(self):
        ret = cli.main(["--root", str(self.root), "autodiagnose", "--no-subllm", "--feed-planfile", "--sprint", "current"])
        self.assertEqual(ret, 0)

        # Verify that sprint file was created in test-project
        sprint_file = self.root / "test-project" / ".planfile" / "sprints" / "current.yaml"
        self.assertTrue(sprint_file.is_file())

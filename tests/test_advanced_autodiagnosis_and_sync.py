from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from monag import autodiagnosis, panel


class TestAdvancedAutodiagnosis(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_detect_git_conflict_markers(self):
        repo = self.root / "conflict-repo"
        repo.mkdir(parents=True)
        subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@test.com"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test User"], check=True)

        bad_file = repo / "main.py"
        bad_file.write_text("<<<<<<< HEAD\nprint('ours')\n=======\nprint('theirs')\n>>>>>>> branch\n")
        subprocess.run(["git", "-C", str(repo), "add", "main.py"], check=True)

        anomalies = autodiagnosis.inspect_repository_anomalies(repo)
        codes = {a["code"]: a for a in anomalies}
        self.assertIn("GIT_CONFLICT_MARKERS", codes)
        self.assertEqual(codes["GIT_CONFLICT_MARKERS"]["tier"], "floor")
        self.assertEqual(codes["GIT_CONFLICT_MARKERS"]["severity"], "ERROR")

    def test_detect_broken_virtualenv(self):
        repo = self.root / "broken-venv-repo"
        repo.mkdir(parents=True)
        subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
        (repo / "pyproject.toml").write_text("[project]\nname='test'\n")

        # Incomplete venv without python
        venv_dir = repo / ".venv"
        venv_dir.mkdir(parents=True)

        anomalies = autodiagnosis.inspect_repository_anomalies(repo)
        codes = {a["code"]: a for a in anomalies}
        self.assertIn("BROKEN_VENV", codes)
        self.assertEqual(codes["BROKEN_VENV"]["tier"], "floor")

    def test_sync_planfile_github_success(self):
        repo = self.root / "sync-repo"
        repo.mkdir(parents=True)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Synced 2 issues", stderr="")
            res = autodiagnosis.sync_planfile_github(repo)
            self.assertTrue(res["ok"])
            self.assertEqual(res["exit_code"], 0)
            self.assertIn("Synced 2 issues", res["stdout"])

    def test_dispatch_tickets_with_sync_github(self):
        repo = self.root / "dispatched-repo"
        repo.mkdir(parents=True)
        (repo / ".git").mkdir()

        tickets = [
            {
                "title": "[dispatched-repo] Fix defect",
                "description": "Fix defect",
                "target_repo": "dispatched-repo",
                "tier": "floor",
                "priority": "critical",
                "created_at": "2026-09-25T12:00:00Z",
            }
        ]

        with patch("monag.autodiagnosis.sync_planfile_github") as mock_sync:
            mock_sync.return_value = {"target": str(repo), "ok": True, "exit_code": 0}
            res = autodiagnosis.dispatch_tickets_to_planfile(tickets, root=self.root, sync_github=True)
            self.assertEqual(res["dispatched"], 1)
            self.assertEqual(len(res["github_sync"]), 1)
            self.assertTrue(res["github_sync"][0]["ok"])

    def test_panel_sync_github_endpoint(self):
        repo = self.root / "panel-repo"
        repo.mkdir(parents=True)
        (repo / ".planfile").mkdir()

        state = panel.State(root=self.root, state_dir=self.root / ".state")
        with patch("monag.autodiagnosis.sync_planfile_github") as mock_sync:
            mock_sync.return_value = {"target": str(repo), "ok": True, "exit_code": 0}
            res = state.autodiagnosis_sync_github()
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["synced_repositories"], 1)
            self.assertTrue(res["results"][0]["ok"])

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

    def test_ignore_decorative_separator_lines(self):
        repo = self.root / "separator-repo"
        repo.mkdir(parents=True)
        subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@test.com"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test User"], check=True)

        clean_file = repo / "LICENSE"
        clean_file.write_text("================================================================================\nNOTICE\n")
        subprocess.run(["git", "-C", str(repo), "add", "LICENSE"], check=True)

        anomalies = autodiagnosis.inspect_repository_anomalies(repo)
        codes = {a["code"]: a for a in anomalies}
        self.assertNotIn("GIT_CONFLICT_MARKERS", codes)

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

    def test_detect_willman_daemon_log_error(self):
        repo = self.root / "willman-repo"
        repo.mkdir(parents=True)
        (repo / ".git").mkdir()
        logs_dir = repo / ".willman" / "logs"
        logs_dir.mkdir(parents=True)
        dlog = logs_dir / "daemon-8780.log"
        dlog.write_text(
            "Traceback (most recent call last):\n"
            "  File 'willman/rest.py', line 186, in respond\n"
            "    self.wfile.write(raw)\n"
            "BrokenPipeError: [Errno 32] Broken pipe\n"
        )

        anomalies = autodiagnosis.inspect_repository_anomalies(repo)
        codes = {a["code"]: a for a in anomalies}
        self.assertIn("SYSTEM_LOG_ERROR", codes)
        self.assertEqual(codes["SYSTEM_LOG_ERROR"]["tier"], "floor")
        self.assertEqual(codes["SYSTEM_LOG_ERROR"]["severity"], "ERROR")
        self.assertIn("willman", codes["SYSTEM_LOG_ERROR"]["summary"].lower())
        self.assertIn("Broken pipe", codes["SYSTEM_LOG_ERROR"]["evidence"])

    def test_detect_willman_task_ndjson_failure(self):
        repo = self.root / "willman-task-repo"
        repo.mkdir(parents=True)
        (repo / ".git").mkdir()
        logs_dir = repo / ".willman" / "logs"
        logs_dir.mkdir(parents=True)
        ndjson = logs_dir / "task-01.ndjson"
        ndjson.write_text('{"task_id": "t-1", "status": "failed", "error": "ConnectionRefusedError: port 8765 unreachable"}\n')

        anomalies = autodiagnosis.inspect_repository_anomalies(repo)
        codes = {a["code"]: a for a in anomalies}
        self.assertIn("SYSTEM_LOG_ERROR", codes)
        self.assertEqual(codes["SYSTEM_LOG_ERROR"]["tier"], "floor")
        self.assertIn("failed task execution", codes["SYSTEM_LOG_ERROR"]["summary"].lower())

    def test_detect_willmux_agent_log_and_event_failures(self):
        repo = self.root / "willmux"
        repo.mkdir(parents=True)
        (repo / ".git").mkdir()
        cfg_dir = repo / ".config" / "willmux"
        cfg_dir.mkdir(parents=True)

        # agent-log.jsonl with error
        (cfg_dir / "agent-log.jsonl").write_text(
            '{"t": 1791189900, "src": "agent", "msg": "Docker socket /var/run/docker.sock unreachable", "level": "error"}\n'
        )

        anomalies = autodiagnosis.inspect_repository_anomalies(repo, willmux_config_dir=cfg_dir)
        codes = {a["code"]: a for a in anomalies}
        self.assertIn("SYSTEM_LOG_ERROR", codes)
        self.assertIn("Docker socket", codes["SYSTEM_LOG_ERROR"]["summary"])

    def test_system_log_error_synthesis_and_opencode_dispatch(self):
        anomaly = {
            "code": "SYSTEM_LOG_ERROR",
            "tier": "floor",
            "severity": "ERROR",
            "target": "willman",
            "summary": "Runtime system error detected in willman daemon log: BrokenPipeError",
            "evidence": "BrokenPipeError: [Errno 32] Broken pipe",
        }

        tickets = autodiagnosis.synthesize_tickets_with_subllm([anomaly], runner=None)
        self.assertEqual(len(tickets), 1)
        t = tickets[0]
        self.assertEqual(t["target_repo"], "willman")
        self.assertEqual(t["priority"], "critical")
        self.assertEqual(t["tier"], "floor")

        # Dispatch to planfile in target repo
        target_dir = self.root / "willman"
        target_dir.mkdir(parents=True)
        (target_dir / ".git").mkdir()

        res = autodiagnosis.dispatch_tickets_to_planfile(tickets, root=self.root)
        self.assertEqual(res["dispatched"], 1)

        import yaml
        sprint_content = yaml.safe_load((target_dir / ".planfile" / "sprints" / "current.yaml").read_text())
        task_entry = sprint_content["tasks"][0]
        self.assertEqual(task_entry["inputs"]["provider"], "opencode")
        self.assertEqual(task_entry["inputs"]["runner"], "opencode")
        self.assertTrue(task_entry["inputs"]["patch_mode"])
        self.assertEqual(task_entry["inputs"]["contract"], "wellmanifest.defect-repair/v1")
        self.assertEqual(task_entry["executor"]["runner"], "opencode")
        t_id = task_entry["id"]
        self.assertEqual(sprint_content["sprint"]["tickets"][t_id]["inputs"]["provider"], "opencode")


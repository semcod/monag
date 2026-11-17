"""Bounded procfs observations, PID reuse and visibility failures."""
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch

from monag import autodiagnosis as diagnosis


class HostZombieTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.proc = Path(temporary.name)
        self.root = self.proc / "workspace"

    def process(self, pid, parent=1, state="S", start=100, name="worker"):
        directory = self.proc / str(pid)
        directory.mkdir(exist_ok=True)
        # stat field 22 is starttime; command names may contain spaces and ')'.
        fields = [state, str(parent)] + ["0"] * 17 + [str(start)]
        (directory / "stat").write_text(f"{pid} ({name}) " + " ".join(fields))

    def probe(self, **kwargs):
        return diagnosis._probe_host_zombies(self.root, self.proc, **kwargs)

    def test_grouped_parents_use_start_identity_and_no_command_line_reads(self):
        self.process(10, start=777, name="worker ) with spaces")
        self.process(20, start=888)
        self.process(11, parent=10, state="Z")
        self.process(12, parent=10, state="Z")
        self.process(21, parent=20, state="Z")
        finding, = self.probe()
        self.assertEqual(finding["code"], "HOST_UNREAPED_CHILDREN")
        details = finding["details"]
        self.assertEqual(details["zombies_observed"], 3)
        self.assertEqual([(p["pid"], p["start_ticks"], p["zombies"]) for p in details["parents"]],
                         [(10, 777, 2), (20, 888, 1)])
        self.assertFalse(details["partial"])
        self.assertFalse(details["history_available"])
        self.assertEqual(details["trend"], "unknown")

    def test_reused_parent_pid_is_not_attributed_to_new_identity(self):
        self.process(11, parent=10, state="Z")
        read = diagnosis._read_process_state
        starts = iter([777, 888])

        def changing_parent(path):
            return ("S", 1, next(starts)) if path.name == "10" else read(path)

        with patch.object(diagnosis, "_read_process_state", side_effect=changing_parent):
            parent = self.probe()[0]["details"]["parents"][0]
        self.assertIsNone(parent["start_ticks"])
        self.assertEqual(parent["identity_status"], "unavailable_or_changed")

    def test_missing_parent_keeps_count_without_guessing_identity(self):
        self.process(11, parent=10, state="Z")
        details = self.probe()[0]["details"]
        self.assertEqual(details["zombies_observed"], 1)
        self.assertIsNone(details["parents"][0]["start_ticks"])

    def test_missing_procfs_does_not_report_health(self):
        result = diagnosis._probe_host_zombies(self.root, self.proc / "absent")
        self.assertEqual(result[0]["code"], "HOST_PROCESS_VISIBILITY_PARTIAL")
        self.assertIn("procfs_unavailable", result[0]["details"]["partial_reasons"])

    def test_malformed_or_denied_stat_is_explicitly_partial(self):
        self.process(10)
        (self.proc / "10/stat").write_text("malformed")
        details = self.probe()[0]["details"]
        self.assertEqual(details["unreadable_processes"], 1)
        with patch.object(diagnosis, "_read_process_state", side_effect=PermissionError):
            self.assertTrue(self.probe()[0]["details"]["partial"])

    def test_process_budget_stops_reads_and_reports_partial(self):
        self.process(10)
        with patch.object(diagnosis, "_read_process_state") as read:
            details = self.probe(max_processes=0)[0]["details"]
        read.assert_not_called()
        self.assertEqual(details["processes_scanned"], 0)
        self.assertIn("process_limit", details["partial_reasons"])

    def test_time_budget_stops_before_reading(self):
        self.process(10)
        moments = iter([0.0, 1.0])
        with patch.object(diagnosis, "_read_process_state") as read:
            details = self.probe(clock=lambda: next(moments))[0]["details"]
        read.assert_not_called()
        self.assertIn("time_budget", details["partial_reasons"])

    def test_parent_output_is_bounded_but_total_is_preserved(self):
        for number in range(12):
            self.process(100 + number, parent=200 + number, state="Z")
        details = self.probe()[0]["details"]
        self.assertEqual(details["zombies_observed"], 12)
        self.assertEqual(len(details["parents"]), 8)
        self.assertEqual(details["omitted_parent_groups"], 4)

    def test_healthy_visible_snapshot_has_no_anomaly(self):
        self.process(10)
        self.assertEqual(self.probe(), [])

    def test_generated_verification_refuses_zombies_and_incomplete_visibility(self):
        for code in ("HOST_UNREAPED_CHILDREN", "HOST_PROCESS_VISIBILITY_PARTIAL"):
            ticket = diagnosis._parse_subllm_response("", {"code": code, "target": "host/system"})
            script = shlex.split(ticket["verification_command"])[2]
            with patch.object(diagnosis, "_probe_host_zombies", return_value=[]):
                exec(script, {})
            with patch.object(diagnosis, "_probe_host_zombies", return_value=[{"code": code}]):
                with self.assertRaises(AssertionError):
                    exec(script, {})

    def test_autonomy_probe_includes_zombies_and_global_disable_still_applies(self):
        self.process(11, parent=10, state="Z")
        with patch.object(diagnosis, "_probe_systemd_user_units", return_value=[]), \
                patch.object(diagnosis, "_probe_heyasa_daemon_status", return_value=[]), \
                patch.object(diagnosis, "_probe_host_load_saturation", return_value=[]), \
                patch.dict(diagnosis.os.environ, {"MONAG_DISABLE_AUTONOMY_PROBES": "0"}):
            result = diagnosis.probe_autonomy_health(self.root, proc_root=self.proc)
            self.assertEqual(result[0]["code"], "HOST_UNREAPED_CHILDREN")
            with patch.dict(diagnosis.os.environ, {"MONAG_DISABLE_AUTONOMY_PROBES": "1"}):
                self.assertEqual(diagnosis.probe_autonomy_health(self.root, proc_root=self.proc), [])


if __name__ == "__main__":
    unittest.main()

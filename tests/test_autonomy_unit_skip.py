"""ExecCondition skips are reported as AUTONOMY_UNIT_SKIPPED, not as failures."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from monag import autodiagnosis


def _runner(stdout: str):
    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout, "")
    return run


def _unit(uid: str, active: str, sub: str, result: str, status: str = "0") -> str:
    return f"Id={uid}\nLoadState=loaded\nActiveState={active}\nSubState={sub}\nResult={result}\nExecMainStatus={status}"


class AutonomyUnitSkipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def probe(self, *units: str):
        return autodiagnosis._probe_systemd_user_units(self.root, runner=_runner("\n\n".join(units)))

    def test_exec_condition_skip_is_medium_skip_not_critical_failure(self) -> None:
        anomalies = self.probe(_unit("subactor-repair-agent.service", "inactive", "dead", "exec-condition"))
        self.assertEqual([a["code"] for a in anomalies], ["AUTONOMY_UNIT_SKIPPED"])
        skip = anomalies[0]
        self.assertEqual(skip["severity"], "MEDIUM")
        self.assertTrue(skip["autonomy_probe"])
        self.assertEqual(skip["details"]["unit"], "subactor-repair-agent.service")
        self.assertEqual(skip["target"], autodiagnosis.AUTONOMY_UNIT_TARGETS.get("subactor-repair-agent.service", "subactor/autonom"))

    def test_condition_crash_that_leaves_unit_failed_stays_critical(self) -> None:
        # ExecCondition exit 255 makes systemd mark the unit failed (coding-agent on 2026-11-14).
        anomalies = self.probe(_unit("subactor-coding-agent.service", "failed", "failed", "exit-code", "0"))
        self.assertEqual([a["code"] for a in anomalies], ["AUTONOMY_UNIT_FAILED"])
        self.assertEqual(anomalies[0]["severity"], "CRITICAL")

    def test_other_inactive_non_success_results_stay_failures(self) -> None:
        for result in ("exit-code", "timeout", "signal", "start-limit-hit"):
            with self.subTest(result=result):
                codes = [a["code"] for a in self.probe(_unit("subactor-autonom-user.service", "inactive", "dead", result))]
                self.assertEqual(codes, ["AUTONOMY_UNIT_FAILED"])

    def test_healthy_units_report_nothing(self) -> None:
        self.assertEqual(self.probe(
            _unit("subactor-repair-agent.service", "inactive", "dead", "success"),
            _unit("heyasa.service", "active", "running", "success"),
        ), [])

    def test_skip_ranks_below_failures_and_has_a_remediation(self) -> None:
        anomalies = self.probe(
            _unit("subactor-repair-agent.service", "inactive", "dead", "exec-condition"),
            _unit("subactor-pr-controller.service", "failed", "failed", "exit-code", "200"),
        )
        by_code = {a["code"]: a for a in anomalies}
        self.assertLess(by_code["AUTONOMY_UNIT_SKIPPED"]["weight"], by_code["AUTONOMY_UNIT_FAILED"]["weight"])
        skipped = by_code["AUTONOMY_UNIT_SKIPPED"]
        with patch.object(autodiagnosis, "_find_subllm_runner", return_value=None):
            ticket, = autodiagnosis.synthesize_tickets_with_subllm([skipped])
        self.assertIn("ExecCondition", ticket["description"])

    def test_model_restart_cannot_replace_observed_skip(self) -> None:
        skipped, failed = self.probe(
            _unit("subactor-repair-agent.service", "inactive", "dead", "exec-condition"),
            _unit("subactor-pr-controller.service", "failed", "failed", "exit-code"),
        )
        runner = Mock(return_value=json.dumps({
            "title": "Restart the service", "action": "systemctl --user restart service",
            "acceptance_criteria": ["Unit is active"],
        }))
        tickets = autodiagnosis.synthesize_tickets_with_subllm([skipped, failed], runner=runner)
        by_code = {t["source"]["context"]["code"]: t for t in tickets}
        ticket = by_code["AUTONOMY_UNIT_SKIPPED"]
        self.assertNotIn("restart", ticket["description"].lower())
        self.assertIn("ExecCondition", ticket["verification_command"])
        self.assertIn("subactor-repair-agent.service", ticket["verification_command"])
        self.assertIn("Result=exec-condition", ticket["description"])
        self.assertFalse(ticket["inputs"]["expect_files_changed"])
        self.assertEqual(by_code["AUTONOMY_UNIT_FAILED"]["title"], "Restart the service")
        self.assertEqual(runner.call_count, 1)


if __name__ == "__main__":
    unittest.main()

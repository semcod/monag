import json
from pathlib import Path
import tempfile
import unittest

from monag import estimation


class TestEstimationIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.samples_file = Path(self.temp_dir.name) / "process-samples.jsonl"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_derive_process_uri(self):
        self.assertEqual(
            estimation.derive_process_uri("pytest -q tests/", "semcod/monag"),
            "testql://semcod/monag/query/tests"
        )
        self.assertEqual(
            estimation.derive_process_uri("git status --porcelain", "semcod/monag"),
            "artifact://semcod/monag/registry/query/check"
        )
        self.assertEqual(
            estimation.derive_process_uri("monag doctor --fix", "semcod/monag"),
            "control://semcod/monag/remediation/execute"
        )

    def test_estimate_verification_with_samples(self):
        # Create mock process samples
        samples = [
            {
                "schema": "semcod.estimation.sample/v1",
                "sample_id": f"sample:{i}",
                "ticket_id": "TICKET-1",
                "process_uri": "testql://semcod/monag/query/tests",
                "process_key": "testql://semcod/monag/query/tests",
                "program": "pytest",
                "duration_seconds": 2.0 + (i * 0.5),
                "peak_rss_bytes": (100 + i * 10) * 1024 * 1024,
                "effective_cpu_cores": 0.75 + (i * 0.05),
                "outcome": "succeeded",
                "exit_code": 0,
            }
            for i in range(5)
        ]
        self.samples_file.write_text("\n".join(json.dumps(s) for s in samples) + "\n")

        est = estimation.estimate_verification(
            "pytest -q tests/",
            "semcod/monag",
            store_path=self.samples_file
        )
        self.assertEqual(est["source"], "semcod.estimation")
        self.assertGreater(est["duration_p90_seconds"], 2.0)
        self.assertGreater(est["peak_rss_mb"], 90.0)
        self.assertEqual(est["confidence"], "medium")
        self.assertEqual(est["samples_count"], 5)

        # Markdown formatting check
        md = estimation.format_estimation_markdown(est)
        self.assertIn("## Empirical Resource Estimation (semcod/estimation)", md)
        self.assertIn(f"**{est['duration_p90_seconds']}s** (p90)", md)
        self.assertIn(f"{est['peak_rss_mb']} MB", md)

    def test_estimate_verification_fallback_when_no_samples(self):
        non_existent = Path(self.temp_dir.name) / "empty.jsonl"
        est = estimation.estimate_verification("some_unknown_cmd", "org/repo", store_path=non_existent)
        self.assertEqual(est["source"], "default_envelope")
        self.assertEqual(est["confidence"], "none")
        self.assertGreater(est["duration_p90_seconds"], 0)


if __name__ == "__main__":
    unittest.main()

"""The frozen summary probe runs isolated (`python -I -S -B`) and reports what the function returns."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

PROBE = Path(__file__).resolve().parent / "acceptance" / "summary_probe.py"
DAY = "2026-11-12"
HISTORY = f"history-{DAY}.yaml.fast.json"
STAMP = "2026-11-12T07:28:19.332203+00:00"


def sprint(tickets):
    return {"data": {"sprint": {"tickets": tickets}}}


def ticket(status, updated=None, **extra):
    row = {"name": "task", "status": status, "created_at": "2026-11-10T08:00:00.000000Z"}
    if updated:
        row["updated_at"] = updated
    row.update(extra)
    return row


def probe(request):
    return subprocess.run([sys.executable, "-I", "-S", "-B", str(PROBE)], input=json.dumps(request),
                          capture_output=True, text=True, timeout=30)


class SummaryAcceptanceProbeTests(unittest.TestCase):
    def answer(self, view, files):
        done = probe({"date": DAY, "view": view, "sprints": files})
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_an_empty_tree_has_no_work(self):
        self.assertEqual(self.answer("counts", {}),
                         {"completed_count": 0, "completed_ids": [], "queued_count": 0})

    def test_done_history_entries_are_completed(self):
        files = {HISTORY: sprint({"PLF-1": ticket("done", STAMP), "PLF-2": ticket("done", STAMP)})}
        self.assertEqual(self.answer("counts", files),
                         {"completed_count": 2, "completed_ids": ["PLF-1", "PLF-2"], "queued_count": 0})

    def test_the_current_queue_is_not_completed(self):
        files = {"current.yaml.fast.json": sprint({"PLF-1": ticket("open"), "PLF-2": ticket("in_progress"),
                                                   "PLF-3": ticket("blocked")})}
        self.assertEqual(self.answer("counts", files),
                         {"completed_count": 0, "completed_ids": [], "queued_count": 2})

    def test_current_tickets_finished_today_are_completed_and_yesterday_is_not(self):
        today = {"current.yaml.fast.json": sprint({"PLF-1": ticket("done", STAMP),
                                                   "PLF-2": ticket("completed", STAMP)})}
        self.assertEqual(self.answer("counts", today)["completed_ids"], ["PLF-1", "PLF-2"])
        yesterday = {"current.yaml.fast.json": sprint({"PLF-1": ticket("done", "2026-11-11T20:00:00.000000+00:00")})}
        self.assertEqual(self.answer("counts", yesterday)["completed_count"], 0)

    def test_a_short_finish_time_is_reported_unchanged(self):
        files = {HISTORY: sprint({"PLF-1": ticket("done", execution={"finished_at": "07:28:19"})})}
        self.assertEqual(self.answer("times", files), {"finished_at": {"PLF-1": "07:28:19"}})

    def test_the_probe_refuses_what_it_does_not_define(self):
        changes = (
            {"sprints": {"history-2026-11-11.yaml.fast.json": {}}},  # another day's history
            {"sprints": {"../outside.json": {}}},
            {"view": "everything"},
        )
        for change in changes:
            with self.subTest(change=change):
                request = {"date": DAY, "view": "counts", "sprints": {}}
                request.update(change)
                done = probe(request)
                self.assertNotEqual(done.returncode, 0)
                self.assertEqual(done.stdout, "")


if __name__ == "__main__":
    unittest.main()

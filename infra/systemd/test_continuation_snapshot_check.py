from datetime import datetime, timezone
import json
from pathlib import Path
import runpy
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).with_name("check-continuation-snapshot.py")
inspect_snapshot = runpy.run_path(str(SCRIPT))["inspect_snapshot"]
NOW = datetime(2026, 11, 24, 21, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(("change", "expected"), [
    ({}, "fresh"),
    ({"observed_at": "2026-11-24T20:58:59Z"}, "stale"),
    ({"observed_at": "2026-11-24T20:59:00Z"}, "fresh"),
    ({"observed_at": "2026-11-24T21:01:00Z"}, "future-timestamp"),
    ({"observed_at": "2026-11-24T21:00:00"}, "invalid-document"),
    ({"observed_at": 5}, "invalid-document"),
    ({"schema": "other"}, "wrong-schema"),
    ({"root": "/wrong"}, "wrong-workspace-or-projects"),
    ({"projects": None}, "wrong-workspace-or-projects"),
])
def test_validity_and_freshness(tmp_path, change, expected):
    report = {"schema": "monag.resume/v1", "root": str(tmp_path), "projects": [], "observed_at": NOW.isoformat()}
    f = tmp_path / "report.json"
    f.write_text(json.dumps(dict(report, **change)))
    result = inspect_snapshot(f, tmp_path, NOW, 60)
    assert result["state"] == expected and result["bytes"] == f.stat().st_size


def test_failed_and_recovered_observations_share_target_and_cause(tmp_path):
    path = tmp_path / "snapshot.json"
    cmd = [sys.executable, str(SCRIPT), "--root", str(tmp_path), "--target", "continuation",
           "--snapshot", str(path), "--max-age-seconds", "60", "--last-observation", str(tmp_path / "last.json")]
    missing = json.loads(subprocess.check_output(cmd))
    assert json.loads(subprocess.check_output(cmd)) == missing
    path.touch()
    invalid = json.loads(subprocess.check_output(cmd))
    path.write_text(json.dumps({"schema": "monag.resume/v1", "root": str(tmp_path), "projects": [],
                                "observed_at": datetime.now(timezone.utc).isoformat()}))
    recovered = json.loads(subprocess.check_output(cmd))
    assert json.loads(subprocess.check_output(cmd)) == recovered
    assert len({row["source_event_id"] for row in (missing, invalid, recovered)}) == 3
    assert [row["status"] for row in [missing, invalid, recovered]] == ["failure", "failure", "success"]
    assert [row["evidence"]["state"] for row in [missing, invalid, recovered]] == ["missing", "invalid-document", "fresh"]
    assert len({(row["operation"], row["task_id"], row["failure_code"]) for row in [missing, invalid, recovered]}) == 1

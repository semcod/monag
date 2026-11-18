import json
from datetime import date

import pytest
import yaml

from monag.summary import format_markdown, gather_summary

DAY = date(2026, 11, 12)
STAMP = "2026-11-13T00:05:32.123456+02:00"


def write_sprint(repo, name, rows, layout):
    directory = repo / ".planfile" / "sprints"
    directory.mkdir(exist_ok=True, parents=True)
    path = directory / f"{name}.yaml"
    doc = {"sprint": {"tickets": rows}}
    if layout == "fast":
        path.with_suffix(".yaml.fast.json").write_text(json.dumps({"data": doc}))
    else:
        if layout == "legacy":
            doc = {"tasks": [dict(id=key, **row) for key, row in rows.items()]}
        path.write_text(yaml.safe_dump(doc))


@pytest.mark.parametrize("layout", ["fast", "yaml", "legacy"])
@pytest.mark.parametrize("mode", ["day", "summary"])
def test_daily_report_deduplicates_within_repo_and_preserves_finish(layout, mode, tmp_path):
    done = {"status": "done", "execution": {"finished_at": STAMP}}
    write_sprint(tmp_path / "first", f"history-{DAY}", {
        "A": done, "reopened": done, "blocked": {"status": "blocked"},
        "failed": {"status": "failed"}, "missing_status": {"updated_at": STAMP},
    }, layout)
    write_sprint(tmp_path / "first", "current", {
        "A": {"status": "completed", "updated_at": "2026-11-14T10:00:00Z"},
        "reopened": {"status": "open", "estimated_duration_seconds": 125},
        "older": {"status": "done", "created_at": str(DAY), "updated_at": str(DAY),
                  "finished_at": "2026-11-12T00:00:05+01:00"},
        "undated": {"status": "completed", "finished_at": "unknown", "created_at": str(DAY)},
    }, layout)
    write_sprint(tmp_path / "second", "current", {"A": {"status": "done", "updated_at": STAMP}}, layout)
    report = gather_summary(tmp_path, github=False, target_date=DAY, mode=mode)
    data = report["planfile"]
    assert data["completed_today"] == 2
    assert [(row["repo"], row["id"], row["finished_at"], row["finished_at_source"])
            for row in data["completed_tickets"]] == [
                ("first", "A", STAMP, "execution.finished_at"), ("second", "A", STAMP, "updated_at")]
    assert data["unknown_completion_time_count"] == 1
    assert "bez daty ukończenia: 1" in format_markdown(report)
    if mode == "summary":
        assert data["queued"] == 1
        assert data["estimated_minutes"] == 2
    assert report["github"]["merged_prs_count"] == 0


@pytest.mark.parametrize("cache", ["{", json.dumps({"yaml_mtime_ns": 1, "data": {"sprint": {"tickets": {}}}})])
def test_unusable_cache_falls_back_to_source_yaml(tmp_path, cache):
    write_sprint(tmp_path, "current", {"ok": {"status": "done", "finished_at": STAMP}}, "yaml")
    (tmp_path / ".planfile/sprints/current.yaml.fast.json").write_text(cache)
    data = gather_summary(tmp_path, github=False, target_date=DAY)["planfile"]
    assert [row["id"] for row in data["completed_tickets"]] == ["ok"]

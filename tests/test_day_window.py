"""`monag day --hours N` reports a rolling N-hour GitHub window (ticket-140)."""

from __future__ import annotations

import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from monag import summary

_EMPTY_PRS = {
    "open_prs_count": 0,
    "merged_prs_count": 0,
    "opened_prs_count": 0,
    "open_prs": [],
    "merged_prs": [],
    "opened_prs": [],
}


def test_day_queries_github_from_now_minus_hours(tmp_path: Path) -> None:
    before = datetime.now(timezone.utc)
    with patch("monag.summary.query_github_pr_metrics", return_value=dict(_EMPTY_PRS)) as gh:
        data = summary.gather_summary(tmp_path, hours=12, github=True, mode="day", state_dir=tmp_path)
    after = datetime.now(timezone.utc)

    since = gh.call_args.kwargs["since"]
    assert before - timedelta(hours=12, seconds=1) <= since <= after - timedelta(hours=12) + timedelta(seconds=1)
    window = data["github_window_since"]
    assert window == since.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert data["counts_labeled"]["github_merged_prs_24h"]["filter"].endswith(f"merged:>={window}")

    md = summary.format_markdown(data)
    assert "MONAG 12h Operational Delta" in md
    assert "## 2. 12h Delta — GitHub Pull Requests" in md
    assert f"Zmergowane PR (>= {window})" in md
    assert "24h" not in md
    assert "dzień kalendarzowy" in md


def test_pinned_date_and_summary_keep_calendar_day(tmp_path: Path) -> None:
    pinned = date(2026, 9, 25)
    with patch("monag.summary.query_github_pr_metrics", return_value=dict(_EMPTY_PRS)) as gh:
        day_data = summary.gather_summary(
            tmp_path, hours=12, github=True, target_date=pinned, mode="day", state_dir=tmp_path
        )
        assert gh.call_args.kwargs["since"] is None
        summary.gather_summary(tmp_path, hours=12, github=True, mode="summary", state_dir=tmp_path)
        assert gh.call_args.kwargs["since"] is None
    assert day_data["github_window_since"] == "2026-09-25"


def test_query_passes_timestamp_qualifier_to_gh() -> None:
    since = datetime(2026, 11, 17, 8, 49, 34, tzinfo=timezone.utc)
    calls: list[list[str]] = []

    def _run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="[]", stderr="")

    with patch("monag.summary.shutil.which", return_value="/usr/bin/gh"), patch(
        "monag.summary.subprocess.run", side_effect=_run
    ):
        summary.query_github_pr_metrics(target_date=date(2026, 11, 17), since=since)

    flat = [" ".join(argv) for argv in calls]
    assert any("--merged-at >=2026-11-17T08:49:34Z" in item for item in flat)
    assert any("--created >=2026-11-17T08:49:34Z" in item for item in flat)


def test_integral_float_hours_render_without_decimal(tmp_path: Path) -> None:
    with patch("monag.summary.query_github_pr_metrics", return_value=dict(_EMPTY_PRS)):
        data = summary.gather_summary(tmp_path, hours=12.0, github=True, mode="day", state_dir=tmp_path)  # type: ignore[arg-type]
    md = summary.format_markdown(data)
    assert "MONAG 12h Operational Delta" in md
    assert "12.0h" not in md

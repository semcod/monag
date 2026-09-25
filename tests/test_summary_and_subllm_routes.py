import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from monag import summary
from monag.autodiagnosis import _find_subllm_runner


def test_subllm_route_invocation_koru_agent():
    mock_complete = MagicMock()
    mock_resp = MagicMock()
    mock_resp.content = '{"analysis": "ok"}'
    mock_complete.return_value = mock_resp

    with patch.dict("sys.modules", {"subllm": MagicMock(complete=mock_complete), "subllm.client_types": MagicMock(CompletionResponse=type(mock_resp))}):
        runner = _find_subllm_runner()
        assert runner is not None
        result = runner("diagnose repo")
        assert result == '{"analysis": "ok"}'
        mock_complete.assert_called_once_with(
            "koru-agent",
            "nl-to-koru-dsl",
            [{"role": "user", "content": "diagnose repo"}],
            timeout_seconds=30.0,
        )


def test_subllm_route_fallback_todo2code():
    mock_complete = MagicMock()
    mock_resp = MagicMock()
    mock_resp.content = '{"fallback": "todo2code"}'
    # First call raises, second succeeds
    mock_complete.side_effect = [RuntimeError("Route not found"), mock_resp]

    with patch.dict("sys.modules", {"subllm": MagicMock(complete=mock_complete), "subllm.client_types": MagicMock(CompletionResponse=type(mock_resp))}):
        runner = _find_subllm_runner()
        assert runner is not None
        result = runner("diagnose fallback")
        assert result == '{"fallback": "todo2code"}'
        assert mock_complete.call_count == 2
        mock_complete.assert_any_call(
            "todo2code",
            "semantic",
            [{"role": "user", "content": "diagnose fallback"}],
            timeout_seconds=30.0,
        )


def test_gather_planfile_daily(tmp_path: Path):
    sprints_dir = tmp_path / ".planfile" / "sprints"
    sprints_dir.mkdir(parents=True)

    current_data = {
        "data": {
            "sprint": {
                "tickets": {
                    "T-001": {
                        "name": "Fix Bug",
                        "status": "done",
                        "updated_at": "2026-09-25T10:00:00Z",
                    },
                    "T-002": {
                        "name": "Add Feature",
                        "status": "open",
                        "priority": "high",
                        "estimated_duration_seconds": 600,
                    },
                }
            }
        }
    }
    (sprints_dir / "current.yaml.fast.json").write_text(json.dumps(current_data))

    from datetime import date
    target = date(2026, 9, 25)
    data = summary.gather_planfile_daily(tmp_path, target_date=target)

    assert data["completed_count"] == 1
    assert data["queued_count"] == 1
    assert data["total_estimated_minutes"] == 10
    assert data["completed_tickets"][0]["id"] == "T-001"
    assert data["queued_tickets"][0]["id"] == "T-002"
    assert data["queued_tickets"][0]["priority"] == "high"


def test_gather_summary_and_markdown(tmp_path: Path):
    with patch("monag.summary.gather_planfile_daily") as mock_pf, patch("monag.summary.query_github_pr_metrics") as mock_gh:
        mock_pf.return_value = {
            "date": "2026-09-25",
            "completed_count": 3,
            "queued_count": 2,
            "total_estimated_minutes": 45,
            "completed_tickets": [
                {"repo": "semcod/monag", "id": "PLF-001", "title": "Done Task 1"},
            ],
            "queued_tickets": [
                {"repo": "semcod/monag", "id": "PLF-002", "title": "Queued Task 1", "priority": "high"},
            ],
        }
        mock_gh.return_value = {
            "open_prs_count": 1,
            "merged_prs_count": 2,
            "open_prs": [],
            "merged_prs": [],
        }

        data = summary.gather_summary(tmp_path, hours=24, github=True)
        assert data["schema"] == summary.SCHEMA
        assert data["planfile"]["completed_today"] == 3
        assert data["planfile"]["queued"] == 2
        assert data["github"]["open_prs_count"] == 1
        assert data["github"]["merged_prs_count"] == 2

        md = summary.format_markdown(data)
        assert "MONAG Daily Execution Summary (2026-09-25)" in md
        assert "**Wykonane dzisiaj**: `3` zadań" in md
        assert "**Oczekujące w kolejce**: `2` zadań (szacunkowo `45 min`" in md
        assert "**Otwarte PR w kolejce**: `1`" in md
        assert "**Zmergowane dzisiaj (>= 2026-09-25)**: `2`" in md
        assert "Done Task 1" in md
        assert "Queued Task 1" in md

"""Acceptance tests for ticket-122: reuse audit open_prs_count in monag advise."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from monag import advise, export


def test_export_scan_exposes_open_prs_count_in_audit_sources(tmp_path: Path) -> None:
    fake_audit = {
        "repository_count": 2,
        "errors": [],
        "repositories": [
            {"name": "repo-a", "path": str(tmp_path / "a"), "open_prs": [{"number": 1}, {"number": 2}], "issues": []},
            {"name": "repo-b", "path": str(tmp_path / "b"), "open_prs": [{"number": 3}], "issues": []},
        ],
    }
    fake_catalog = {"repository_count": 2, "repositories": []}
    fake_resume = {"project_count": 0, "projects": []}

    with (
        patch("monag.export.audit.scan", return_value=fake_audit),
        patch("monag.export.catalog.scan", return_value=fake_catalog),
        patch("monag.export.resume.scan", return_value=fake_resume),
    ):
        res = export.scan(tmp_path)

    assert res["sources"]["audit"]["open_prs_count"] == 3


def test_advise_reuses_export_open_prs_count_without_calling_prs_scan(tmp_path: Path) -> None:
    fake_export = {
        "candidates": [],
        "sources": {
            "audit": {
                "repository_count": 2,
                "open_prs_count": 7,
                "errors": 0,
            }
        },
    }
    fake_reflex = {"available": False, "patterns": [], "proposals": []}

    with (
        patch("monag.advise.collect_reflex_patterns", return_value=fake_reflex),
        patch("monag.prs.scan", side_effect=AssertionError("prs.scan must not be called when export_data has open_prs_count")),
        patch("monag.audit.targets", return_value=("workspace", [], None)),
        patch("monag.audit.collect_worktrees", return_value={"worktrees": [{"path": "wt1"}], "repos_with_worktrees": 1}),
    ):
        res = advise.advise(tmp_path, export_data=fake_export, include_metrics=True)

    assert res["metrics"]["total_open_prs"] == 7
    assert res["metrics"]["total_worktrees"] == 1
    assert res["metrics"]["repos_with_worktrees"] == 1

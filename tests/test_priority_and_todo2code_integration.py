import json
from pathlib import Path
import tempfile
import yaml

from monag import autodiagnosis


def test_priority_sort_key_and_sort_tickets_by_priority():
    tickets = [
        {"id": "t1", "tier": "backlog", "priority": "low", "created_at": "2026-09-25T10:00:00Z"},
        {"id": "t2", "tier": "floor", "priority": "critical", "created_at": "2026-09-25T12:00:00Z"},
        {"id": "t3", "tier": "mission", "priority": "high", "created_at": "2026-09-25T09:00:00Z"},
        {"id": "t4", "tier": "hygiene", "priority": "medium", "created_at": "2026-09-25T11:00:00Z"},
        {"id": "t5", "tier": "floor", "priority": "critical", "created_at": "2026-09-25T11:00:00Z"},
    ]

    sorted_tickets = autodiagnosis.sort_tickets_by_priority(tickets)
    sorted_ids = [t["id"] for t in sorted_tickets]

    # Floor (t5 older than t2), Mission (t3), Hygiene (t4), Backlog (t1)
    assert sorted_ids == ["t5", "t2", "t3", "t4", "t1"]


def test_synthesize_tickets_todo2code_enrichment():
    raw_anomalies = [
        {
            "code": "DIRTY_WORKTREE",
            "tier": "floor",
            "severity": "ERROR",
            "target": "pkg-a",
            "path": "/workspace/pkg-a",
            "summary": "Uncommitted files in primary checkout.",
            "evidence": "2 modified files.",
        },
        {
            "code": "NO_README",
            "tier": "hygiene",
            "severity": "INFO",
            "target": "pkg-b",
            "path": "/workspace/pkg-b",
            "summary": "Missing README.md file.",
            "evidence": "No README found.",
        }
    ]

    tickets = autodiagnosis.synthesize_tickets_with_subllm(raw_anomalies, runner=None)
    assert len(tickets) == 2

    # Tier floor must outrank hygiene
    assert tickets[0]["tier"] == "floor"
    assert tickets[0]["priority"] == "critical"
    assert tickets[1]["tier"] == "hygiene"
    assert tickets[1]["priority"] == "medium"

    # Verify todo2code attributes
    for tkt in tickets:
        labels = tkt["labels"]
        assert "todo2code" in labels
        assert "type:development-defect" in labels
        assert f"tier:{tkt['tier']}" in labels

        src = tkt["source"]
        assert isinstance(src, dict)
        assert src["tool"] == "todo2code"
        assert src["origin"] == "monag.autodiagnosis"
        assert len(src["context"]["diagnostic_ids"]) >= 1
        assert src["context"]["diagnostic_ids"][0].startswith("DIAG-")

        inputs = tkt["inputs"]
        assert isinstance(inputs, dict)
        assert inputs["contract"] == "wellmanifest.defect-repair/v1"
        assert inputs["expect_files_changed"] is True
        assert inputs["patch_mode"] is True
        assert "verify_command" in inputs

        executor = tkt["executor"]
        assert executor["kind"] == "llm"
        assert executor["mode"] == "automatic"


def test_dispatch_to_planfile_preserves_todo2code_and_sorts():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        repo_dir = root / "service-x"
        repo_dir.mkdir(parents=True)
        (repo_dir / ".git").mkdir()

        tickets = [
            {
                "title": "[service-x] Low priority cleanup",
                "description": "Clean unused imports",
                "target_repo": "service-x",
                "tier": "backlog",
                "priority": "low",
                "labels": ["todo2code", "type:development-defect", "tier:backlog"],
                "verification_command": "pytest -q",
                "created_at": "2026-09-25T10:00:00Z",
            },
            {
                "title": "[service-x] Blocker git repair",
                "description": "Repair broken git marker",
                "target_repo": "service-x",
                "tier": "floor",
                "priority": "critical",
                "labels": ["todo2code", "type:development-defect", "tier:floor"],
                "verification_command": "git status --porcelain",
                "created_at": "2026-09-25T11:00:00Z",
            },
        ]

        res = autodiagnosis.dispatch_tickets_to_planfile(tickets, root=root, sprint="sprint-01")
        assert res["dispatched"] == 2

        sprint_yaml = repo_dir / ".planfile" / "sprints" / "sprint-01.yaml"
        assert sprint_yaml.is_file()

        content = yaml.safe_load(sprint_yaml.read_text())
        tasks = content["tasks"]
        assert len(tasks) == 2

        # First task must be the floor/critical task
        assert tasks[0]["tier"] == "floor"
        assert tasks[0]["priority"] == "critical"
        assert "Blocker git repair" in tasks[0]["title"]
        assert tasks[0]["inputs"]["contract"] == "wellmanifest.defect-repair/v1"
        assert tasks[0]["source"]["tool"] == "todo2code"

        # Second task must be the backlog/low task
        assert tasks[1]["tier"] == "backlog"
        assert tasks[1]["priority"] == "low"
        assert "Low priority cleanup" in tasks[1]["title"]

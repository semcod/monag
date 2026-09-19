"""Unit tests for monag.triage — holistic multi-org algorithmic triage and guidance."""
from pathlib import Path
import json
import pytest
from unittest import mock

from monag import triage, advise, cli


def test_classify_candidate_tiers():
    """Verify deterministic categorization across all 4 tiers."""
    # 1. Immediate Blocker
    crit_cand = {
        "title": "Critical disk full alert",
        "priority": "critical",
        "origin": "diagnostics",
    }
    cat, score = triage.classify_candidate(crit_cand, "semcod/fixos", {"has_collision": False})
    assert cat == triage.CATEGORY_IMMEDIATE_BLOCKER
    assert score >= 2000

    # 2. Core Foundation
    core_cand = {
        "title": "Merge docs adoption PR #170",
        "origin": "prs-open-pr",
        "pr_number": 170,
        "priority": "high",
        "checks_passed": True,
    }
    cat, score = triage.classify_candidate(core_cand, "semcod/monag", {"has_collision": False})
    assert cat == triage.CATEGORY_CORE_FOUNDATION
    assert score >= 1200

    # 3. Strategic Architecture
    strat_cand = {
        "title": "Universal interface parity CLI and MCP",
        "origin": "feature-request",
        "priority": "high",
    }
    cat, score = triage.classify_candidate(strat_cand, "tellmesh/uri3", {"has_collision": False})
    assert cat == triage.CATEGORY_STRATEGIC_ARCHITECTURE
    assert 800 <= score < 1200

    # 4. Code Smell & Hygiene
    smell_cand = {
        "title": "Address code smell: Shotgun surgery in config",
        "origin": "audit-untracked-issue",
        "priority": "medium",
    }
    cat, score = triage.classify_candidate(smell_cand, "semcod/tagi", {"has_collision": False})
    assert cat == triage.CATEGORY_CODE_SMELL_HYGIENE
    assert score < 800


def test_agent_collision_detection(tmp_path):
    """Verify running agent collision detection from leases and algocode."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()
    leases_dir = repo_dir / ".subactor" / "leases"
    leases_dir.mkdir(parents=True)

    # Inactive lease
    (leases_dir / "ticket-001.json").write_text(json.dumps({
        "status": "released",
        "owner": "old-agent",
    }), encoding="utf-8")

    info_no_collision = triage.check_agent_collision(repo_dir)
    assert not info_no_collision["has_collision"]

    # Active lease
    (leases_dir / "ticket-002.json").write_text(json.dumps({
        "status": "active",
        "owner": "active-worker-agent",
        "phase": "in_progress",
    }), encoding="utf-8")

    info_collision = triage.check_agent_collision(repo_dir)
    assert info_collision["has_collision"]
    assert "active-worker-agent" in info_collision["active_owners"]

    # Candidate score should reflect collision penalty
    cand = {"title": "Refactor auth pipeline", "priority": "high"}
    cat, score_safe = triage.classify_candidate(cand, "test_repo", {"has_collision": False})
    cat, score_colliding = triage.classify_candidate(cand, "test_repo", {"has_collision": True})
    assert score_colliding < score_safe


def test_guidance_synthesis_and_markdown():
    """Verify step-by-step guidance and markdown rendering."""
    mock_report = {
        "schema": triage.SCHEMA,
        "root": "/workspace/github",
        "discovered_repos_count": 2,
        "total_candidates": 2,
        "collision_count": 1,
        "generated_at": "2026-09-19T14:00:00Z",
        "guidance_steps": [
            {
                "step": 1,
                "category": triage.CATEGORY_IMMEDIATE_BLOCKER,
                "repo": "semcod/fixos",
                "title": "Disk usage threshold exceeded",
                "score": 2100,
                "action": "Mitigate critical blocker in semcod/fixos",
                "command": "fixos run --repo semcod/fixos",
                "collision_safe": True,
                "guardrails": ["Require 100% green tests before commit."],
            },
            {
                "step": 2,
                "category": triage.CATEGORY_CORE_FOUNDATION,
                "repo": "semcod/monag",
                "title": "Merge PR #78",
                "score": 1350,
                "action": "Verify and merge PR #78 in semcod/monag",
                "command": "gh pr merge 78 --repo semcod/monag --squash --admin",
                "collision_safe": False,
                "guardrails": ["CAUTION: Running agent lease held by active-agent."],
            },
        ],
    }

    md = triage.triage_markdown(mock_report)
    assert "# MONAG Holistic Algorithmic Workspace Triage" in md
    assert "Step 1: [IMMEDIATE BLOCKER] `semcod/fixos`" in md
    assert "Step 2: [CORE FOUNDATION] `semcod/monag`" in md
    assert "gh pr merge 78" in md
    assert "⚠️ Collision Risk" in md
    assert "🛡️ Safe" in md


def test_planfile_export_and_feed(tmp_path):
    """Verify exporting guidance steps to Planfile format."""
    mock_report = {
        "guidance_steps": [
            {
                "step": 1,
                "category": triage.CATEGORY_CORE_FOUNDATION,
                "repo": "semcod/algocode",
                "title": "Adopt wellmanifest/docs 19efafb",
                "action": "Update governance docs pin",
                "command": "python3 check.py",
                "score": 1200,
                "guardrails": [],
            }
        ]
    }

    tasks = triage.export_planfile_tasks(mock_report)
    assert len(tasks) == 1
    assert tasks[0]["repository"] == "semcod/algocode"
    assert tasks[0]["priority"] == "P1"

    # Feed to planfile test
    planfile_dir = tmp_path / ".planfile" / "sprints"
    planfile_dir.mkdir(parents=True)
    res = triage.feed_to_planfile(mock_report, root=tmp_path, sprint="current")
    assert res["success"]
    assert res["tasks_count"] == 1


def test_advise_holistic_delegation(tmp_path):
    """Verify monag.advise(..., holistic=True) delegates to triage engine."""
    with mock.patch("monag.triage.run_holistic_triage") as mock_triage:
        mock_triage.return_value = {"schema": triage.SCHEMA, "guidance_steps": []}
        res = advise.advise(tmp_path, holistic=True)
        assert res["schema"] == triage.SCHEMA
        mock_triage.assert_called_once()

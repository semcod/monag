"""Unit tests for monag.triage — holistic multi-org algorithmic triage and guidance."""
import json
import pytest
from unittest import mock

from monag import triage, advise


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


def test_agent_collision_detection(tmp_path, monkeypatch):
    """Verify running agent collision detection from leases and algocode."""
    monkeypatch.setattr(triage, "_find_algocode_runner", lambda: None)
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
    assert not info_collision["has_collision"]
    assert info_collision["blocking"]
    assert info_collision["active_lease_count"] == 1
    assert not info_collision["ownership_verified"]
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
                "command": "gh pr view 78 --repo semcod/monag",
                "collision_safe": False,
                "guardrails": ["CAUTION: Running agent lease held by active-agent."],
            },
        ],
    }

    md = triage.triage_markdown(mock_report)
    assert "# MONAG Holistic Algorithmic Workspace Triage" in md
    assert "Step 1: [IMMEDIATE BLOCKER] `semcod/fixos`" in md
    assert "Step 2: [CORE FOUNDATION] `semcod/monag`" in md
    assert "gh pr view 78" in md
    assert "⚠️ Declared conflict" in md
    assert "Ownership unverified" in md
    assert "🛡️ Safe" not in md


def test_planfile_export_and_feed(tmp_path, monkeypatch):
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

    monkeypatch.setattr(triage.shutil, "which", lambda _: None)
    result = triage.feed_to_planfile(mock_report, root=tmp_path)
    assert not result["success"]
    assert result["tasks_count"] == 0
    assert result["requested_count"] == 1


def test_advise_holistic_delegation(tmp_path):
    """Verify monag.advise(..., holistic=True) delegates to triage engine."""
    with mock.patch("monag.triage.run_holistic_triage") as mock_triage:
        mock_triage.return_value = {"schema": triage.SCHEMA, "guidance_steps": []}
        res = advise.advise(tmp_path, holistic=True)
        assert res["schema"] == triage.SCHEMA
        mock_triage.assert_called_once()


@pytest.mark.parametrize("phase", ["released", "closed", "merged", "cancelled"])
def test_terminal_change_lease_is_not_active(tmp_path, monkeypatch, phase):
    monkeypatch.setattr(triage, "_find_algocode_runner", lambda: None)
    directory = tmp_path / ".subactor" / "leases"
    directory.mkdir(parents=True)
    (directory / "ticket.json").write_text(json.dumps({
        "schema": "wellmanifest.change-lease/v1", "phase": phase,
        "ownerActor": "old-owner", "leaseRevision": 3, "fencingToken": 5,
    }))
    result = triage.check_agent_collision(tmp_path)
    assert result["active_lease_count"] == 0
    assert not result["blocking"]
    assert not result["ownership_verified"]
    assert result["lease_evidence"][0]["lease_fencing_token"] == 5


@pytest.mark.parametrize("data", ["{broken", '{"schema":"future/v9"}',
    '{"schema":"wellmanifest.change-lease/v1","phase":"expired"}'])
def test_unknown_or_expired_lease_blocks_without_transfer(tmp_path, monkeypatch, data):
    monkeypatch.setattr(triage, "_find_algocode_runner", lambda: None)
    directory = tmp_path / ".subactor" / "leases"
    directory.mkdir(parents=True)
    (directory / "ticket.json").write_text(data)
    result = triage.check_agent_collision(tmp_path)
    assert result["blocking"]
    assert result["unknown_lease_count"] == 1
    assert not result["has_collision"]
    assert not result["ownership_verified"]


def test_missing_checks_and_ownership_never_authorize_mutations():
    candidate = {"origin": "prs-open-pr", "pr_number": 78}
    _, unknown = triage.classify_candidate(candidate, "semcod/monag", {})
    _, passed = triage.classify_candidate(dict(candidate, checks_passed=True), "semcod/monag", {})
    assert passed > unknown
    for item in [candidate, {"issue_number": 9, "triage_status": "ALREADY_RESOLVED"}]:
        action = triage.synthesize_triage_action(item, triage.CATEGORY_CORE_FOUNDATION, "semcod/monag", {})
        assert " view " in action["suggested_command"]
        assert "--admin" not in action["suggested_command"]
        assert " merge " not in action["suggested_command"]
        assert " close " not in action["suggested_command"]


def test_local_scan_respects_depth_and_observes_linked_worktree(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setattr(triage, "_find_algocode_runner", lambda: None)
    repo = tmp_path / "org" / "repo"
    repo.mkdir(parents=True)
    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    git("init")
    git("-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "--allow-empty", "-m", "seed")
    linked = repo / ".worktrees" / "ticket-001--fixture"
    git("worktree", "add", "-b", "ticket/001-fixture", str(linked))
    original_run = subprocess.run
    calls = []
    def local_only(args, **kwargs):
        calls.append(args)
        assert args[0] == "git"
        return original_run(args, **kwargs)
    monkeypatch.setattr(triage.subprocess, "run", local_only)
    assert triage.run_holistic_triage(tmp_path, depth=1)["discovered_repos_count"] == 0
    report = triage.run_holistic_triage(tmp_path, depth=2, scan_issues=True)
    assert report["discovered_repos_count"] == 1
    assert report["github_api_requests"] == 0
    assert report["issue_scan_performed"] is False
    assert report["collision_count"] == 0
    assert report["recommendations"][0]["origin"] == "worktree-observed"
    assert "active" not in report["recommendations"][0]["title"].lower()
    assert report["guidance_steps"][0]["collision_safe"] is None
    assert not report["guidance_steps"][0]["ownership_verified"]
    leases = repo / ".subactor" / "leases"
    leases.mkdir(parents=True)
    (leases / "claim.json").write_text('{"status":"active","owner":"primary-owner"}')
    linked_report = triage.run_holistic_triage(linked)
    assert linked_report["discovered_repos_count"] == 1
    assert linked_report["lease_blocked_repo_count"] == 1
    assert triage.check_agent_collision(linked)["active_owners"] == ["primary-owner"]
    assert calls


def test_suggested_inspection_command_quotes_checkout_path():
    import shlex
    path = "/workspace/a $(touch bad); repo"
    result = triage.synthesize_triage_action({"path": path}, "", "org/repo", {})
    assert shlex.split(result["suggested_command"]) == ["git", "-C", path, "status", "--short"]



def feed_fixture(*repositories):
    return {"guidance_steps": [{"category": triage.CATEGORY_CORE_FOUNDATION,
        "repo": repository, "title": "Inspect local evidence", "action": "Review ownership",
        "command": "git status --short", "guardrails": [], "score": 1200}
        for repository in repositories]}


def test_feed_routes_projects_and_reads_back_ids(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setattr(triage.shutil, "which", lambda _: "/bin/planfile-fixture")
    for name in ["one", "two"]:
        root = tmp_path / "org" / name
        (root / ".git").mkdir(parents=True)
        (root / ".planfile").mkdir()
    stored = {}
    def native(args, cwd, **kwargs):
        assert "--sync" not in args
        label = args[args.index("--label") + 1]
        if args[2] == "create":
            stored.setdefault((cwd, label), {"id": "PLF-001", "labels": [label], "status": "open"})
            return subprocess.CompletedProcess(args, 0, "Created", "")
        return subprocess.CompletedProcess(args, 0, json.dumps([stored[(cwd, label)]]), "")
    monkeypatch.setattr(triage.subprocess, "run", native)
    for _ in range(2):
        result = triage.feed_to_planfile(feed_fixture("org/one", "org/two"), tmp_path)
        assert result["success"]
        assert result["tasks_count"] == 2
        assert {row["repository"] for row in result["tickets"]} == {"org/one", "org/two"}
    assert len(stored) == 2


def test_feed_rejects_missing_and_escaping_projects(tmp_path, monkeypatch):
    monkeypatch.setattr(triage.shutil, "which", lambda _: "/bin/planfile-fixture")
    with mock.patch.object(triage.subprocess, "run") as run:
        result = triage.feed_to_planfile(feed_fixture("org/missing", "../outside", "/absolute"), tmp_path)
    assert not result["success"]
    assert len(result["errors"]) == 3
    assert result["tasks_count"] == 0
    run.assert_not_called()


def test_feed_cannot_claim_success_from_command_exit_alone(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setattr(triage.shutil, "which", lambda _: "/bin/planfile-fixture")
    (tmp_path / "org/repo/.git").mkdir(parents=True)
    (tmp_path / "org/repo/.planfile").mkdir()
    with mock.patch.object(triage.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "[]", "")):
        result = triage.feed_to_planfile(feed_fixture("org/repo"), tmp_path)
    assert not result["success"]
    assert result["tasks_count"] == 0
    assert "persisted dedupe owner" in result["errors"][0]["error"]


def test_feed_cli_json_reports_partial_failure(tmp_path, capsys):
    from monag import cli
    result = {"success": False, "tasks_count": 1, "tickets": [{"repository": "org/repo", "id": "PLF-001"}],
              "errors": [{"repository": "org/missing", "error": "missing store"}]}
    with mock.patch.object(triage, "run_holistic_triage", return_value={}):
        with mock.patch.object(triage, "feed_to_planfile", return_value=result):
            assert cli.main(["--root", str(tmp_path), "--json", "triage", "--feed-planfile"]) == 1
    assert json.loads(capsys.readouterr().out) == result

"""Unit tests for Wellmanifest Worktrees v5 Safe Worktree Auditor and Pruner."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from monag.cli import main
from monag.worktrees import (
    get_repo_leases,
    audit_fleet_worktrees,
    audit_worktree_safety,
    is_branch_merged,
    is_process_inside_path,
    is_worktree_dirty,
    markdown_audit,
    markdown_prune,
    prune_fleet_worktrees_safe,
    prune_worktrees_safe,
)


class TestWorktreesSafePrune(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def git(self, repo: Path, *args: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(repo), *args],
            stderr=subprocess.DEVNULL,
            text=True,
        )

    def make_repo(self, name: str) -> Path:
        repo = self.root / name
        repo.mkdir(parents=True, exist_ok=True)
        self.git(repo, "init", "-b", "main")
        self.git(repo, "config", "user.email", "agent@example.invalid")
        self.git(repo, "config", "user.name", "Agent")
        (repo / "README.md").write_text("initial\n")
        self.git(repo, "add", "README.md")
        self.git(repo, "commit", "-m", "init")
        return repo

    def make_worktree(self, repo: Path, ticket_id: str, branch: str) -> Path:
        wt_dir = repo / ".worktrees" / ticket_id
        wt_dir.parent.mkdir(parents=True, exist_ok=True)
        self.git(repo, "worktree", "add", "-b", branch, str(wt_dir), "main")
        (wt_dir / "work.txt").write_text(f"work for {ticket_id}\n")
        self.git(wt_dir, "add", "work.txt")
        self.git(wt_dir, "commit", "-m", f"feat: {ticket_id}")
        return wt_dir

    def test_process_guard_protects_worktree(self):
        repo = self.make_repo("service-proc")
        wt = self.make_worktree(repo, "ticket-101", "ticket/101-proc")
        self.git(repo, "merge", "ticket/101-proc")

        # Fake active process inside worktree
        fake_cwds = {wt.resolve(), Path("/other/path")}
        audit = audit_worktree_safety(
            repo,
            {"path": str(wt), "branch": "ticket/101-proc", "is_primary": False},
            active_cwds=fake_cwds,
            leases={},
        )
        self.assertFalse(audit["safe_to_prune"])
        self.assertTrue(audit["active_process"])
        self.assertIn("active_process_running", audit["reasons"])

        # Also verify is_process_inside_path directly
        self.assertTrue(is_process_inside_path(wt, fake_cwds))
        self.assertTrue(is_process_inside_path(wt, {(wt / "subdir").resolve()}))
        self.assertFalse(is_process_inside_path(self.root / "other-dir", {wt.resolve()}))

    def test_dirty_tree_guard_protects_worktree(self):
        repo = self.make_repo("service-dirty")
        wt = self.make_worktree(repo, "ticket-102", "ticket/102-dirty")
        self.git(repo, "merge", "ticket/102-dirty")

        # Add uncommitted modification
        (wt / "uncommitted.txt").write_text("draft changes\n")
        dirty, reason = is_worktree_dirty(wt)
        self.assertTrue(dirty)
        self.assertIn("1 uncommitted file", reason)

        audit = audit_worktree_safety(
            repo,
            {"path": str(wt), "branch": "ticket/102-dirty", "is_primary": False},
            active_cwds=set(),
            leases={},
        )
        self.assertFalse(audit["safe_to_prune"])
        self.assertTrue(audit["dirty"])
        self.assertTrue(any("uncommitted_changes" in r for r in audit["reasons"]))

    def test_active_lease_guard_protects_worktree(self):
        repo = self.make_repo("service-lease")
        wt = self.make_worktree(repo, "ticket-103", "ticket/103-lease")
        self.git(repo, "merge", "ticket/103-lease")

        leases_dir = repo / ".subactor" / "leases"
        leases_dir.mkdir(parents=True, exist_ok=True)
        lease_file = leases_dir / "ticket-103.json"
        lease_data = {
            "ticket": "ticket-103",
            "branch": "ticket/103-lease",
            "worktreePath": str(wt),
            "status": "active",
        }
        lease_file.write_text(json.dumps(lease_data))

        audit = audit_worktree_safety(
            repo,
            {"path": str(wt), "branch": "ticket/103-lease", "is_primary": False},
            active_cwds=set(),
        )
        self.assertFalse(audit["safe_to_prune"])
        self.assertTrue(audit["active_lease"])
        self.assertTrue(any("active_lease" in r for r in audit["reasons"]))

    def test_unmerged_branch_guard_protects_worktree(self):
        repo = self.make_repo("service-unmerged")
        wt = self.make_worktree(repo, "ticket-104", "ticket/104-unmerged")
        # Do NOT merge into main

        self.assertFalse(is_branch_merged(repo, "ticket/104-unmerged"))
        audit = audit_worktree_safety(
            repo,
            {"path": str(wt), "branch": "ticket/104-unmerged", "is_primary": False},
            active_cwds=set(),
            leases={},
        )
        self.assertFalse(audit["safe_to_prune"])
        self.assertFalse(audit["is_merged"])
        self.assertIn("branch_unmerged", audit["reasons"])

    def test_clean_merged_inactive_worktree_is_pruned(self):
        repo = self.make_repo("service-clean")
        wt = self.make_worktree(repo, "ticket-105", "ticket/105-clean")
        self.git(repo, "merge", "ticket/105-clean")

        # Dry-run first
        dry = prune_worktrees_safe(repo, dry_run=True, active_cwds=set())
        self.assertEqual(len(dry["pruned"]), 1)
        self.assertEqual(len(dry["protected"]), 0)
        self.assertTrue(wt.exists())

        # Real prune
        res = prune_worktrees_safe(repo, dry_run=False, active_cwds=set())
        self.assertEqual(len(res["pruned"]), 1)
        self.assertEqual(len(res["protected"]), 0)
        self.assertFalse(wt.exists())
        self.assertIn("ticket/105-clean", res["deleted_branches"])

    def test_locked_worktree_remains_protected(self):
        repo = self.make_repo("service-locked-clean")
        wt = self.make_worktree(repo, "ticket-105b", "ticket/105b-locked")
        self.git(repo, "merge", "ticket/105b-locked")
        self.git(repo, "worktree", "lock", "--reason", "locked for active inspection", str(wt))

        audit = audit_worktree_safety(
            repo,
            {"path": str(wt), "branch": "ticket/105b-locked", "is_primary": False, "locked": True},
            active_cwds=set(),
            leases={},
        )
        self.assertFalse(audit["safe_to_prune"])
        self.assertTrue(audit.get("locked"))
        self.assertIn("worktree_locked", audit["reasons"])

        res = prune_worktrees_safe(repo, dry_run=False, active_cwds=set())
        self.assertEqual(len(res["pruned"]), 0)
        self.assertEqual(len(res["protected"]), 1)
        self.assertTrue(wt.exists())
        self.assertIn("worktree_locked", res["protected"][0]["reasons"])

    def test_change_lease_v1_phases_protect_worktree(self):
        repo = self.make_repo("service-change-lease-v1")
        wt = self.make_worktree(repo, "ticket-201", "ticket/201-lease-phase")
        self.git(repo, "merge", "ticket/201-lease-phase")

        leases_dir = repo / ".subactor" / "leases"
        leases_dir.mkdir(parents=True, exist_ok=True)
        lease_file = leases_dir / "ticket-201.json"

        # 1. Claimed phase must protect
        lease_file.write_text(json.dumps({
            "schema": "wellmanifest.change-lease/v1",
            "ticketId": "ticket-201",
            "worktreeId": wt.name,
            "branchRef": "refs/heads/ticket/201-lease-phase",
            "phase": "claimed",
            "ownerActor": "agent:test",
        }))
        leases = get_repo_leases(repo)
        audit = audit_worktree_safety(repo, {"path": str(wt), "branch": "ticket/201-lease-phase", "is_primary": False}, active_cwds=set(), leases=leases)
        self.assertFalse(audit["safe_to_prune"])
        self.assertTrue(audit["active_lease"])

        # 2. Expired phase must still protect (fails closed per AC-01)
        lease_file.write_text(json.dumps({
            "schema": "wellmanifest.change-lease/v1",
            "ticketId": "ticket-201",
            "worktreeId": wt.name,
            "branchRef": "refs/heads/ticket/201-lease-phase",
            "phase": "expired",
            "ownerActor": "agent:test",
        }))
        leases = get_repo_leases(repo)
        audit = audit_worktree_safety(repo, {"path": str(wt), "branch": "ticket/201-lease-phase", "is_primary": False}, active_cwds=set(), leases=leases)
        self.assertFalse(audit["safe_to_prune"])
        self.assertTrue(audit["active_lease"])

        # 3. Released phase allows pruning
        lease_file.write_text(json.dumps({
            "schema": "wellmanifest.change-lease/v1",
            "ticketId": "ticket-201",
            "worktreeId": wt.name,
            "branchRef": "refs/heads/ticket/201-lease-phase",
            "phase": "released",
            "ownerActor": "agent:test",
        }))
        leases = get_repo_leases(repo)
        audit = audit_worktree_safety(repo, {"path": str(wt), "branch": "ticket/201-lease-phase", "is_primary": False}, active_cwds=set(), leases=leases)
        self.assertTrue(audit["safe_to_prune"])
        self.assertFalse(audit["active_lease"])

    def test_malformed_unreadable_lease_protects_worktree(self):
        repo = self.make_repo("service-malformed-lease")
        wt = self.make_worktree(repo, "ticket-202", "ticket/202-bad-lease")
        self.git(repo, "merge", "ticket/202-bad-lease")

        leases_dir = repo / ".subactor" / "leases"
        leases_dir.mkdir(parents=True, exist_ok=True)
        (leases_dir / f"{wt.name}.json").write_text("NOT_VALID_JSON{")

        leases = get_repo_leases(repo)
        audit = audit_worktree_safety(repo, {"path": str(wt), "branch": "ticket/202-bad-lease", "is_primary": False}, active_cwds=set(), leases=leases)
        self.assertFalse(audit["safe_to_prune"])
        self.assertTrue(audit["active_lease"])
        self.assertTrue(any("malformed" in r for r in audit["reasons"]))

    def test_controller_lease_is_never_rewritten_by_monag(self):
        repo = self.make_repo("service-lease-immutable")
        wt = self.make_worktree(repo, "ticket-203", "ticket/203-immutable")
        self.git(repo, "merge", "ticket/203-immutable")

        leases_dir = repo / ".subactor" / "leases"
        leases_dir.mkdir(parents=True, exist_ok=True)
        lease_path = leases_dir / "ticket-203.json"
        original_lease_content = json.dumps({
            "schema": "wellmanifest.change-lease/v1",
            "ticketId": "ticket-203",
            "worktreeId": wt.name,
            "branchRef": "refs/heads/ticket/203-immutable",
            "phase": "released",
            "ownerActor": "agent:test",
            "fencingToken": 42,
        }, indent=2) + "\n"
        lease_path.write_text(original_lease_content)

        # Execute prune
        res = prune_worktrees_safe(repo, dry_run=False, active_cwds=set())
        self.assertEqual(len(res["pruned"]), 1)
        self.assertFalse(wt.exists())

        # Verify lease content was NOT altered by Monag
        self.assertEqual(lease_path.read_text(), original_lease_content)

    def test_branch_cannot_establish_merge_merely_against_own_head(self):
        repo = self.make_repo("service-own-head")
        wt = self.make_worktree(repo, "ticket-204", "ticket/204-own-head")
        # Do not merge into main
        # In git worktree wt, HEAD is ticket/204-own-head.
        # Calling is_branch_merged should compare against main, NOT HEAD.
        self.assertFalse(is_branch_merged(wt, "ticket/204-own-head"))

    @patch("monag.worktrees.audit_active_process_cwds", return_value=(set(), {}))
    def test_fleet_worktree_audit_and_markdown(self, _mock_proc):
        repo = self.make_repo("service-fleet")
        wt = self.make_worktree(repo, "ticket-106", "ticket/106-fleet")
        self.git(repo, "merge", "ticket/106-fleet")

        fleet_audit = audit_fleet_worktrees(self.root)
        self.assertEqual(fleet_audit["repositories_audited"], 1)
        self.assertEqual(fleet_audit["total_safe_to_prune"], 1)
        self.assertEqual(fleet_audit["total_protected"], 0)

        md = markdown_audit(fleet_audit)
        self.assertIn("Wellmanifest Worktrees v5 Safety Audit", md)
        self.assertIn("SAFE TO PRUNE", md)

        # Prune fleet
        fleet_prune = prune_fleet_worktrees_safe(self.root, dry_run=False)
        self.assertEqual(fleet_prune["total_pruned"], 1)
        md_prune = markdown_prune(fleet_prune)
        self.assertIn("Wellmanifest Worktrees v5 Safe Pruning", md_prune)
        self.assertIn("PRUNED", md_prune)

    @patch("monag.worktrees.audit_active_process_cwds", return_value=(set(), {}))
    def test_cli_worktrees_list_and_prune(self, _mock_proc):
        repo = self.make_repo("service-cli")
        wt = self.make_worktree(repo, "ticket-107", "ticket/107-cli")
        self.git(repo, "merge", "ticket/107-cli")

        # CLI list
        code_list = main(["worktrees", "list", "--root", str(self.root), "--json"])
        self.assertEqual(code_list, 0)

        # CLI prune dry-run
        code_dry = main(["worktrees", "prune", "--root", str(self.root), "--dry-run", "--json"])
        self.assertEqual(code_dry, 0)
        self.assertTrue(wt.exists())

        # CLI prune real
        code_prune = main(["worktrees", "prune", "--root", str(self.root), "--json"])
        self.assertEqual(code_prune, 0)
        self.assertFalse(wt.exists())

    @patch("monag.worktrees.audit_active_process_cwds", return_value=(set(), {}))
    def test_panel_worktrees_prune_safe_route(self, _mock_proc):
        from monag.panel import State
        state = State(root=self.root, state_dir=self.root / "state", depth=1)
        res = state.worktrees_prune_safe(dry_run=True)
        self.assertIn("repositories_audited", res)
        self.assertIn("total_pruned", res)
        self.assertIn("total_protected", res)

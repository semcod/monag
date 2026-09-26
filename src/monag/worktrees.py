"""Wellmanifest Worktrees v5 Safe Worktree Auditor and Pruner.

Enforces:
1. Active process / IDE guard (never prune worktrees where an agent, IDE, or compiler is running).
2. Dirty tree guard (never prune worktrees with uncommitted/untracked changes).
3. Lease lifecycle guard (never prune worktrees with active leases in .subactor/leases/).
4. Branch merge guard (never prune worktrees with unmerged commits).
5. Legacy/external checkout preservation (never prune external checkouts merely to normalize appearance).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Set, Tuple


def command(cmd: list[str], cwd: Optional[Path] = None) -> tuple[str, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return proc.stdout.strip(), proc.stderr.strip()
    except (subprocess.SubprocessError, OSError) as err:
        return "", str(err)


def audit_active_process_cwds() -> tuple[set[Path], dict[int, str]]:
    """Inspect /proc to discover current working directories of all running processes."""
    active_cwds: set[Path] = set()
    proc_map: dict[int, str] = {}
    proc_root = Path("/proc")

    if not proc_root.exists():
        return active_cwds, proc_map

    for p in proc_root.iterdir():
        if not p.name.isdigit():
            continue
        pid = int(p.name)
        try:
            cwd_link = os.readlink(p / "cwd")
            cwd_path = Path(cwd_link).resolve()
            active_cwds.add(cwd_path)

            cmdline_file = p / "cmdline"
            if cmdline_file.exists():
                try:
                    with open(cmdline_file, "rb", buffering=0) as f:
                        cmdline = f.read(1024).replace(b"\x00", b" ").decode(errors="replace").strip()
                        proc_map[pid] = cmdline
                except (OSError, UnicodeDecodeError):
                    pass
        except (OSError, UnicodeDecodeError):
            continue

    return active_cwds, proc_map


def get_repo_leases(repo: Path) -> dict[str, dict[str, Any]]:
    """Read all leases from .subactor/leases/*.json."""
    leases: dict[str, dict[str, Any]] = {}
    leases_dir = repo / ".subactor" / "leases"
    if not leases_dir.is_dir():
        return leases

    for lease_file in leases_dir.glob("*.json"):
        try:
            data = json.loads(lease_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                ticket = str(data.get("ticket") or "").strip()
                worktree_path = str(data.get("worktreePath") or "").strip()
                branch = str(data.get("branch") or "").strip()
                if ticket:
                    leases[ticket] = data
                if worktree_path:
                    leases[worktree_path] = data
                    leases[Path(worktree_path).name] = data
                if branch:
                    leases[branch] = data
        except (OSError, json.JSONDecodeError):
            continue

    return leases


def is_worktree_dirty(wt_path: Path) -> tuple[bool, str]:
    """Check if the worktree has any uncommitted or untracked changes."""
    if not wt_path.is_dir():
        return False, ""
    out, err = command(["git", "-C", str(wt_path), "status", "--porcelain"])
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    if lines:
        return True, f"{len(lines)} uncommitted file(s)"
    return False, ""


def is_branch_merged(repo: Path, branch: str) -> bool:
    """Check if branch is merged to main, master, or HEAD."""
    if not branch:
        return False

    targets = ["main", "master", "HEAD"]
    for t in targets:
        chk, _ = command(["git", "-C", str(repo), "rev-parse", "--verify", t])
        if not chk.strip():
            continue
        # Check merge-base --is-ancestor branch target
        proc = subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", branch, t],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            return True

    return False


def is_process_inside_path(path: Path, active_cwds: set[Path]) -> bool:
    """Return True if any active process cwd is path or a descendant of path."""
    try:
        resolved = path.resolve()
        for active in active_cwds:
            if active == resolved or resolved in active.parents:
                return True
    except OSError:
        pass
    return False


def audit_worktree_safety(
    repo: Path,
    wt: dict[str, Any],
    active_cwds: Optional[set[Path]] = None,
    leases: Optional[dict[str, dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Audit single worktree against Wellmanifest Worktrees v5 safety invariants."""
    if active_cwds is None:
        active_cwds, _ = audit_active_process_cwds()
    if leases is None:
        leases = get_repo_leases(repo)

    wt_path_str = wt.get("path", "")
    wt_path = Path(wt_path_str)
    branch = wt.get("branch", "")
    is_primary = wt.get("is_primary", False)
    exists = wt_path.is_dir()

    safety = {
        "repo": repo.name,
        "repo_path": str(repo),
        "path": wt_path_str,
        "branch": branch,
        "is_primary": is_primary,
        "exists": exists,
        "safe_to_prune": False,
        "reasons": [],
        "dirty": False,
        "active_process": False,
        "active_lease": False,
        "is_merged": False,
    }

    # Primary checkouts are NEVER prunable
    if is_primary:
        safety["reasons"].append("primary_checkout")
        return safety

    # Dead worktree entries (folder gone but git still references it)
    if not exists:
        safety["safe_to_prune"] = True
        safety["reasons"].append("dead_worktree_reference")
        return safety

    # 1. Process / IDE Guard
    if is_process_inside_path(wt_path, active_cwds):
        safety["active_process"] = True
        safety["reasons"].append("active_process_running")

    # 2. Dirty Tree Guard
    dirty, dirty_reason = is_worktree_dirty(wt_path)
    if dirty:
        safety["dirty"] = True
        safety["reasons"].append(f"uncommitted_changes ({dirty_reason})")

    # 3. Lease Lifecycle Guard
    lease = leases.get(wt_path.name) or leases.get(branch)
    if lease:
        lease_status = str(lease.get("status", "")).lower()
        if lease_status == "active":
            safety["active_lease"] = True
            safety["reasons"].append(f"active_lease (ticket: {lease.get('ticket')})")

    # 4. Branch Merge Guard
    merged = is_branch_merged(repo, branch)
    safety["is_merged"] = merged
    if not merged and branch:
        safety["reasons"].append("branch_unmerged")

    # 5. Wellmanifest Layout Guard: must be in .worktrees/ or recognized linked checkout
    try:
        rel = wt_path.resolve().relative_to(repo.resolve())
        is_in_worktrees = rel.parts and rel.parts[0] == ".worktrees"
    except ValueError:
        is_in_worktrees = False

    if not is_in_worktrees:
        safety["reasons"].append("external_or_legacy_checkout")

    # Determine if safe
    if (
        not safety["active_process"]
        and not safety["dirty"]
        and not safety["active_lease"]
        and (safety["is_merged"] or not branch)
        and is_in_worktrees
    ):
        safety["safe_to_prune"] = True
        safety["reasons"].append("merged_clean_inactive")

    return safety


def prune_worktrees_safe(
    repo: Path,
    dry_run: bool = False,
    active_cwds: Optional[set[Path]] = None,
) -> dict[str, Any]:
    """Safely prune worktrees in a single repository according to Wellmanifest v5."""
    if active_cwds is None:
        active_cwds, _ = audit_active_process_cwds()

    from . import doctor
    wts = doctor.audit_worktrees(repo)
    leases = get_repo_leases(repo)

    result = {
        "repo": repo.name,
        "repo_path": str(repo),
        "dry_run": dry_run,
        "pruned": [],
        "protected": [],
        "deleted_branches": [],
        "errors": [],
    }

    # 1. Prune dead worktrees from git metadata first
    if not dry_run:
        command(["git", "-C", str(repo), "worktree", "prune"])

    for wt in wts:
        if wt.get("is_primary"):
            continue
        audit = audit_worktree_safety(repo, wt, active_cwds=active_cwds, leases=leases)
        wt_path = Path(wt["path"])

        if not audit["safe_to_prune"]:
            result["protected"].append({
                "path": str(wt_path),
                "branch": wt.get("branch", ""),
                "reasons": audit["reasons"],
            })
            continue

        # If it's a dead worktree reference
        if not audit["exists"]:
            result["pruned"].append({
                "path": str(wt_path),
                "branch": wt.get("branch", ""),
                "action": "git_worktree_prune_dead_ref",
            })
            continue

        # Live worktree passed all safety invariants
        if dry_run:
            result["pruned"].append({
                "path": str(wt_path),
                "branch": wt.get("branch", ""),
                "action": "would_remove_clean_merged_worktree",
            })
            continue

        # Re-verify immediately before deletion (double check)
        still_active = is_process_inside_path(wt_path, active_cwds)
        still_dirty, _ = is_worktree_dirty(wt_path)
        if still_active or still_dirty:
            result["protected"].append({
                "path": str(wt_path),
                "branch": wt.get("branch", ""),
                "reasons": ["race_detected_active_or_dirty_at_removal"],
            })
            continue

        # Execute safe removal
        out, err = command(["git", "-C", str(repo), "worktree", "remove", str(wt_path)])
        if wt_path.exists():
            # If standard worktree remove didn't clear directory, check again and remove
            try:
                shutil.rmtree(wt_path)
            except Exception as e:
                result["errors"].append(f"Failed to remove directory {wt_path}: {e}")

        command(["git", "-C", str(repo), "worktree", "prune"])
        result["pruned"].append({
            "path": str(wt_path),
            "branch": wt.get("branch", ""),
            "action": "worktree_removed",
        })

        # Update lease if present
        lease_entry = leases.get(wt_path.name) or leases.get(wt.get("branch", ""))
        if lease_entry:
            tkt = lease_entry.get("ticket")
            lease_path = repo / ".subactor" / "leases" / f"{tkt}.json"
            if not lease_path.exists():
                lease_path = repo / ".subactor" / "leases" / f"{wt_path.name}.json"
            if lease_path.exists():
                try:
                    ldata = json.loads(lease_path.read_text(encoding="utf-8"))
                    ldata["status"] = "pruned"
                    lease_path.write_text(json.dumps(ldata, indent=2) + "\n")
                except Exception:
                    pass

        # Clean up merged ticket branch if safe
        branch = wt.get("branch", "")
        if branch and branch.startswith(("ticket/", "ticket-")) and is_branch_merged(repo, branch):
            b_out, _ = command(["git", "-C", str(repo), "branch", "-d", branch])
            result["deleted_branches"].append(branch)

    return result


def prune_fleet_worktrees_safe(
    root: Path,
    depth: int = 2,
    dry_run: bool = False,
    target_repo: Optional[str] = None,
) -> dict[str, Any]:
    """Safely audit and prune worktrees across all repositories in root."""
    from . import doctor
    repos = doctor.find_git_repositories(root)
    if target_repo:
        repos = [r for r in repos if r.name == target_repo or f"{r.parent.name}/{r.name}" == target_repo]

    active_cwds, proc_map = audit_active_process_cwds()

    fleet_summary = {
        "root": str(root),
        "dry_run": dry_run,
        "repositories_audited": len(repos),
        "total_pruned": 0,
        "total_protected": 0,
        "total_deleted_branches": 0,
        "active_processes_monitored": len(proc_map),
        "results": [],
    }

    for repo in repos:
        try:
            repo_res = prune_worktrees_safe(repo, dry_run=dry_run, active_cwds=active_cwds)
            fleet_summary["total_pruned"] += len(repo_res["pruned"])
            fleet_summary["total_protected"] += len(repo_res["protected"])
            fleet_summary["total_deleted_branches"] += len(repo_res["deleted_branches"])
            fleet_summary["results"].append(repo_res)
        except Exception as err:
            fleet_summary["results"].append({
                "repo": repo.name,
                "repo_path": str(repo),
                "error": str(err),
            })

    return fleet_summary


def audit_fleet_worktrees(
    root: Path,
    depth: int = 2,
    target_repo: Optional[str] = None,
) -> dict[str, Any]:
    """Audit worktree safety across all repositories under root."""
    from . import doctor
    repos = doctor.find_git_repositories(root)
    if target_repo:
        repos = [r for r in repos if r.name == target_repo or f"{r.parent.name}/{r.name}" == target_repo]

    active_cwds, proc_map = audit_active_process_cwds()
    results = []
    total_safe = 0
    total_protected = 0
    total_wts = 0

    for repo in repos:
        leases = get_repo_leases(repo)
        wts = doctor.audit_worktrees(repo)
        non_primary = [w for w in wts if not w.get("is_primary")]
        if not non_primary:
            continue
        repo_audits = []
        for wt in non_primary:
            audit = audit_worktree_safety(repo, wt, active_cwds=active_cwds, leases=leases)
            repo_audits.append(audit)
            total_wts += 1
            if audit["safe_to_prune"]:
                total_safe += 1
            else:
                total_protected += 1
        results.append({
            "repo": repo.name,
            "repo_path": str(repo),
            "worktrees": repo_audits,
        })

    return {
        "root": str(root),
        "repositories_audited": len(repos),
        "repositories_with_worktrees": len(results),
        "total_secondary_worktrees": total_wts,
        "total_safe_to_prune": total_safe,
        "total_protected": total_protected,
        "active_processes_monitored": len(proc_map),
        "results": results,
    }


def markdown_audit(data: dict[str, Any]) -> str:
    lines = [
        "# Wellmanifest Worktrees v5 Safety Audit",
        "",
        f"- **Repositories checked**: {data.get('repositories_audited', 0)} ({data.get('repositories_with_worktrees', 0)} with secondary worktrees)",
        f"- **Active processes monitored**: {data.get('active_processes_monitored', 0)}",
        f"- **Safe to prune**: `{data.get('total_safe_to_prune', 0)}` worktrees (clean, merged, inactive, no active leases)",
        f"- **Protected**: `{data.get('total_protected', 0)}` worktrees (active processes, uncommitted changes, active leases, or unmerged branches)",
        "",
    ]

    for repo_res in data.get("results", []):
        r_name = repo_res.get("repo", "unknown")
        lines.append(f"### {r_name}")
        for wt in repo_res.get("worktrees", []):
            branch = wt.get("branch") or "detached"
            path = Path(wt.get("path", "")).name
            if wt.get("safe_to_prune"):
                lines.append(f"- ✓ **[SAFE TO PRUNE]** `{path}` (`{branch}`): {', '.join(wt.get('reasons', []))}")
            else:
                reasons = ", ".join(wt.get("reasons", []))
                lines.append(f"- ⏳ **[PROTECTED]** `{path}` (`{branch}`): {reasons}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def render_audit(data: dict[str, Any]) -> str:
    try:
        from rich.console import Console
        from rich.markdown import Markdown
        import io
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=False)
        console.print(Markdown(markdown_audit(data)))
        return buf.getvalue()
    except ImportError:
        return markdown_audit(data)


def markdown_prune(data: dict[str, Any]) -> str:
    dry_run = data.get("dry_run", False)
    mode_str = "(DRY RUN - Preview Only)" if dry_run else "(Applied)"
    lines = [
        f"# Wellmanifest Worktrees v5 Safe Pruning {mode_str}",
        "",
        f"- **Repositories scanned**: {data.get('repositories_audited', 0)}",
        f"- **Total worktrees pruned**: `{data.get('total_pruned', 0)}`",
        f"- **Total worktrees protected**: `{data.get('total_protected', 0)}`",
        f"- **Total branches deleted**: `{data.get('total_deleted_branches', 0)}`",
        "",
    ]

    for repo_res in data.get("results", []):
        pruned = repo_res.get("pruned", [])
        protected = repo_res.get("protected", [])
        if not pruned and not protected:
            continue
        r_name = repo_res.get("repo", "unknown")
        lines.append(f"### {r_name}")
        for p in pruned:
            branch = p.get("branch") or "detached"
            path = Path(p.get("path", "")).name
            action = p.get("action", "pruned")
            lines.append(f"- ✓ **[PRUNED]** `{path}` (`{branch}`): {action}")
        for p in protected:
            branch = p.get("branch") or "detached"
            path = Path(p.get("path", "")).name
            reasons = ", ".join(p.get("reasons", []))
            lines.append(f"- ⏳ **[PROTECTED]** `{path}` (`{branch}`): {reasons}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def render_prune(data: dict[str, Any]) -> str:
    try:
        from rich.console import Console
        from rich.markdown import Markdown
        import io
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=False)
        console.print(Markdown(markdown_prune(data)))
        return buf.getvalue()
    except ImportError:
        return markdown_prune(data)

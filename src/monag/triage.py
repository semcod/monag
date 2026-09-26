"""Holistic algorithmic workspace triage and guidance engine.

Integrates semcod/algocode and monag discovery across multi-organization
workspaces (e.g. semcod, wellmanifest, tellmesh), recording local ownership claims
and synthesizing read-only inspection steps. Remote Issues and CI are not scanned.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import shutil
from pathlib import Path
import shlex
import subprocess
import sys
import time
from typing import Any, Dict, List, Tuple

SCHEMA = "monag.triage/v1"

# Actionable algorithmic triage categories (Issue #68)
CATEGORY_IMMEDIATE_BLOCKER = "immediate_blocker"
CATEGORY_CORE_FOUNDATION = "core_foundation"
CATEGORY_STRATEGIC_ARCHITECTURE = "strategic_architecture"
CATEGORY_OPERATOR_IDE_ALERT = "operator_ide_alert"
CATEGORY_FLEET_HEALTH_DIAGNOSTIC = "fleet_health_diagnostic"
CATEGORY_CODE_SMELL_HYGIENE = "code_smell_hygiene"

CATEGORY_ORDER = [
    CATEGORY_IMMEDIATE_BLOCKER,
    CATEGORY_CORE_FOUNDATION,
    CATEGORY_STRATEGIC_ARCHITECTURE,
    CATEGORY_OPERATOR_IDE_ALERT,
    CATEGORY_FLEET_HEALTH_DIAGNOSTIC,
    CATEGORY_CODE_SMELL_HYGIENE,
]

CATEGORY_BASE_SCORES = {
    CATEGORY_IMMEDIATE_BLOCKER: 2000,
    CATEGORY_CORE_FOUNDATION: 1200,
    CATEGORY_STRATEGIC_ARCHITECTURE: 800,
    CATEGORY_OPERATOR_IDE_ALERT: 650,
    CATEGORY_FLEET_HEALTH_DIAGNOSTIC: 500,
    CATEGORY_CODE_SMELL_HYGIENE: 300,
}

CORE_REPOSITORIES = {
    "semcod/monag",
    "semcod/algocode",
    "semcod/repatch",
    "semcod/goal",
    "semcod/prefact",
    "semcod/tagi",
}


def _find_algocode_runner() -> str | None:
    """Check if semcod/algocode engine is importable or available in workspace."""
    try:
        import algocode.engine  # noqa: F401
        return "import"
    except ImportError:
        pass
    for parent in [Path.cwd(), Path.home() / "github", Path.home() / "github" / "semcod"]:
        algo_dir = parent / "algocode" / "src"
        if (algo_dir / "algocode").is_dir() and str(algo_dir) not in sys.path:
            sys.path.insert(0, str(algo_dir))
            try:
                import algocode.engine  # noqa: F401
                return "import"
            except ImportError:
                pass
    import shutil
    if shutil.which("algocode"):
        return "cli"
    return None


def audit_active_fleet_processes(root: Path | None = None) -> List[Dict[str, Any]]:
    """Scan machine processes to find active autonomous agents and their worktrees."""
    from . import monitor
    try:
        res = monitor.processes(root=root or (Path.home() / "github"), machine=True, open_files=False)
        if isinstance(res, tuple):
            return res[0]
        return res
    except Exception:
        return []


def _lease_evidence(repo_path: Path) -> List[Dict[str, Any]]:
    from .fleet import lease_observation
    if (repo_path / ".git").is_file():
        try:
            inventory = subprocess.run(
                ["git", "worktree", "list", "--porcelain", "-z"],
                cwd=str(repo_path), capture_output=True, text=True, timeout=3,
            )
            first = inventory.stdout.split("\0", 1)[0]
            if inventory.returncode or not first.startswith("worktree "):
                raise ValueError("primary checkout unavailable")
            repo_path = Path(first.removeprefix("worktree "))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return [{"lease_kind": "invalid", "lease_status": "unknown", "path": str(repo_path)}]
    directory = repo_path / ".subactor" / "leases"
    try:
        paths = sorted(directory.glob("*.json")) if directory.is_dir() else []
    except OSError:
        return [{"lease_kind": "invalid", "lease_status": "unknown", "path": str(directory)}]
    return [dict(lease_observation(path), path=str(path)) for path in paths]


def collect_active_leases(repo_path: Path) -> List[Dict[str, Any]]:
    """Return observed ownership claims, never proof of a running process."""
    active = {"active", "claimed", "editing", "in_progress", "validating",
              "publication_frozen", "dispatching", "approved"}
    return [row for row in _lease_evidence(repo_path) if row.get("lease_status") in active]


def check_agent_collision(
    repo_path: Path,
    ticket: str | None = None,
    fleet_processes: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Audit active agent fleet, worktree locks, and lease conflicts for a repository."""
    repo_path = repo_path.resolve()
    evidence = _lease_evidence(repo_path)
    active = {"active", "claimed", "editing", "in_progress", "validating",
              "publication_frozen", "dispatching", "approved"}
    terminal = {"released", "closed", "merged", "cancelled", "canceled", "complete", "completed", "done"}
    leases = [row for row in evidence if row.get("lease_status") in active]
    unknown = [row for row in evidence if row.get("lease_status") not in active | terminal]

    conflict_report: Dict[str, Any] = {}
    if _find_algocode_runner() == "import":
        try:
            import algocode.engine as algo
            conflict_report = algo.check_conflict(repo_root=repo_path)
        except Exception:
            pass

    # 1. Audit active agent processes running in or targeting this repo / worktrees
    active_agent_pids: List[int] = []
    active_agent_kinds: List[str] = []
    active_agent_worktrees: List[str] = []
    active_agent_descriptions: List[str] = []

    if isinstance(fleet_processes, tuple):
        fleet_processes = fleet_processes[0]
    elif fleet_processes is None:
        fleet_processes = audit_active_fleet_processes(repo_path)

    for proc in (fleet_processes or []):
        if not isinstance(proc, dict):
            continue
        pwds = list(proc.get("working_directories") or [])
        cwd = proc.get("cwd")
        if cwd and cwd not in pwds:
            pwds.append(cwd)

        matching_dirs = []
        for d in pwds:
            if not d:
                continue
            try:
                p = Path(d).resolve()
                if p == repo_path or repo_path in p.parents or p in repo_path.parents:
                    matching_dirs.append(str(p))
            except Exception:
                continue

        if matching_dirs:
            pid = proc.get("pid")
            kind = proc.get("kind") or "agent"
            if pid and pid not in active_agent_pids:
                active_agent_pids.append(pid)
            if kind and kind not in active_agent_kinds:
                active_agent_kinds.append(kind)
            for m in matching_dirs:
                if m not in active_agent_worktrees:
                    active_agent_worktrees.append(m)
            active_agent_descriptions.append(f"{kind} (PID {pid}) in {Path(matching_dirs[0]).name}")

    # 2. Audit dirty worktrees in repository
    dirty_worktrees: List[str] = []
    worktree_dir = repo_path / ".worktrees"
    if worktree_dir.is_dir():
        try:
            for wt in worktree_dir.iterdir():
                if wt.is_dir() and (wt / ".git").exists():
                    status_proc = subprocess.run(
                        ["git", "status", "--porcelain"],
                        cwd=str(wt), capture_output=True, text=True, timeout=2,
                    )
                    if status_proc.returncode == 0 and status_proc.stdout.strip():
                        dirty_worktrees.append(wt.name)
        except Exception:
            pass

    # Determine collision and blocking state
    has_process_collision = bool(active_agent_pids)
    has_algo_collision = bool(conflict_report.get("has_conflict", False))
    has_lease_collision = bool(leases)
    has_dirty_collision = bool(dirty_worktrees)

    has_collision = has_process_collision or has_algo_collision or (ticket and any(ticket in row.get("path", "") for row in leases))
    blocking = bool(conflict_report.get("blocking", False) or leases or unknown or active_agent_pids or dirty_worktrees)

    conflict_reasons = []
    if active_agent_descriptions:
        conflict_reasons.append(f"active agent process: {', '.join(active_agent_descriptions)}")
    if dirty_worktrees:
        conflict_reasons.append(f"uncommitted worktrees: {', '.join(dirty_worktrees)}")
    if leases:
        owners = sorted({row["lease_owner"] for row in leases if isinstance(row.get("lease_owner"), str)})
        conflict_reasons.append(f"active leases: {', '.join(owners) if owners else len(leases)}")
    if has_algo_collision:
        conflict_reasons.append("algocode declared scope conflict")

    conflict_basis = "; ".join(conflict_reasons) if conflict_reasons else "declared scopes; process activity verified safe"

    return {
        "has_collision": bool(has_collision),
        "conflict_basis": conflict_basis,
        "active_lease_count": len(leases),
        "active_owners": sorted({row["lease_owner"] for row in leases if isinstance(row.get("lease_owner"), str)}),
        "lease_evidence": evidence,
        "unknown_lease_count": len(unknown),
        "algocode_conflicts": conflict_report.get("conflicts", []),
        "active_agent_pids": active_agent_pids,
        "active_agent_kinds": active_agent_kinds,
        "active_agent_worktrees": active_agent_worktrees,
        "dirty_worktrees": dirty_worktrees,
        "blocking": bool(blocking),
        "ownership_verified": False,
    }


def classify_candidate(
    candidate: Dict[str, Any],
    repo_name: str,
    collision_info: Dict[str, Any],
) -> Tuple[str, int]:
    """Deterministically categorize and score candidate item.

    Returns:
        (category, final_score)
    """
    origin = candidate.get("origin", "")
    title = candidate.get("title", "").lower()
    priority = candidate.get("priority", "medium").lower()

    # 1. Immediate Blocker
    if (
        "critical" in priority
        or "blocker" in title
        or "disk full" in title
        or "memory leak" in title
        or "out of memory" in title
        or "panic" in title
        or candidate.get("health_status") == "critical"
        or candidate.get("failing_ci", False)
    ):
        score = CATEGORY_BASE_SCORES[CATEGORY_IMMEDIATE_BLOCKER]
        if "critical" in priority:
            score += 100
        return CATEGORY_IMMEDIATE_BLOCKER, score

    # 2. Core Foundation
    is_core = repo_name in CORE_REPOSITORIES or any(repo_name.endswith("/" + c.split("/")[-1]) for c in CORE_REPOSITORIES)
    if is_core and (origin in ("prs-open-pr", "prs-ahead-commits", "worktree-active", "worktree-observed") or "adopt" in title or "docs" in title):
        score = CATEGORY_BASE_SCORES[CATEGORY_CORE_FOUNDATION]
        if origin == "prs-open-pr" and candidate.get("checks_passed") is True:
            score += 150  # green PRs ready to merge get immediate elevation
        return CATEGORY_CORE_FOUNDATION, score

    # 3. Operator & IDE Integration Alert
    if (
        origin in ("mcp-bootstrap", "operator-alert", "ide-integration")
        or "bootstrap mcp" in title
        or "mcp telemetry" in title
        or "mcp server" in title
        or "planfile api" in title
        or "ide integration alert" in title
    ):
        score = CATEGORY_BASE_SCORES[CATEGORY_OPERATOR_IDE_ALERT]
        if priority in ("high", "p1"):
            score += 80
        elif priority in ("medium", "p2"):
            score += 40
        return CATEGORY_OPERATOR_IDE_ALERT, score

    # 4. Fleet Health Diagnostic
    if (
        "prune stale" in title
        or "stale git worktree" in title
        or "no-license" in title
        or "planfile-github-sync" in title
        or "fleet health" in title
        or origin in ("autodiagnosis", "fleet-diagnostic")
    ):
        score = CATEGORY_BASE_SCORES[CATEGORY_FLEET_HEALTH_DIAGNOSTIC]
        if priority in ("high", "p1"):
            score += 80
        elif priority in ("medium", "p2"):
            score += 40
        return CATEGORY_FLEET_HEALTH_DIAGNOSTIC, score

    # 5. Code Smell & Hygiene
    if (
        "shotgun" in title
        or "smell" in title
        or "god class" in title
        or "data clump" in title
        or "dead code" in title
        or "duplicate" in title
        or "catalog-undescribed" in origin
        or "taskill-doc-drift" in origin
        or candidate.get("triage_status") in ("DUPLICATE", "ALREADY_RESOLVED")
    ):
        score = CATEGORY_BASE_SCORES[CATEGORY_CODE_SMELL_HYGIENE]
        if candidate.get("triage_status") == "ALREADY_RESOLVED":
            score += 50
        return CATEGORY_CODE_SMELL_HYGIENE, score

    # 6. Strategic Architecture (default for substantive work)
    score = CATEGORY_BASE_SCORES[CATEGORY_STRATEGIC_ARCHITECTURE]
    if is_core:
        score += 100
    if priority in ("high", "p1"):
        score += 80
    elif priority in ("medium", "p2"):
        score += 40

    # If collision risk present, apply penalty to prevent stomping
    if collision_info.get("blocking") or collision_info.get("has_collision"):
        score -= 200

    return CATEGORY_STRATEGIC_ARCHITECTURE, score


def synthesize_triage_action(
    candidate: Dict[str, Any],
    category: str,
    repo_name: str,
    collision_info: Dict[str, Any],
) -> Dict[str, Any]:
    """Generate exact action, suggested command, and guardrails."""
    title = candidate.get("title", "")
    origin = candidate.get("origin", "")
    issue_num = candidate.get("issue_number")
    pr_num = candidate.get("pr_number")

    guardrails = [
        "Verify ticket ownership, exact scope and current lease fencing before writing.",
        "A missing, expired or historical lease never authorizes takeover.",
        "Use Wellmanifest Worktrees v5 (<primary>/.worktrees/ticket-NNN--slug).",
        "Publication requires current required checks and the configured protected delivery process.",
    ]
    if collision_info.get("active_agent_pids"):
        agents_str = ", ".join(f"{k} (PID {p})" for k, p in zip(collision_info.get("active_agent_kinds", []), collision_info.get("active_agent_pids", [])))
        guardrails.append(f"Active agent running: {agents_str}; pause write operations until agent completes.")
    if collision_info.get("dirty_worktrees"):
        wts_str = ", ".join(collision_info["dirty_worktrees"])
        guardrails.append(f"Uncommitted changes in worktrees ({wts_str}); inspect and clean before allocating new tickets.")
    if collision_info.get("active_owners"):
        owners = ", ".join(collision_info.get("active_owners", []))
        guardrails.append(f"Ownership or declared scope needs reconciliation ({owners}); do not edit overlapping files.")
    repo_arg = shlex.quote(repo_name)
    path_arg = shlex.quote(str(candidate.get("path") or repo_name))
    suggested_command = f"git -C {path_arg} status --short"
    action = f"Inspect ticket, checkout and ownership evidence in {repo_name}: {title}"
    if origin == "prs-open-pr" and str(pr_num or "").isdigit():
        action = f"Inspect current PR #{pr_num} before protected publication in {repo_name}"
        suggested_command = f"gh pr view {int(pr_num)} --repo {repo_arg} --json number,state,headRefOid,mergeable,statusCheckRollup"
    elif issue_num and str(issue_num).isdigit():
        action = f"Verify requirements and resolution evidence for issue #{issue_num} in {repo_name}"
        suggested_command = f"gh issue view {int(issue_num)} --repo {repo_arg}"

    return {
        "action": action,
        "suggested_command": suggested_command,
        "guardrails": guardrails,
        "evidence": candidate.get("evidence", f"{repo_name}: {title}"),
    }


def run_holistic_triage(
    root: Path,
    depth: int = 2,
    limit: int = 15,
    scan_issues: bool = True,
    extra_candidates: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Inspect local repositories; scan_issues is reserved and performs no API calls."""
    root = root.resolve()
    started = time.monotonic()
    discovered_repos: List[Tuple[str, Path]] = []

    # Audit running agent fleet across system/workspace once for performance
    active_fleet = audit_active_fleet_processes(root)

    errors = []
    def visit(path: Path, level: int) -> None:
        if (path / ".git").exists():
            name = str(path.relative_to(root)) if path != root else f"{path.parent.name}/{path.name}"
            discovered_repos.append((name, path))
            return
        if level >= depth:
            return
        try:
            children = sorted(path.iterdir())
        except OSError as error:
            errors.append(f"{path}: {type(error).__name__}")
            return
        for child in children:
            if child.is_dir() and not child.is_symlink() and not child.name.startswith("."):
                visit(child, level + 1)
    visit(root, 0)

    all_raw_candidates: List[Dict[str, Any]] = list(extra_candidates or [])

    # 2. Inspect each repo for active checkouts, unpushed commits, active processes and leases
    collisions_by_repo: Dict[str, Dict[str, Any]] = {}

    for repo_name, repo_path in discovered_repos:
        collision_info = check_agent_collision(repo_path, fleet_processes=active_fleet)
        collisions_by_repo[repo_name] = collision_info

        # Check for unpushed commits / ahead of origin
        try:
            proc = subprocess.run(
                ["git", "rev-list", "--count", "@{u}..HEAD"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=3,
            )
            if proc.returncode == 0 and proc.stdout.strip().isdigit():
                ahead = int(proc.stdout.strip())
                if ahead > 0:
                    all_raw_candidates.append({
                        "origin": "prs-ahead-commits",
                        "repo": repo_name,
                        "path": str(repo_path),
                        "title": f"{ahead} commit(s) ahead of local upstream ref; remote state unverified",
                        "priority": "high",
                        "ahead_count": ahead,
                    })
        except Exception as error:
            errors.append(f"{repo_path}: upstream comparison: {type(error).__name__}")

        # Check for worktrees
        try:
            wt_proc = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=3,
            )
            if wt_proc.returncode == 0:
                lines = wt_proc.stdout.splitlines()
                wt_paths = [line.split(" ", 1)[1] for line in lines if line.startswith("worktree ") and line.split(" ", 1)[1] != str(repo_path)]
                for wt in wt_paths:
                    wt_name = Path(wt).name
                    all_raw_candidates.append({
                        "origin": "worktree-observed",
                        "repo": repo_name,
                        "path": wt,
                        "title": f"Registered worktree to inspect: {wt_name}",
                        "priority": "medium",
                    })
            else:
                errors.append(f"{repo_path}: worktree inventory failed (exit {wt_proc.returncode})")
        except (OSError, subprocess.TimeoutExpired) as error:
            errors.append(f"{repo_path}: worktree inventory: {type(error).__name__}")

    # 3. Algorithmic categorization, ranking, and step synthesis
    categorized_items: List[Dict[str, Any]] = []

    for c in all_raw_candidates:
        repo_name = c.get("repo") or Path(c.get("path", "")).name
        collision_info = collisions_by_repo.get(repo_name, {"has_collision": False})

        category, score = classify_candidate(c, repo_name, collision_info)
        details = synthesize_triage_action(c, category, repo_name, collision_info)

        categorized_items.append({
            "repo": repo_name,
            "title": c.get("title", ""),
            "origin": c.get("origin", ""),
            "category": category,
            "score": score,
            "action": details["action"],
            "suggested_command": details["suggested_command"],
            "guardrails": details["guardrails"],
            "evidence": details["evidence"],
            "collision": collision_info,
            "radar": c.get("radar"),
        })

    # Sort descending by score
    categorized_items.sort(key=lambda item: item["score"], reverse=True)
    capped_items = categorized_items[:limit]

    # Generate sequential deterministic guidance steps
    guidance_steps = []
    for idx, item in enumerate(capped_items, start=1):
        is_collision = bool(item["collision"].get("has_collision") or item["collision"].get("blocking"))
        guidance_steps.append({
            "step": idx,
            "category": item["category"],
            "repo": item["repo"],
            "title": item["title"],
            "score": item["score"],
            "action": item["action"],
            "command": item["suggested_command"],
            "collision_safe": False if is_collision else None,
            "ownership_verified": False,
            "guardrails": item["guardrails"],
            "active_agent_pids": item["collision"].get("active_agent_pids", []),
            "dirty_worktrees": item["collision"].get("dirty_worktrees", []),
        })

    duration = round(time.monotonic() - started, 2)
    active_pids = sorted({pid for c in collisions_by_repo.values() for pid in c.get("active_agent_pids", [])})
    dirty_wts = sum(len(c.get("dirty_worktrees", [])) for c in collisions_by_repo.values())

    return {
        "schema": SCHEMA,
        "root": str(root),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": duration,
        "discovered_repos_count": len(discovered_repos),
        "total_candidates": len(all_raw_candidates),
        "active_agents_count": len(active_fleet),
        "active_agent_pids": active_pids,
        "dirty_worktrees_count": dirty_wts,
        "collision_count": sum(1 for c in collisions_by_repo.values() if c.get("has_collision")),
        "lease_blocked_repo_count": sum(1 for c in collisions_by_repo.values() if c.get("blocking")),
        "issue_scan_performed": False,
        "github_api_requests": 0,
        "evidence_scope": "local Git, process, worktree and lease observations",
        "errors": errors,
        "recommendations": capped_items,
        "guidance_steps": guidance_steps,
    }


def triage_markdown(report: Dict[str, Any]) -> str:
    """Format holistic triage report as GitHub Flavored Markdown."""
    lines = [
        "# MONAG Holistic Algorithmic Workspace Triage",
        "",
        f"- **Root**: `{report.get('root')}`",
        f"- **Discovered Repositories**: {report.get('discovered_repos_count')}",
        f"- **Total Candidates Evaluated**: {report.get('total_candidates')}",
        f"- **Active Agent Processes**: {report.get('active_agents_count', 0)} (PIDs: {report.get('active_agent_pids', [])})",
        f"- **Dirty / Uncommitted Worktrees**: {report.get('dirty_worktrees_count', 0)}",
        f"- **Declared Scope / Worktree Conflicts**: {report.get('collision_count')}",
        "- **Evidence**: local process, git worktree and lease observations; Wellmanifest Worktrees v5 compliant.",
        f"- **Generated At**: {report.get('generated_at')}",
        "",
        "## Deterministic Step-by-Step Guidance Plan",
        "",
    ]

    steps = report.get("guidance_steps", [])
    if not steps:
        lines.append("*No candidates found in the inspected local evidence; remote Issues were not scanned.*")
        return "\n".join(lines)

    for s in steps:
        cat_tag = s["category"].upper().replace("_", " ")
        safety = "Ownership verified" if s.get("ownership_verified") else ("⚠️ Declared conflict / active agent" if s.get("collision_safe") is False else "Ownership unverified (collision-safe)")
        lines.append(f"### Step {s['step']}: [{cat_tag}] `{s['repo']}` — {s['title']}")
        lines.append(f"- **Score**: `{s['score']}` | **Status**: {safety}")
        lines.append(f"- **Action**: {s['action']}")
        lines.append("- **Suggested Command**:")
        lines.append("  ```sh")
        lines.append(f"  {s['command']}")
        lines.append("  ```")
        if s["guardrails"]:
            lines.append("- **Guardrails**:")
            for g in s["guardrails"]:
                lines.append(f"  - {g}")
        lines.append("")

    return "\n".join(lines)


def export_planfile_tasks(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Export triage steps as Planfile-compatible ticket specifications."""
    tasks = []
    for s in report.get("guidance_steps", []):
        tasks.append({
            "title": f"[{s['category']}] {s['repo']}: {s['title']}",
            "description": s["action"],
            "command": s["command"],
            "priority": "P0" if s["category"] == CATEGORY_IMMEDIATE_BLOCKER else ("P1" if s["category"] == CATEGORY_CORE_FOUNDATION else "P2"),
            "repository": s["repo"],
            "guardrails": s["guardrails"],
            "score": s["score"],
        })
    return tasks


def feed_to_planfile(report: Dict[str, Any], root: Path, sprint: str = "current") -> Dict[str, Any]:
    """Persist project-local inspection tickets through the installed Planfile CLI."""
    tasks = export_planfile_tasks(report)
    result = {"success": True, "tasks_count": 0, "requested_count": len(tasks),
              "tickets": [], "errors": [], "remote_sync_performed": False}
    if not tasks:
        return result
    binary = shutil.which("planfile")
    if not binary:
        return dict(result, success=False, reason="planfile CLI not found on PATH")
    root = root.resolve()
    for task in tasks:
        repository = task["repository"]
        try:
            relative = Path(repository)
            if not repository or relative.is_absolute() or ".." in relative.parts:
                raise ValueError("invalid project path")
            project = (root / relative).resolve()
            if (root / ".git").exists() and repository == f"{root.parent.name}/{root.name}":
                project = root
            if not project.is_relative_to(root):
                raise ValueError("project escapes scan root")
            if not (project / ".git").exists() or not (project / ".planfile").is_dir():
                raise ValueError("owning project Git checkout and .planfile are required")
            digest = hashlib.sha256(json.dumps(
                [repository, task["title"], task["command"]], ensure_ascii=False
            ).encode()).hexdigest()[:32]
            label = "dedupe:monag-" + digest
            description = "\n".join([task["description"], task["command"], *task["guardrails"]])
            description = description.replace("<primary>", "registered primary checkout")
            priority = {"P0": "critical", "P1": "high"}.get(task["priority"], "normal")
            create = subprocess.run(
                [binary, "ticket", "create", "--priority", priority, "--sprint", sprint,
                 "--source", "monag-triage", "--label", label,
                 "--description", description, "--", task["title"]],
                cwd=str(project), capture_output=True, text=True, timeout=30,
            )
            if create.returncode:
                raise ValueError(f"Planfile creation failed (exit {create.returncode})")
            readback = subprocess.run(
                [binary, "ticket", "list", "--sprint", "all", "--label", label, "--format", "json"],
                cwd=str(project), capture_output=True, text=True, timeout=30,
            )
            if readback.returncode:
                raise ValueError(f"Planfile readback failed (exit {readback.returncode})")
            records = json.loads(readback.stdout)
            if not isinstance(records, list):
                raise ValueError("Planfile readback must be a ticket list")
            matches = [row for row in records if isinstance(row, dict)
                       and label in row.get("labels", []) and row.get("id")
                       and row.get("status") not in {"done", "canceled"}]
            if len(matches) != 1:
                raise ValueError("Planfile did not return one persisted dedupe owner")
            result["tickets"].append({"repository": repository, "id": matches[0]["id"],
                                      "project": str(project)})
            result["tasks_count"] += 1
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            result["errors"].append({"repository": repository, "error": str(error)})
    result["success"] = not result["errors"]
    if result["errors"]:
        result["reason"] = "Some tickets could not be persisted or verified; inspect errors and retry safely"
    return result

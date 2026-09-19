"""Holistic algorithmic workspace triage and guidance engine.

Integrates semcod/algocode and monag discovery across multi-organization
workspaces (e.g. semcod, wellmanifest, tellmesh), detecting running agent collisions,
evaluating issue backlogs, and synthesizing deterministic step-by-step guidance.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple

SCHEMA = "monag.triage/v1"

# Four algorithmic triage tiers
CATEGORY_IMMEDIATE_BLOCKER = "immediate_blocker"
CATEGORY_CORE_FOUNDATION = "core_foundation"
CATEGORY_STRATEGIC_ARCHITECTURE = "strategic_architecture"
CATEGORY_CODE_SMELL_HYGIENE = "code_smell_hygiene"

CATEGORY_ORDER = [
    CATEGORY_IMMEDIATE_BLOCKER,
    CATEGORY_CORE_FOUNDATION,
    CATEGORY_STRATEGIC_ARCHITECTURE,
    CATEGORY_CODE_SMELL_HYGIENE,
]

CATEGORY_BASE_SCORES = {
    CATEGORY_IMMEDIATE_BLOCKER: 2000,
    CATEGORY_CORE_FOUNDATION: 1200,
    CATEGORY_STRATEGIC_ARCHITECTURE: 800,
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


def collect_active_leases(repo_path: Path) -> List[Dict[str, Any]]:
    """Collect active change leases from .subactor/leases/ in repo."""
    leases = []
    leases_dir = repo_path / ".subactor" / "leases"
    if not leases_dir.is_dir():
        return leases

    for p in leases_dir.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            status = data.get("status", "")
            phase = data.get("phase", "")
            # Active if status is active or phase is not released
            if status == "active" or (phase and phase != "released"):
                leases.append(data)
        except Exception:
            continue
    return leases


def check_agent_collision(repo_path: Path, ticket: str | None = None) -> Dict[str, Any]:
    """Check if repository has active running agent leases or conflict signals."""
    active_leases = collect_active_leases(repo_path)
    runner = _find_algocode_runner()
    conflict_report: Dict[str, Any] = {}

    if runner == "import":
        try:
            import algocode.engine as algo
            conflict_report = algo.check_conflict(repo_root=repo_path)
        except Exception:
            conflict_report = {}

    has_collision = len(active_leases) > 0 or conflict_report.get("has_conflict", False)
    active_owners = [l.get("owner") or l.get("ownerActor") for l in active_leases if l.get("owner") or l.get("ownerActor")]

    return {
        "has_collision": has_collision,
        "active_lease_count": len(active_leases),
        "active_owners": sorted(set(filter(None, active_owners))),
        "algocode_conflicts": conflict_report.get("conflicts", []),
        "blocking": conflict_report.get("blocking", False) or len(active_leases) > 0,
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
    if is_core and (origin in ("prs-open-pr", "prs-ahead-commits", "worktree-active") or "adopt" in title or "docs" in title):
        score = CATEGORY_BASE_SCORES[CATEGORY_CORE_FOUNDATION]
        if origin == "prs-open-pr" and candidate.get("checks_passed", True):
            score += 150  # green PRs ready to merge get immediate elevation
        return CATEGORY_CORE_FOUNDATION, score

    # 3. Code Smell & Hygiene
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

    # 4. Strategic Architecture (default for substantive work)
    score = CATEGORY_BASE_SCORES[CATEGORY_STRATEGIC_ARCHITECTURE]
    if is_core:
        score += 100
    if priority in ("high", "p1"):
        score += 80
    elif priority in ("medium", "p2"):
        score += 40

    # If collision risk present, apply penalty to prevent stomping
    if collision_info.get("has_collision"):
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
    url = candidate.get("url", "")
    issue_num = candidate.get("issue_number")
    pr_num = candidate.get("pr_number")

    guardrails = []
    if collision_info.get("has_collision"):
        owners = ", ".join(collision_info.get("active_owners", [])) or "active lease"
        guardrails.append(f"CAUTION: Running agent lease held by ({owners}). Do NOT edit overlapping files.")

    guardrails.append("Require 100% green tests before commit or merge (Prymat Zielonych Testów).")
    guardrails.append("Use Wellmanifest Worktrees v5 (<primary>/.worktrees/ticket-NNN--slug).")

    if category == CATEGORY_IMMEDIATE_BLOCKER:
        action = f"Mitigate critical blocker in {repo_name}: {title}"
        suggested_command = f"fixos run --repo {repo_name}" if "disk" in title or "health" in title else f"git -C {repo_name} status"
    elif category == CATEGORY_CORE_FOUNDATION:
        if origin == "prs-open-pr" and pr_num:
            action = f"Verify and merge PR #{pr_num} in core repo {repo_name}"
            suggested_command = f"gh pr merge {pr_num} --repo {repo_name} --squash --admin"
        else:
            action = f"Advance core foundational task in {repo_name}: {title}"
            suggested_command = f"monag advise --root {repo_name}"
    elif category == CATEGORY_STRATEGIC_ARCHITECTURE:
        action = f"Implement architectural task in {repo_name}: {title}"
        suggested_command = f"algocode triage {repo_name}"
    else:  # code_smell_hygiene
        if candidate.get("triage_status") == "ALREADY_RESOLVED" and issue_num:
            action = f"Close reconciled issue #{issue_num} in {repo_name}"
            suggested_command = f"gh issue close {issue_num} --repo {repo_name} --comment 'Reconciled in recent git commit.'"
        elif candidate.get("triage_status") == "DUPLICATE" and issue_num:
            action = f"Consolidate duplicate issue #{issue_num} in {repo_name}"
            suggested_command = f"gh issue comment {issue_num} --repo {repo_name} --body 'Consolidated duplicate.'"
        else:
            action = f"Resolve quality/code-smell item in {repo_name}: {title}"
            suggested_command = f"prefact run --repo {repo_name}"

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
    """Execute holistic multi-org triage across all repositories under root."""
    started = time.monotonic()
    discovered_repos: List[Tuple[str, Path]] = []

    # 1. Discover all repositories across multi-org root
    if (root / ".git").is_dir():
        discovered_repos.append((root.name, root))
    else:
        # Multi-org discovery (e.g. ~/github/*/*)
        for org_dir in sorted(root.iterdir()):
            if not org_dir.is_dir() or org_dir.name.startswith("."):
                continue
            if (org_dir / ".git").is_dir():
                discovered_repos.append((org_dir.name, org_dir))
            else:
                for repo_dir in sorted(org_dir.iterdir()):
                    if repo_dir.is_dir() and (repo_dir / ".git").is_dir():
                        repo_name = f"{org_dir.name}/{repo_dir.name}"
                        discovered_repos.append((repo_name, repo_dir))

    all_raw_candidates: List[Dict[str, Any]] = list(extra_candidates or [])

    # 2. Inspect each repo for active checkouts, unpushed commits, and leases
    collisions_by_repo: Dict[str, Dict[str, Any]] = {}

    for repo_name, repo_path in discovered_repos:
        collision_info = check_agent_collision(repo_path)
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
                        "title": f"{ahead} unpushed commit(s) on main/current branch",
                        "priority": "high",
                        "ahead_count": ahead,
                    })
        except Exception:
            pass

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
                wt_paths = [l.split(" ", 1)[1] for l in lines if l.startswith("worktree ") and l.split(" ", 1)[1] != str(repo_path)]
                for wt in wt_paths:
                    wt_name = Path(wt).name
                    all_raw_candidates.append({
                        "origin": "worktree-active",
                        "repo": repo_name,
                        "path": wt,
                        "title": f"Active worktree: {wt_name}",
                        "priority": "medium",
                    })
        except Exception:
            pass

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
        guidance_steps.append({
            "step": idx,
            "category": item["category"],
            "repo": item["repo"],
            "title": item["title"],
            "score": item["score"],
            "action": item["action"],
            "command": item["suggested_command"],
            "collision_safe": not item["collision"].get("has_collision", False),
            "guardrails": item["guardrails"],
        })

    duration = round(time.monotonic() - started, 2)

    return {
        "schema": SCHEMA,
        "root": str(root),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": duration,
        "discovered_repos_count": len(discovered_repos),
        "total_candidates": len(all_raw_candidates),
        "collision_count": sum(1 for c in collisions_by_repo.values() if c.get("has_collision")),
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
        f"- **Active Agent Collisions Detected**: {report.get('collision_count')}",
        f"- **Generated At**: {report.get('generated_at')}",
        "",
        "## Deterministic Step-by-Step Guidance Plan",
        "",
    ]

    steps = report.get("guidance_steps", [])
    if not steps:
        lines.append("*No pending tasks or blockers found across discovered repositories.*")
        return "\n".join(lines)

    for s in steps:
        cat_tag = s["category"].upper().replace("_", " ")
        safety = "🛡️ Safe" if s["collision_safe"] else "⚠️ Collision Risk"
        lines.append(f"### Step {s['step']}: [{cat_tag}] `{s['repo']}` — {s['title']}")
        lines.append(f"- **Score**: `{s['score']}` | **Status**: {safety}")
        lines.append(f"- **Action**: {s['action']}")
        lines.append(f"- **Suggested Command**:")
        lines.append(f"  ```sh")
        lines.append(f"  {s['command']}")
        lines.append(f"  ```")
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
    """Ingest guidance steps into workspace Planfile backlog/sprint."""
    tasks = export_planfile_tasks(report)
    planfile_dir = root / ".planfile"
    if not planfile_dir.is_dir():
        planfile_dir = root / "semcod" / "monag" / ".planfile"

    if not planfile_dir.is_dir():
        return {"success": False, "reason": "No .planfile directory found", "tasks_count": len(tasks)}

    sprint_file = planfile_dir / "sprints" / f"{sprint}.yaml"
    return {
        "success": True,
        "target": str(sprint_file),
        "tasks_count": len(tasks),
        "tasks": tasks,
    }

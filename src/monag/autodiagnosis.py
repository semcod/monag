"""Autodiagnosis & SubLLM ticket generation engine for workspace fleet.

Integrates fleet diagnostics (diagit, git-state), task coverage (monag),
and learning-loop failure patterns (subactor.reflex). Synthesizes actionable,
high-value tickets via SubLLM, writes them directly to target repositories'
Planfile sprints, and prepares them for GitHub Issues synchronization and
autonomous execution by Koru Autonomous.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml

SCHEMA = "monag.autodiagnosis/v1"

TIER_FLOOR = "floor"
TIER_MISSION = "mission"
TIER_HYGIENE = "hygiene"
TIER_BACKLOG = "backlog"

TIER_PRIORITY_MAP = {
    TIER_FLOOR: "critical",
    TIER_MISSION: "high",
    TIER_HYGIENE: "medium",
    TIER_BACKLOG: "low",
}

TIER_ORDER = {
    TIER_FLOOR: 0,
    TIER_MISSION: 1,
    TIER_HYGIENE: 2,
    TIER_BACKLOG: 3,
}

PRIORITY_ORDER = {
    "critical": 0,
    "highest": 0,
    "high": 1,
    "medium": 2,
    "normal": 2,
    "low": 3,
    "lowest": 4,
}


def priority_sort_key(ticket_or_task: Dict[str, Any]) -> tuple:
    """Sort key matching Wellmanifest lexicographic tiers and priority order.

    1. Tier: floor (0) < mission (1) < hygiene (2) < backlog (3)
    2. Priority: critical (0) < high (1) < medium/normal (2) < low (3) < lowest (4)
    3. Created at: older first (FIFO)
    """
    tier = str(ticket_or_task.get("tier") or TIER_BACKLOG).lower()
    priority = str(ticket_or_task.get("priority") or "normal").lower()
    created_at = str(ticket_or_task.get("created_at") or "")

    tier_weight = TIER_ORDER.get(tier, 3)
    priority_weight = PRIORITY_ORDER.get(priority, 2)
    return (tier_weight, priority_weight, created_at)


def sort_tickets_by_priority(tickets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deterministically sort tickets according to Wellmanifest priority tiers."""
    return sorted(tickets, key=priority_sort_key)



def _find_subllm_runner() -> Optional[Callable[[str], str]]:
    """Locate SubLLM client runner or return None if unavailable."""
    # 1. Direct Python import
    try:
        from subllm import complete  # noqa: F401
        from subllm.client_types import CompletionResponse

        def _subllm_import_runner(prompt: str) -> str:
            messages = [{"role": "user", "content": prompt}]
            try:
                resp = complete("koru-agent", "nl-to-koru-dsl", messages, timeout_seconds=30.0)
                if isinstance(resp, CompletionResponse):
                    return resp.content
                return str(resp)
            except Exception:
                try:
                    resp = complete("todo2code", "semantic", messages, timeout_seconds=30.0)
                    if isinstance(resp, CompletionResponse):
                        return resp.content
                    return str(resp)
                except Exception as e:
                    raise RuntimeError(f"SubLLM import invocation failed: {e}") from e

        return _subllm_import_runner
    except ImportError:
        pass

    # 2. Check workspace paths
    for parent in [Path.cwd(), Path.home() / "github", Path.home() / "github" / "subactor"]:
        subllm_src = parent / "subllm" / "src"
        if subllm_src.is_dir() and str(subllm_src) not in sys.path:
            sys.path.insert(0, str(subllm_src))
            try:
                from subllm import complete  # noqa: F401
                from subllm.client_types import CompletionResponse

                def _subllm_workspace_runner(prompt: str) -> str:
                    messages = [{"role": "user", "content": prompt}]
                    try:
                        resp = complete("koru-agent", "nl-to-koru-dsl", messages, timeout_seconds=30.0)
                        if isinstance(resp, CompletionResponse):
                            return resp.content
                        return str(resp)
                    except Exception:
                        try:
                            resp = complete("todo2code", "semantic", messages, timeout_seconds=30.0)
                            if isinstance(resp, CompletionResponse):
                                return resp.content
                            return str(resp)
                        except Exception as e:
                            raise RuntimeError(f"SubLLM workspace invocation failed: {e}") from e

                return _subllm_workspace_runner
            except ImportError:
                pass

    # 3. CLI executable
    subllm_complete_bin = shutil.which("subllm-complete")
    if subllm_complete_bin:
        def _subllm_cli_runner(prompt: str) -> str:
            proc = subprocess.run([subllm_complete_bin, "koru-agent", "nl-to-koru-dsl"],
                                  input=prompt, capture_output=True, text=True, timeout=30)
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
            raise RuntimeError(f"subllm-complete CLI failed: {proc.stderr.strip()}")

        return _subllm_cli_runner

    return None


def inspect_repository_anomalies(repo_path: Path) -> List[Dict[str, Any]]:
    """Fast, read-only inspection of repository technical state and anomalies."""
    anomalies: List[Dict[str, Any]] = []
    repo_name = repo_path.name
    if repo_path.parent and repo_path.parent.name:
        repo_name = f"{repo_path.parent.name}/{repo_path.name}"

    git_dir = repo_path / ".git"
    if not git_dir.exists():
        return anomalies

    # 1. Missing standard files
    has_readme = any((repo_path / f).exists() for f in ["README.md", "readme.md", "README", "README.txt"])
    if not has_readme:
        anomalies.append({
            "code": "NO_README",
            "tier": TIER_HYGIENE,
            "severity": "WARNING",
            "target": repo_name,
            "path": str(repo_path),
            "summary": "Repository is missing a README.md file.",
            "evidence": "No README or README.md found in repository root.",
        })

    has_license = any((repo_path / f).exists() for f in ["LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE"])
    if not has_license:
        anomalies.append({
            "code": "NO_LICENSE",
            "tier": TIER_HYGIENE,
            "severity": "WARNING",
            "target": repo_name,
            "path": str(repo_path),
            "summary": "Repository is missing a LICENSE file.",
            "evidence": "No LICENSE file found in repository root.",
        })

    # 2. Git status checks (read-only porcelain)
    try:
        proc_status = subprocess.run(["git", "-C", str(repo_path), "status", "--porcelain"],
                                     capture_output=True, text=True, timeout=10)
        if proc_status.returncode == 0 and proc_status.stdout.strip():
            dirty_lines = proc_status.stdout.strip().splitlines()
            anomalies.append({
                "code": "DIRTY_WORKTREE",
                "tier": TIER_FLOOR,
                "severity": "WARNING",
                "target": repo_name,
                "path": str(repo_path),
                "summary": f"Repository has {len(dirty_lines)} uncommitted changes in primary checkout.",
                "evidence": f"git status --porcelain reports {len(dirty_lines)} modified/untracked files.",
                "details": dirty_lines[:5],
            })
    except Exception:
        pass

    # 3. Worktree checks
    try:
        proc_wt = subprocess.run(["git", "-C", str(repo_path), "worktree", "list", "--porcelain"],
                                 capture_output=True, text=True, timeout=10)
        if proc_wt.returncode == 0:
            wt_blocks = [b.strip() for b in proc_wt.stdout.strip().split("\n\n") if b.strip()]
            if len(wt_blocks) > 5:
                anomalies.append({
                    "code": "HIGH_WORKTREE_COUNT",
                    "tier": TIER_HYGIENE,
                    "severity": "INFO",
                    "target": repo_name,
                    "path": str(repo_path),
                    "summary": f"Repository has {len(wt_blocks)} linked worktrees.",
                    "evidence": f"Observed {len(wt_blocks)} active or leftover worktrees in git worktree list.",
                })
    except Exception:
        pass

    # 4. Planfile checks
    planfile_dir = repo_path / ".planfile"
    if not planfile_dir.is_dir():
        anomalies.append({
            "code": "PLANFILE_UNINITIALIZED",
            "tier": TIER_MISSION,
            "severity": "INFO",
            "target": repo_name,
            "path": str(repo_path),
            "summary": "Repository has no .planfile directory for task orchestration.",
            "evidence": "Missing .planfile/sprints structure.",
        })
    else:
        sync_file = planfile_dir / "sync" / "github.state.yaml"
        if not sync_file.is_file():
            anomalies.append({
                "code": "PLANFILE_GITHUB_SYNC_MISSING",
                "tier": TIER_HYGIENE,
                "severity": "INFO",
                "target": repo_name,
                "path": str(repo_path),
                "summary": "Planfile is not configured for GitHub Issues synchronization.",
                "evidence": "Missing .planfile/sync/github.state.yaml.",
            })

    # 5. Dependency / packaging check
    pyproject = repo_path / "pyproject.toml"
    package_json = repo_path / "package.json"
    if pyproject.is_file():
        text = pyproject.read_text(errors="replace")
        if "dependencies" in text and "git+" in text:
            anomalies.append({
                "code": "DEPENDENCY_GIT_URL_FOUND",
                "tier": TIER_FLOOR,
                "severity": "WARNING",
                "target": repo_name,
                "path": str(repo_path),
                "summary": "Repository contains unpinned or raw Git URL dependencies in pyproject.toml.",
                "evidence": "Found 'git+' URL in pyproject.toml dependencies.",
            })
    if package_json.is_file():
        text = package_json.read_text(errors="replace")
        if "git+" in text or "github:" in text:
            anomalies.append({
                "code": "DEPENDENCY_GIT_URL_FOUND",
                "tier": TIER_FLOOR,
                "severity": "WARNING",
                "target": repo_name,
                "path": str(repo_path),
                "summary": "Repository contains unpinned Git URL dependencies in package.json.",
                "evidence": "Found 'git+' or 'github:' reference in package.json dependencies.",
            })

    # 6. Unresolved Git merge conflict markers
    try:
        proc_conflict = subprocess.run(
            ["git", "-C", str(repo_path), "grep", "-I", "-l", "-E", "^(<<<<<<< |=======|>>>>>>> )"],
            capture_output=True, text=True, timeout=10
        )
        if proc_conflict.returncode == 0 and proc_conflict.stdout.strip():
            conflict_files = proc_conflict.stdout.strip().splitlines()
            anomalies.append({
                "code": "GIT_CONFLICT_MARKERS",
                "tier": TIER_FLOOR,
                "severity": "ERROR",
                "target": repo_name,
                "path": str(repo_path),
                "summary": f"Repository contains unresolved Git merge conflict markers in {len(conflict_files)} files.",
                "evidence": f"Unresolved conflict markers detected in: {', '.join(conflict_files[:3])}",
                "details": conflict_files,
            })
    except Exception:
        pass

    # 7. Broken or missing Python virtualenv
    if pyproject.is_file() or (repo_path / "requirements.txt").is_file():
        venv_candidates = [repo_path / ".venv", repo_path / "venv"]
        for vpath in venv_candidates:
            if vpath.is_symlink() and not vpath.exists():
                anomalies.append({
                    "code": "BROKEN_VENV",
                    "tier": TIER_FLOOR,
                    "severity": "ERROR",
                    "target": repo_name,
                    "path": str(repo_path),
                    "summary": f"Broken virtualenv symlink detected at {vpath.name}.",
                    "evidence": f"Symlink {vpath} points to non-existent target.",
                })
            elif vpath.is_dir() and not (vpath / "bin" / "python").exists() and not (vpath / "Scripts" / "python.exe").exists():
                anomalies.append({
                    "code": "BROKEN_VENV",
                    "tier": TIER_FLOOR,
                    "severity": "WARNING",
                    "target": repo_name,
                    "path": str(repo_path),
                    "summary": f"Incomplete or damaged virtualenv at {vpath.name} (missing python executable).",
                    "evidence": f"Virtualenv directory {vpath} does not contain bin/python or Scripts/python.exe.",
                })

    return anomalies


def diagnose_fleet(root: Path, depth: int = 2, db: Optional[Any] = None,
                   use_cache: bool = True, state_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Scan workspace fleet for technical defects, governance drift, and ticket readiness."""
    started = datetime.now(timezone.utc)
    repos: List[Path] = []

    if (root / ".git").exists():
        repos.append(root)
    else:
        ignored = {".git", ".cache", "node_modules", ".venv", "venv", ".worktrees"}
        for p in root.iterdir():
            try:
                if p.is_dir() and p.name not in ignored and not p.name.startswith("."):
                    if (p / ".git").exists():
                        repos.append(p)
                    elif depth > 1:
                        for sub in p.iterdir():
                            if sub.is_dir() and sub.name not in ignored and not sub.name.startswith("."):
                                if (sub / ".git").exists():
                                    repos.append(sub)
            except (OSError, PermissionError):
                pass

    database = None
    if use_cache:
        if db is not None:
            database = db
        else:
            try:
                from . import autodiag_store
                database = autodiag_store.connect(state_dir=state_dir)
            except Exception:
                database = None

    all_anomalies: List[Dict[str, Any]] = []
    cached_repos_count = 0
    repo_fingerprints: Dict[str, Tuple[str, str]] = {}

    for r in sorted(set(repos)):
        repo_str = str(r)
        if database is not None:
            try:
                from . import autodiag_store
                head_sha, dirty_digest = autodiag_store.compute_repo_fingerprint(r)
                repo_fingerprints[repo_str] = (head_sha, dirty_digest)
                cached = autodiag_store.get_cached_diagnosis(database, repo_str, head_sha, dirty_digest)
                if cached is not None:
                    cached_anom, _ = cached
                    all_anomalies.extend(cached_anom)
                    cached_repos_count += 1
                    continue
            except Exception:
                pass

        all_anomalies.extend(inspect_repository_anomalies(r))

    return {
        "schema": SCHEMA,
        "root": str(root),
        "timestamp": started.isoformat(),
        "repositories_checked": len(repos),
        "repositories_cached": cached_repos_count,
        "anomalies_count": len(all_anomalies),
        "anomalies": all_anomalies,
        "_repo_fingerprints": repo_fingerprints,
        "_database": database,
    }


def _format_subllm_prompt(anomaly: Dict[str, Any]) -> str:
    """Prepare a strict JSON-focused prompt for SubLLM ticket synthesis."""
    return f"""You are a Lead AI Architect and Autonomous Software Engineer.
Synthesize an autonomous remediation ticket for an observed repository anomaly.

Observed Anomaly:
- Repository: {anomaly.get('target')}
- Code: {anomaly.get('code')}
- Tier: {anomaly.get('tier')}
- Severity: {anomaly.get('severity')}
- Summary: {anomaly.get('summary')}
- Evidence: {anomaly.get('evidence')}

Output a single valid JSON object with the following fields:
{{
  "title": "[{anomaly.get('target')}] Concise action title",
  "target_repo": "{anomaly.get('target')}",
  "tier": "{anomaly.get('tier')}",
  "priority": "{TIER_PRIORITY_MAP.get(anomaly.get('tier', 'backlog'), 'normal')}",
  "action": "Exact technical step required to remediate this issue",
  "acceptance_criteria": [
    "AC-01: First testable acceptance condition",
    "AC-02: Second testable acceptance condition"
  ],
  "verification_command": "Command to run to verify the fix",
  "satisfied_when": "Clear completion condition",
  "labels": ["monag", "autodiagnosis", "koru-autonomous"]
}}
Return ONLY valid raw JSON without markdown code fences or conversational prose.
"""


def _parse_subllm_response(text: str, fallback_anomaly: Dict[str, Any]) -> Dict[str, Any]:
    """Parse JSON response from SubLLM or return structured fallback ticket."""
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\n", "", clean)
        clean = re.sub(r"\n```$", "", clean)

    try:
        data = json.loads(clean)
        if isinstance(data, dict) and data.get("title") and data.get("acceptance_criteria"):
            return data
    except Exception:
        pass

    # Rule-based fallback synthesis
    code = fallback_anomaly.get("code", "DEFECT")
    target = fallback_anomaly.get("target", "repository")
    tier = fallback_anomaly.get("tier", TIER_BACKLOG)
    action_map = {
        "NO_README": "Create standard README.md documenting project purpose, quickstart, and testing instructions.",
        "NO_LICENSE": "Add Apache-2.0 or approved standard LICENSE file.",
        "DIRTY_WORKTREE": "Investigate uncommitted changes in primary checkout, commit or isolate in dedicated delivery worktree.",
        "HIGH_WORKTREE_COUNT": "Audit and prune obsolete or merged worktrees using diagit or monag doctor --fix.",
        "PLANFILE_UNINITIALIZED": "Initialize .planfile/sprints directory structure for task orchestration and autonomous agent delivery.",
        "PLANFILE_GITHUB_SYNC_MISSING": "Configure .planfile/sync/github.state.yaml to enable bidirectional GitHub Issues synchronization.",
        "DEPENDENCY_GIT_URL_FOUND": "Replace unbounded git+ URL dependency with published package contract or bounded version pin.",
        "GIT_CONFLICT_MARKERS": "Resolve merge conflicts, remove conflict markers, and verify syntax with git status and tests.",
        "BROKEN_VENV": "Recreate damaged virtual environment (.venv) and reinstall project dependencies.",
    }
    action = action_map.get(code, f"Resolve {code} in {target}.")
    ac1 = f"AC-01: {fallback_anomaly.get('summary', 'Anomaly is remediated')}."
    ac2 = "AC-02: Verification checks and automated test suite pass with exit code 0."

    return {
        "title": f"[{target}] fix({code.lower().replace('_', '-')}): {fallback_anomaly.get('summary')}",
        "target_repo": target,
        "tier": tier,
        "priority": TIER_PRIORITY_MAP.get(tier, "normal"),
        "action": action,
        "acceptance_criteria": [ac1, ac2],
        "verification_command": "git status --porcelain && npm test || pytest -q",
        "satisfied_when": f"{code} condition is resolved and verified.",
        "labels": ["monag", "autodiagnosis", "koru-autonomous", f"tier:{tier}"],
    }


def synthesize_tickets_with_subllm(anomalies: Any,
                                   runner: Optional[Callable[[str], str]] = None,
                                   db: Optional[Any] = None) -> List[Dict[str, Any]]:
    """Synthesize high-fidelity Planfile/GitHub/Koru tickets from raw anomalies using SubLLM."""
    if runner is None:
        runner = _find_subllm_runner()

    report_dict: Optional[Dict[str, Any]] = None
    if isinstance(anomalies, dict):
        report_dict = anomalies
        anom_list = anomalies.get("anomalies", [])
    else:
        anom_list = list(anomalies or [])

    tickets: List[Dict[str, Any]] = []
    for anom in anom_list:
        subllm_result: Optional[str] = None
        if runner:
            try:
                prompt = _format_subllm_prompt(anom)
                subllm_result = runner(prompt)
            except Exception:
                subllm_result = None

        ticket_spec = _parse_subllm_response(subllm_result or "", anom)

        # Assemble full Planfile ticket with Koru handoff directives, empirical estimation, and GitHub issue markdown
        target = ticket_spec.get("target_repo", anom.get("target", "workspace"))
        title = ticket_spec.get("title", f"[{target}] Remediate technical defect")
        ac_lines = "\n".join(f"- [ ] {ac}" for ac in ticket_spec.get("acceptance_criteria", []))
        cmd = ticket_spec.get("verification_command", "npm test || pytest -q")

        # Enrich with semcod/estimation empirical resource envelope
        try:
            from . import estimation as est_mod
            estimation_data = est_mod.estimate_verification(cmd, target)
            estimation_md = est_mod.format_estimation_markdown(estimation_data)
        except Exception:
            estimation_data = {
                "duration_p50_seconds": 2.5,
                "duration_p90_seconds": 4.5,
                "peak_rss_mb": 128.0,
                "effective_cpu_cores": 0.8,
                "confidence": "none",
                "samples_count": 0,
                "source": "default_envelope"
            }
            estimation_md = ""

        description = f"""## Context
Observed technical defect in `{target}`:
- **Code**: `{anom.get('code')}`
- **Severity**: {anom.get('severity', 'WARNING')}
- **Evidence**: {anom.get('evidence', 'Observed in fleet autodiagnosis.')}

## Problem & Action
{ticket_spec.get('action', anom.get('summary'))}

## Acceptance Criteria
{ac_lines}

## Verification
```sh
{cmd}
```

{estimation_md}
## Planfile & Koru Autonomous Handoff
- Driven by: `koru autonomous`
- When checks pass and the work is complete, mark done via: `planfile ticket done <id>`
- Git discipline: commit only files modified for this ticket; stage explicitly by path; write conventional commit message.
"""

        tier = ticket_spec.get("tier", anom.get("tier", TIER_BACKLOG))
        priority = ticket_spec.get("priority", TIER_PRIORITY_MAP.get(tier, "normal"))

        # Build stable diagnostic ID from target and anomaly code
        code_str = str(anom.get("code") or "DEFECT")
        diag_hash = hashlib.md5(f"{target}:{code_str}".encode("utf-8")).hexdigest()[:8]
        diag_id = f"DIAG-{diag_hash}"

        # todo2code label integration
        labels = list(dict.fromkeys(ticket_spec.get("labels", ["monag", "autodiagnosis", "koru-autonomous"]) + [
            "todo2code",
            "type:development-defect",
            f"tier:{tier}",
            f"priority:{priority}",
        ]))

        source_info = {
            "tool": "todo2code",
            "origin": "monag.autodiagnosis",
            "context": {
                "target_repo": target,
                "code": code_str,
                "diagnostic_ids": [diag_id],
            }
        }

        inputs_info = {
            "verify_command": cmd,
            "expect_files_changed": True,
            "patch_mode": True,
            "worktree": True,
            "risk_class": "R1",
            "contract": "wellmanifest.defect-repair/v1",
            "llm_timeout_seconds": 300,
            "max_patch_attempts": 3,
        }

        executor_info = {
            "kind": "llm",
            "mode": "automatic",
        }

        ticket = {
            "title": title,
            "description": description.strip(),
            "target_repo": target,
            "tier": tier,
            "priority": priority,
            "labels": labels,
            "action": ticket_spec.get("action"),
            "acceptance_criteria": ticket_spec.get("acceptance_criteria", []),
            "satisfied_when": ticket_spec.get("satisfied_when"),
            "verification_command": cmd,
            "estimation": estimation_data,
            "estimated_duration_seconds": estimation_data.get("duration_p90_seconds"),
            "estimated_peak_rss_mb": estimation_data.get("peak_rss_mb"),
            "estimation_confidence": estimation_data.get("confidence"),
            "source": source_info,
            "inputs": inputs_info,
            "executor": executor_info,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        tickets.append(ticket)

    # Sort tickets deterministically by Wellmanifest Priority tiers
    tickets = sort_tickets_by_priority(tickets)

    # Persist into SQLite cache if database is available
    database = db or (report_dict.get("_database") if report_dict else None)
    if database is not None and report_dict is not None:
        try:
            from . import autodiag_store
            fingerprints = report_dict.get("_repo_fingerprints", {})
            for repo_str, (head_sha, dirty_digest) in fingerprints.items():
                repo_anoms = [a for a in anom_list if a.get("target") in (repo_str, Path(repo_str).name)]
                repo_tkts = [t for t in tickets if t.get("target_repo") in (repo_str, Path(repo_str).name)]
                autodiag_store.save_cached_diagnosis(database, repo_str, head_sha, dirty_digest, repo_anoms, repo_tkts)
        except Exception:
            pass

    return tickets


def sync_planfile_github(repo_path: Path) -> Dict[str, Any]:
    """Run planfile sync github in the target repository if planfile is available."""
    planfile_bin = shutil.which("planfile")
    cmd = [planfile_bin, "sync", "github"] if planfile_bin else [sys.executable, "-m", "planfile", "sync", "github"]
    try:
        proc = subprocess.run(cmd, cwd=str(repo_path), capture_output=True, text=True, timeout=60)
        return {
            "target": str(repo_path),
            "ok": proc.returncode == 0,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "exit_code": proc.returncode,
        }
    except Exception as err:
        return {
            "target": str(repo_path),
            "ok": False,
            "error": str(err),
            "exit_code": 1,
        }


def dispatch_tickets_to_planfile(tickets: List[Dict[str, Any]], root: Path,
                                 sprint: str = "current",
                                 sync_github: bool = False) -> Dict[str, Any]:
    """Write synthesized tickets into target projects' Planfile sprint storage."""
    results: Dict[str, Any] = {
        "total_tickets": len(tickets),
        "dispatched": 0,
        "repositories_updated": [],
        "tickets_by_repo": {},
        "errors": [],
    }

    # Group tickets by target_repo
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for t in tickets:
        target = t.get("target_repo", "")
        grouped.setdefault(target, []).append(t)

    for target, repo_tickets in grouped.items():
        # Find directory for target
        target_path: Optional[Path] = None
        if (root / target).is_dir():
            target_path = root / target
        elif (root / target.split("/")[-1]).is_dir():
            target_path = root / target.split("/")[-1]
        elif root.name == target or f"{root.parent.name}/{root.name}" == target:
            target_path = root

        if not target_path or not target_path.is_dir():
            results["errors"].append(f"Target repository directory not found for: {target}")
            continue

        planfile_sprints_dir = target_path / ".planfile" / "sprints"
        planfile_sprints_dir.mkdir(parents=True, exist_ok=True)
        sprint_file = planfile_sprints_dir / f"{sprint}.yaml"

        existing_data: Dict[str, Any] = {}
        if sprint_file.is_file():
            try:
                loaded = yaml.safe_load(sprint_file.read_text())
                if isinstance(loaded, dict):
                    existing_data = loaded
            except Exception:
                pass

        if "tasks" not in existing_data:
            existing_data["tasks"] = []
        if "schema" not in existing_data:
            existing_data["schema"] = "planfile.sprint/v1"
        if "sprint" not in existing_data:
            existing_data["sprint"] = sprint

        existing_titles = {tsk.get("title") for tsk in existing_data["tasks"] if isinstance(tsk, dict)}

        added_for_repo: List[str] = []
        for t in repo_tickets:
            if t["title"] in existing_titles:
                continue

            ticket_id = f"task_{int(datetime.now(timezone.utc).timestamp())}_{len(existing_data['tasks']) + 1}"
            t_inputs = dict(t.get("inputs") or {})
            t_inputs.setdefault("verify_command", t.get("verification_command", "npm test || pytest -q"))
            t_inputs.setdefault("contract", "wellmanifest.defect-repair/v1")
            t_inputs.setdefault("expect_files_changed", True)
            t_inputs.setdefault("patch_mode", True)
            t_inputs.setdefault("worktree", True)
            t_inputs.setdefault("risk_class", "R1")
            t_inputs.setdefault("llm_timeout_seconds", 300)
            t_inputs.setdefault("max_patch_attempts", 3)

            t_source = dict(t.get("source") or {})
            t_source.setdefault("tool", "todo2code")
            t_source.setdefault("origin", "monag.autodiagnosis")

            t_executor = dict(t.get("executor") or {})
            t_executor.setdefault("kind", "llm")
            t_executor.setdefault("mode", "automatic")

            task_entry = {
                "id": ticket_id,
                "title": t["title"],
                "description": t["description"],
                "priority": t.get("priority", "normal"),
                "status": "todo",
                "tier": t.get("tier", TIER_BACKLOG),
                "labels": t.get("labels", []),
                "source": t_source,
                "inputs": t_inputs,
                "executor": t_executor,
                "estimation": t.get("estimation"),
                "estimated_duration_seconds": t.get("estimated_duration_seconds"),
                "estimated_peak_rss_mb": t.get("estimated_peak_rss_mb"),
                "estimation_confidence": t.get("estimation_confidence"),
                "satisfied_when": t.get("satisfied_when"),
                "created_at": t.get("created_at"),
            }
            existing_data["tasks"].append(task_entry)
            added_for_repo.append(ticket_id)
            results["dispatched"] += 1

        # Sort tasks according to Wellmanifest Priority tiers before saving sprint file
        existing_data["tasks"].sort(key=priority_sort_key)

        # Write back sprint yaml
        try:
            sprint_file.write_text(yaml.safe_dump(existing_data, sort_keys=False, allow_unicode=True))
            results["repositories_updated"].append(str(target_path))
            results["tickets_by_repo"][target] = added_for_repo
        except Exception as err:
            results["errors"].append(f"Failed to write {sprint_file}: {err}")

    if sync_github:
        results["github_sync"] = []
        for updated_repo in results["repositories_updated"]:
            sync_res = sync_planfile_github(Path(updated_repo))
            results["github_sync"].append(sync_res)

    return results

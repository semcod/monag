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
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import yaml

SCHEMA = "monag.autodiagnosis/v1"

DEFAULT_AUTONOMY_UNITS: Tuple[str, ...] = (
    "subactor-coding-agent.service",
    "subactor-pr-controller.service",
    "subactor-repair-agent.service",
    "subactor-autonom-user.service",
    "heyasa.service",
)

AUTONOMY_UNIT_TARGETS: Dict[str, str] = {
    "subactor-coding-agent.service": "subactor/coding-agent",
    "subactor-pr-controller.service": "subactor/pr-controller",
    "subactor-repair-agent.service": "subactor/repair-agent",
    "subactor-autonom-user.service": "subactor/autonom",
    "heyasa.service": "heyasa/heyasa",
}

DEFAULT_HEYASA_STATUS_URLS: Tuple[str, ...] = (
    "http://127.0.0.1:8765/v1/daemon/status",
    "http://127.0.0.1:7080/v1/daemon/status",
)

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

SEVERITY_ORDER = {
    "CRITICAL": 0,
    "HIGH": 1,
    "ERROR": 2,
    "WARNING": 3,
    "INFO": 4,
}


def priority_sort_key(ticket_or_task: Dict[str, Any]) -> tuple:
    """Sort key matching Operational Weight + Wellmanifest lexicographic tiers and priority order.

    0. Operational stall weight: higher weight first (autonomy stalls > 0, repo hygiene = 0)
    1. Tier: floor (0) < mission (1) < hygiene (2) < backlog (3)
    2. Priority: critical (0) < high (1) < medium/normal (2) < low (3) < lowest (4)
    3. Created at: older first (FIFO)
    """
    try:
        weight = int(ticket_or_task.get("weight", 0) or 0)
    except (TypeError, ValueError):
        weight = 0
    tier = str(ticket_or_task.get("tier") or TIER_BACKLOG).lower()
    priority = str(ticket_or_task.get("priority") or "normal").lower()
    created_at = str(ticket_or_task.get("created_at") or "")

    tier_weight = TIER_ORDER.get(tier, 3)
    priority_weight = PRIORITY_ORDER.get(priority, 2)
    return (-weight, tier_weight, priority_weight, created_at)


def anomaly_sort_key(anomaly: Dict[str, Any]) -> tuple:
    """Sort raw anomalies so operational autonomy stalls always precede repo hygiene findings."""
    try:
        weight = int(anomaly.get("weight", 0) or 0)
    except (TypeError, ValueError):
        weight = 0
    tier = str(anomaly.get("tier") or TIER_BACKLOG).lower()
    severity = str(anomaly.get("severity") or "INFO").upper()
    return (
        -weight,
        TIER_ORDER.get(tier, 3),
        SEVERITY_ORDER.get(severity, 5),
        str(anomaly.get("target") or ""),
        str(anomaly.get("code") or ""),
    )


def sort_tickets_by_priority(tickets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deterministically sort tickets according to Wellmanifest priority tiers."""
    return sorted(tickets, key=priority_sort_key)



def _subllm_timeout_seconds() -> float:
    try:
        return max(0.05, float(os.environ.get("MONAG_SUBLLM_TIMEOUT_SECONDS", "6.0")))
    except ValueError:
        return 6.0


def _invoke_runner_bounded(runner: Callable[[str], str], prompt: str, timeout_seconds: float) -> Optional[str]:
    """Run one SubLLM synthesis call behind a non-blocking daemon thread wall-clock deadline."""
    outcome: "queue.Queue[Tuple[bool, Any]]" = queue.Queue(maxsize=1)

    def _target() -> None:
        try:
            outcome.put((True, runner(prompt)))
        except Exception as exc:
            outcome.put((False, exc))

    worker = threading.Thread(target=_target, name="monag-subllm-synth", daemon=True)
    worker.start()
    try:
        ok, value = outcome.get(timeout=max(0.05, timeout_seconds))
    except queue.Empty:
        return None
    if not ok or not isinstance(value, str) or not value.strip():
        return None
    return value


def _find_subllm_runner() -> Optional[Callable[[str], str]]:
    """Locate SubLLM client runner or return None if unavailable."""
    if os.environ.get("MONAG_DISABLE_SUBLLM") == "1":
        return None
    call_timeout = _subllm_timeout_seconds()
    # 1. Direct Python import
    try:
        from subllm import complete  # noqa: F401
        from subllm.client_types import CompletionResponse

        def _subllm_import_runner(prompt: str) -> str:
            messages = [{"role": "user", "content": prompt}]
            try:
                resp = complete("koru-agent", "nl-to-koru-dsl", messages, timeout_seconds=call_timeout)
                if isinstance(resp, CompletionResponse):
                    return resp.content
                return str(resp)
            except Exception:
                try:
                    resp = complete("todo2code", "semantic", messages, timeout_seconds=call_timeout)
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
                        resp = complete("koru-agent", "nl-to-koru-dsl", messages, timeout_seconds=call_timeout)
                        if isinstance(resp, CompletionResponse):
                            return resp.content
                        return str(resp)
                    except Exception:
                        try:
                            resp = complete("todo2code", "semantic", messages, timeout_seconds=call_timeout)
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
                                  input=prompt, capture_output=True, text=True, timeout=max(1, int(call_timeout)))
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
            raise RuntimeError(f"subllm-complete CLI failed: {proc.stderr.strip()}")

        return _subllm_cli_runner

    return None


def inspect_repository_anomalies(repo_path: Path,
                                  willmux_config_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
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
            ["git", "-C", str(repo_path), "grep", "-I", "-l", "-E", "^(<{7} |={7}$|>{7} )"],
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

    # 8. Runtime system service logs (willman, willmux, and workspace services)
    # 8a. Willman daemon logs and task execution outcomes (.willman/logs)
    willman_logs = repo_path / ".willman" / "logs"
    if willman_logs.is_dir():
        daemon_logs = sorted(willman_logs.glob("daemon-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        for dlog in daemon_logs[:3]:
            try:
                size = dlog.stat().st_size
                with dlog.open("rb") as f:
                    if size > 65536:
                        f.seek(size - 65536)
                    chunk = f.read().decode("utf-8", errors="replace")
                matches = re.findall(
                    r"(?:Traceback \(most recent call last\):[\s\S]{10,600}?(?:\w+Error|\w+Exception):[^\n]+|(?:CRITICAL|FATAL|BrokenPipeError):[^\n]+)",
                    chunk,
                )
                if matches:
                    last_err = matches[-1].strip()
                    first_err_line = last_err.splitlines()[-1] if "\n" in last_err else last_err
                    anomalies.append({
                        "code": "SYSTEM_LOG_ERROR",
                        "tier": TIER_FLOOR,
                        "severity": "ERROR",
                        "target": repo_name,
                        "path": str(repo_path),
                        "summary": f"Runtime system error detected in willman daemon log: {first_err_line[:120]}",
                        "evidence": f"Error excerpt from {dlog.name}:\n{last_err[:400]}",
                        "details": {
                            "service": "willman",
                            "file": str(dlog),
                            "error": first_err_line,
                        },
                    })
                    break
            except Exception:
                pass

        if not any(a["code"] == "SYSTEM_LOG_ERROR" and a["target"] == repo_name for a in anomalies):
            task_ndjsons = sorted(willman_logs.glob("*.ndjson"), key=lambda p: p.stat().st_mtime, reverse=True)
            for tj in task_ndjsons[:10]:
                try:
                    with tj.open(encoding="utf-8", errors="replace") as f:
                        for line in f:
                            if '"status": "failed"' in line or '"error"' in line:
                                try:
                                    entry = json.loads(line)
                                    if entry.get("status") == "failed" or entry.get("error"):
                                        err_msg = entry.get("error") or entry.get("result", {}).get("error") or "Task execution failed"
                                        anomalies.append({
                                            "code": "SYSTEM_LOG_ERROR",
                                            "tier": TIER_FLOOR,
                                            "severity": "ERROR",
                                            "target": repo_name,
                                            "path": str(repo_path),
                                            "summary": f"Failed task execution recorded in willman logs: {str(err_msg)[:120]}",
                                            "evidence": f"Failed task entry in {tj.name}: {line.strip()[:400]}",
                                            "details": {
                                                "service": "willman",
                                                "file": str(tj),
                                                "entry": entry,
                                            },
                                        })
                                        break
                                except Exception:
                                    pass
                        if any(a["code"] == "SYSTEM_LOG_ERROR" and a["target"] == repo_name for a in anomalies):
                            break
                except Exception:
                    pass

    # 8b. Willmux agent and event logs
    if "willmux" in repo_name or (repo_path / "agent" / "willmux_agent").is_dir():
        candidate_dirs = [
            repo_path / ".config" / "willmux",
            Path.home() / ".config" / "willmux",
        ]
        if willmux_config_dir:
            candidate_dirs.insert(0, Path(willmux_config_dir))

        for cdir in candidate_dirs:
            if not cdir.is_dir():
                continue

            agent_log = cdir / "agent-log.jsonl"
            if agent_log.is_file():
                try:
                    with agent_log.open(encoding="utf-8", errors="replace") as f:
                        lines = f.readlines()
                    for line in reversed(lines[-50:]):
                        if '"level": "error"' in line or '"level": "fatal"' in line:
                            try:
                                entry = json.loads(line)
                                if entry.get("level") in ("error", "fatal"):
                                    anomalies.append({
                                        "code": "SYSTEM_LOG_ERROR",
                                        "tier": TIER_FLOOR,
                                        "severity": "ERROR",
                                        "target": repo_name,
                                        "path": str(repo_path),
                                        "summary": f"willmux agent logged error: {entry.get('msg', '')[:120]}",
                                        "evidence": f"Found error entry in {agent_log.name}: {line.strip()[:400]}",
                                        "details": {
                                            "service": "willmux",
                                            "file": str(agent_log),
                                            "entry": entry,
                                        },
                                    })
                                    break
                            except Exception:
                                pass
                except Exception:
                    pass

            events_file = cdir / "events.jsonl"
            if events_file.is_file() and not any(a["code"] == "SYSTEM_LOG_ERROR" and a["target"] == repo_name for a in anomalies):
                try:
                    with events_file.open(encoding="utf-8", errors="replace") as f:
                        lines = f.readlines()
                    for line in reversed(lines[-100:]):
                        if '"status": "failed"' in line:
                            try:
                                entry = json.loads(line)
                                data = entry.get("data") or {}
                                project_ref = str(data.get("project") or "").strip()
                                if project_ref and Path(project_ref).name != repo_name and project_ref != str(repo_path):
                                    continue
                                if data.get("status") == "failed" or any(s.get("status") == "failed" for s in data.get("steps", [])):
                                    failed_steps = [s for s in data.get("steps", []) if s.get("status") == "failed"]
                                    result_obj = data.get("result") if isinstance(data.get("result"), dict) else {}
                                    output_obj = result_obj.get("output") if isinstance(result_obj.get("output"), dict) else {}
                                    reason = (
                                        (failed_steps[0].get("reason") or failed_steps[0].get("error"))
                                        if failed_steps
                                        else (
                                            data.get("reason")
                                            or data.get("error")
                                            or result_obj.get("error")
                                            or output_obj.get("error")
                                            or data.get("title")
                                            or "unknown"
                                        )
                                    )
                                    reason = str(reason)
                                    anomalies.append({
                                        "code": "SYSTEM_LOG_ERROR",
                                        "tier": TIER_FLOOR,
                                        "severity": "ERROR",
                                        "target": repo_name,
                                        "path": str(repo_path),
                                        "summary": f"willmux event store recorded failed plan step: {reason[:120]}",
                                        "evidence": f"Failed step in {events_file.name} (seq {entry.get('seq')}): {line.strip()[:400]}",
                                        "details": {
                                            "service": "willmux",
                                            "file": str(events_file),
                                            "seq": entry.get("seq"),
                                            "reason": reason,
                                        },
                                    })
                                    break
                            except Exception:
                                pass
                except Exception:
                    pass
            break

    return anomalies


def _is_loopback_status_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    return (parsed.hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}


def _probe_systemd_user_units(
    root: Path,
    units: Sequence[str] = DEFAULT_AUTONOMY_UNITS,
    timeout: float = 2.5,
    runner: Optional[Callable[..., Any]] = None,
) -> List[Dict[str, Any]]:
    """Read-only probe of known systemd --user autonomy units with short timeout."""
    if not units:
        return []
    exec_run = runner or subprocess.run
    try:
        proc = exec_run(
            [
                "systemctl",
                "--user",
                "show",
                *units,
                "--property=Id,LoadState,ActiveState,SubState,Result,ExecMainStatus",
            ],
            capture_output=True,
            text=True,
            timeout=max(0.2, float(timeout)),
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return []

    raw_out = getattr(proc, "stdout", "") or ""
    if not isinstance(raw_out, str) or not raw_out.strip():
        return []

    anomalies: List[Dict[str, Any]] = []
    blocks = [blk.strip() for blk in raw_out.split("\n\n") if blk.strip()]
    for block in blocks:
        props: Dict[str, str] = {}
        for line in block.splitlines():
            if "=" in line:
                key, val = line.split("=", 1)
                props[key.strip()] = val.strip()
        unit_id = props.get("Id", "")
        if not unit_id:
            continue
        load_state = props.get("LoadState", "").lower()
        if load_state in ("", "not-found", "masked"):
            continue
        active_state = props.get("ActiveState", "").lower()
        sub_state = props.get("SubState", "").lower()
        result_state = props.get("Result", "").lower()
        exec_status = props.get("ExecMainStatus", "")

        target = AUTONOMY_UNIT_TARGETS.get(unit_id, "subactor/autonom")
        target_path = root / target if (root / target).is_dir() else root

        is_failed = (
            active_state == "failed"
            or sub_state == "failed"
            or (result_state not in ("", "success") and active_state != "active")
        )
        if is_failed:
            anomalies.append({
                "code": "AUTONOMY_UNIT_FAILED",
                "tier": TIER_FLOOR,
                "severity": "CRITICAL",
                "weight": 1000,
                "autonomy_probe": True,
                "target": target,
                "path": str(target_path),
                "summary": (
                    f"Autonomy systemd --user unit '{unit_id}' failed "
                    f"(ActiveState={active_state or 'unknown'}, Result={result_state or 'unknown'}, "
                    f"ExecMainStatus={exec_status or 'n/a'})."
                ),
                "evidence": (
                    f"systemctl --user show {unit_id}: LoadState={load_state}, "
                    f"ActiveState={active_state}, SubState={sub_state}, "
                    f"Result={result_state}, ExecMainStatus={exec_status}."
                ),
                "details": {
                    "unit": unit_id,
                    "load_state": load_state,
                    "active_state": active_state,
                    "sub_state": sub_state,
                    "result": result_state,
                    "exec_main_status": exec_status,
                },
            })
        elif unit_id == "heyasa.service" and active_state in ("inactive", "deactivating"):
            anomalies.append({
                "code": "AUTONOMY_DAEMON_INACTIVE",
                "tier": TIER_FLOOR,
                "severity": "HIGH",
                "weight": 920,
                "autonomy_probe": True,
                "target": target,
                "path": str(target_path),
                "summary": f"Autonomy orchestrator unit '{unit_id}' is loaded but {active_state}.",
                "evidence": (
                    f"systemctl --user show {unit_id}: LoadState={load_state}, "
                    f"ActiveState={active_state}, SubState={sub_state}."
                ),
                "details": {
                    "unit": unit_id,
                    "load_state": load_state,
                    "active_state": active_state,
                    "sub_state": sub_state,
                },
            })

    return anomalies


def _extract_heyasa_flowguard(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Extract flowguard metrics from nested or flat /v1/daemon/status payloads."""
    candidates = [
        ((payload.get("last_result") or {}).get("willman") or {}).get("flowguard"),
        (payload.get("willman") or {}).get("flowguard"),
        payload.get("flowguard"),
        payload,
    ]
    merged: Dict[str, Any] = {}
    for obj in candidates:
        if isinstance(obj, dict):
            for key in (
                "eligible_projects",
                "admitted_slots",
                "blocked_candidates",
                "admitted_candidates",
                "project_exclusions",
                "blocked_reasons",
            ):
                if key not in merged and key in obj and obj[key] is not None:
                    merged[key] = obj[key]
    return merged


def _probe_heyasa_daemon_status(
    root: Path,
    status_url: Optional[str] = None,
    status_payload: Optional[Dict[str, Any]] = None,
    timeout: float = 1.5,
    opener: Optional[Callable[..., Any]] = None,
) -> List[Dict[str, Any]]:
    """Read-only loopback probe of local Heyasa /v1/daemon/status for dispatch or velocity stalls."""
    payload: Optional[Dict[str, Any]] = status_payload
    observed_url = status_url or os.environ.get("MONAG_HEYASA_STATUS_URL", "").strip()

    if payload is None:
        urls: Sequence[str] = (observed_url,) if observed_url else DEFAULT_HEYASA_STATUS_URLS
        open_fn = opener or urllib.request.urlopen
        for candidate_url in urls:
            if not candidate_url or not _is_loopback_status_url(candidate_url):
                continue
            try:
                req = urllib.request.Request(candidate_url, headers={"Accept": "application/json"}, method="GET")
                with open_fn(req, timeout=max(0.2, float(timeout))) as resp:
                    raw = resp.read(256 * 1024)
                decoded = json.loads(raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw))
                if isinstance(decoded, dict):
                    payload = decoded
                    observed_url = candidate_url
                    break
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                continue

    if not isinstance(payload, dict):
        return []

    target = "heyasa/heyasa"
    target_path = root / target if (root / target).is_dir() else root
    flow = _extract_heyasa_flowguard(payload)
    anomalies: List[Dict[str, Any]] = []

    eligible = flow.get("eligible_projects")
    admitted = flow.get("admitted_slots")
    blocked = flow.get("blocked_candidates", 0)
    blocked_reasons = flow.get("blocked_reasons") if isinstance(flow.get("blocked_reasons"), dict) else {}
    exclusions = flow.get("project_exclusions") if isinstance(flow.get("project_exclusions"), dict) else {}

    try:
        eligible_int = int(eligible) if eligible is not None else None
    except (TypeError, ValueError):
        eligible_int = None
    try:
        admitted_int = int(admitted) if admitted is not None else None
    except (TypeError, ValueError):
        admitted_int = None
    try:
        blocked_int = int(blocked or 0)
    except (TypeError, ValueError):
        blocked_int = 0

    if eligible_int is not None and eligible_int == 0:
        anomalies.append({
            "code": "AUTONOMY_ELIGIBLE_PROJECTS_ZERO",
            "tier": TIER_FLOOR,
            "severity": "CRITICAL",
            "weight": 980,
            "autonomy_probe": True,
            "target": target,
            "path": str(target_path),
            "summary": (
                f"Autonomy stall: Heyasa daemon reports 0 eligible projects "
                f"(admitted_slots={admitted_int if admitted_int is not None else 'n/a'}, "
                f"blocked_candidates={blocked_int})."
            ),
            "evidence": (
                f"{observed_url or 'heyasa.daemon-status'}: eligible_projects=0, "
                f"exclusions={len(exclusions)}, blocked_reasons={json.dumps(blocked_reasons, sort_keys=True)[:240]}."
            ),
            "details": {
                "url": observed_url or "inline",
                "eligible_projects": eligible_int,
                "admitted_slots": admitted_int,
                "blocked_candidates": blocked_int,
                "blocked_reasons": blocked_reasons,
            },
        })

    if admitted_int is not None and admitted_int == 0 and blocked_int > 0:
        anomalies.append({
            "code": "AUTONOMY_ADMISSION_STALL",
            "tier": TIER_FLOOR,
            "severity": "CRITICAL",
            "weight": 960,
            "autonomy_probe": True,
            "target": target,
            "path": str(target_path),
            "summary": (
                f"Autonomy admission stall: 0 admitted slots while {blocked_int} candidate tasks are blocked."
            ),
            "evidence": (
                f"{observed_url or 'heyasa.daemon-status'}: admitted_slots=0, "
                f"blocked_candidates={blocked_int}, reasons={json.dumps(blocked_reasons, sort_keys=True)[:240]}."
            ),
            "details": {
                "url": observed_url or "inline",
                "admitted_slots": admitted_int,
                "blocked_candidates": blocked_int,
                "blocked_reasons": blocked_reasons,
            },
        })

    velocity = payload.get("velocity_status")
    vel_stalled = False
    vel_summary = ""
    if isinstance(velocity, str):
        if velocity.strip().lower() in {"stall", "stalled", "degraded", "zero", "blocked", "critical"}:
            vel_stalled = True
            vel_summary = f"velocity_status={velocity.strip()}"
    elif isinstance(velocity, dict):
        completed_cnt = velocity.get("completed_count")
        open_cands = velocity.get("open_candidates_count") or 0
        target_cap = velocity.get("target_capacity") or 0
        status_label = str(velocity.get("status") or "").strip().lower()
        if (
            bool(velocity.get("is_degraded"))
            or status_label in {"stall", "stalled", "degraded", "critical"}
            or (completed_cnt == 0 and int(open_cands) > 0 and int(target_cap) > 0)
        ):
            vel_stalled = True
            vel_summary = str(
                velocity.get("summary")
                or f"completed={completed_cnt}/{target_cap}, open_candidates={open_cands}"
            )

    if vel_stalled:
        anomalies.append({
            "code": "AUTONOMY_VELOCITY_STALL",
            "tier": TIER_FLOOR,
            "severity": "HIGH",
            "weight": 930,
            "autonomy_probe": True,
            "target": target,
            "path": str(target_path),
            "summary": f"Autonomy velocity stall detected: {vel_summary[:180]}",
            "evidence": f"{observed_url or 'heyasa.daemon-status'} velocity_status: {vel_summary[:300]}",
            "details": {
                "url": observed_url or "inline",
                "velocity_status": velocity,
            },
        })

    return anomalies


def _probe_host_load_saturation(
    root: Path,
    load_fn: Optional[Callable[[], Tuple[float, float, float]]] = None,
    cpu_count_fn: Optional[Callable[[], Optional[int]]] = None,
    warning_ratio: float = 1.5,
    critical_ratio: float = 2.0,
) -> List[Dict[str, Any]]:
    """Check 1-minute host load average against logical CPU count."""
    get_load = load_fn or getattr(os, "getloadavg", None)
    get_cpus = cpu_count_fn or os.cpu_count
    if get_load is None:
        return []
    try:
        load_1m, load_5m, load_15m = get_load()
        cpus = max(1, int(get_cpus() or 1))
    except (OSError, TypeError, ValueError):
        return []

    ratio = float(load_1m) / float(cpus)
    if ratio <= warning_ratio:
        return []

    is_critical = ratio > critical_ratio
    return [
        {
            "code": "HOST_LOAD_SATURATION",
            "tier": TIER_FLOOR if is_critical else TIER_MISSION,
            "severity": "CRITICAL" if is_critical else "WARNING",
            "weight": 900 if is_critical else 850,
            "autonomy_probe": True,
            "target": "host/system",
            "path": str(root),
            "summary": (
                f"Host CPU load saturation ({'critical' if is_critical else 'warning'}): "
                f"1m load {load_1m:.2f} across {cpus} CPUs ({ratio:.2f}x capacity)."
            ),
            "evidence": (
                f"os.getloadavg()=({load_1m:.2f}, {load_5m:.2f}, {load_15m:.2f}), "
                f"os.cpu_count()={cpus}, ratio={ratio:.2f}x "
                f"(thresholds: warning>{warning_ratio:.1f}x, critical>{critical_ratio:.1f}x)."
            ),
            "details": {
                "load_1m": round(float(load_1m), 2),
                "load_5m": round(float(load_5m), 2),
                "load_15m": round(float(load_15m), 2),
                "cpu_count": cpus,
                "load_per_cpu": round(ratio, 3),
            },
        }
    ]


def probe_autonomy_health(
    root: Path,
    *,
    units: Sequence[str] = DEFAULT_AUTONOMY_UNITS,
    systemctl_timeout: float = 2.5,
    systemctl_runner: Optional[Callable[..., Any]] = None,
    heyasa_status_url: Optional[str] = None,
    heyasa_payload: Optional[Dict[str, Any]] = None,
    heyasa_timeout: float = 1.5,
    http_opener: Optional[Callable[..., Any]] = None,
    load_fn: Optional[Callable[[], Tuple[float, float, float]]] = None,
    cpu_count_fn: Optional[Callable[[], Optional[int]]] = None,
) -> List[Dict[str, Any]]:
    """Run deterministic, read-only host & daemon autonomy stall probes."""
    if os.environ.get("MONAG_DISABLE_AUTONOMY_PROBES") == "1":
        return []
    findings: List[Dict[str, Any]] = []
    findings.extend(
        _probe_systemd_user_units(
            root=root,
            units=units,
            timeout=systemctl_timeout,
            runner=systemctl_runner,
        )
    )
    findings.extend(
        _probe_heyasa_daemon_status(
            root=root,
            status_url=heyasa_status_url,
            status_payload=heyasa_payload,
            timeout=heyasa_timeout,
            opener=http_opener,
        )
    )
    findings.extend(
        _probe_host_load_saturation(
            root=root,
            load_fn=load_fn,
            cpu_count_fn=cpu_count_fn,
        )
    )
    findings.sort(key=anomaly_sort_key)
    return findings


def diagnose_fleet(root: Path, depth: int = 2, db: Optional[Any] = None,
                   use_cache: bool = True, state_dir: Optional[Path] = None,
                   include_autonomy: bool = True) -> Dict[str, Any]:
    """Scan workspace fleet for operational autonomy stalls, technical defects, and ticket readiness."""
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

    autonomy_anomalies: List[Dict[str, Any]] = probe_autonomy_health(root) if include_autonomy else []
    repo_anomalies: List[Dict[str, Any]] = []
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
                    repo_anomalies.extend(cached_anom)
                    cached_repos_count += 1
                    continue
            except Exception:
                pass

        repo_anomalies.extend(inspect_repository_anomalies(r))

    all_anomalies: List[Dict[str, Any]] = sorted(
        [*autonomy_anomalies, *repo_anomalies],
        key=anomaly_sort_key,
    )

    return {
        "schema": SCHEMA,
        "root": str(root),
        "timestamp": started.isoformat(),
        "repositories_checked": len(repos),
        "repositories_cached": cached_repos_count,
        "autonomy_anomalies_count": len(autonomy_anomalies),
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
        "SYSTEM_LOG_ERROR": "Diagnose root cause of runtime system log error, apply code/configuration fix, and verify service stability with tests.",
        "AUTONOMY_UNIT_FAILED": "Inspect failed systemd --user journal logs, repair unit configuration or runtime crash, and verify active service health.",
        "AUTONOMY_DAEMON_INACTIVE": "Inspect heyasa.service user unit status and restart or re-enable autonomous orchestrator daemon.",
        "AUTONOMY_ELIGIBLE_PROJECTS_ZERO": "Inspect Heyasa flowguard project_exclusions and unblock repository eligibility or lease gates.",
        "AUTONOMY_ADMISSION_STALL": "Inspect Heyasa flowguard blocked_reasons and slot capacity to restore candidate admission.",
        "AUTONOMY_VELOCITY_STALL": "Inspect stalled Heyasa execution pipeline, executor health, and open candidate backlog.",
        "HOST_LOAD_SATURATION": "Inspect top CPU-consuming processes, runaway test suites, or duplicate agent loops causing host saturation.",
    }
    action = action_map.get(code, f"Resolve {code} in {target}.")
    ac1 = f"AC-01: {fallback_anomaly.get('summary', 'Anomaly is remediated')}."
    ac2 = "AC-02: Verification checks and automated test suite pass with exit code 0."
    verify_cmd = "git status --porcelain && npm test || pytest -q"
    if code in {"AUTONOMY_UNIT_FAILED", "AUTONOMY_DAEMON_INACTIVE"}:
        unit_name = (fallback_anomaly.get("details") or {}).get("unit", "heyasa.service")
        verify_cmd = f"systemctl --user is-active {unit_name}"
    elif code in {"AUTONOMY_ELIGIBLE_PROJECTS_ZERO", "AUTONOMY_ADMISSION_STALL", "AUTONOMY_VELOCITY_STALL"}:
        verify_cmd = "curl -fsS http://127.0.0.1:8765/v1/daemon/status || curl -fsS http://127.0.0.1:7080/v1/daemon/status"
    elif code == "HOST_LOAD_SATURATION":
        verify_cmd = "python3 -c 'import os; assert os.getloadavg()[0] <= 1.5 * (os.cpu_count() or 1)'"

    return {
        "title": f"[{target}] fix({code.lower().replace('_', '-')}): {fallback_anomaly.get('summary')}",
        "target_repo": target,
        "tier": tier,
        "priority": TIER_PRIORITY_MAP.get(tier, "normal"),
        "action": action,
        "acceptance_criteria": [ac1, ac2],
        "verification_command": verify_cmd,
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

    call_timeout = _subllm_timeout_seconds()
    try:
        budget_seconds = max(0.0, float(os.environ.get("MONAG_AUTODIAG_LLM_BUDGET_SECONDS", "18.0")))
    except ValueError:
        budget_seconds = 18.0
    try:
        max_failures = max(1, int(os.environ.get("MONAG_SUBLLM_MAX_FAILURES", "2")))
    except ValueError:
        max_failures = 2

    started_mono = time.monotonic()
    consecutive_failures = 0
    circuit_open = False

    tickets: List[Dict[str, Any]] = []
    for anom in anom_list:
        subllm_result: Optional[str] = None
        remaining_budget = budget_seconds - (time.monotonic() - started_mono)
        if runner and not circuit_open and remaining_budget > 0.0:
            prompt = _format_subllm_prompt(anom)
            subllm_result = _invoke_runner_bounded(runner, prompt, min(call_timeout, remaining_budget))
            if subllm_result:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                if consecutive_failures >= max_failures:
                    circuit_open = True

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
            "weight": int(anom.get("weight", 0) or 0),
            "autonomy_probe": bool(anom.get("autonomy_probe", False)),
            "code": code_str,
            "severity": str(anom.get("severity") or "WARNING"),
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
        "skipped_external_targets": [],
        "errors": [],
    }

    # Group tickets by target_repo
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for t in tickets:
        target = t.get("target_repo", "")
        grouped.setdefault(target, []).append(t)

    from functools import lru_cache

    @lru_cache(maxsize=64)
    def _load_sprint_yaml_cached(path_str: str, mtime_ns: int) -> Any:
        del mtime_ns
        return yaml.safe_load(Path(path_str).read_text(encoding="utf-8"))

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
            if all(bool(t.get("autonomy_probe")) for t in repo_tickets):
                results["skipped_external_targets"].append(target)
                continue
            results["errors"].append(f"Target repository directory not found for: {target}")
            continue

        planfile_sprints_dir = target_path / ".planfile" / "sprints"
        planfile_sprints_dir.mkdir(parents=True, exist_ok=True)
        sprint_file = planfile_sprints_dir / f"{sprint}.yaml"

        existing_data: Dict[str, Any] = {}
        if sprint_file.is_file():
            try:
                loaded = _load_sprint_yaml_cached(str(sprint_file), sprint_file.stat().st_mtime_ns)
                if isinstance(loaded, dict):
                    existing_data = dict(loaded)
            except Exception:
                pass

        if "tasks" not in existing_data or not isinstance(existing_data["tasks"], list):
            existing_data["tasks"] = []
        if "schema" not in existing_data:
            existing_data["schema"] = "planfile.sprint/v1"

        # Koru native format expects sprint to be a dict: {id: ..., status: ..., tickets: {...}}
        if not isinstance(existing_data.get("sprint"), dict):
            sprint_id = existing_data.get("sprint") if isinstance(existing_data.get("sprint"), str) else sprint
            existing_data["sprint"] = {
                "id": sprint_id or sprint,
                "status": "active",
                "tickets": {},
            }
        elif "tickets" not in existing_data["sprint"] or not isinstance(existing_data["sprint"]["tickets"], dict):
            existing_data["sprint"]["tickets"] = {}

        existing_titles = {tsk.get("title") for tsk in existing_data["tasks"] if isinstance(tsk, dict)}
        for t_info in existing_data["sprint"]["tickets"].values():
            if isinstance(t_info, dict):
                title = t_info.get("title") or t_info.get("name")
                if title:
                    existing_titles.add(title)
        if isinstance(existing_data.get("tickets"), dict):
            for t_info in existing_data["tickets"].values():
                if isinstance(t_info, dict):
                    title = t_info.get("title") or t_info.get("name")
                    if title:
                        existing_titles.add(title)

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
            t_inputs.setdefault("provider", "opencode")
            t_inputs.setdefault("runner", "opencode")
            t_inputs.setdefault("risk_class", "R1")
            t_inputs.setdefault("llm_timeout_seconds", 300)
            t_inputs.setdefault("max_patch_attempts", 3)

            t_source = dict(t.get("source") or {})
            t_source.setdefault("tool", "todo2code")
            t_source.setdefault("origin", "monag.autodiagnosis")

            t_executor = dict(t.get("executor") or {})
            t_executor.setdefault("kind", "llm")
            t_executor.setdefault("mode", "automatic")
            t_executor.setdefault("runner", "opencode")

            task_entry = {
                "id": ticket_id,
                "title": t["title"],
                "description": t["description"],
                "priority": t.get("priority", "normal"),
                "status": "ready",
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

            # Koru native sprint tickets mapping
            koru_ticket = {
                "id": ticket_id,
                "title": t["title"],
                "name": t["title"],
                "description": t["description"],
                "priority": t.get("priority", "normal"),
                "status": "ready",
                "execution": {
                    "state": "ready",
                    "queue": os.environ.get("MONAG_PLANFILE_QUEUE", "default") or "default",
                    "attempt": 0,
                    "max_attempts": 3,
                },
                "executor": t_executor,
                "inputs": {
                    "prompt": t["description"],
                    **t_inputs,
                },
                "labels": list(t.get("labels", [])),
                "tier": t.get("tier", TIER_BACKLOG),
                "source": t_source,
                "estimation": t.get("estimation"),
                "satisfied_when": t.get("satisfied_when"),
                "created_at": t.get("created_at"),
            }
            existing_data["sprint"]["tickets"][ticket_id] = koru_ticket
            if isinstance(existing_data.get("tickets"), dict):
                existing_data["tickets"][ticket_id] = koru_ticket

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

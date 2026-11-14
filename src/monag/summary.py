"""Daily 24h operational delta (`day`) and portfolio/queue snapshot (`summary`).

Aggregates completed work, active queues, local agent task runs, active leases,
GitHub PR metrics, and explicit source/scope/filter labels across a workspace.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Dict, List, Optional

SCHEMA = "monag.summary/v1"


from functools import lru_cache


@lru_cache(maxsize=64)
def _load_yaml_cached(path_str: str, mtime_ns: int) -> Any:
    del mtime_ns
    import yaml
    return yaml.safe_load(Path(path_str).read_text(encoding="utf-8"))


def gather_planfile_daily(root: Path, target_date: Optional[date] = None, depth: int = 2) -> Dict[str, Any]:
    """Scan Planfile sprints for tasks completed on target_date and currently queued tasks."""
    target_date = target_date or date.today()
    today_str = target_date.strftime("%Y-%m-%d")

    done_tickets: List[Dict[str, Any]] = []
    queued_tickets: List[Dict[str, Any]] = []

    sprint_dirs: List[Path] = []
    if (root / ".planfile" / "sprints").is_dir():
        sprint_dirs.append(root / ".planfile" / "sprints")
    if depth >= 1:
        sprint_dirs.extend(root.glob("*/.planfile/sprints"))
    if depth >= 2:
        sprint_dirs.extend(root.glob("*/*/.planfile/sprints"))
    sprint_dirs = sorted(set(sprint_dirs))

    total_est_minutes = 0

    for sprints_dir in sprint_dirs:
        try:
            repo_rel = str(sprints_dir.parent.parent.relative_to(root)) if sprints_dir.parent.parent != root else root.name
        except Exception:
            repo_rel = sprints_dir.parent.parent.name

        # 1. Check history file for today
        hist_fast = sprints_dir / f"history-{today_str}.yaml.fast.json"
        hist_yaml = sprints_dir / f"history-{today_str}.yaml"
        if hist_fast.is_file():
            try:
                data = json.loads(hist_fast.read_text(encoding="utf-8"))
                tickets = data.get("data", {}).get("sprint", {}).get("tickets", {})
                for tid, t in tickets.items():
                    fin_at = (t.get("execution") or {}).get("finished_at") or t.get("updated_at", "")
                    done_tickets.append({
                        "repo": repo_rel,
                        "id": tid,
                        "title": t.get("name") or t.get("description", "")[:80],
                        "status": t.get("status", "done"),
                        "finished_at": fin_at[-14:-5] if len(fin_at) >= 19 else fin_at,
                    })
            except Exception:
                pass
        elif hist_yaml.is_file():
            try:
                data = _load_yaml_cached(str(hist_yaml), hist_yaml.stat().st_mtime_ns)
                if isinstance(data, dict):
                    tasks = data.get("tasks", [])
                    for t in tasks:
                        if isinstance(t, dict):
                            done_tickets.append({
                                "repo": repo_rel,
                                "id": t.get("id", ""),
                                "title": t.get("title") or t.get("description", "")[:80],
                                "status": t.get("status", "done"),
                                "finished_at": t.get("finished_at", ""),
                            })
            except Exception:
                pass

        # 2. Check current sprint file
        curr_fast = sprints_dir / "current.yaml.fast.json"
        curr_yaml = sprints_dir / "current.yaml"
        if curr_fast.is_file():
            try:
                data = json.loads(curr_fast.read_text(encoding="utf-8"))
                tickets = data.get("data", {}).get("sprint", {}).get("tickets", {})
                for tid, t in tickets.items():
                    status = t.get("status", "open")
                    created = (t.get("created_at") or "")[:10]
                    updated = (t.get("updated_at") or "")[:10]
                    title = t.get("name") or t.get("description", "")[:80]

                    if status in ("done", "completed") and (updated == today_str or created == today_str):
                        fin_at = (t.get("execution") or {}).get("finished_at") or t.get("updated_at", "")
                        done_tickets.append({
                            "repo": repo_rel,
                            "id": tid,
                            "title": title,
                            "status": "done",
                            "finished_at": fin_at[-14:-5] if len(fin_at) >= 19 else fin_at,
                        })
                    elif status in ("todo", "open", "in_progress", "planned"):
                        est_sec = t.get("estimated_duration_seconds")
                        est_mins = max(1, int(round(est_sec / 60))) if est_sec else 5
                        total_est_minutes += est_mins
                        queued_tickets.append({
                            "repo": repo_rel,
                            "id": tid,
                            "title": title,
                            "priority": t.get("priority", "normal"),
                            "status": status,
                            "estimated_minutes": est_mins,
                        })
            except Exception:
                pass
        elif curr_yaml.is_file():
            try:
                data = _load_yaml_cached(str(curr_yaml), curr_yaml.stat().st_mtime_ns)
                if isinstance(data, dict):
                    tasks = data.get("tasks", [])
                    for t in tasks:
                        if isinstance(t, dict):
                            status = t.get("status", "open")
                            updated = str(t.get("updated_at") or t.get("created_at") or "")[:10]
                            title = t.get("title") or t.get("description", "")[:80]
                            if status in ("done", "completed") and updated == today_str:
                                done_tickets.append({
                                    "repo": repo_rel,
                                    "id": t.get("id", ""),
                                    "title": title,
                                    "status": "done",
                                    "finished_at": str(t.get("finished_at", "")),
                                })
                            elif status in ("todo", "open", "in_progress", "planned"):
                                est_sec = t.get("estimated_duration_seconds")
                                est_mins = max(1, int(round(est_sec / 60))) if est_sec else 5
                                total_est_minutes += est_mins
                                queued_tickets.append({
                                    "repo": repo_rel,
                                    "id": t.get("id", ""),
                                    "title": title,
                                    "priority": t.get("priority", "normal"),
                                    "status": status,
                                    "estimated_minutes": est_mins,
                                })
            except Exception:
                pass

    return {
        "date": today_str,
        "completed_count": len(done_tickets),
        "queued_count": len(queued_tickets),
        "total_estimated_minutes": total_est_minutes,
        "completed_tickets": done_tickets,
        "queued_tickets": queued_tickets,
    }


def _labeled_count(value: int, source: str, scope: str, filter_expr: str) -> Dict[str, Any]:
    """Attach explicit source, scope, and filter provenance to a reported count."""
    return {
        "value": int(value),
        "source": source,
        "scope": scope,
        "filter": filter_expr,
    }


def _discover_sprint_dirs(root: Path, depth: int = 2) -> List[Path]:
    sprint_dirs: List[Path] = []
    if (root / ".planfile" / "sprints").is_dir():
        sprint_dirs.append(root / ".planfile" / "sprints")
    if depth >= 1:
        sprint_dirs.extend(root.glob("*/.planfile/sprints"))
    if depth >= 2:
        sprint_dirs.extend(root.glob("*/*/.planfile/sprints"))
    return sorted(set(sprint_dirs))


def _scan_planfile_portfolio_and_blockers(
    root: Path,
    target_date: Optional[date] = None,
    hours: int = 24,
    depth: int = 2,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Collect current sprint status breakdown and newly blocked tasks without mutating gather_planfile_daily."""
    target_date = target_date or date.today()
    today_str = target_date.strftime("%Y-%m-%d")
    ref_now = now or datetime.now(timezone.utc)
    cutoff = ref_now - timedelta(hours=max(1, int(hours)))
    sprint_dirs = _discover_sprint_dirs(root, depth=depth)

    open_or_todo = 0
    in_progress = 0
    planned = 0
    blocked_total = 0
    done_in_current = 0
    canceled_or_other = 0
    all_entries = 0
    new_blockers: List[Dict[str, Any]] = []

    def _is_within_window(ts_raw: Any) -> bool:
        if not ts_raw:
            return False
        ts_str = str(ts_raw).strip()
        if ts_str[:10] == today_str:
            return True
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt >= cutoff
        except ValueError:
            return False

    for sprints_dir in sprint_dirs:
        try:
            repo_rel = str(sprints_dir.parent.parent.relative_to(root)) if sprints_dir.parent.parent != root else root.name
        except Exception:
            repo_rel = sprints_dir.parent.parent.name

        curr_fast = sprints_dir / "current.yaml.fast.json"
        curr_yaml = sprints_dir / "current.yaml"
        records: List[tuple[str, Dict[str, Any]]] = []
        if curr_fast.is_file():
            try:
                data = json.loads(curr_fast.read_text(encoding="utf-8"))
                tickets = data.get("data", {}).get("sprint", {}).get("tickets", {})
                if isinstance(tickets, dict):
                    records = [(str(tid), t) for tid, t in tickets.items() if isinstance(t, dict)]
            except Exception:
                records = []
        elif curr_yaml.is_file():
            try:
                data = _load_yaml_cached(str(curr_yaml), curr_yaml.stat().st_mtime_ns)
                if isinstance(data, dict):
                    sprint_tickets = (data.get("sprint") or {}).get("tickets") if isinstance(data.get("sprint"), dict) else None
                    if isinstance(sprint_tickets, dict) and sprint_tickets:
                        records = [(str(tid), t) for tid, t in sprint_tickets.items() if isinstance(t, dict)]
                    elif isinstance(data.get("tasks"), list):
                        records = [(str(t.get("id", "")), t) for t in data["tasks"] if isinstance(t, dict)]
            except Exception:
                records = []

        for tid, t in records:
            all_entries += 1
            status = str(t.get("status", "open")).lower()
            title = t.get("name") or t.get("title") or str(t.get("description", ""))[:80]
            updated_raw = t.get("updated_at") or t.get("created_at") or ""
            if status in ("todo", "open", "ready"):
                open_or_todo += 1
            elif status == "in_progress":
                in_progress += 1
            elif status == "planned":
                planned += 1
            elif status == "blocked":
                blocked_total += 1
                if _is_within_window(updated_raw):
                    new_blockers.append({
                        "repo": repo_rel,
                        "id": tid,
                        "title": title,
                        "updated_at": str(updated_raw),
                        "reason": str(t.get("blocked_reason") or t.get("reason") or "status=blocked"),
                    })
            elif status in ("done", "completed"):
                done_in_current += 1
            else:
                canceled_or_other += 1

    return {
        "repositories_with_planfile": len(sprint_dirs),
        "open_or_todo_count": open_or_todo,
        "in_progress_count": in_progress,
        "planned_count": planned,
        "blocked_total_count": blocked_total,
        "done_in_current_count": done_in_current,
        "canceled_or_other_count": canceled_or_other,
        "all_current_sprint_entries": all_entries,
        "new_blockers_count": len(new_blockers),
        "new_blockers": new_blockers,
    }


def _scan_agent_runs_window(
    root: Path,
    state_dir: Optional[Path] = None,
    hours: int = 24,
    now_epoch: Optional[float] = None,
) -> Dict[str, Any]:
    """Scan local <state_dir>/tasks/*.json records updated within the last `hours` hours."""
    resolved_state = Path(
        state_dir
        or os.environ.get("MONAG_STATE_DIR")
        or (Path.home() / ".local" / "state" / "monag")
    )
    tasks_dir = resolved_state / "tasks"
    ref_epoch = now_epoch if now_epoch is not None else datetime.now(timezone.utc).timestamp()
    cutoff_epoch = ref_epoch - float(max(1, hours)) * 3600.0

    completed = 0
    failed = 0
    running = 0
    samples: List[Dict[str, Any]] = []

    if tasks_dir.is_dir():
        try:
            root_resolved = root.resolve()
        except OSError:
            root_resolved = root

        for tf in sorted(tasks_dir.glob("*.json")):
            try:
                row = json.loads(tf.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(row, dict):
                continue
            updated = row.get("updated")
            if not isinstance(updated, (int, float)) or float(updated) < cutoff_epoch:
                continue
            cwd_str = str(row.get("cwd") or "")
            if cwd_str:
                try:
                    cwd_p = Path(cwd_str).resolve()
                    if cwd_p != root_resolved and root_resolved not in cwd_p.parents:
                        continue
                except OSError:
                    pass
            status = str(row.get("status") or row.get("outcome") or "").lower()
            if status in ("completed", "done", "ok", "success"):
                completed += 1
            elif status in ("failed", "error", "stale"):
                failed += 1
            elif status == "running":
                running += 1
            else:
                continue
            samples.append({
                "id": tf.stem,
                "status": status,
                "task": str(row.get("task") or "")[:100],
                "ticket": row.get("ticket"),
                "cwd": cwd_str,
                "updated": float(updated),
            })

    samples.sort(key=lambda item: item["updated"], reverse=True)
    return {
        "state_tasks_dir": str(tasks_dir),
        "completed_runs_count": completed,
        "failed_runs_count": failed,
        "running_runs_count": running,
        "total_runs_in_window": completed + failed + running,
        "recent_runs": samples[:10],
    }


def _scan_active_leases_snapshot(root: Path, depth: int = 2) -> Dict[str, Any]:
    """Count active vs terminal .subactor/leases/*.json records across workspace repositories."""
    from . import worktrees

    lease_dirs: List[Path] = []
    if (root / ".subactor" / "leases").is_dir():
        lease_dirs.append(root / ".subactor" / "leases")
    if depth >= 1:
        lease_dirs.extend(root.glob("*/.subactor/leases"))
    if depth >= 2:
        lease_dirs.extend(root.glob("*/*/.subactor/leases"))
    lease_dirs = sorted(set(lease_dirs))

    active_count = 0
    terminal_count = 0
    for ldir in lease_dirs:
        for lf in sorted(ldir.glob("*.json")):
            try:
                parsed = json.loads(lf.read_text(encoding="utf-8"))
                data = parsed if isinstance(parsed, dict) else {"schema": "malformed"}
            except (OSError, ValueError):
                data = {"schema": "unreadable"}
            is_act, _ = worktrees.is_lease_active(data)
            if is_act:
                active_count += 1
            else:
                terminal_count += 1

    return {
        "repositories_with_leases": len(lease_dirs),
        "active_leases_count": active_count,
        "terminal_leases_count": terminal_count,
    }


def query_github_pr_metrics(target_date: Optional[date] = None, timeout: int = 15) -> Dict[str, Any]:
    """Fast query of open, newly opened, and merged Pull Requests using gh search prs."""
    target_date = target_date or date.today()
    today_str = target_date.strftime("%Y-%m-%d")

    result: Dict[str, Any] = {
        "open_prs_count": 0,
        "merged_prs_count": 0,
        "opened_prs_count": 0,
        "open_prs": [],
        "merged_prs": [],
        "opened_prs": [],
    }

    gh_bin = shutil.which("gh")
    if not gh_bin:
        return result

    try:
        # 1. Open PRs (current queue snapshot)
        proc_open = subprocess.run(
            [gh_bin, "search", "prs", "--author", "@me", "--state", "open",
             "--json", "number,title,repository,url", "--limit", "50"],
            capture_output=True, text=True, timeout=timeout
        )
        if proc_open.returncode == 0 and proc_open.stdout.strip():
            raw_open = json.loads(proc_open.stdout)
            result["open_prs_count"] = len(raw_open)
            result["open_prs"] = [
                {
                    "repo": p.get("repository", {}).get("nameWithOwner", ""),
                    "number": p.get("number"),
                    "title": p.get("title"),
                    "url": p.get("url"),
                }
                for p in raw_open
            ]
    except Exception:
        pass

    try:
        # 2. Merged PRs in window (>= target_date)
        proc_merged = subprocess.run(
            [gh_bin, "search", "prs", "--author", "@me", "--state", "closed", "--merged",
             "--merged-at", f">={today_str}", "--json", "number,title,repository,url", "--limit", "100"],
            capture_output=True, text=True, timeout=timeout
        )
        if proc_merged.returncode == 0 and proc_merged.stdout.strip():
            raw_merged = json.loads(proc_merged.stdout)
            result["merged_prs_count"] = len(raw_merged)
            result["merged_prs"] = [
                {
                    "repo": p.get("repository", {}).get("nameWithOwner", ""),
                    "number": p.get("number"),
                    "title": p.get("title"),
                    "url": p.get("url"),
                }
                for p in raw_merged
            ]
    except Exception:
        pass

    try:
        # 3. Newly opened PRs in window (>= target_date)
        proc_opened = subprocess.run(
            [gh_bin, "search", "prs", "--author", "@me",
             "--created", f">={today_str}", "--json", "number,title,repository,url,state", "--limit", "100"],
            capture_output=True, text=True, timeout=timeout
        )
        if proc_opened.returncode == 0 and proc_opened.stdout.strip():
            raw_opened = json.loads(proc_opened.stdout)
            result["opened_prs_count"] = len(raw_opened)
            result["opened_prs"] = [
                {
                    "repo": p.get("repository", {}).get("nameWithOwner", ""),
                    "number": p.get("number"),
                    "title": p.get("title"),
                    "state": p.get("state"),
                    "url": p.get("url"),
                }
                for p in raw_opened
            ]
    except Exception:
        pass

    return result


def gather_summary(
    root: Path,
    hours: int = 24,
    github: bool = True,
    target_date: Optional[date] = None,
    depth: int = 2,
    state_dir: Optional[Path] = None,
    mode: str = "summary",
) -> Dict[str, Any]:
    """Compile either current portfolio/queue snapshot (`summary`) or 24h operational delta (`day`)."""
    normalized_mode = "day" if str(mode).lower() == "day" else "summary"
    started = datetime.now(timezone.utc)
    planfile_data = gather_planfile_daily(root, target_date=target_date, depth=depth)
    day_str = planfile_data["date"]
    pf_extended = _scan_planfile_portfolio_and_blockers(
        root,
        target_date=target_date,
        hours=int(hours),
        depth=depth,
        now=started,
    )

    pr_summary: Dict[str, Any] = {
        "open_prs_count": 0,
        "merged_prs_count": 0,
        "opened_prs_count": 0,
        "open_prs": [],
        "merged_prs": [],
        "opened_prs": [],
    }
    if github:
        queried_prs = query_github_pr_metrics(target_date=target_date)
        pr_summary.update(queried_prs)
        pr_summary.setdefault("opened_prs_count", len(pr_summary.get("opened_prs", [])))
        pr_summary.setdefault("opened_prs", [])

    scope_str = f"workspace:{root} (depth<={depth})"
    gh_scope = "github:author=@me" if github else "github:disabled(--no-github)"

    if normalized_mode == "day":
        agent_runs = _scan_agent_runs_window(root, state_dir=state_dir, hours=int(hours))
        counts_labeled = {
            "planfile_completed_24h": _labeled_count(
                planfile_data["completed_count"],
                source=".planfile/sprints/{history-YYYY-MM-DD,current}.yaml(.fast.json)",
                scope=scope_str,
                filter_expr=f"history-{day_str} U (current.status in {{done,completed}} & date=={day_str})",
            ),
            "planfile_new_blockers_24h": _labeled_count(
                pf_extended["new_blockers_count"],
                source=".planfile/sprints/current.yaml(.fast.json)",
                scope=scope_str,
                filter_expr=f"status==blocked & updated_within_last_{int(hours)}h",
            ),
            "agent_runs_completed_24h": _labeled_count(
                agent_runs["completed_runs_count"],
                source=f"{agent_runs['state_tasks_dir']}/*.json",
                scope=scope_str,
                filter_expr=f"status in {{completed,done,ok,success}} & updated_within_last_{int(hours)}h",
            ),
            "agent_runs_failed_24h": _labeled_count(
                agent_runs["failed_runs_count"],
                source=f"{agent_runs['state_tasks_dir']}/*.json",
                scope=scope_str,
                filter_expr=f"status in {{failed,error,stale}} & updated_within_last_{int(hours)}h",
            ),
            "github_merged_prs_24h": _labeled_count(
                pr_summary.get("merged_prs_count", 0),
                source="gh search prs",
                scope=gh_scope,
                filter_expr=f"author:@me state:closed is:merged merged:>={day_str}",
            ),
            "github_opened_prs_24h": _labeled_count(
                pr_summary.get("opened_prs_count", 0),
                source="gh search prs",
                scope=gh_scope,
                filter_expr=f"author:@me created:>={day_str}",
            ),
        }
        return {
            "schema": SCHEMA,
            "mode": "day",
            "report_kind": "day_24h_delta",
            "root": str(root),
            "hours": hours,
            "depth": depth,
            "timestamp": started.isoformat(),
            "date": day_str,
            "delta_24h": {
                "window_hours": hours,
                "completed_tasks_count": planfile_data["completed_count"],
                "completed_tickets": planfile_data["completed_tickets"],
                "new_blockers_count": pf_extended["new_blockers_count"],
                "new_blockers": pf_extended["new_blockers"][:20],
                "agent_runs_completed": agent_runs["completed_runs_count"],
                "agent_runs_failed": agent_runs["failed_runs_count"],
                "agent_runs_running": agent_runs["running_runs_count"],
                "recent_agent_runs": agent_runs["recent_runs"],
                "merged_prs_count": pr_summary.get("merged_prs_count", 0),
                "merged_prs": pr_summary.get("merged_prs", []),
                "opened_prs_count": pr_summary.get("opened_prs_count", 0),
                "opened_prs": pr_summary.get("opened_prs", []),
            },
            "planfile": {
                "completed_today": planfile_data["completed_count"],
                "new_blockers_24h": pf_extended["new_blockers_count"],
                "completed_tickets": planfile_data["completed_tickets"],
                "new_blockers": pf_extended["new_blockers"][:20],
            },
            "agent_runs": agent_runs,
            "github": {
                "merged_prs_count": pr_summary.get("merged_prs_count", 0),
                "opened_prs_count": pr_summary.get("opened_prs_count", 0),
                "merged_prs": pr_summary.get("merged_prs", []),
                "opened_prs": pr_summary.get("opened_prs", []),
            },
            "counts_labeled": counts_labeled,
        }

    leases_snap = _scan_active_leases_snapshot(root, depth=depth)
    counts_labeled = {
        "planfile_queued_actionable": _labeled_count(
            planfile_data["queued_count"],
            source=".planfile/sprints/current.yaml(.fast.json)",
            scope=scope_str,
            filter_expr="status in {todo,open,in_progress,planned} (current sprint only; excludes blocked/done/history)",
        ),
        "planfile_in_progress": _labeled_count(
            pf_extended["in_progress_count"],
            source=".planfile/sprints/current.yaml(.fast.json)",
            scope=scope_str,
            filter_expr="status == in_progress (current sprint)",
        ),
        "planfile_blocked_total": _labeled_count(
            pf_extended["blocked_total_count"],
            source=".planfile/sprints/current.yaml(.fast.json)",
            scope=scope_str,
            filter_expr="status == blocked (current sprint)",
        ),
        "planfile_current_sprint_all_entries": _labeled_count(
            pf_extended["all_current_sprint_entries"],
            source=".planfile/sprints/current.yaml(.fast.json)",
            scope=scope_str,
            filter_expr="all statuses in current sprint (excludes archived history-*.yaml)",
        ),
        "planfile_completed_today": _labeled_count(
            planfile_data["completed_count"],
            source=".planfile/sprints/{history-YYYY-MM-DD,current}.yaml(.fast.json)",
            scope=scope_str,
            filter_expr=f"history-{day_str} U (current.status in {{done,completed}} & date=={day_str})",
        ),
        "subactor_active_leases": _labeled_count(
            leases_snap["active_leases_count"],
            source=".subactor/leases/*.json",
            scope=scope_str,
            filter_expr="phase not in {released,merged,closed,cancelled}",
        ),
        "github_open_prs_queue": _labeled_count(
            pr_summary.get("open_prs_count", 0),
            source="gh search prs",
            scope=gh_scope,
            filter_expr="author:@me state:open (limit<=50)",
        ),
        "github_merged_prs_today": _labeled_count(
            pr_summary.get("merged_prs_count", 0),
            source="gh search prs",
            scope=gh_scope,
            filter_expr=f"author:@me state:closed is:merged merged:>={day_str}",
        ),
    }

    return {
        "schema": SCHEMA,
        "mode": "summary",
        "report_kind": "portfolio_queue_snapshot",
        "root": str(root),
        "hours": hours,
        "depth": depth,
        "timestamp": started.isoformat(),
        "date": day_str,
        "portfolio_snapshot": {
            "repositories_with_planfile": pf_extended["repositories_with_planfile"],
            "queued_actionable": planfile_data["queued_count"],
            "open_or_todo": pf_extended["open_or_todo_count"],
            "in_progress": pf_extended["in_progress_count"],
            "planned": pf_extended["planned_count"],
            "blocked_total": pf_extended["blocked_total_count"],
            "all_current_sprint_entries": pf_extended["all_current_sprint_entries"],
            "estimated_minutes": planfile_data["total_estimated_minutes"],
            "active_leases_count": leases_snap["active_leases_count"],
            "terminal_leases_count": leases_snap["terminal_leases_count"],
            "open_prs_count": pr_summary.get("open_prs_count", 0),
        },
        "planfile": {
            "completed_today": planfile_data["completed_count"],
            "queued": planfile_data["queued_count"],
            "in_progress": pf_extended["in_progress_count"],
            "blocked": pf_extended["blocked_total_count"],
            "all_current_sprint_entries": pf_extended["all_current_sprint_entries"],
            "estimated_minutes": planfile_data["total_estimated_minutes"],
            "completed_tickets": planfile_data["completed_tickets"],
            "queued_tickets": planfile_data["queued_tickets"][:20],
        },
        "leases": leases_snap,
        "github": pr_summary,
        "counts_labeled": counts_labeled,
    }


def gather_day(
    root: Path,
    hours: int = 24,
    github: bool = True,
    target_date: Optional[date] = None,
    depth: int = 2,
    state_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Compile 24h operational delta (`monag day`)."""
    return gather_summary(
        root=root,
        hours=hours,
        github=github,
        target_date=target_date,
        depth=depth,
        state_dir=state_dir,
        mode="day",
    )


def _fmt_label_suffix(labeled: Optional[Dict[str, Any]], default_source: str, default_filter: str) -> str:
    if isinstance(labeled, dict):
        src = labeled.get("source") or default_source
        scope = labeled.get("scope") or "workspace"
        flt = labeled.get("filter") or default_filter
        return f" *(źródło: `{src}`, zakres: `{scope}`, filtr: `{flt}`)*"
    return f" *(źródło: `{default_source}`, filtr: `{default_filter}`)*"


def format_markdown(data: Dict[str, Any]) -> str:
    """Format `day` (24h operational delta) or `summary` (portfolio/queue snapshot) into Markdown."""
    mode = str(data.get("mode") or "summary").lower()
    day = data.get("date", str(date.today()))
    labels = data.get("counts_labeled") or {}

    if mode == "day":
        delta = data.get("delta_24h") or {}
        gh = data.get("github") or {}
        hours = data.get("hours", 24)
        comp_cnt = delta.get("completed_tasks_count", (data.get("planfile") or {}).get("completed_today", 0))
        blk_cnt = delta.get("new_blockers_count", 0)
        runs_ok = delta.get("agent_runs_completed", 0)
        runs_fail = delta.get("agent_runs_failed", 0)
        merged_cnt = delta.get("merged_prs_count", gh.get("merged_prs_count", 0))
        opened_cnt = delta.get("opened_prs_count", gh.get("opened_prs_count", 0))

        lines = [
            f"# MONAG 24h Operational Delta (`day` — {day}, okno: {hours}h)",
            "",
            "## 1. 24h Delta — Planfile & Uruchomienia Agentów",
            (
                f"- **Ukończone zadania (okno 24h)**: `{comp_cnt}` zadań"
                + _fmt_label_suffix(labels.get("planfile_completed_24h"), ".planfile/sprints", f"date=={day}")
            ),
            (
                f"- **Nowe blokery (ostatnie {hours}h)**: `{blk_cnt}` zadań"
                + _fmt_label_suffix(labels.get("planfile_new_blockers_24h"), ".planfile/sprints/current.yaml", f"status==blocked & updated<={hours}h")
            ),
            (
                f"- **Zakończone przebiegi agentów (ostatnie {hours}h)**: `{runs_ok}` ukończonych"
                + _fmt_label_suffix(labels.get("agent_runs_completed_24h"), "state_dir/tasks/*.json", f"status==completed & updated<={hours}h")
            ),
            (
                f"- **Nieudane / przerwane przebiegi agentów (ostatnie {hours}h)**: `{runs_fail}` błędnych"
                + _fmt_label_suffix(labels.get("agent_runs_failed_24h"), "state_dir/tasks/*.json", f"status in {{failed,stale}} & updated<={hours}h")
            ),
            "",
            "## 2. 24h Delta — GitHub Pull Requests",
            (
                f"- **Zmergowane PR (>= {day})**: `{merged_cnt}`"
                + _fmt_label_suffix(labels.get("github_merged_prs_24h"), "gh search prs", f"is:merged merged:>={day}")
            ),
            (
                f"- **Nowo otwarte PR (>= {day})**: `{opened_cnt}`"
                + _fmt_label_suffix(labels.get("github_opened_prs_24h"), "gh search prs", f"created:>={day}")
            ),
            "",
        ]

        new_blockers = delta.get("new_blockers") or []
        if new_blockers:
            lines.append("### Nowe blokery wykryte w oknie 24h:")
            for b in new_blockers[:5]:
                lines.append(f"- 🛑 **[{b.get('repo')}]** `{b.get('id')}`: {b.get('title')} ({b.get('reason')})")
            lines.append("")

        recent_runs = delta.get("recent_agent_runs") or []
        if recent_runs:
            lines.append("### Ostatnie przebiegi agentów (24h):")
            for r in recent_runs[:5]:
                icon = "✓" if r.get("status") in ("completed", "done", "ok", "success") else "✗"
                tkt = f" (`{r.get('ticket')}`)" if r.get("ticket") else ""
                lines.append(f"- {icon} **[{r.get('status')}]** `{r.get('id')}`{tkt}: {r.get('task')}")
            lines.append("")

        merged_prs = delta.get("merged_prs") or gh.get("merged_prs", [])
        if merged_prs:
            lines.append("### Zmergowane Pull Requesty w oknie 24h:")
            for pr in merged_prs[:5]:
                lines.append(f"- ✓ **[{pr.get('repo')}]** `#{pr.get('number')}`: {pr.get('title')}")
            lines.append("")

        opened_prs = delta.get("opened_prs") or gh.get("opened_prs", [])
        if opened_prs:
            lines.append("### Nowo otwarte Pull Requesty w oknie 24h:")
            for pr in opened_prs[:5]:
                lines.append(f"- ➕ **[{pr.get('repo')}]** `#{pr.get('number')}`: {pr.get('title')}")
            lines.append("")

        completed = delta.get("completed_tickets") or (data.get("planfile") or {}).get("completed_tickets", [])
        if completed:
            lines.append("### Ukończone zadania Planfile w oknie 24h:")
            for t in completed[:5]:
                lines.append(f"- ✓ **[{t.get('repo')}]** `{t.get('id')}`: {t.get('title')}")
            lines.append("")

        return "\n".join(lines)

    # mode == "summary": Current Portfolio & Queue Snapshot
    pf = data.get("planfile", {})
    gh = data.get("github", {})
    snap = data.get("portfolio_snapshot") or {}

    est_mins = pf.get("estimated_minutes", 0)
    est_hours = round(est_mins / 60.0, 1)
    queued_cnt = pf.get("queued", 0)
    in_prog_cnt = pf.get("in_progress", snap.get("in_progress", 0))
    blocked_cnt = pf.get("blocked", snap.get("blocked_total", 0))
    all_curr_cnt = pf.get("all_current_sprint_entries", snap.get("all_current_sprint_entries", queued_cnt))
    active_leases = snap.get("active_leases_count", (data.get("leases") or {}).get("active_leases_count", 0))

    lines = [
        f"# MONAG Portfolio & Queue Summary ({day})",
        "",
        "## 1. Bieżący Stan Kolejki i Portfela (Snapshot)",
        (
            f"- **Oczekujące w kolejce**: `{queued_cnt}` zadań (szacunkowo `{est_mins} min` / `~{est_hours}h`)"
            + _fmt_label_suffix(
                labels.get("planfile_queued_actionable"),
                ".planfile/sprints/current.yaml",
                "status in {todo,open,in_progress,planned}",
            )
        ),
        (
            f"- **W trakcie realizacji (in_progress)**: `{in_prog_cnt}` zadań"
            + _fmt_label_suffix(
                labels.get("planfile_in_progress"),
                ".planfile/sprints/current.yaml",
                "status == in_progress",
            )
        ),
        (
            f"- **Zablokowane w bieżącym sprincie**: `{blocked_cnt}` zadań"
            + _fmt_label_suffix(
                labels.get("planfile_blocked_total"),
                ".planfile/sprints/current.yaml",
                "status == blocked",
            )
        ),
        (
            f"- **Wszystkie wpisy bieżącego sprintu**: `{all_curr_cnt}` rekordów"
            + _fmt_label_suffix(
                labels.get("planfile_current_sprint_all_entries"),
                ".planfile/sprints/current.yaml",
                "all statuses in current sprint (excl. archived history-*.yaml)",
            )
        ),
        (
            f"- **Aktywne dzierżawy robocze (.subactor/leases)**: `{active_leases}`"
            + _fmt_label_suffix(
                labels.get("subactor_active_leases"),
                ".subactor/leases/*.json",
                "phase not in {released,merged,closed,cancelled}",
            )
        ),
        (
            f"- **Wykonane dzisiaj**: `{pf.get('completed_today', 0)}` zadań"
            + _fmt_label_suffix(
                labels.get("planfile_completed_today"),
                ".planfile/sprints/{history,current}.yaml",
                f"completed on {day}",
            )
        ),
        "",
        "## 2. Kolejka GitHub Pull Requests",
        (
            f"- **Otwarte PR w kolejce**: `{gh.get('open_prs_count', 0)}`"
            + _fmt_label_suffix(
                labels.get("github_open_prs_queue"),
                "gh search prs",
                "author:@me state:open",
            )
        ),
        (
            f"- **Zmergowane dzisiaj (>= {day})**: `{gh.get('merged_prs_count', 0)}`"
            + _fmt_label_suffix(
                labels.get("github_merged_prs_today"),
                "gh search prs",
                f"author:@me is:merged merged:>={day}",
            )
        ),
        "",
    ]

    open_prs = gh.get("open_prs", [])
    if open_prs:
        lines.append("### Otwarte Pull Requesty w kolejce do zmergowania:")
        for pr in open_prs[:5]:
            lines.append(f"- ⏳ **[{pr.get('repo')}]** `#{pr.get('number')}`: {pr.get('title')}")
        if len(open_prs) > 5:
            lines.append(f"  *...oraz {len(open_prs) - 5} kolejnych otwartych PR.*")
        lines.append("")

    completed = pf.get("completed_tickets", [])
    if completed:
        lines.append("### Ostatnio ukończone zadania Planfile dzisiaj:")
        for t in completed[:5]:
            lines.append(f"- ✓ **[{t.get('repo')}]** `{t.get('id')}`: {t.get('title')}")
        if len(completed) > 5:
            lines.append(f"  *...oraz {len(completed) - 5} kolejnych zrealizowanych dzisiaj zadań.*")
        lines.append("")

    queued = pf.get("queued_tickets", [])
    if queued:
        lines.append("### Przykładowe zadania w kolejce:")
        for t in queued[:5]:
            prio = t.get("priority", "normal")
            lines.append(f"- ⏳ **[{t.get('repo')}]** `[{prio}]` `{t.get('id')}`: {t.get('title')}")
        if len(queued) > 5:
            lines.append(f"  *...oraz {pf.get('queued', len(queued)) - 5} kolejnych zadań oczekujących w kolejce.*")
        lines.append("")

    return "\n".join(lines)

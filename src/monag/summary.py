"""Daily execution summary for Planfile, Koru, and GitHub Pull Requests.

Aggregates completed work, active queues, GitHub PR metrics, and time estimates
across the fleet or a single project.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, Dict, List, Optional

SCHEMA = "monag.summary/v1"


def gather_planfile_daily(root: Path, target_date: Optional[date] = None) -> Dict[str, Any]:
    """Scan Planfile sprints for tasks completed on target_date and currently queued tasks."""
    target_date = target_date or date.today()
    today_str = target_date.strftime("%Y-%m-%d")

    done_tickets: List[Dict[str, Any]] = []
    queued_tickets: List[Dict[str, Any]] = []

    sprint_dirs: List[Path] = []
    if (root / ".planfile" / "sprints").is_dir():
        sprint_dirs.append(root / ".planfile" / "sprints")
    sprint_dirs.extend(root.glob("*/.planfile/sprints"))
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
                import yaml
                data = yaml.safe_load(hist_yaml.read_text(encoding="utf-8"))
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
                import yaml
                data = yaml.safe_load(curr_yaml.read_text(encoding="utf-8"))
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


def query_github_pr_metrics(target_date: Optional[date] = None, timeout: int = 15) -> Dict[str, Any]:
    """Fast query of open and merged Pull Requests using gh search prs."""
    target_date = target_date or date.today()
    today_str = target_date.strftime("%Y-%m-%d")

    result = {
        "open_prs_count": 0,
        "merged_prs_count": 0,
        "open_prs": [],
        "merged_prs": [],
    }

    gh_bin = shutil.which("gh")
    if not gh_bin:
        return result

    try:
        # 1. Open PRs
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
        # 2. Merged PRs today
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

    return result


def gather_summary(root: Path, hours: int = 24, github: bool = True,
                   target_date: Optional[date] = None, depth: int = 2) -> Dict[str, Any]:
    """Compile comprehensive daily summary spanning Planfile, Koru, and GitHub PRs."""
    started = datetime.now(timezone.utc)
    planfile_data = gather_planfile_daily(root, target_date=target_date)

    pr_summary: Dict[str, Any] = {
        "open_prs_count": 0,
        "merged_prs_count": 0,
        "open_prs": [],
        "merged_prs": [],
    }

    if github:
        pr_summary = query_github_pr_metrics(target_date=target_date)

    return {
        "schema": SCHEMA,
        "root": str(root),
        "timestamp": started.isoformat(),
        "date": planfile_data["date"],
        "planfile": {
            "completed_today": planfile_data["completed_count"],
            "queued": planfile_data["queued_count"],
            "estimated_minutes": planfile_data["total_estimated_minutes"],
            "completed_tickets": planfile_data["completed_tickets"],
            "queued_tickets": planfile_data["queued_tickets"][:20],
        },
        "github": pr_summary,
    }


def format_markdown(data: Dict[str, Any]) -> str:
    """Format daily summary data into clean GitHub-flavored markdown."""
    pf = data.get("planfile", {})
    gh = data.get("github", {})
    day = data.get("date", str(date.today()))

    est_mins = pf.get("estimated_minutes", 0)
    est_hours = round(est_mins / 60.0, 1)

    lines = [
        f"# MONAG Daily Execution Summary ({day})",
        "",
        "## 1. Planfile & Koru Living Execution",
        f"- **Wykonane dzisiaj**: `{pf.get('completed_today', 0)}` zadań",
        f"- **Oczekujące w kolejce**: `{pf.get('queued', 0)}` zadań (szacunkowo `{est_mins} min` / `~{est_hours}h`)",
        "",
        "## 2. GitHub Pull Requests",
        f"- **Otwarte PR w kolejce**: `{gh.get('open_prs_count', 0)}`",
        f"- **Zmergowane dzisiaj (>= {day})**: `{gh.get('merged_prs_count', 0)}`",
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

    merged_prs = gh.get("merged_prs", [])
    if merged_prs:
        lines.append("### Ostatnio zmergowane Pull Requesty dzisiaj:")
        for pr in merged_prs[:5]:
            lines.append(f"- ✓ **[{pr.get('repo')}]** `#{pr.get('number')}`: {pr.get('title')}")
        if len(merged_prs) > 5:
            lines.append(f"  *...oraz {len(merged_prs) - 5} kolejnych zmergowanych PR dzisiaj.*")
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

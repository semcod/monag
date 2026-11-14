"""Report actual dependencies, git fleet worktrees, code duplication and observation coverage."""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Callable
from .monitor import command

DOCTOR_PHASES = ("environment", "ecosystem_tools", "repositories", "agent_storage")


def _remaining_budget(deadline: float | None, clock: Callable[[], float]) -> float | None:
    if deadline is None:
        return None
    return deadline - clock()


def _bounded_cmd_timeout(deadline: float | None, clock: Callable[[], float], default: float = 10.0) -> float:
    rem = _remaining_budget(deadline, clock)
    if rem is None:
        return default
    return max(0.1, min(default, rem))


def find_git_repositories(root: Path, max_depth: int = 2) -> list[Path]:
    """Find all git repositories in root or within subdirectories up to max_depth."""
    if not root.is_dir():
        return []
    if (root / '.git').exists():
        return [root]

    repos = []
    ignored = {'.git', '.cache', '.pytest_tmp', 'node_modules', '.venv', 'venv'}

    for p in root.iterdir():
        try:
            if p.is_dir() and p.name not in ignored and not p.name.startswith('.'):
                if (p / '.git').exists():
                    repos.append(p)
                elif max_depth > 1:
                    for sub in p.iterdir():
                        if sub.is_dir() and sub.name not in ignored and not sub.name.startswith('.'):
                            if (sub / '.git').exists():
                                repos.append(sub)
        except (OSError, PermissionError):
            pass

    return sorted(set(repos))


def parse_worktrees_porcelain(repo: Path, timeout: float = 10.0) -> list[dict]:
    """Parse git worktree list --porcelain output for a repository."""
    out, err = command(['git', '-C', str(repo), 'worktree', 'list', '--porcelain'], timeout=max(0.1, timeout))
    if err or not out:
        return []

    worktrees = []
    current: dict = {}
    for line in out.splitlines():
        line = line.strip()
        if not line:
            if current:
                worktrees.append(current)
                current = {}
            continue
        if line.startswith('worktree '):
            current['path'] = line.split('worktree ', 1)[1].strip()
        elif line.startswith('HEAD '):
            current['head'] = line.split('HEAD ', 1)[1].strip()
        elif line.startswith('branch '):
            ref = line.split('branch ', 1)[1].strip()
            current['branch'] = ref.replace('refs/heads/', '')
        elif line.startswith('bare'):
            current['bare'] = True
        elif line.startswith('locked'):
            current['locked'] = True
        elif line.startswith('prunable'):
            current['prunable'] = True

    if current:
        worktrees.append(current)

    return worktrees


def is_branch_merged(
    repo: Path,
    branch: str,
    target: str = 'main',
    resolved_target: str | None = None,
    timeout: float = 10.0,
) -> bool:
    """Check if a branch is merged into target branch (or HEAD if target does not exist)."""
    if resolved_target is not None:
        effective_target = resolved_target
    else:
        t_out, _ = command(['git', '-C', str(repo), 'rev-parse', '--verify', target], timeout=max(0.1, timeout))
        if not t_out.strip():
            t_out, _ = command(['git', '-C', str(repo), 'rev-parse', '--verify', 'master'], timeout=max(0.1, timeout))
            effective_target = 'master' if t_out.strip() else 'HEAD'
        else:
            effective_target = target

    try:
        code = subprocess.run(
            ['git', '-C', str(repo), 'merge-base', '--is-ancestor', branch, effective_target],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=max(0.2, timeout),
        ).returncode
        return code == 0
    except (subprocess.SubprocessError, OSError):
        return False


def audit_worktrees(
    repo: Path,
    leases: dict[str, dict[str, Any]] | None = None,
    target_branch: str | None = None,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> list[dict]:
    """Audit worktrees of a repo, identifying secondary, stale, or merged worktrees."""
    rem = _remaining_budget(deadline, clock)
    if rem is not None and rem <= 0.0:
        return []

    raw_worktrees = parse_worktrees_porcelain(repo, timeout=_bounded_cmd_timeout(deadline, clock, 10.0))
    if not raw_worktrees:
        return []

    audited: list[dict] = []
    try:
        repo_resolved = repo.resolve()
    except OSError:
        repo_resolved = repo

    parsed_entries: list[tuple[dict, str, Path, bool]] = []
    has_secondary = False
    for wt in raw_worktrees:
        wt_path_str = wt.get('path', '')
        if not wt_path_str:
            continue
        wt_path = Path(wt_path_str)
        is_primary = False
        try:
            if wt_path.resolve() == repo_resolved:
                is_primary = True
        except OSError:
            pass
        if not is_primary:
            has_secondary = True
        parsed_entries.append((wt, wt_path_str, wt_path, is_primary))

    from . import worktrees

    repo_leases: dict[str, dict[str, Any]] = {}
    resolved_target: str | None = target_branch
    if has_secondary:
        repo_leases = worktrees.get_repo_leases(repo) if leases is None else leases
        if resolved_target is None:
            resolved_target = (
                worktrees.resolve_default_target_branch(
                    repo,
                    timeout=_bounded_cmd_timeout(deadline, clock, 10.0),
                )
                or ""
            )

    for wt, wt_path_str, wt_path, is_primary in parsed_entries:
        rem = _remaining_budget(deadline, clock)
        if rem is not None and rem <= 0.0:
            break

        exists = wt_path.is_dir()
        branch = wt.get('branch', '')
        is_merged = False
        dirty = False
        locked = bool(wt.get('locked', False))
        has_active_lease = False
        cmd_timeout = _bounded_cmd_timeout(deadline, clock, 10.0)

        if branch and not is_primary:
            is_merged = worktrees.is_branch_merged(
                repo,
                branch,
                target_branch=resolved_target,
                timeout=cmd_timeout,
            )
        if exists and not is_primary:
            dirty, _ = worktrees.is_worktree_dirty(wt_path, timeout=cmd_timeout)

        if not is_primary:
            lease = worktrees._resolve_worktree_lease(repo_leases, wt_path, wt_path_str, branch)
            if lease:
                has_active_lease, _ = worktrees.is_lease_active(lease)

        is_stale = (
            ((not exists) or wt.get('prunable', False) or (is_merged and not is_primary))
            and not dirty
            and not locked
            and not has_active_lease
        )

        audited.append({
            'repo': repo.name,
            'repo_path': str(repo),
            'path': wt_path_str,
            'branch': branch,
            'head': wt.get('head', ''),
            'is_primary': is_primary,
            'exists': exists,
            'is_merged': is_merged,
            'dirty': dirty,
            'locked': wt.get('locked', False),
            'prunable': wt.get('prunable', False),
            'stale': is_stale,
        })

    return audited


def audit_merged_branches(
    repo: Path,
    target_branch: str | None = None,
    timeout: float = 10.0,
) -> list[str]:
    """Find local branches that are already merged into main/HEAD."""
    if target_branch:
        target = target_branch
    else:
        target = 'main'
        t_out, _ = command(['git', '-C', str(repo), 'rev-parse', '--verify', target], timeout=max(0.1, timeout))
        if not t_out.strip():
            t_out, _ = command(['git', '-C', str(repo), 'rev-parse', '--verify', 'master'], timeout=max(0.1, timeout))
            target = 'master' if t_out.strip() else 'HEAD'

    out, _ = command(['git', '-C', str(repo), 'branch', '--merged', target], timeout=max(0.1, timeout))
    if not out:
        return []

    merged = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith('*') or line.startswith('+'):
            continue
        b_name = line.split()[-1]
        if b_name not in ('main', 'master', 'HEAD'):
            merged.append(b_name)

    return merged


def prune_and_remediate(
    repo: Path,
    stale_worktrees: list[dict],
    merged_branches: list[str],
    leases: dict[str, dict[str, Any]] | None = None,
    target_branch: str | None = None,
) -> dict:
    """Remediate a repo by safely pruning worktrees and deleting merged ticket branches conforming to Wellmanifest v5."""
    from . import worktrees
    res = worktrees.prune_worktrees_safe(repo, dry_run=False)
    deleted = list(res['deleted_branches'])
    active_branches = {w.get('branch') for w in parse_worktrees_porcelain(repo) if w.get('branch')}
    repo_leases = worktrees.get_repo_leases(repo) if leases is None else leases
    for b in merged_branches:
        if b in deleted or b in active_branches:
            continue
        lease = worktrees._resolve_worktree_lease(repo_leases, Path(b), "", b)
        if lease and worktrees.is_lease_active(lease)[0]:
            continue
        if is_branch_merged(repo, b, resolved_target=target_branch or None):
            _, err = command(['git', '-C', str(repo), 'branch', '-d', b])
            if not err:
                deleted.append(b)
    return {
        'worktrees_pruned': res['pruned'],
        'branches_deleted': [{'repo': repo.name, 'branch': b} for b in deleted],
        'protected': res['protected'],
    }


def audit_agent_storage_health(
    home: Path | None = None,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """Audit local coding agent session storage integrity and panic history.

    Delegates to semcod/uncrash diagnostics when available, with a lightweight
    standalone SQLite quick_check fallback bounded by deadline.
    """
    rem = _remaining_budget(deadline, clock)
    if rem is not None and rem <= 0.0:
        return {'status': 'SKIPPED_TIMEOUT', 'corrupted_sessions': [], 'detected_panics': [], 'timed_out': True}

    target_home = Path(home or Path.home())
    try:
        from uncrash.diagnostics import check_agent_storage_health
        if deadline is None:
            return check_agent_storage_health(target_home)
        outcome: "queue.Queue[tuple[bool, Any]]" = queue.Queue(maxsize=1)

        def _run_uncrash() -> None:
            try:
                outcome.put((True, check_agent_storage_health(target_home)))
            except Exception as exc:
                outcome.put((False, exc))

        worker = threading.Thread(target=_run_uncrash, name="monag-doctor-uncrash", daemon=True)
        worker.start()
        try:
            ok, val = outcome.get(timeout=max(0.05, rem))
            if ok and isinstance(val, dict):
                return val
        except queue.Empty:
            return {'status': 'PARTIAL_TIMEOUT', 'corrupted_sessions': [], 'detected_panics': [], 'timed_out': True}
    except ImportError:
        pass

    # Fallback lightweight audit
    import sqlite3
    agy_root = target_home / '.gemini/antigravity-cli'
    if not agy_root.is_dir():
        return {'status': 'NOT_PRESENT', 'corrupted_sessions': [], 'detected_panics': []}

    def _quick_check_db(db_path: Path, db_timeout: float) -> dict | None:
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=max(0.1, min(1.0, db_timeout)))
            res = conn.execute("PRAGMA quick_check;").fetchone()
            conn.close()
            if not res or res[0] != 'ok':
                return {'session_id': db_path.stem, 'path': str(db_path), 'error': res[0] if res else 'failed'}
        except Exception as e:
            return {'session_id': db_path.stem, 'path': str(db_path), 'error': str(e)}
        return None

    corrupt = []
    partial_timeout = False
    conv_dir = agy_root / 'conversations'
    if conv_dir.is_dir():
        for db in sorted(conv_dir.glob('*.db')):
            rem = _remaining_budget(deadline, clock)
            if rem is not None and rem <= 0.0:
                partial_timeout = True
                break
            item = _quick_check_db(db, rem if rem is not None else 1.0)
            if item is not None:
                corrupt.append(item)

    panics = []
    log_dir = agy_root / 'log'
    if not partial_timeout and log_dir.is_dir():
        for lf in sorted(log_dir.glob('*.log'), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)[:10]:
            rem = _remaining_budget(deadline, clock)
            if rem is not None and rem <= 0.0:
                partial_timeout = True
                break
            try:
                txt = lf.read_text(encoding='utf-8', errors='replace')[:256 * 1024]
                if 'panic' in txt.lower() or 'disk image is malformed' in txt.lower():
                    panics.append({'log_name': lf.name, 'log_path': str(lf)})
            except (OSError, UnicodeError):
                continue

    status = 'CORRUPTED' if corrupt else ('DEGRADED' if panics else ('PARTIAL_TIMEOUT' if partial_timeout else 'HEALTHY'))
    out_health = {'status': status, 'corrupted_sessions': corrupt, 'detected_panics': panics}
    if partial_timeout:
        out_health['timed_out'] = True
    return out_health


def diagnose(
    root: Path,
    fix: bool = False,
    home: Path | None = None,
    budget_seconds: float | None = 60.0,
    phase_budgets: dict[str, float] | None = None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    started = clock()
    overall_deadline = (started + max(0.0, float(budget_seconds))) if budget_seconds is not None else None
    configured_phase_budgets = dict(phase_budgets or {})

    completed_phases: list[str] = []
    timed_out_phases: list[str] = []
    skipped_phases: list[str] = []
    skipped_repositories: list[str] = []
    phase_durations_seconds: dict[str, float] = {}
    timed_out = False

    def _phase_deadline(phase_name: str, phase_start: float) -> float | None:
        pb = configured_phase_budgets.get(phase_name)
        p_dead = (phase_start + max(0.0, float(pb))) if pb is not None else None
        if overall_deadline is not None and p_dead is not None:
            return min(overall_deadline, p_dead)
        return p_dead if p_dead is not None else overall_deadline

    def _emit_progress(phase_name: str, **payload: Any) -> None:
        if progress_callback is not None:
            try:
                progress_callback(phase_name, payload)
            except Exception:
                pass

    # Phase 1: environment
    errors: list[str] = []
    git = ""
    git_error = ""
    namespace, process_count = 'unavailable', 0
    own = Path('/proc/self')

    p1_start = clock()
    if overall_deadline is not None and p1_start >= overall_deadline:
        timed_out = True
        skipped_phases.append('environment')
    else:
        p1_dead = _phase_deadline('environment', p1_start)
        _emit_progress('environment', state='started')
        git, git_error = command(['git', '--version'], timeout=_bounded_cmd_timeout(p1_dead, clock, 5.0))
        try:
            namespace = os.readlink(own / 'ns/pid')
            process_count = sum(p.name.isdigit() for p in Path('/proc').iterdir())
        except OSError:
            namespace, process_count = 'unavailable', 0
        if git_error:
            errors.append(git_error)
        if not root.is_dir():
            errors.append('workspace root does not exist')
        if not (own / 'stat').exists():
            errors.append('Linux /proc process data is unavailable')
        p1_end = clock()
        phase_durations_seconds['environment'] = round(max(0.0, p1_end - p1_start), 4)
        if p1_dead is not None and p1_end > p1_dead:
            timed_out = True
            timed_out_phases.append('environment')
        else:
            completed_phases.append('environment')
        _emit_progress('environment', state='completed', duration=phase_durations_seconds['environment'])

    # Phase 2: ecosystem_tools
    tools: dict[str, bool] = {
        'git': bool(git and not git_error),
        'gh': bool(shutil.which('gh')),
        'diagit': False,
        'redup': False,
        'prefact': False,
    }
    p2_start = clock()
    if overall_deadline is not None and p2_start >= overall_deadline:
        timed_out = True
        skipped_phases.append('ecosystem_tools')
    else:
        p2_dead = _phase_deadline('ecosystem_tools', p2_start)
        _emit_progress('ecosystem_tools', state='started')
        from .ecosystem import audit_ecosystem_tools
        eco_capabilities = audit_ecosystem_tools()
        tools['diagit'] = bool(eco_capabilities.get('diagit') and eco_capabilities['diagit'].available)
        tools['redup'] = bool(eco_capabilities.get('redup') and eco_capabilities['redup'].available)
        tools['prefact'] = bool(eco_capabilities.get('prefact') and eco_capabilities['prefact'].available)
        for tool_name, cap in eco_capabilities.items():
            if cap.available and tool_name not in tools:
                tools[tool_name] = True
        p2_end = clock()
        phase_durations_seconds['ecosystem_tools'] = round(max(0.0, p2_end - p2_start), 4)
        if p2_dead is not None and p2_end > p2_dead:
            timed_out = True
            timed_out_phases.append('ecosystem_tools')
        else:
            completed_phases.append('ecosystem_tools')
        _emit_progress('ecosystem_tools', state='completed', duration=phase_durations_seconds['ecosystem_tools'])

    # Phase 3: repositories
    repos: list[Path] = []
    repos_audited_count = 0
    all_worktrees: list[dict] = []
    stale_worktrees: list[dict] = []
    all_merged_branches: list[dict] = []
    remediation_summary: dict = {'worktrees_pruned': [], 'branches_deleted': []}

    p3_start = clock()
    if overall_deadline is not None and p3_start >= overall_deadline:
        timed_out = True
        skipped_phases.append('repositories')
        if root.is_dir():
            repos = find_git_repositories(root)
            skipped_repositories = [r.name for r in repos]
    else:
        p3_dead = _phase_deadline('repositories', p3_start)
        _emit_progress('repositories', state='started')
        repos = find_git_repositories(root)
        repo_phase_timed_out = False
        from . import worktrees as wt_mod

        for idx, repo in enumerate(repos):
            rem = _remaining_budget(p3_dead, clock)
            if rem is not None and rem <= 0.0:
                timed_out = True
                repo_phase_timed_out = True
                skipped_repositories.extend(r.name for r in repos[idx:])
                break

            _emit_progress('repositories', state='repo', repo=repo.name, index=idx + 1, total=len(repos))
            try:
                cmd_timeout = _bounded_cmd_timeout(p3_dead, clock, 10.0)
                resolved_target = wt_mod.resolve_default_target_branch(repo, timeout=cmd_timeout) or ""
                repo_leases: dict[str, dict[str, Any]] | None = None

                wts = audit_worktrees(
                    repo,
                    leases=repo_leases,
                    target_branch=resolved_target,
                    deadline=p3_dead,
                    clock=clock,
                )
                all_worktrees.extend(wts)
                repo_stale = [w for w in wts if w.get('stale')]
                stale_worktrees.extend(repo_stale)

                rem_after_wt = _remaining_budget(p3_dead, clock)
                if rem_after_wt is not None and rem_after_wt <= 0.0:
                    timed_out = True
                    repo_phase_timed_out = True
                    skipped_repositories.extend(r.name for r in repos[idx + 1:])
                    repos_audited_count += 1
                    break

                merged_b = audit_merged_branches(
                    repo,
                    target_branch=resolved_target or None,
                    timeout=_bounded_cmd_timeout(p3_dead, clock, 10.0),
                )
                for b in merged_b:
                    all_merged_branches.append({'repo': repo.name, 'branch': b})

                if fix and (repo_stale or merged_b):
                    res = prune_and_remediate(
                        repo,
                        repo_stale,
                        merged_b,
                        leases=repo_leases,
                        target_branch=resolved_target or None,
                    )
                    remediation_summary['worktrees_pruned'].extend(res['worktrees_pruned'])
                    remediation_summary['branches_deleted'].extend(res['branches_deleted'])

                repos_audited_count += 1
            except Exception as e:
                errors.append(f"Error auditing {repo.name}: {e}")

        p3_end = clock()
        phase_durations_seconds['repositories'] = round(max(0.0, p3_end - p3_start), 4)
        if repo_phase_timed_out or (p3_dead is not None and p3_end > p3_dead):
            timed_out = True
            if 'repositories' not in timed_out_phases:
                timed_out_phases.append('repositories')
        else:
            completed_phases.append('repositories')
        _emit_progress(
            'repositories',
            state='timed_out' if repo_phase_timed_out else 'completed',
            audited=repos_audited_count,
            total=len(repos),
            duration=phase_durations_seconds['repositories'],
        )

    # Phase 4: agent_storage
    recommendations: list[str] = []
    agent_health: dict[str, Any] = {'status': 'SKIPPED_TIMEOUT', 'corrupted_sessions': [], 'detected_panics': []}
    p4_start = clock()
    if overall_deadline is not None and p4_start >= overall_deadline:
        timed_out = True
        skipped_phases.append('agent_storage')
    else:
        if 'agent_storage' not in configured_phase_budgets and overall_deadline is not None:
            rem_overall = max(0.0, overall_deadline - p4_start)
            p4_dead: float | None = p4_start + min(rem_overall, 10.0)
        else:
            p4_dead = _phase_deadline('agent_storage', p4_start)
        _emit_progress('agent_storage', state='started')
        agent_health = audit_agent_storage_health(home=home, deadline=p4_dead, clock=clock)
        p4_end = clock()
        phase_durations_seconds['agent_storage'] = round(max(0.0, p4_end - p4_start), 4)
        if agent_health.get('timed_out') or (overall_deadline is not None and p4_end > overall_deadline):
            timed_out = True
            timed_out_phases.append('agent_storage')
        else:
            completed_phases.append('agent_storage')
        _emit_progress('agent_storage', state='completed', duration=phase_durations_seconds['agent_storage'])

    if agent_health.get('corrupted_sessions'):
        recommendations.append(
            f"Detected {len(agent_health['corrupted_sessions'])} corrupted agent session database(s) in ~/.gemini/antigravity-cli. Run 'uncrash' or restore via SQLite dump (wellmanifest/session-recovery)."
        )
    elif agent_health.get('detected_panics'):
        recommendations.append(
            f"Detected {len(agent_health['detected_panics'])} recent agent panic/crash log(s). Inspect logs or run 'uncrash diagnose'."
        )

    if timed_out:
        recommendations.append(
            f"Doctor reached time budget ({budget_seconds}s); partial diagnostics returned "
            f"(timed_out_phases={timed_out_phases}, skipped_repositories={len(skipped_repositories)}). "
            "Pass a larger --timeout for an exhaustive scan."
        )

    if not fix:
        if stale_worktrees or all_merged_branches:
            recommendations.append(
                f"Found {len(stale_worktrees)} stale worktrees and {len(all_merged_branches)} merged branches across {repos_audited_count} repositories. Run 'monag doctor --fix' to prune them."
            )
    else:
        recommendations.append(
            f"Remediated {len(remediation_summary['worktrees_pruned'])} stale worktrees and {len(remediation_summary['branches_deleted'])} merged branches."
        )

    if tools.get('redup'):
        recommendations.append("reDUP is available for deep AST code duplication analysis ('redup scan').")
    if tools.get('diagit'):
        recommendations.append("diagit is available for fleet git audits ('diagit worktrees').")
    if tools.get('prefact'):
        recommendations.append("prefact is available for automated refactoring ('prefact fix').")
    if tools.get('subllm'):
        recommendations.append("SubLLM is available for centralized LLM proxy and gateway routing ('subllm usage').")
    if tools.get('koru'):
        recommendations.append("Koru is available for autonomous living execution ('koru autonomous').")
    if tools.get('planfile'):
        recommendations.append("Planfile is available for backlog and sprint ticket lifecycle ('planfile ticket').")
    if tools.get('uncrash'):
        recommendations.append("Uncrash is available for workspace snapshots and agent session disaster recovery ('uncrash diagnose').")

    elapsed = round(max(0.0, clock() - started), 4)
    result = {
        'python': sys.version.split()[0],
        'runtime_dependencies': 'rich>=14,<15 (terminal Markdown); PyYAML>=6,<7 (Planfile backlog)',
        'git': git.strip() or None,
        'github_cli': shutil.which('gh'),
        'ecosystem_tools': [k for k, v in tools.items() if v],
        'agent_storage_status': agent_health.get('status', 'UNKNOWN'),
        'corrupted_agent_sessions': len(agent_health.get('corrupted_sessions', [])),
        'pid_namespace': namespace,
        'visible_processes': process_count,
        'uid': os.getuid(),
        'root': str(root),
        'repositories_discovered': len(repos),
        'repositories_checked': repos_audited_count,
        'worktrees_audited': len([w for w in all_worktrees if not w.get('is_primary')]),
        'stale_worktrees_detected': len(stale_worktrees),
        'merged_branches_detected': len(all_merged_branches),
        'fix_mode': fix,
        'budget_seconds': budget_seconds,
        'elapsed_seconds': elapsed,
        'timed_out': timed_out,
        'completed_phases': completed_phases,
        'timed_out_phases': timed_out_phases,
        'skipped_phases': skipped_phases,
        'skipped_repositories': skipped_repositories,
        'phase_durations_seconds': phase_durations_seconds,
        'errors': errors,
        'coverage': [
            'Only processes visible in this PID namespace can be observed.',
            'IDE or remote agents need explicit process registration or a future host adapter.',
            'No prompt, transcript, environment-variable or file-content collection.'
        ]
    }

    if fix:
        result['remediated_worktrees'] = len(remediation_summary['worktrees_pruned'])
        result['remediated_branches'] = len(remediation_summary['branches_deleted'])
        result['remediation_details'] = remediation_summary

    if recommendations:
        result['recommendations'] = recommendations

    return result

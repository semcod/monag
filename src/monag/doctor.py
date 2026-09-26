"""Report actual dependencies, git fleet worktrees, code duplication and observation coverage."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from .monitor import command


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


def parse_worktrees_porcelain(repo: Path) -> list[dict]:
    """Parse git worktree list --porcelain output for a repository."""
    out, err = command(['git', '-C', str(repo), 'worktree', 'list', '--porcelain'])
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


def is_branch_merged(repo: Path, branch: str, target: str = 'main') -> bool:
    """Check if a branch is merged into target branch (or HEAD if target does not exist)."""
    t_out, _ = command(['git', '-C', str(repo), 'rev-parse', '--verify', target])
    if not t_out.strip():
        t_out, _ = command(['git', '-C', str(repo), 'rev-parse', '--verify', 'master'])
        target = 'master' if t_out.strip() else 'HEAD'

    code = subprocess.run(
        ['git', '-C', str(repo), 'merge-base', '--is-ancestor', branch, target],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    ).returncode
    return code == 0


def audit_worktrees(repo: Path) -> list[dict]:
    """Audit worktrees of a repo, identifying secondary, stale, or merged worktrees."""
    raw_worktrees = parse_worktrees_porcelain(repo)
    audited = []
    try:
        repo_resolved = repo.resolve()
    except OSError:
        repo_resolved = repo

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

        exists = wt_path.is_dir()
        branch = wt.get('branch', '')
        is_merged = False
        if branch and not is_primary:
            is_merged = is_branch_merged(repo, branch)

        is_stale = (not exists) or wt.get('prunable', False) or (is_merged and not is_primary)

        audited.append({
            'repo': repo.name,
            'repo_path': str(repo),
            'path': wt_path_str,
            'branch': branch,
            'head': wt.get('head', ''),
            'is_primary': is_primary,
            'exists': exists,
            'is_merged': is_merged,
            'prunable': wt.get('prunable', False),
            'stale': is_stale,
        })

    return audited


def audit_merged_branches(repo: Path) -> list[str]:
    """Find local branches that are already merged into main/HEAD."""
    target = 'main'
    t_out, _ = command(['git', '-C', str(repo), 'rev-parse', '--verify', target])
    if not t_out.strip():
        t_out, _ = command(['git', '-C', str(repo), 'rev-parse', '--verify', 'master'])
        target = 'master' if t_out.strip() else 'HEAD'

    out, _ = command(['git', '-C', str(repo), 'branch', '--merged', target])
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


def prune_and_remediate(repo: Path, stale_worktrees: list[dict], merged_branches: list[str]) -> dict:
    """Remediate a repo by safely pruning worktrees and deleting merged ticket branches conforming to Wellmanifest v5."""
    from . import worktrees
    res = worktrees.prune_worktrees_safe(repo, dry_run=False)
    return {
        'worktrees_pruned': res['pruned'],
        'branches_deleted': [{'repo': repo.name, 'branch': b} for b in res['deleted_branches']],
        'protected': res['protected'],
    }


def diagnose(root: Path, fix: bool = False) -> dict:
    git, git_error = command(['git', '--version'])
    own = Path('/proc/self')
    try:
        namespace = os.readlink(own / 'ns/pid')
        process_count = sum(p.name.isdigit() for p in Path('/proc').iterdir())
    except OSError:
        namespace, process_count = 'unavailable', 0
    errors = []
    if git_error:
        errors.append(git_error)
    if not root.is_dir():
        errors.append('workspace root does not exist')
    if not (own / 'stat').exists():
        errors.append('Linux /proc process data is unavailable')

    # Audit ecosystem CLI tools
    tools = {
        'git': bool(git and not git_error),
        'gh': bool(shutil.which('gh')),
        'diagit': bool(shutil.which('diagit')),
        'redup': bool(shutil.which('redup')),
        'prefact': bool(shutil.which('prefact')),
    }

    # Audit repositories and worktrees
    repos = find_git_repositories(root)
    all_worktrees = []
    stale_worktrees = []
    all_merged_branches = []
    remediation_summary: dict = {'worktrees_pruned': [], 'branches_deleted': []}

    for repo in repos:
        try:
            wts = audit_worktrees(repo)
            all_worktrees.extend(wts)
            repo_stale = [w for w in wts if w.get('stale')]
            stale_worktrees.extend(repo_stale)

            merged_b = audit_merged_branches(repo)
            for b in merged_b:
                all_merged_branches.append({'repo': repo.name, 'branch': b})

            if fix and (repo_stale or merged_b):
                res = prune_and_remediate(repo, repo_stale, merged_b)
                remediation_summary['worktrees_pruned'].extend(res['worktrees_pruned'])
                remediation_summary['branches_deleted'].extend(res['branches_deleted'])
        except Exception as e:
            errors.append(f"Error auditing {repo.name}: {e}")

    recommendations = []
    if not fix:
        if stale_worktrees or all_merged_branches:
            recommendations.append(
                f"Found {len(stale_worktrees)} stale worktrees and {len(all_merged_branches)} merged branches across {len(repos)} repositories. Run 'monag doctor --fix' to prune them."
            )
    else:
        recommendations.append(
            f"Remediated {len(remediation_summary['worktrees_pruned'])} stale worktrees and {len(remediation_summary['branches_deleted'])} merged branches."
        )

    if tools['redup']:
        recommendations.append("reDUP is available for deep AST code duplication analysis ('redup scan').")
    if tools['diagit']:
        recommendations.append("diagit is available for fleet git audits ('diagit worktrees').")
    if tools['prefact']:
        recommendations.append("prefact is available for automated refactoring ('prefact fix').")

    result = {
        'python': sys.version.split()[0],
        'runtime_dependencies': 'rich>=14,<15 (terminal Markdown); PyYAML>=6,<7 (Planfile backlog)',
        'git': git.strip() or None,
        'github_cli': shutil.which('gh'),
        'ecosystem_tools': [k for k, v in tools.items() if v],
        'pid_namespace': namespace,
        'visible_processes': process_count,
        'uid': os.getuid(),
        'root': str(root),
        'repositories_checked': len(repos),
        'worktrees_audited': len([w for w in all_worktrees if not w.get('is_primary')]),
        'stale_worktrees_detected': len(stale_worktrees),
        'merged_branches_detected': len(all_merged_branches),
        'fix_mode': fix,
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

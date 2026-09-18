"""Read-only audit of local Git branches, unpushed commits, and open Pull Requests.

Inspects local repositories under `--root` for:
- branches with unpushed commits (`ahead > 0`),
- local-only branches without a remote tracking branch,
- working copy changes (dirty files),
- open GitHub Pull Requests via `gh`, correlating them with local branches.

In workspace mode (`--root ~/github`), fast local Git inspection filters active
repositories (commits within `--within HOURS`, dirty files, or ahead branches)
before issuing `gh` network requests, avoiding unnecessary API rate consumption.
Use `--all-repos` to force querying GitHub across all discovered repositories.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import socket
import struct
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import urllib.parse
import urllib.request

from .audit import targets as discover_targets
from .monitor import command, github_repo
from .presentation import table

SCHEMA = 'monag.prs/v1'


def parse_iso(value):
    """Parse ISO-8601 timestamp into aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def age_label(moment, now):
    """Compact 'in X'/'X ago' age string."""
    if moment is None:
        return '-'
    seconds = int((now - moment).total_seconds())
    if seconds < 0:
        return f'in {-seconds}s'
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days > 0:
        return f'{days}d{hours}h ago'
    if hours > 0:
        return f'{hours}h{minutes}m ago'
    if minutes > 0:
        return f'{minutes}m ago'
    return f'{seconds}s ago'


def repo_remote(path):
    """Return owner/repo from remote.origin.url or None."""
    remote, _ = command(['git', 'config', '--get', 'remote.origin.url'], path)
    return github_repo(remote) if remote else None


def _normalize_rest_pr(pr):
    """Normalize a GitHub REST API pull request payload to standard prs dict format."""
    state = 'MERGED' if pr.get('merged_at') else (pr.get('state') or '').upper()
    return {
        'number': pr.get('number'),
        'title': pr.get('title'),
        'headRefName': (pr.get('head') or {}).get('ref'),
        'baseRefName': (pr.get('base') or {}).get('ref'),
        'url': pr.get('html_url'),
        'isDraft': bool(pr.get('draft', False)),
        'state': state,
        'author': {'login': (pr.get('user') or {}).get('login')},
        'updatedAt': pr.get('updated_at'),
        'createdAt': pr.get('created_at'),
        'mergedAt': pr.get('merged_at'),
    }


def github_prs_via_rest(repo, state='all', limit=200):
    """Fetch pull requests via GitHub REST API (gh api repos/<repo>/pulls).

    Used as resilient fallback when GraphQL-based gh pr list hits secondary rate limits.
    """
    gh_state = state if state in {'open', 'closed', 'all'} else 'all'
    endpoint = f'repos/{repo}/pulls?state={gh_state}&per_page={min(limit, 100)}'
    out, error = command(['gh', 'api', endpoint], timeout=25)
    if error:
        return None, [f'{repo}: REST fallback failed: {error}']
    try:
        data = json.loads(out)
        if not isinstance(data, list):
            raise ValueError('expected a JSON array')
        return [_normalize_rest_pr(p) for p in data], []
    except (ValueError, TypeError):
        return None, [f'{repo}: invalid REST JSON']


def github_open_prs(repo, state='all', limit=200):
    """Fetch pull requests for a repository via gh with automatic REST fallback."""
    gh_state = state if state in {'open', 'closed', 'merged', 'all'} else 'all'
    out, error = command(['gh', 'pr', 'list', '--repo', repo, '--state', gh_state,
                          '--limit', str(limit), '--json',
                          'number,title,headRefName,baseRefName,url,isDraft,state,author,updatedAt,createdAt,mergedAt'],
                         timeout=25)
    if not error:
        try:
            prs = json.loads(out)
            if isinstance(prs, list):
                return prs, []
        except (ValueError, TypeError):
            pass

    # Resilient fallback: use GitHub REST API when gh pr list fails (e.g. GraphQL burst rate limits)
    prs_rest, rest_err = github_prs_via_rest(repo, state=state, limit=limit)
    if prs_rest is not None:
        return prs_rest, []

    return None, [f'{repo}: {error or "unknown gh error"}']



def inspect_working_tree(path):
    """Return (clean: bool, dirty_files: list[str], errors: list[str])."""
    st_out, st_err = command(['git', 'status', '--porcelain=v1'], path)
    if st_err:
        return None, [], [f'{path}: git status failed: {st_err}']
    dirty_files = [line.strip() for line in st_out.splitlines() if line.strip()]
    return len(dirty_files) == 0, dirty_files, []


def inspect_branches(path, now=None):
    """Inspect local branches, upstreams, ahead/behind counts, and recency."""
    now = now or datetime.now(timezone.utc)
    errors = []

    # Current branch name
    b_out, _ = command(['git', 'branch', '--show-current'], path)
    current_branch = b_out.strip() or None

    # Available remote branches on origin
    r_out, _ = command(['git', 'for-each-ref', '--format=%(refname:short)', 'refs/remotes/origin/'], path)
    remote_refs = set(line.strip() for line in r_out.splitlines() if line.strip())

    # Detect default remote branch to compare local-only branches against
    default_base = None
    for candidate in ('origin/main', 'origin/master', 'origin/trunk', 'origin/HEAD'):
        if candidate in remote_refs:
            default_base = candidate
            break

    # Inspect all local branches
    fmt = '%(refname:short)%00%(upstream:short)%00%(upstream:track)%00%(committerdate:iso-strict)%00%(subject)'
    l_out, l_err = command(['git', 'for-each-ref', f'--format={fmt}', 'refs/heads/'], path)
    if l_err:
        errors.append(f'{path}: git for-each-ref failed: {l_err}')
        return [], current_branch, errors

    branches = []
    for line in l_out.splitlines():
        if not line.strip():
            continue
        parts = line.split('\0')
        if len(parts) < 5:
            continue
        name, upstream, track, date_iso, subject = parts[0], parts[1], parts[2], parts[3], parts[4]
        dt = parse_iso(date_iso)
        commit_age = age_label(dt, now)

        ahead = 0
        behind = 0
        has_remote = False

        if upstream:
            has_remote = True
            m_ahead = re.search(r'ahead (\d+)', track)
            m_behind = re.search(r'behind (\d+)', track)
            if m_ahead:
                ahead = int(m_ahead.group(1))
            if m_behind:
                behind = int(m_behind.group(1))
        else:
            # Check if origin/<name> exists
            expected_remote = f'origin/{name}'
            if expected_remote in remote_refs:
                has_remote = True
                out_a, _ = command(['git', 'rev-list', '--count', f'{expected_remote}..{name}'], path)
                out_b, _ = command(['git', 'rev-list', '--count', f'{name}..{expected_remote}'], path)
                if out_a.strip().isdigit():
                    ahead = int(out_a.strip())
                if out_b.strip().isdigit():
                    behind = int(out_b.strip())
            else:
                has_remote = False
                if default_base and name not in ('main', 'master'):
                    out_a, _ = command(['git', 'rev-list', '--count', f'{default_base}..{name}'], path)
                    if out_a.strip().isdigit():
                        ahead = int(out_a.strip())

        # Determine readable branch status
        if ahead > 0 and not has_remote:
            status = f'unpushed ({ahead} commit{"s" if ahead != 1 else ""} ahead of base, no remote branch)'
        elif ahead > 0 and behind > 0:
            status = f'diverged (+{ahead}, -{behind})'
        elif ahead > 0:
            status = f'unpushed (+{ahead})'
        elif behind > 0:
            status = f'behind (-{behind})'
        elif not has_remote:
            status = 'local only (in sync with base)'
        else:
            status = 'synced'

        commit_ts = dt.timestamp() if dt else None

        branches.append({
            'name': name,
            'is_current': name == current_branch,
            'upstream': upstream or None,
            'has_remote': has_remote,
            'ahead': ahead,
            'behind': behind,
            'commit_date': date_iso,
            'commit_age': commit_age,
            'commit_ts': commit_ts,
            'commit_subject': subject,
            'status': status,
        })

    return branches, current_branch, errors


from .resume import registrations


def audit_local_repo(path, cutoff_dt=None, now=None):
    """Fast local repository inspection without network calls."""
    now = now or datetime.now(timezone.utc)
    cutoff_ts = cutoff_dt.timestamp() if cutoff_dt else None
    path = Path(path)
    clean, dirty_files, st_errors = inspect_working_tree(path)
    branches, current_branch, b_errors = inspect_branches(path, now=now)
    repo = repo_remote(path)

    # Check if there are unpushed commits or recent commits
    has_unpushed = any(b['ahead'] > 0 for b in branches)
    has_dirty = clean is False
    has_recent = False
    if cutoff_ts:
        for b in branches:
            if b.get('commit_ts') and b['commit_ts'] >= cutoff_ts:
                has_recent = True
                break

    # Inspect all registered worktrees for working copy changes
    records, reg_err = registrations(path)
    if not records or reg_err:
        records = [{'path': str(path), 'branch': current_branch}]

    dirty_worktrees = []
    st_errors = [f'{path}: {reg_err}'] if reg_err else []
    checked_out_branches = {}

    for rec in records:
        w_path = Path(rec['path'])
        branch = rec.get('branch')
        if branch:
            checked_out_branches[branch] = w_path.name if w_path != path else '(primary)'
        if w_path.is_dir():
            clean, dirty_files, errs = inspect_working_tree(w_path)
            st_errors.extend(errs)
            if clean is False:
                dirty_worktrees.append({
                    'worktree': w_path.name if w_path != path else '(primary)',
                    'path': str(w_path),
                    'branch': branch or '(detached)',
                    'dirty_count': len(dirty_files),
                    'dirty_files': dirty_files,
                })

    # Annotate branches with worktree checkout info
    for b in branches:
        if b['name'] in checked_out_branches:
            b['is_current'] = True
            b['worktree'] = checked_out_branches[b['name']]
        else:
            b['worktree'] = None

    # Check if there are unpushed commits or recent commits
    has_unpushed = any(b['ahead'] > 0 for b in branches)
    has_dirty = len(dirty_worktrees) > 0
    has_recent = False
    if cutoff_dt:
        for b in branches:
            if b.get('commit_dt') and b['commit_dt'] >= cutoff_dt:
                has_recent = True
                break

    is_active = has_unpushed or has_dirty or has_recent
    total_dirty = sum(w['dirty_count'] for w in dirty_worktrees)

    return {
        'path': str(path),
        'name': path.name,
        'repo': repo,
        'clean': not has_dirty,
        'dirty_count': total_dirty,
        'dirty_files': [f for w in dirty_worktrees for f in w['dirty_files']],
        'dirty_worktrees': dirty_worktrees,
        'branches': branches,
        'current_branch': current_branch,
        'checked_out_branches': checked_out_branches,
        'has_unpushed': has_unpushed,
        'has_dirty': has_dirty,
        'has_recent': has_recent,
        'is_active': is_active,
        'errors': st_errors + b_errors,
    }


def scan(root, depth=2, hours=24.0, within_hours=None, state='all', pr_limit=200,
         unpushed_only=False, all_repos=False):
    """Perform a comprehensive audit of unpushed commits, branches, and open PRs."""
    started = time.monotonic()
    now = datetime.now(timezone.utc)
    effective_hours = within_hours if within_hours is not None else hours
    cutoff_dt = (now - timedelta(hours=effective_hours)) if effective_hours is not None else None

    mode, paths, target_errors = discover_targets(root, depth)

    # Step 1: Fast local inspection of all candidate repositories
    with ThreadPoolExecutor(max_workers=16) as pool:
        local_reports = list(pool.map(lambda p: audit_local_repo(p, cutoff_dt=cutoff_dt, now=now), paths))

    # Step 2: Determine which repositories to query for GitHub Pull Requests
    if mode == 'repository' or all_repos:
        to_query = local_reports
    else:
        # In workspace mode, only query active repositories (recent commits, dirty, or unpushed branches)
        to_query = [r for r in local_reports if r['is_active']]

    # Step 3: Query GitHub open PRs for selected repositories with a GitHub remote
    repos_with_remote = [r for r in to_query if r['repo']]
    repo_to_prs = {}
    gh_errors = []

    def fetch_prs(report):
        prs, errs = github_open_prs(report['repo'], state=state, limit=pr_limit)
        return report['repo'], prs, errs

    if repos_with_remote:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for repo_name, prs, errs in pool.map(fetch_prs, repos_with_remote):
                if prs is not None:
                    repo_to_prs[repo_name] = prs
                if errs:
                    gh_errors.extend(errs)

    # Step 4: Correlate PRs with branches and synthesize reports
    all_unpushed_branches = []
    all_local_only_branches = []
    all_open_prs = []
    all_merged_prs = []
    dirty_repos = []
    repo_reports = []

    for r in local_reports:
        repo_name = r['repo']
        prs = repo_to_prs.get(repo_name, [])
        pr_by_branch = {pr.get('headRefName'): pr for pr in prs if isinstance(pr, dict)}

        # Annotate branches with PR info
        for b in r['branches']:
            matching_pr = pr_by_branch.get(b['name'])
            if matching_pr:
                b['pr'] = {
                    'number': matching_pr.get('number'),
                    'title': matching_pr.get('title'),
                    'url': matching_pr.get('url'),
                    'state': matching_pr.get('state'),
                    'is_draft': matching_pr.get('isDraft', False),
                }
            else:
                b['pr'] = None

            if b['ahead'] > 0:
                all_unpushed_branches.append({
                    'repo': repo_name or r['name'],
                    'repo_path': r['path'],
                    'branch': b['name'],
                    'is_current': b['is_current'],
                    'ahead': b['ahead'],
                    'behind': b['behind'],
                    'status': b['status'],
                    'pr': b['pr'],
                    'commit_age': b['commit_age'],
                    'commit_subject': b['commit_subject'],
                })

            if not b['has_remote']:
                all_local_only_branches.append({
                    'repo': repo_name or r['name'],
                    'repo_path': r['path'],
                    'branch': b['name'],
                    'is_current': b['is_current'],
                    'ahead': b['ahead'],
                    'status': b['status'],
                    'pr': b['pr'],
                    'commit_age': b['commit_age'],
                })

        # Annotate PRs with local branch state
        local_branch_by_name = {b['name']: b for b in r['branches']}
        for pr in prs:
            head_ref = pr.get('headRefName')
            local_b = local_branch_by_name.get(head_ref)
            pr_author = (pr.get('author') or {}).get('login', '-') if isinstance(pr.get('author'), dict) else '-'
            updated_iso = pr.get('updatedAt')
            pr_state = pr.get('state')
            pr_dict = {
                'repo': repo_name,
                'repo_path': r['path'],
                'number': pr.get('number'),
                'title': pr.get('title'),
                'branch': head_ref,
                'base': pr.get('baseRefName'),
                'url': pr.get('url'),
                'state': pr_state,
                'is_draft': pr.get('isDraft', False),
                'author': pr_author,
                'updated_at': updated_iso,
                'updated_age': age_label(parse_iso(updated_iso), now),
                'merged_at': pr.get('mergedAt'),
                'merged_age': age_label(parse_iso(pr.get('mergedAt')), now) if pr.get('mergedAt') else None,
                'local_exists': local_b is not None,
                'local_is_current': local_b['is_current'] if local_b else False,
                'local_ahead': local_b['ahead'] if local_b else None,
                'local_status': local_b['status'] if local_b else 'not checked out locally',
            }
            if pr_state == 'OPEN':
                all_open_prs.append(pr_dict)
            elif pr_state == 'MERGED':
                merged_dt = parse_iso(pr.get('mergedAt')) or parse_iso(pr.get('updatedAt'))
                if cutoff_dt is None or (merged_dt and merged_dt >= cutoff_dt):
                    all_merged_prs.append(pr_dict)

        for dw in r.get('dirty_worktrees', []):
            dirty_repos.append({
                'repo': repo_name or r['name'],
                'repo_path': dw['path'],
                'worktree': dw['worktree'],
                'current_branch': dw['branch'],
                'dirty_count': dw['dirty_count'],
                'dirty_files': dw['dirty_files'],
            })

        r['prs'] = prs
        r['open_prs'] = [p for p in prs if p.get('state') == 'OPEN']
        r['merged_prs'] = [p for p in prs if p.get('state') == 'MERGED']
        repo_reports.append(r)

    # Sort outputs: unpushed branches by ahead descending; PRs by updated descending
    all_unpushed_branches.sort(key=lambda item: (-item['ahead'], item['repo'], item['branch']))
    all_open_prs.sort(key=lambda item: item['updated_at'] or '', reverse=True)
    all_merged_prs.sort(key=lambda item: item['merged_at'] or item['updated_at'] or '', reverse=True)
    dirty_repos.sort(key=lambda item: (-item['dirty_count'], item['repo']))

    all_merged = (len(all_open_prs) == 0 and len(all_unpushed_branches) == 0 and len(dirty_repos) == 0)

    return {
        'schema': SCHEMA,
        'root': str(root),
        'mode': mode,
        'observed_at': now.isoformat(),
        'duration_seconds': round(time.monotonic() - started, 2),
        'hours': effective_hours,
        'state': state,
        'unpushed_only': unpushed_only,
        'all_repos': all_repos,
        'all_merged': all_merged,
        'scanned_repos_count': len(local_reports),
        'queried_repos_count': len(repos_with_remote),
        'total_unpushed_branches': len(all_unpushed_branches),
        'total_local_only_branches': len(all_local_only_branches),
        'total_open_prs': len(all_open_prs),
        'total_merged_prs': len(all_merged_prs),
        'total_dirty_repos': len(dirty_repos),
        'unpushed_branches': all_unpushed_branches,
        'local_only_branches': all_local_only_branches,
        'open_prs': all_open_prs,
        'merged_prs': all_merged_prs,
        'dirty_repos': dirty_repos,
        'repositories': repo_reports,
        'errors': target_errors + gh_errors,
        'notice': 'Read-only audit of local Git branches, unpushed commits, and open GitHub PRs via `gh`. '
                  'No pushes or branch modifications are performed.',
    }


def markdown(data, limit=20):
    """Render Markdown report with tables of unpushed branches, open PRs, and dirty working trees."""
    hours_info = f"within last {data['hours']:g}h" if data.get('hours') else 'all'
    if data.get('all_repos'):
        hours_info = 'all repositories (--all-repos)'

    lines = [
        '# MONAG — Pull Requests & Unpushed Branches Audit',
        '',
        f"Mode: **{data['mode']}** · repositories scanned: **{data['scanned_repos_count']}** "
        f"(GitHub queried: **{data['queried_repos_count']}**, {hours_info}) · "
        f"scan: {data['duration_seconds']} s.",
        '',
        f"Unpushed branches: **{data['total_unpushed_branches']}** · "
        f"open Pull Requests: **{data['total_open_prs']}** · "
        f"merged Pull Requests: **{data.get('total_merged_prs', 0)}** · "
        f"uncommitted working copies: **{data['total_dirty_repos']}**.",
        '',
    ]

    status_verdict = (
        '**ALL MERGED**: all observed PRs in the window are merged, branches are pushed, and worktrees are clean.'
        if data.get('all_merged')
        else f"**ACTIVE UNMERGED WORK**: {data['total_open_prs']} open PR(s), {data['total_unpushed_branches']} unpushed branch(es), {data['total_dirty_repos']} dirty repo(s)."
    )
    lines.extend([f"Merge status: {status_verdict}", ''])

    # Section 1: Branches needing push (ahead > 0)
    unpushed = data.get('unpushed_branches', [])
    if unpushed:
        lines.extend([
            '## Branches with unpushed commits',
            '',
            table(
                ['Repository', 'Branch', 'Ahead', 'Behind', 'PR Status', 'Last commit age', 'Latest commit subject'],
                [[
                    u['repo'],
                    f"*{u['branch']}*" if u['is_current'] else u['branch'],
                    f"+{u['ahead']}",
                    f"-{u['behind']}" if u['behind'] > 0 else '0',
                    f"#{u['pr']['number']} (PR)" if u['pr'] else 'No PR',
                    u['commit_age'],
                    (u['commit_subject'] or '')[:45],
                ] for u in unpushed[:limit]]
            ),
            '',
        ])
    else:
        lines.extend(['## Branches with unpushed commits', '', '_All checked branches are up to date with remote._', ''])

    # Section 2: Open Pull Requests
    prs = data.get('open_prs', [])
    if prs:
        lines.extend([
            '## Open GitHub Pull Requests',
            '',
            table(
                ['Repository', 'PR', 'Branch', 'Author', 'Draft', 'Local checkout status', 'Updated', 'Title'],
                [[
                    p['repo'],
                    f"#{p['number']}",
                    p['branch'],
                    p['author'],
                    'yes' if p['is_draft'] else 'no',
                    f"*{p['local_status']}*" if p.get('local_is_current') else p['local_status'],
                    p['updated_age'],
                    (p['title'] or '')[:45],
                ] for p in prs[:limit]]
            ),
            '',
        ])
    else:
        lines.extend(['## Open GitHub Pull Requests', '', '_No open pull requests observed in active repositories._', ''])

    # Section 3: Merged Pull Requests
    merged = data.get('merged_prs', [])
    if merged and not data.get('unpushed_only'):
        lines.extend([
            f"## Merged Pull Requests ({hours_info})",
            '',
            table(
                ['Repository', 'PR', 'Branch', 'Author', 'Merged', 'Title'],
                [[
                    m['repo'],
                    f"#{m['number']}",
                    m['branch'],
                    m['author'],
                    m['merged_age'] or '-',
                    (m['title'] or '')[:45],
                ] for m in merged[:limit]]
            ),
            '',
        ])

    # Section 3: Dirty repositories
    dirty = data.get('dirty_repos', [])
    if dirty:
        lines.extend([
            '## Repositories with uncommitted changes',
            '',
            table(
                ['Repository', 'Branch', 'Uncommitted files', 'Modified sample'],
                [[
                    d['repo'],
                    d['current_branch'] or '(detached)',
                    f"{d['dirty_count']} file{'s' if d['dirty_count'] != 1 else ''}",
                    ', '.join(d['dirty_files'][:3]) + (f' (+{d["dirty_count"] - 3} more)' if d['dirty_count'] > 3 else ''),
                ] for d in dirty[:limit]]
            ),
            '',
        ])

    # Section 4: Errors if any
    errors = data.get('errors', [])
    if errors:
        lines.extend([
            '## Read errors',
            '',
            table(['Error'], [[err] for err in errors[:limit]]),
            '',
        ])

    lines.extend([
        data.get('notice', ''),
        '',
        'Full JSON data: `monag --json prs` or `monag prs --all-repos`.',
    ])

    return '\n'.join(lines) + '\n'


class BrowserCDPMerger:
    """Lightweight RFC 6455 WebSocket client to merge PRs via active Chromium session."""

    def __init__(self, port: int = 9222):
        self.port = port

    def is_available(self) -> bool:
        try:
            req = urllib.request.urlopen(f'http://127.0.0.1:{self.port}/json/version', timeout=1.5)
            data = json.loads(req.read().decode('utf-8'))
            return 'webSocketDebuggerUrl' in data or 'Browser' in data
        except Exception:
            return False

    def _get_page_targets(self) -> List[Dict[str, Any]]:
        try:
            req = urllib.request.urlopen(f'http://127.0.0.1:{self.port}/json', timeout=4)
            targets = json.loads(req.read().decode('utf-8'))
            return [t for t in targets if t.get('type') == 'page']
        except Exception:
            return []

    def _send_cmd(self, path: str, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 12.0) -> Any:
        s = socket.create_connection(('127.0.0.1', self.port), timeout=timeout)
        s.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        s.sendall(
            f'GET {path} HTTP/1.1\r\n'
            f'Host: 127.0.0.1:{self.port}\r\n'
            f'Upgrade: websocket\r\n'
            f'Connection: Upgrade\r\n'
            f'Sec-WebSocket-Key: {key}\r\n'
            f'Sec-WebSocket-Version: 13\r\n\r\n'.encode()
        )
        buf = b''
        while b'\r\n\r\n' not in buf:
            chunk = s.recv(1024)
            if not chunk:
                s.close()
                return None
            buf += chunk

        req_id = 1
        body = {'id': req_id, 'method': method}
        if params:
            body['params'] = params
        msg = json.dumps(body).encode('utf-8')
        mask = os.urandom(4)
        l = len(msg)

        if l < 126:
            h = bytearray([0x81, 0x80 | l])
        elif l < 65536:
            h = bytearray([0x81, 0x80 | 126] + list(struct.pack('!H', l)))
        else:
            h = bytearray([0x81, 0x80 | 127] + list(struct.pack('!Q', l)))
        h.extend(mask)
        h.extend(bytearray(b ^ mask[i % 4] for i, b in enumerate(msg)))
        s.sendall(h)

        deadline = time.time() + timeout
        val = None
        while time.time() < deadline:
            hdr = s.recv(2)
            if not hdr or len(hdr) < 2:
                break
            plen = hdr[1] & 0x7F
            if plen == 126:
                plen = struct.unpack('!H', s.recv(2))[0]
            elif plen == 127:
                plen = struct.unpack('!Q', s.recv(8))[0]
            mb = s.recv(4) if bool(hdr[1] & 0x80) else b''
            payload = b''
            while len(payload) < plen:
                chunk = s.recv(plen - len(payload))
                if not chunk:
                    break
                payload += chunk
            if mb:
                payload = bytes(b ^ mb[i % 4] for i, b in enumerate(payload))
            try:
                data = json.loads(payload.decode('utf-8'))
                if data.get('id') == req_id:
                    val = data.get('result')
                    break
            except Exception:
                pass
        s.close()
        return val

    def eval(self, path: str, expr: str, timeout: float = 12.0) -> Any:
        res = self._send_cmd(path, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True}, timeout=timeout)
        if not res:
            return None
        return res.get('result', {}).get('value')

    def navigate(self, path: str, url: str) -> None:
        self._send_cmd(path, 'Page.navigate', {'url': url})

    def merge_pr_page(self, pr_url: str, method: str = 'squash', admin_bypass: bool = True) -> Dict[str, Any]:
        targets = self._get_page_targets()
        if not targets:
            return {'ok': False, 'status': 'NO_BROWSER_TABS', 'error': 'No active browser tabs found on CDP port'}

        target = next((t for t in targets if 'github.com' in t.get('url', '')), None)
        if not target:
            target = next((t for t in targets if not t.get('url', '').startswith('chrome://')), targets[0])

        ws_url = target.get('webSocketDebuggerUrl', '')
        path = urllib.parse.urlparse(ws_url).path

        self.navigate(path, pr_url)

        # Wait for page & merge box to load
        for _ in range(8):
            time.sleep(1.0)
            loaded = self.eval(path, """(() => {
                const b = document.body ? document.body.innerText : '';
                if (b.includes('Loading merge status') || b.includes('Checking mergeability')) return false;
                if (document.querySelector('[data-testid=\"mergebox-border-container\"]') || document.querySelector('.branch-action-item')) return true;
                if (document.querySelector('.State--purple, .State--red')) return true;
                return false;
            })()""")
            if loaded:
                break

        # Check existing state
        state = self.eval(path, """(() => {
            const body = document.body ? document.body.innerText : '';
            const isMerged = !!document.querySelector('.State--purple, [title*=\"Status: Merged\"], [aria-label*=\"Status: Merged\"]') || body.includes('Pull request successfully merged and closed');
            const isClosed = !isMerged && (!!document.querySelector('.State--red, [title*=\"Status: Closed\"], [aria-label*=\"Status: Closed\"]') || body.includes('closed this in'));
            const hasConflicts = body.includes('This branch has conflicts that must be resolved') || body.includes('Conflicts must be resolved');
            return {isMerged, isClosed, hasConflicts};
        })()""")

        if not state:
            return {'ok': False, 'status': 'EVAL_FAILED', 'error': 'Could not read DOM from browser'}

        if state.get('isMerged'):
            return {'ok': True, 'status': 'ALREADY_MERGED', 'message': 'Pull request is already merged'}

        if state.get('isClosed'):
            return {'ok': False, 'status': 'ALREADY_CLOSED', 'error': 'Pull request is closed'}

        if state.get('hasConflicts'):
            return {'ok': False, 'status': 'CONFLICTING', 'error': 'This branch has conflicts that must be resolved'}

        # Update branch if out of date
        self.eval(path, """(() => {
            const btn = Array.from(document.querySelectorAll('button')).find(b => b.innerText && b.innerText.trim() === 'Update branch' && !b.disabled);
            if (btn) btn.click();
        })()""")
        time.sleep(2.0)

        # Bypass rules if needed and available
        if admin_bypass:
            self.eval(path, """(() => {
                const lbl = Array.from(document.querySelectorAll('label')).find(l => l.innerText && l.innerText.includes('bypass rules'));
                if (!lbl) return;
                const forId = lbl.getAttribute('for');
                const cb = forId ? document.getElementById(forId) : lbl.querySelector('input');
                if (cb && !cb.checked) cb.click();
            })()""")
            time.sleep(1.0)

        # Click merge button
        merge_label = 'Squash and merge' if method == 'squash' else ('Rebase and merge' if method == 'rebase' else 'Merge pull request')
        clicked_btn = self.eval(path, f"""(() => {{
            const btns = Array.from(document.querySelectorAll('button, input[type=submit]'));
            const bypassBtn = btns.find(b => b.innerText && b.innerText.includes('Bypass rules and merge') && !b.disabled);
            if (bypassBtn) {{ bypassBtn.click(); return 'Bypass rules and merge'; }}
            const targetBtn = btns.find(b => b.innerText && b.innerText.includes('{merge_label}') && !b.disabled);
            if (targetBtn) {{ targetBtn.click(); return '{merge_label}'; }}
            const anyMerge = btns.find(b => /merge pull request|squash and merge|rebase and merge/i.test(b.innerText || b.value) && !b.disabled);
            if (anyMerge) {{ anyMerge.click(); return anyMerge.innerText.trim(); }}
            return null;
        }})()""")

        time.sleep(1.5)

        # Confirm merge
        confirmed = self.eval(path, """(() => {
            const btns = Array.from(document.querySelectorAll('button, input[type=submit]'));
            const confirmBtn = btns.find(b => b.innerText && b.innerText.toLowerCase().includes('confirm') && !b.disabled);
            if (confirmBtn) {
                confirmBtn.click();
                return confirmBtn.innerText.trim();
            }
            return null;
        })()""")

        time.sleep(3.5)

        # Verify final merge state
        final_state = self.eval(path, """(() => {
            const body = document.body ? document.body.innerText : '';
            return !!document.querySelector('.State--purple, [title*=\"Status: Merged\"], [aria-label*=\"Status: Merged\"]') || body.includes('Pull request successfully merged and closed');
        })()""")

        if final_state:
            return {'ok': True, 'status': 'MERGED', 'method': method, 'button': clicked_btn}

        return {'ok': False, 'status': 'FAILED', 'error': 'Merge confirmation did not transition to Merged'}


def merge_via_browser_cdp(pr_url: str, method: str = 'squash', admin_bypass: bool = True, cdp_port: int = 9222) -> Dict[str, Any]:
    merger = BrowserCDPMerger(port=cdp_port)
    if not merger.is_available():
        return {'ok': False, 'status': 'CDP_UNAVAILABLE', 'error': f'Chromium CDP endpoint not reachable at 127.0.0.1:{cdp_port}'}
    return merger.merge_pr_page(pr_url, method=method, admin_bypass=admin_bypass)


def merge_pull_request(pr_url_or_number: Any, repo: Optional[str] = None, method: str = 'squash',
                       admin_bypass: bool = True, use_browser: bool = False, cdp_port: int = 9222) -> Dict[str, Any]:
    """Merge a GitHub Pull Request using gh CLI with automated fallback to Browser CDP."""
    target_str = str(pr_url_or_number).strip()
    pr_url = ''
    pr_number = None

    url_match = re.search(r'https?://github\.com/([a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-]+)/pull/(\d+)', target_str)
    if url_match:
        repo = url_match.group(1)
        pr_number = int(url_match.group(2))
        pr_url = target_str
    elif '#' in target_str:
        parts = target_str.split('#', 1)
        repo = parts[0].strip()
        pr_number = int(parts[1].strip())
        pr_url = f'https://github.com/{repo}/pull/{pr_number}'
    elif target_str.isdigit():
        pr_number = int(target_str)
        if not repo:
            repo = repo_remote('.')
        if not repo:
            return {'ok': False, 'status': 'NO_REPO', 'error': 'Could not detect GitHub repository for PR number'}
        pr_url = f'https://github.com/{repo}/pull/{pr_number}'
    else:
        return {'ok': False, 'status': 'INVALID_TARGET', 'error': f'Unrecognized PR target: {pr_url_or_number}'}

    record = {
        'repo': repo,
        'number': pr_number,
        'url': pr_url,
        'method': method,
    }

    # If browser is not forced, try gh pr merge first
    if not use_browser:
        cmd = ['gh', 'pr', 'merge', str(pr_number), '--repo', repo, f'--{method}']
        if admin_bypass:
            cmd.append('--admin')
        out, err = command(cmd, timeout=30)
        if not err and ('merged' in (out or '').lower() or 'already' in (out or '').lower()):
            record.update(ok=True, status='MERGED', via='gh', output=out)
            return record
        # Check if error was rate limit or permission that can be handled via browser
        err_lower = (err or '').lower()
        if 'conflict' in err_lower:
            record.update(ok=False, status='CONFLICTING', via='gh', error=err)
            return record

    # Browser CDP fallback or forced browser mode
    b_res = merge_via_browser_cdp(pr_url, method=method, admin_bypass=admin_bypass, cdp_port=cdp_port)
    record.update(b_res)
    record['via'] = 'browser_cdp'
    return record


def merge_open_prs(open_prs: List[Dict[str, Any]], method: str = 'squash', admin_bypass: bool = True,
                   use_browser: bool = False, cdp_port: int = 9222) -> List[Dict[str, Any]]:
    """Merge a list of open PR dictionaries."""
    results = []
    for pr in open_prs:
        url = pr.get('url') or f"https://github.com/{pr.get('repo')}/pull/{pr.get('number')}"
        res = merge_pull_request(url, repo=pr.get('repo'), method=method,
                                admin_bypass=admin_bypass, use_browser=use_browser, cdp_port=cdp_port)
        results.append(res)
    return results


def merge_result_markdown(results: List[Dict[str, Any]]) -> str:
    """Format PR merge execution results into a clean markdown table."""
    lines = ['# MONAG: Pull Request Merge Report', '']
    if not results:
        lines.append('_No Pull Requests processed._\n')
        return '\n'.join(lines)

    rows = []
    for r in results:
        status = r.get('status', 'UNKNOWN')
        icon = '✅' if r.get('ok') else ('⚠️' if status == 'CONFLICTING' else '❌')
        repo_str = r.get('repo', '-')
        pr_str = f"#{r.get('number')}" if r.get('number') else '-'
        via_str = r.get('via', '-')
        msg = r.get('error') or r.get('message') or r.get('status') or 'Success'
        rows.append([icon, repo_str, pr_str, status, via_str, msg[:50]])

    lines.extend([
        table(['', 'Repository', 'PR', 'Status', 'Via', 'Details'], rows),
        '',
    ])
    return '\n'.join(lines) + '\n'

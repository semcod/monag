"""Read-only audit of local Planfile ticket coverage against GitHub Issues.

For one repository (`--root` is a Git checkout) this reports how many of its
GitHub Issues have a corresponding Planfile ticket, which tickets have none,
and whether a ticket's own GitHub mapping agrees with the repository-wide
sync index (`.planfile/sync/github.state.yaml`). When `--root` is a workspace
of several repositories (not itself a checkout, e.g. the default `~/github`),
the same audit runs for every discovered repository with a GitHub remote.

Confirmed GitHub forks are ignored because their Issues are not part of the
canonical repository's coverage. A failed fork-metadata lookup is reported as
an explicit unknown and never silently treated as "zero".
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time

import yaml

from .monitor import command, github_repo
from .presentation import table
from .resume import planfile as read_planfile, registrations, roots as discover_roots

SCHEMA = 'monag.audit/v1'


def sync_index(path):
    """The repository-wide Planfile-to-GitHub mapping, if one is recorded."""
    file = Path(path) / '.planfile' / 'sync' / 'github.state.yaml'
    if not file.is_file():
        return {}, None, None
    try:
        if file.stat().st_size > 2_000_000:
            raise ValueError('file exceeds 2 MB read limit')
        data = yaml.load(file.read_text(), Loader=getattr(yaml, 'CSafeLoader', yaml.SafeLoader))
        mapping = data.get('ticket_map') if isinstance(data, dict) else None
        if not isinstance(mapping, dict):
            raise ValueError('expected a ticket_map mapping')
        return ({str(k): str(v) for k, v in mapping.items() if v is not None},
                str(file), None)
    except (OSError, ValueError, TypeError, yaml.YAMLError, RecursionError) as error:
        return {}, str(file), f'{file}: {type(error).__name__}'


def repo_remote(path):
    remote, _ = command(['git', 'config', '--get', 'remote.origin.url'], path)
    return github_repo(remote) if remote else None


def github_repo_is_fork(repo):
    """Return GitHub's fork flag before making any Issue request.

    ``None`` means the repository metadata could not be trusted. Callers must
    then leave Issue coverage unknown rather than querying an unclassified
    repository.
    """
    out, error = command(['gh', 'repo', 'view', repo, '--json', 'isFork'], timeout=20)
    if error:
        return None, [f'{repo}: {error}']
    try:
        data = json.loads(out)
        if not isinstance(data, dict) or not isinstance(data.get('isFork'), bool):
            raise ValueError('expected a boolean isFork field')
        return data['isFork'], []
    except (ValueError, TypeError):
        return None, [f'{repo}: invalid gh repository metadata JSON']


def github_issues(repo, limit=200):
    """All GitHub Issues (open and closed) for a repository, via `gh`."""
    out, error = command(['gh', 'issue', 'list', '--repo', repo, '--state', 'all',
                          '--limit', str(limit), '--json',
                          'number,title,state,url,createdAt,updatedAt,closedAt,labels,author'],
                         timeout=20)
    if error:
        return None, [f'{repo}: {error}']
    try:
        issues = json.loads(out)
        if not isinstance(issues, list):
            raise ValueError('expected a JSON array')
        return issues, []
    except (ValueError, TypeError):
        return None, [f'{repo}: invalid gh JSON']


def github_prs(repo, limit=200):
    """All pull requests for a repository, via `gh`.

    Tickets frequently map to a pull request number, and Issues and PRs share
    one number space; without PR data a ticket mapped to a real PR would be
    misreported as an orphan.
    """
    out, error = command(['gh', 'pr', 'list', '--repo', repo, '--state', 'all',
                          '--limit', str(limit), '--json',
                          'number,title,state,url,createdAt,updatedAt,closedAt,mergedAt,'
                          'labels,author'], timeout=20)
    if error:
        return None, [f'{repo}: {error}']
    try:
        issues = json.loads(out)
        if not isinstance(issues, list):
            raise ValueError('expected a JSON array')
        return issues, []
    except (ValueError, TypeError):
        return None, [f'{repo}: invalid gh JSON']


def parse_iso(value):
    """GitHub's ISO-8601 timestamp as an aware datetime, or None when unusable."""
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def age_label(moment, now):
    """Compact 'in X'/'X ago' age for a table cell."""
    seconds = int((now - moment).total_seconds())
    label = f'{-seconds}s ago' if seconds < 0 else None
    if label is None:
        days, seconds = divmod(seconds, 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes, _ = divmod(seconds, 60)
        label = (f'{days}d{hours}h' if days else f'{hours}h{minutes}m' if hours
                 else f'{minutes}m' if minutes else f'{seconds}s') + ' ago'
    return label


def change_type(item, kind, cutoff):
    """Dominant event inside the window: opened/closed/merged, else updated."""
    merged = parse_iso(item.get('mergedAt'))
    if kind == 'pr' and merged and merged >= cutoff:
        return 'merged'
    closed = parse_iso(item.get('closedAt'))
    if closed and closed >= cutoff:
        return 'merged' if kind == 'pr' and item.get('state') == 'MERGED' else 'closed'
    created = parse_iso(item.get('createdAt'))
    if created and created >= cutoff:
        return 'opened'
    return 'updated'


def labels_label(item):
    labels = item.get('labels')
    if not isinstance(labels, list):
        return '-'
    names = [item['name'] for item in labels if isinstance(item, dict) and item.get('name')]
    return ','.join(names) if names else '-'


def audit_repo(path, issue_limit=200, recent_hours=None, now=None):
    """One repository's coverage report; never raises, errors are data."""
    path = Path(path)
    repo = repo_remote(path)
    is_fork, metadata_errors = (None, []) if repo is None else github_repo_is_fork(repo)
    if is_fork is True:
        return {
            'path': str(path), 'repo': repo, 'is_fork': True,
            'ignored': True, 'ignored_reason': 'github-fork',
            'planfile_available': False, 'planfile_sources': [], 'planfile_errors': [],
            'tickets': [], 'ticket_count': 0, 'mapped_ticket_count': 0,
            'sync_index_source': None, 'sync_index_error': None,
            'github_fetched': False, 'github_errors': [], 'github_issue_count': None,
            'github_open': None, 'github_closed': None, 'github_pr_count': None,
            'github_pr_open': None, 'github_pr_merged': None, 'github_pr_closed': None,
            'open_prs': [],
            'recent_issues': [],
            'recent_ops': [], 'untracked_issues': [], 'orphan_tickets': [],
            'pr_tickets': [], 'sync_drift': [],
        }

    tickets, planfile_sources, planfile_errors = read_planfile(path)
    index, index_source, index_error = sync_index(path)
    issues, github_errors = ((None, metadata_errors) if repo is not None and is_fork is None
                             else ((None, []) if repo is None else github_issues(repo, issue_limit)))
    prs, pr_errors = ((None, metadata_errors) if repo is not None and is_fork is None
                      else ((None, []) if repo is None else github_prs(repo, issue_limit)))
    github_errors = github_errors + pr_errors
    fetched = repo is not None and not github_errors
    pr_fetched = prs is not None
    issues = issues or []
    prs = prs or []
    issue_by_number = {str(item['number']): item for item in issues
                       if isinstance(item, dict) and 'number' in item}
    pr_by_number = {str(item['number']): item for item in prs
                    if isinstance(item, dict) and 'number' in item}
    mapped = {t['id']: t['github'] for t in tickets if t.get('github')}
    tracked_numbers = set(mapped.values())
    untracked_issues = ([item for item in issues
                         if str(item.get('number')) not in tracked_numbers] if fetched else [])
    # A ticket mapped to a pull request is tracked, not orphaned; PR numbers
    # share the Issue number space but `gh issue list` never returns them.
    pr_tickets = ([{'id': ticket_id, 'github': issue_id,
                    'pr_state': pr_by_number[issue_id].get('state', '')}
                   for ticket_id, issue_id in sorted(mapped.items())
                   if issue_id in pr_by_number] if pr_fetched else [])
    orphan_tickets = ([{'id': ticket_id, 'github': issue_id} for ticket_id, issue_id in mapped.items()
                       if issue_id not in issue_by_number
                       and issue_id not in pr_by_number] if fetched else [])
    # Meaningful only once a sync index file exists: its absence is a different,
    # unrelated fact from an existing index missing one ticket's entry.
    sync_drift = ([{'id': ticket_id, 'github': issue_id, 'in_sync_index': index.get(ticket_id) == issue_id}
                  for ticket_id, issue_id in sorted(mapped.items()) if index.get(ticket_id) != issue_id]
                 if index_source is not None else [])
    if fetched and recent_hours is not None:
        cutoff = (now or datetime.now(timezone.utc)) - timedelta(hours=recent_hours)
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        recent_issues = sorted(
            (item for item in issues
             if (parse_iso(item.get('updatedAt')) or epoch) >= cutoff),
            key=lambda item: item.get('updatedAt') or '', reverse=True)
        recent_ops = sorted(
            ({'kind': kind, 'change': change_type(item, kind, cutoff),
              'number': item.get('number'), 'state': item.get('state', ''),
              'title': item.get('title', ''), 'updatedAt': item.get('updatedAt'),
              'actor': (item.get('author') or {}).get('login', '-'),
              'labels': labels_label(item)}
             for kind, items in (('issue', issues), ('pr', prs)) for item in items
             if (parse_iso(item.get('updatedAt')) or epoch) >= cutoff),
            key=lambda op: op.get('updatedAt') or '', reverse=True)
    else:
        recent_issues = []
        recent_ops = []
    open_prs = [p for p in prs if p.get('state') == 'OPEN'] if pr_fetched else []
    merged_prs = [p for p in prs if p.get('state') == 'MERGED'] if pr_fetched else []
    closed_prs = [p for p in prs if p.get('state') == 'CLOSED' and not p.get('mergedAt')] if pr_fetched else []
    return {
        'path': str(path), 'repo': repo, 'is_fork': False if repo is not None and is_fork is False else None,
        'ignored': False, 'ignored_reason': None,
        'planfile_available': bool(planfile_sources),
        'planfile_sources': planfile_sources, 'planfile_errors': planfile_errors,
        'tickets': tickets, 'ticket_count': len(tickets), 'mapped_ticket_count': len(mapped),
        'sync_index_source': index_source, 'sync_index_error': index_error,
        'github_fetched': fetched, 'github_errors': github_errors,
        'github_issue_count': len(issues) if fetched else None,
        'github_open': sum(1 for i in issues if i.get('state') == 'OPEN') if fetched else None,
        'github_closed': sum(1 for i in issues if i.get('state') == 'CLOSED') if fetched else None,
        'github_pr_count': len(prs) if pr_fetched else None,
        'github_pr_open': len(open_prs) if pr_fetched else None,
        'github_pr_merged': len(merged_prs) if pr_fetched else None,
        'github_pr_closed': len(closed_prs) if pr_fetched else None,
        'open_prs': [{'number': p.get('number'), 'title': p.get('title', ''),
                      'url': p.get('url', ''), 'author': (p.get('author') or {}).get('login', '-'),
                      'updatedAt': p.get('updatedAt')} for p in open_prs] if pr_fetched else [],
        'recent_issues': recent_issues,
        'recent_ops': recent_ops,
        'untracked_issues': untracked_issues, 'orphan_tickets': orphan_tickets,
        'pr_tickets': pr_tickets, 'sync_drift': sync_drift,
    }


def targets(root, depth):
    """(mode, [primary checkout paths]) — one repository, or every one under root."""
    root = Path(root)
    if (root / '.git').exists():
        records, error = registrations(root)
        primary = Path(records[0]['path']) if records and not error else root
        return 'repository', [primary], ([f'{root}: {error}'] if error else [])
    found, seen, errors = [], set(), []
    for candidate in discover_roots(root, depth):
        records, error = registrations(candidate)
        if error or not records:
            errors.append(f'{candidate}: {error or "no worktree records"}')
            continue
        primary = Path(records[0]['path'])
        if str(primary) in seen:
            continue
        seen.add(str(primary))
        found.append(primary)
    return 'workspace', found, errors


def audit_worktree(record, repo_name, primary_path, cutoff_ts, now):
    path = Path(record['path'])
    name = path.name
    is_primary = (path.resolve() == primary_path.resolve())
    if not path.is_dir():
        return {
            'repo': repo_name, 'repo_path': str(primary_path),
            'path': str(path), 'name': name,
            'is_primary': is_primary, 'is_linked': not is_primary,
            'branch': record.get('branch', '(missing)'),
            'head': record.get('head', '')[:8] if record.get('head') else None,
            'commit_time': None, 'commit_age': '-', 'commit_subject': '',
            'commit_ts': None, 'clean': None, 'dirty_count': 0, 'dirty_files': [],
            'recent': False, 'exists': False,
            'errors': [f'{path}: directory does not exist'],
        }
    out, log_err = command(['git', 'log', '-1', '--format=%H%x00%cI%x00%ct%x00%s'], path)
    if log_err or not out.strip():
        head, commit_iso, commit_ts, subject = None, None, None, ''
    else:
        parts = out.strip('\n').split('\0')
        head = parts[0][:8] if len(parts) > 0 and parts[0] else None
        commit_iso = parts[1] if len(parts) > 1 else None
        try:
            commit_ts = float(parts[2]) if len(parts) > 2 and parts[2] else None
        except ValueError:
            commit_ts = None
        subject = parts[3] if len(parts) > 3 else ''
    dt = parse_iso(commit_iso) if commit_iso else None
    commit_age = age_label(dt, now) if dt else '-'
    recent = (commit_ts is not None and commit_ts >= cutoff_ts)
    branch = record.get('branch') or ''
    if not branch or branch == '(detached)':
        b_out, _ = command(['git', 'branch', '--show-current'], path)
        branch = b_out.strip() or record.get('branch', '(detached)')
    st_out, st_err = command(['git', 'status', '--porcelain=v1'], path)
    dirty_files = [line.strip() for line in st_out.splitlines() if line.strip()]
    clean = (len(dirty_files) == 0) if not st_err else None
    errors = []
    if log_err:
        errors.append(f'{path}: git log failed: {log_err}')
    if st_err:
        errors.append(f'{path}: git status failed: {st_err}')
    return {
        'repo': repo_name, 'repo_path': str(primary_path),
        'path': str(path), 'name': name,
        'is_primary': is_primary, 'is_linked': not is_primary,
        'branch': branch, 'head': head,
        'commit_time': commit_iso, 'commit_age': commit_age,
        'commit_subject': subject, 'commit_ts': commit_ts,
        'clean': clean, 'dirty_count': len(dirty_files),
        'dirty_files': dirty_files, 'recent': recent,
        'exists': True, 'errors': errors,
    }


def collect_worktrees(target_paths, hours=10.0, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff_ts = (now - timedelta(hours=hours)).timestamp()
    errors = []
    repos_with_wt = 0
    single_repo = len(target_paths) == 1

    tasks = []
    for primary in target_paths:
        primary = Path(primary)
        records, err = registrations(primary)
        if err:
            errors.append(f'{primary}: {err}')
            continue
        if not records:
            continue
        has_linked = len(records) > 1
        if single_repo or has_linked:
            if has_linked:
                repos_with_wt += 1
            elif single_repo:
                repos_with_wt = 1
            repo_name = repo_remote(primary) or primary.name
            for r in records:
                tasks.append((r, repo_name, primary, cutoff_ts, now))

    with ThreadPoolExecutor(max_workers=16) as pool:
        worktrees = list(pool.map(lambda t: audit_worktree(*t), tasks))

    # Sort: uncommitted first, then recent first, then newest commit timestamp
    worktrees.sort(key=lambda w: (
        w['clean'] is not False,
        not w['recent'],
        -(w['commit_ts'] or 0)
    ))

    recent_worktrees = [w for w in worktrees if w['recent']]
    clean_worktrees = [w for w in worktrees if w['clean'] is True]
    dirty_worktrees = [w for w in worktrees if w['clean'] is False]

    return {
        'worktrees': worktrees,
        'repos_with_worktrees': repos_with_wt,
        'recent_worktrees': recent_worktrees,
        'clean_worktrees': clean_worktrees,
        'dirty_worktrees': dirty_worktrees,
        'errors': errors,
    }


def scan(root, depth=2, issue_limit=200, recent_hours=None, worktrees_hours=10.0,
         worktrees_only=False):
    started = time.monotonic()
    now = datetime.now(timezone.utc)
    mode, paths, errors = targets(root, depth)
    wt_summary = collect_worktrees(paths, hours=worktrees_hours, now=now)

    if worktrees_only:
        return {
            'schema': SCHEMA, 'root': str(root), 'mode': mode,
            'worktrees_only': True,
            'observed_at': now.isoformat(),
            'duration_seconds': round(time.monotonic() - started, 2),
            'worktrees_hours': worktrees_hours,
            'repos_with_worktrees': wt_summary['repos_with_worktrees'],
            'total_worktrees': len(wt_summary['worktrees']),
            'recent_worktree_count': len(wt_summary['recent_worktrees']),
            'clean_worktree_count': len(wt_summary['clean_worktrees']),
            'dirty_worktree_count': len(wt_summary['dirty_worktrees']),
            'worktrees': wt_summary['worktrees'],
            'errors': errors + wt_summary['errors'],
            'notice': 'Read-only audit of local Git worktrees; no network calls. '
                      f'Shows recent commit activity (last {worktrees_hours:g} h) '
                      'and clean/uncommitted status in repositories with worktrees.',
        }

    with ThreadPoolExecutor(max_workers=8) as pool:
        reports = list(pool.map(lambda p: audit_repo(p, issue_limit, recent_hours, now), paths))
    ignored_forks = [r for r in reports if r.get('ignored_reason') == 'github-fork']
    repositories = [r for r in reports if not r.get('ignored')]
    repositories.sort(key=lambda r: (-len(r['untracked_issues']), -len(r['sync_drift']),
                                     -len(r['orphan_tickets']), r['path']))
    return {
        'schema': SCHEMA, 'root': str(root), 'mode': mode,
        'worktrees_only': False,
        'observed_at': now.isoformat(),
        'duration_seconds': round(time.monotonic() - started, 2),
        'repositories': repositories, 'repository_count': len(repositories),
        'ignored_fork_count': len(ignored_forks),
        'ignored_forks': [{'path': r['path'], 'repo': r['repo']} for r in ignored_forks],
        'repositories_with_github': sum(1 for r in repositories if r['repo']),
        'repositories_with_planfile': sum(1 for r in repositories if r['planfile_available']),
        'total_github_issues': sum(r['github_issue_count'] or 0 for r in repositories),
        'total_github_prs': sum(r['github_pr_count'] or 0 for r in repositories),
        'total_github_prs_open': sum(r['github_pr_open'] or 0 for r in repositories),
        'total_github_prs_merged': sum(r['github_pr_merged'] or 0 for r in repositories),
        'total_github_prs_closed': sum(r['github_pr_closed'] or 0 for r in repositories),
        'total_planfile_tickets': sum(r['ticket_count'] for r in repositories),
        'total_untracked_issues': sum(len(r['untracked_issues']) for r in repositories),
        'total_sync_drift': sum(len(r['sync_drift']) for r in repositories),
        'total_pr_tickets': sum(len(r['pr_tickets']) for r in repositories),
        'recent_hours': recent_hours,
        'total_recent_ops': (sum(len(r['recent_ops']) for r in repositories)
                             if recent_hours is not None else None),
        'worktrees_hours': worktrees_hours,
        'repos_with_worktrees': wt_summary['repos_with_worktrees'],
        'total_worktrees': len(wt_summary['worktrees']),
        'recent_worktree_count': len(wt_summary['recent_worktrees']),
        'clean_worktree_count': len(wt_summary['clean_worktrees']),
        'dirty_worktree_count': len(wt_summary['dirty_worktrees']),
        'worktrees': wt_summary['worktrees'],
        'errors': errors + wt_summary['errors'],
        'notice': 'Read-only comparison of local Planfile tickets against GitHub Issues via `gh`; '
                  'no writes to either. A missing GitHub remote or failed `gh` call leaves that '
                  'repository\'s issue counts unset (shown as "-"), never zero. Sync-index drift '
                  'compares a ticket\'s own mapping against .planfile/sync/github.state.yaml; a '
                  'missing global entry does not mean the ticket itself is wrong.',
    }


def markdown(data, limit=12):
    if data.get('worktrees_only'):
        hours = data.get('worktrees_hours', 10.0)
        lines = ['# MONAG — Worktrees activity audit', '',
                 f"Mode: **{data['mode']}** · repositories with worktrees: **{data['repos_with_worktrees']}** · "
                 f"total worktrees: **{data['total_worktrees']}** · scan: {data['duration_seconds']} s.", '',
                 f"Recent commits (last {hours:g} h): **{data['recent_worktree_count']}** · "
                 f"clean: **{data['clean_worktree_count']}** · "
                 f"uncommitted changes: **{data['dirty_worktree_count']}**.", '']
        dirty_wts = [w for w in data['worktrees'] if w['clean'] is False]
        recent_wts = [w for w in data['worktrees'] if w['recent']]
        if dirty_wts:
            lines.extend(['## Worktrees with uncommitted changes', '',
                          table(['Repository', 'Worktree', 'Branch', 'Uncommitted', 'Last commit age'],
                                [[w['repo'], w['name'] + (' (primary)' if w['is_primary'] else ''),
                                  w['branch'], f"{w['dirty_count']} file{'s' if w['dirty_count'] != 1 else ''}",
                                  w['commit_age']] for w in dirty_wts[:limit]]), ''])
            lines.append('### Uncommitted files')
            for w in dirty_wts[:limit]:
                files_str = ', '.join(w['dirty_files'][:4])
                if len(w['dirty_files']) > 4:
                    files_str += f", +{len(w['dirty_files']) - 4} more"
                lines.append(f"- **{w['repo']}** (`{w['name']}`): {files_str}")
            lines.append('')
        if recent_wts:
            lines.extend([f'## Recent worktree commits (last {hours:g} h)', '',
                          table(['Repository', 'Worktree', 'Branch', 'Status', 'Commit age', 'Commit', 'Subject'],
                                [[w['repo'], w['name'] + (' (primary)' if w['is_primary'] else ''),
                                  w['branch'], 'clean' if w['clean'] else f"dirty ({w['dirty_count']})",
                                  w['commit_age'], w['head'] or '-', w['commit_subject'][:50]]
                                 for w in recent_wts[:limit]]), ''])
        shown = data['worktrees'][:limit]
        lines.extend(['## Worktrees overview', '',
                      table(['Repository', 'Worktree', 'Branch', 'Status', f'Committed <{hours:g}h', 'Commit age', 'Subject'],
                            [[w['repo'], w['name'] + (' (primary)' if w['is_primary'] else ''),
                              w['branch'], 'clean' if w['clean'] else f"dirty ({w['dirty_count']})" if w['clean'] is False else '-',
                              'yes' if w['recent'] else 'no', w['commit_age'], w['commit_subject'][:50]]
                             for w in shown]), ''])
        if data.get('errors'):
            lines.extend(['## Read errors', '',
                          table(['Error'], [[err] for err in data['errors'][:limit]]), ''])
        lines.extend([f"Worktrees shown: {min(limit, data['total_worktrees'])}/{data['total_worktrees']}.",
                      '', data['notice'], '', 'Full data and every row: `monag --json audit --worktrees-only`.'])
        return '\n'.join(lines) + '\n'

    lines = ['# MONAG — Planfile / GitHub coverage audit', '',
             f"Mode: **{data['mode']}** · repositories: **{data['repository_count']}** "
             f"({data['repositories_with_github']} with a GitHub remote, "
             f"{data['repositories_with_planfile']} with a local Planfile) · scan: "
             f"{data['duration_seconds']} s. · ignored GitHub forks: "
             f"**{data['ignored_fork_count']}**", '',
             f"GitHub issues observed: **{data['total_github_issues']}** · "
             f"GitHub PRs observed: **{data.get('total_github_prs', 0)}** "
             f"({data.get('total_github_prs_open', 0)} open, {data.get('total_github_prs_merged', 0)} merged) · "
             f"Planfile tickets: **{data['total_planfile_tickets']}** · "
             f"issues with no Planfile ticket: **{data['total_untracked_issues']}** · "
             f"ticket/sync-index drift: **{data['total_sync_drift']}**.", '']
    recent_hours = data.get('recent_hours')
    now = parse_iso(data.get('observed_at')) or datetime.now(timezone.utc)
    if recent_hours is not None:
        lines.extend([f"GitHub issues+PRs updated in the last {recent_hours:g} h: "
                      f"**{data['total_recent_ops']}**", ''])
    lines.extend(['## Repositories', ''])
    shown = data['repositories'][:limit]
    lines.append(table(['Repository', 'GitHub issues', 'PRs', 'Planfile tickets', 'Mapped',
                        'Via PR', 'Untracked', 'Orphan', 'Sync drift'],
                       [[r['repo'] or r['path'],
                         r['github_issue_count'] if r['github_issue_count'] is not None else '-',
                         r['github_pr_count'] if r['github_pr_count'] is not None else '-',
                         r['ticket_count'] if r['planfile_available'] else '-',
                         r['mapped_ticket_count'], len(r['pr_tickets']),
                         len(r['untracked_issues']),
                         len(r['orphan_tickets']), len(r['sync_drift'])] for r in shown]))
    untracked_rows = [[r['repo'] or r['path'], '#' + str(issue.get('number')),
                       issue.get('state', ''), issue.get('title', '')]
                      for r in shown for issue in r['untracked_issues'][:limit]]
    lines.extend(['', '## GitHub issues with no Planfile ticket', '',
                 table(['Repository', 'Issue', 'State', 'Title'], untracked_rows[:limit])])
    all_open_prs = [
        dict(p, repo=r['repo'] or r['path'])
        for r in shown for p in r.get('open_prs', [])
    ]
    if all_open_prs:
        lines.extend(['', '## Open GitHub Pull Requests', '',
                      table(['Repository', 'PR', 'Author', 'Title'],
                            [[p['repo'], '#' + str(p['number']), p.get('author', '-'), p.get('title', '')[:60]]
                             for p in all_open_prs[:limit]])])
    if recent_hours is not None:
        recent_pairs = [(op.get('updatedAt') or '',
                         [r['repo'] or r['path'], op.get('kind', ''),
                          '#' + str(op.get('number')), op.get('change', ''),
                          op.get('state', ''),
                          age_label(parse_iso(op.get('updatedAt')) or now, now),
                          op.get('actor', '-'), op.get('labels', '-'),
                          op.get('title', '')])
                        for r in shown for op in r['recent_ops']]
        recent_pairs.sort(key=lambda pair: pair[0], reverse=True)
        lines.extend(['', f'## GitHub activity in the last {recent_hours:g} h '
                      f'(issues + pull requests)', '',
                      table(['Repository', 'Kind', 'Ref', 'Change', 'State', 'Updated',
                             'Actor', 'Type', 'Title'],
                            [row for _, row in recent_pairs[:limit]])])
    pr_rows = [[r['repo'] or r['path'], pr['id'], pr['github'], pr['pr_state']]
               for r in shown for pr in r['pr_tickets'][:limit]]
    if pr_rows:
        lines.extend(['', '## Planfile tickets mapped to a pull request (not an orphan)', '',
                      table(['Repository', 'Ticket', 'GitHub id', 'PR state'],
                            pr_rows[:limit])])
    drift_rows = [[r['repo'] or r['path'], drift['id'], drift['github'],
                  'present' if drift['in_sync_index'] else 'missing/mismatched']
                  for r in shown for drift in r['sync_drift'][:limit]]
    lines.extend(['', '## Ticket vs. sync-index drift', '',
                 table(['Repository', 'Ticket', 'GitHub id', 'Global sync index'], drift_rows[:limit])])
    orphan_rows = [[r['repo'] or r['path'], orphan['id'], orphan['github']]
                  for r in shown for orphan in r['orphan_tickets'][:limit]]
    if orphan_rows:
        lines.extend(['', '## Planfile tickets mapped to a missing GitHub issue', '',
                     table(['Repository', 'Ticket', 'GitHub id'], orphan_rows[:limit])])

    wt_hours = data.get('worktrees_hours', 10.0)
    total_wt = data.get('total_worktrees', 0)
    if total_wt:
        lines.extend(['', f'## Worktrees activity (last {wt_hours:g} h)', '',
                      f"Observed worktrees: **{total_wt}** across "
                      f"**{data.get('repos_with_worktrees', 0)}** repositories · "
                      f"recent commits (last {wt_hours:g} h): **{data.get('recent_worktree_count', 0)}** · "
                      f"clean: **{data.get('clean_worktree_count', 0)}** · "
                      f"uncommitted changes: **{data.get('dirty_worktree_count', 0)}**.", ''])
        active_wts = [w for w in data.get('worktrees', []) if w['recent'] or w['clean'] is False]
        if active_wts:
            lines.extend([table(['Repository', 'Worktree', 'Branch', 'Status', 'Commit age', 'Subject'],
                                [[w['repo'], w['name'] + (' (primary)' if w['is_primary'] else ''),
                                  w['branch'], 'clean' if w['clean'] else f"dirty ({w['dirty_count']})",
                                  w['commit_age'], w['commit_subject'][:50]]
                                 for w in active_wts[:limit]]), ''])
        dirty_wts = [w for w in data.get('worktrees', []) if w['clean'] is False]
        if dirty_wts:
            lines.append('### Worktrees with uncommitted changes')
            for w in dirty_wts[:limit]:
                files_str = ', '.join(w['dirty_files'][:3])
                if len(w['dirty_files']) > 3:
                    files_str += f", +{len(w['dirty_files']) - 3} more"
                lines.append(f"- **{w['repo']}** (`{w['name']}`): {files_str}")
            lines.append('')

    failures = (data['errors'] + [e for r in data['repositories'] for e in r['planfile_errors']] +
               [e for r in data['repositories'] for e in r['github_errors']])
    lines.extend(['', f"Read errors: {len(failures)}. Repositories shown: {min(limit, data['repository_count'])}/{data['repository_count']}."])
    if failures:
        from collections import Counter
        # Group by the trailing error kind ("{path}: {ticket}: {kind}"),
        # not by the unique ticket id embedded in each message.
        patterns = Counter(e.rsplit(':', 1)[-1].strip()[:100] for e in failures)
        lines.extend(['', '## Read errors — top patterns', '',
                      table(['Count', 'Error'],
                            [[count, pattern] for pattern, count in patterns.most_common(limit)])])
    lines.extend(['', data['notice'], '', 'Full data and every row: `monag --json audit`.'])
    return '\n'.join(lines) + '\n'

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
                          'number,title,state,url,updatedAt,labels'], timeout=20)
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
            'github_open': None, 'github_closed': None, 'recent_issues': [],
            'untracked_issues': [], 'orphan_tickets': [], 'sync_drift': [],
        }

    tickets, planfile_sources, planfile_errors = read_planfile(path)
    index, index_source, index_error = sync_index(path)
    issues, github_errors = ((None, metadata_errors) if repo is not None and is_fork is None
                             else ((None, []) if repo is None else github_issues(repo, issue_limit)))
    fetched = repo is not None and not github_errors
    issues = issues or []
    issue_by_number = {str(item['number']): item for item in issues
                       if isinstance(item, dict) and 'number' in item}
    mapped = {t['id']: t['github'] for t in tickets if t.get('github')}
    tracked_numbers = set(mapped.values())
    untracked_issues = ([item for item in issues
                         if str(item.get('number')) not in tracked_numbers] if fetched else [])
    orphan_tickets = ([{'id': ticket_id, 'github': issue_id} for ticket_id, issue_id in mapped.items()
                       if issue_id not in issue_by_number] if fetched else [])
    # Meaningful only once a sync index file exists: its absence is a different,
    # unrelated fact from an existing index missing one ticket's entry.
    sync_drift = ([{'id': ticket_id, 'github': issue_id, 'in_sync_index': index.get(ticket_id) == issue_id}
                  for ticket_id, issue_id in sorted(mapped.items()) if index.get(ticket_id) != issue_id]
                 if index_source is not None else [])
    if fetched and recent_hours is not None:
        cutoff = (now or datetime.now(timezone.utc)) - timedelta(hours=recent_hours)
        recent_issues = sorted(
            (item for item in issues
             if (parse_iso(item.get('updatedAt')) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff),
            key=lambda item: item.get('updatedAt') or '', reverse=True)
    else:
        recent_issues = []
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
        'recent_issues': recent_issues,
        'untracked_issues': untracked_issues, 'orphan_tickets': orphan_tickets,
        'sync_drift': sync_drift,
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


def scan(root, depth=2, issue_limit=200, recent_hours=None):
    started = time.monotonic()
    now = datetime.now(timezone.utc)
    mode, paths, errors = targets(root, depth)
    with ThreadPoolExecutor(max_workers=8) as pool:
        reports = list(pool.map(lambda p: audit_repo(p, issue_limit, recent_hours, now), paths))
    ignored_forks = [r for r in reports if r.get('ignored_reason') == 'github-fork']
    repositories = [r for r in reports if not r.get('ignored')]
    repositories.sort(key=lambda r: (-len(r['untracked_issues']), -len(r['sync_drift']),
                                     -len(r['orphan_tickets']), r['path']))
    return {
        'schema': SCHEMA, 'root': str(root), 'mode': mode,
        'observed_at': datetime.now(timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - started, 2),
        'repositories': repositories, 'repository_count': len(repositories),
        'ignored_fork_count': len(ignored_forks),
        'ignored_forks': [{'path': r['path'], 'repo': r['repo']} for r in ignored_forks],
        'repositories_with_github': sum(1 for r in repositories if r['repo']),
        'repositories_with_planfile': sum(1 for r in repositories if r['planfile_available']),
        'total_github_issues': sum(r['github_issue_count'] or 0 for r in repositories),
        'total_planfile_tickets': sum(r['ticket_count'] for r in repositories),
        'total_untracked_issues': sum(len(r['untracked_issues']) for r in repositories),
        'total_sync_drift': sum(len(r['sync_drift']) for r in repositories),
        'recent_hours': recent_hours,
        'total_recent_issues': (sum(len(r['recent_issues']) for r in repositories)
                                if recent_hours is not None else None),
        'errors': errors,
        'notice': 'Read-only comparison of local Planfile tickets against GitHub Issues via `gh`; '
                  'no writes to either. A missing GitHub remote or failed `gh` call leaves that '
                  'repository\'s issue counts unset (shown as "-"), never zero. Sync-index drift '
                  'compares a ticket\'s own mapping against .planfile/sync/github.state.yaml; a '
                  'missing global entry does not mean the ticket itself is wrong.',
    }


def markdown(data, limit=12):
    lines = ['# MONAG — Planfile / GitHub coverage audit', '',
             f"Mode: **{data['mode']}** · repositories: **{data['repository_count']}** "
             f"({data['repositories_with_github']} with a GitHub remote, "
             f"{data['repositories_with_planfile']} with a local Planfile) · scan: "
             f"{data['duration_seconds']} s. · ignored GitHub forks: "
             f"**{data['ignored_fork_count']}**", '',
             f"GitHub issues observed: **{data['total_github_issues']}** · "
             f"Planfile tickets: **{data['total_planfile_tickets']}** · "
             f"issues with no Planfile ticket: **{data['total_untracked_issues']}** · "
             f"ticket/sync-index drift: **{data['total_sync_drift']}**.", '']
    recent_hours = data.get('recent_hours')
    now = parse_iso(data.get('observed_at')) or datetime.now(timezone.utc)
    if recent_hours is not None:
        lines.extend([f"GitHub issues updated in the last {recent_hours:g} h: "
                      f"**{data['total_recent_issues']}**", ''])
    lines.extend(['## Repositories', ''])
    shown = data['repositories'][:limit]
    lines.append(table(['Repository', 'GitHub issues', 'Planfile tickets', 'Mapped', 'Untracked', 'Orphan', 'Sync drift'],
                       [[r['repo'] or r['path'],
                         r['github_issue_count'] if r['github_issue_count'] is not None else '-',
                         r['ticket_count'] if r['planfile_available'] else '-',
                         r['mapped_ticket_count'], len(r['untracked_issues']),
                         len(r['orphan_tickets']), len(r['sync_drift'])] for r in shown]))
    untracked_rows = [[r['repo'] or r['path'], '#' + str(issue.get('number')),
                       issue.get('state', ''), issue.get('title', '')]
                      for r in shown for issue in r['untracked_issues'][:limit]]
    lines.extend(['', '## GitHub issues with no Planfile ticket', '',
                 table(['Repository', 'Issue', 'State', 'Title'], untracked_rows[:limit])])
    if recent_hours is not None:
        recent_pairs = [(issue.get('updatedAt') or '',
                         [r['repo'] or r['path'], '#' + str(issue.get('number')),
                          issue.get('state', ''),
                          age_label(parse_iso(issue.get('updatedAt')) or now, now),
                          issue.get('title', '')])
                        for r in shown for issue in r['recent_issues']]
        recent_pairs.sort(key=lambda pair: pair[0], reverse=True)
        lines.extend(['', f'## GitHub issues updated in the last {recent_hours:g} h', '',
                      table(['Repository', 'Issue', 'State', 'Updated', 'Title'],
                            [row for _, row in recent_pairs[:limit]])])
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
    failures = (data['errors'] + [e for r in data['repositories'] for e in r['planfile_errors']] +
               [e for r in data['repositories'] for e in r['github_errors']])
    lines.extend(['', f"Read errors: {len(failures)}. Repositories shown: {min(limit, data['repository_count'])}/{data['repository_count']}.",
                 '', data['notice'], '', 'Full data and every row: `monag --json audit`.'])
    return '\n'.join(lines) + '\n'

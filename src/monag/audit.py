"""Read-only audit of local Planfile ticket coverage against GitHub Issues.

For one repository (`--root` is a Git checkout) this reports how many of its
GitHub Issues have a corresponding Planfile ticket, which tickets have none,
and whether a ticket's own GitHub mapping agrees with the repository-wide
sync index (`.planfile/sync/github.state.yaml`). When `--root` is a workspace
of several repositories (not itself a checkout, e.g. the default `~/github`),
the same audit runs for every discovered repository with a GitHub remote.

`gh` failures, a missing remote, or a repository without a local Planfile are
all reported as explicit unknowns, never silently treated as "zero".
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
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


def audit_repo(path, issue_limit=200):
    """One repository's coverage report; never raises, errors are data."""
    path = Path(path)
    tickets, planfile_sources, planfile_errors = read_planfile(path)
    index, index_source, index_error = sync_index(path)
    repo = repo_remote(path)
    issues, github_errors = (None, []) if repo is None else github_issues(repo, issue_limit)
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
    return {
        'path': str(path), 'repo': repo,
        'planfile_available': bool(planfile_sources),
        'planfile_sources': planfile_sources, 'planfile_errors': planfile_errors,
        'tickets': tickets, 'ticket_count': len(tickets), 'mapped_ticket_count': len(mapped),
        'sync_index_source': index_source, 'sync_index_error': index_error,
        'github_fetched': fetched, 'github_errors': github_errors,
        'github_issue_count': len(issues) if fetched else None,
        'github_open': sum(1 for i in issues if i.get('state') == 'OPEN') if fetched else None,
        'github_closed': sum(1 for i in issues if i.get('state') == 'CLOSED') if fetched else None,
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


def scan(root, depth=2, issue_limit=200):
    started = time.monotonic()
    mode, paths, errors = targets(root, depth)
    with ThreadPoolExecutor(max_workers=8) as pool:
        repositories = list(pool.map(lambda p: audit_repo(p, issue_limit), paths))
    repositories.sort(key=lambda r: (-len(r['untracked_issues']), -len(r['sync_drift']),
                                     -len(r['orphan_tickets']), r['path']))
    return {
        'schema': SCHEMA, 'root': str(root), 'mode': mode,
        'observed_at': datetime.now(timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - started, 2),
        'repositories': repositories, 'repository_count': len(repositories),
        'repositories_with_github': sum(1 for r in repositories if r['repo']),
        'repositories_with_planfile': sum(1 for r in repositories if r['planfile_available']),
        'total_github_issues': sum(r['github_issue_count'] or 0 for r in repositories),
        'total_planfile_tickets': sum(r['ticket_count'] for r in repositories),
        'total_untracked_issues': sum(len(r['untracked_issues']) for r in repositories),
        'total_sync_drift': sum(len(r['sync_drift']) for r in repositories),
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
             f"{data['duration_seconds']} s.", '',
             f"GitHub issues observed: **{data['total_github_issues']}** · "
             f"Planfile tickets: **{data['total_planfile_tickets']}** · "
             f"issues with no Planfile ticket: **{data['total_untracked_issues']}** · "
             f"ticket/sync-index drift: **{data['total_sync_drift']}**.", '',
             '## Repositories', '']
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

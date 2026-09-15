"""Read-only restart inventory. Local observations never authorize takeover."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shlex
import time

import yaml

from .monitor import command, inside, processes
from .presentation import table

CLOSED = {'done', 'closed', 'cancelled', 'canceled', 'completed', 'merged'}
OPEN = {'open', 'todo', 'backlog', 'planned', 'plan', 'ready', 'in_progress',
        'in-progress', 'active', 'review', 'blocked', 'pending'}


def planfile(path):
    """Read supported active YAML sources, never projections or historical copies."""
    files = [path / name for name in ('tickets.planfile.yaml', 'planfile.yaml',
             '.planfile/sprints/current.yaml', '.planfile/sprints/backlog.yaml')]
    result, errors, sources = [], [], []
    for file in files:
        if not file.is_file():
            continue
        sources.append(str(file))
        try:
            if file.stat().st_size > 5_000_000:
                raise ValueError('file exceeds 5 MB read limit')
            data = yaml.load(file.read_text(), Loader=getattr(yaml, 'CSafeLoader', yaml.SafeLoader))
            if not isinstance(data, dict):
                raise ValueError('expected a mapping')
            containers = [data]
            if isinstance(data.get('sprint'), dict):
                containers.append(data['sprint'])
            containers.extend(x for x in data.get('sprints', []) if isinstance(x, dict))
            for container in containers:
                tickets = container.get('tickets', container.get('tasks', {}))
                if isinstance(tickets, dict):
                    iterable = tickets.items()
                elif isinstance(tickets, list):
                    iterable = [(t.get('id'), t) for t in tickets if isinstance(t, dict)]
                else:
                    raise ValueError('unsupported ticket collection')
                for key, item in iterable:
                    if not isinstance(item, dict):
                        continue
                    identity = item.get('id') or key
                    if not identity:
                        errors.append(f'{file}: ticket without stable ID omitted')
                        continue
                    status = str(item.get('status', 'unknown')).lower()
                    result.append({'id': str(identity), 'status': status,
                                   'title': str(item.get('name', item.get('title', identity))),
                                   'source': str(file)})
        except (OSError, ValueError, TypeError, yaml.YAMLError, RecursionError) as error:
            errors.append(f'{file}: {type(error).__name__}')
    return result, sources, errors


def summarize_tickets(items):
    grouped = {}
    for item in items:
        grouped.setdefault(item['id'], []).append(item)
    pending, blocked, conflicts, unknown = [], 0, 0, 0
    for key, rows in grouped.items():
        statuses = {r['status'] for r in rows}
        conflicts += len(statuses) > 1
        unknown += bool(statuses - OPEN - CLOSED)
        if statuses & OPEN:
            pending.append(key)
            blocked += 'blocked' in statuses
    return {'known_tickets': len(grouped), 'remaining': len(pending),
            'blocked': blocked, 'conflicting_statuses': conflicts,
            'unknown_statuses': unknown, 'remaining_ids': sorted(pending)}


def roots(root, depth):
    found = []
    def visit(path, level):
        if (path / '.git').exists():
            found.append(path)
            return
        if level == depth:
            return
        try:
            children = sorted(path.iterdir())
        except OSError:
            return
        for child in children:
            if child.is_dir() and not child.is_symlink() and not child.name.startswith('.') and child.name not in {'node_modules', 'venv', 'dist', 'build'}:
                visit(child, level + 1)
    visit(root, 0)
    return found


def registrations(path):
    output, error = command(['git', 'worktree', 'list', '--porcelain', '-z'], path)
    records, current = [], {}
    for part in output.split('\0'):
        if part.startswith('worktree '):
            if current:
                records.append(current)
            current = {'path': part[9:]}
        elif part.startswith('HEAD '):
            current['head'] = part[5:]
        elif part.startswith('branch '):
            current['branch'] = part[7:].removeprefix('refs/heads/')
        elif part == 'detached':
            current['branch'] = '(detached)'
    if current:
        records.append(current)
    return records, error


def inspect_checkout(record, primary, base, agent_rows):
    path = Path(record['path'])
    row = dict(record, errors=[])
    def git(*args):
        out, error = command(['git', *args], path)
        if error:
            row['errors'].append(error)
        return out
    output = git('status', '--porcelain=v1', '-z', '--untracked-files=normal')
    fields = output.split('\0'); changed = 0; implementation_changes = 0; conflict = False
    i = 0
    while i < len(fields):
        part = fields[i]; i += 1
        if not part:
            continue
        changed += 1
        name = part[3:]
        if not name.startswith(('project/', '.subactor/', '.planfile/')) and name not in {'TODO.md'}:
            implementation_changes += 1
        conflict |= part[:2] in {'DD', 'AU', 'UD', 'UA', 'DU', 'AA', 'UU'}
        if 'R' in part[:2] or 'C' in part[:2]:
            i += 1
    row.update(changed_files=changed, conflicts=conflict, ahead=None, behind=None)
    if base and record.get('head'):
        counts = git('rev-list', '--left-right', '--count', f'{base}...{record["head"]}').split()
        if len(counts) == 2:
            row['behind'], row['ahead'] = map(int, counts)
    row['agent_pids'] = [a['pid'] for a in agent_rows if a.get('cwd') and inside(Path(a['cwd']), path)]
    lease = primary / '.subactor/leases' / (path.name + '.json')
    row['lease_status'] = 'unknown'
    if lease.is_file():
        try:
            row['lease_status'] = str(json.loads(lease.read_text()).get('status', 'unknown'))
        except (OSError, ValueError, AttributeError):
            row['errors'].append('invalid lease')
    ticket = re.search(r'ticket[-/](\d+)', record.get('branch', ''))
    row.update(ticket=None, complexity='unknown', complexity_source='none')
    if ticket:
        row['ticket'] = 'ticket-' + ticket[1]
        intent = path / 'project' / row['ticket'] / 'intent.json'
        try:
            data = json.loads(intent.read_text())
            complexity = data.get('delivery', {}).get('complexity', 'unknown')
            if complexity in {'XS', 'S', 'M', 'L'}:
                row.update(complexity=complexity, complexity_source='declared intent')
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError):
            row['errors'].append('invalid intent')
    row['unfinished'] = bool(changed or row['ahead'] or row['errors'] or row['ahead'] is None)
    row['stage'] = ('conflict' if conflict else 'started (tracking changes only)' if changed and not implementation_changes and row['ticket'] else 'modified' if changed else
                    'unmerged commits' if row['ahead'] else 'no local delta' if row['ahead'] == 0 else 'unknown')
    row['readiness'] = ('inspect errors' if row['errors'] else 'resolve conflict' if conflict else
                        'agent present' if row['agent_pids'] else 'review ownership' if row['unfinished'] else 'no local delta')
    row['command'] = 'cd -- ' + shlex.quote(str(path))
    row['prompt'] = (f'Wznów {row["ticket"] or "zadanie"} w {path}. Najpierw odczytaj AGENTS.md, '
                     'Git status, intent, lease, Planfile oraz bieżący PR i CI. Sprawdź właściciela '
                     'i zależności. Zachowaj istniejące zmiany. Przed zapisem potwierdź dopuszczenie '
                     'do tego zakresu; wykonaj następny krok i właściwe testy. Nie resetuj ani nie '
                     'usuwaj worktree na podstawie samego braku procesu po restarcie.')
    return row


def scan(root, depth=2, sort='backlog'):
    started = time.monotonic()
    agent_rows, denied = processes(root, machine=True)
    projects, errors, seen, groups = [], [], set(), []
    with ThreadPoolExecutor(max_workers=8) as pool:
        candidates = roots(root, depth)
        for candidate, (records, error) in zip(candidates, pool.map(registrations, candidates)):
            if error or not records:
                errors.append(f'{candidate}: {error or "no worktree records"}')
                continue
            primary = Path(records[0]['path'])
            if str(primary) in seen:
                continue
            seen.add(str(primary))
            # Offline inventory uses last fetched remote main; no network or ref mutation.
            base, _ = command(['git', 'rev-parse', '--verify', 'refs/remotes/origin/HEAD'], primary)
            if not base:
                base, _ = command(['git', 'rev-parse', '--verify', 'refs/remotes/origin/main'], primary)
            if not base:
                # No known remote base: leave ahead/behind unknown, including primary.
                base = ''
            groups.append((primary, records, base.strip()))
        futures = [(primary, base, [pool.submit(inspect_checkout, r, primary, base, agent_rows) for r in records])
                   for primary, records, base in groups]
        for primary, base, pending in futures:
            rows = [f.result() for f in pending]
            items, sources, ticket_errors = [], [], []
            for row in rows:
                if row['path'] == str(primary) or row['unfinished']:
                    tickets, files, failures = planfile(Path(row['path']))
                    items.extend(tickets); sources.extend(files); ticket_errors.extend(failures)
            summary = summarize_tickets(items)
            summary['available'] = bool(sources)
            summary['complete'] = bool(sources) and not ticket_errors and not summary['unknown_statuses'] and not summary['conflicting_statuses']
            project = {'path': str(primary), 'checkouts': rows, 'planfile': summary,
                       'planfile_sources': sources, 'errors': ticket_errors,
                       'unfinished_checkouts': sum(r['unfinished'] for r in rows),
                       'changed_files': sum(r['changed_files'] for r in rows),
                       'comparison_base': base, 'remote_freshness': 'not fetched'}
            projects.append(project)
    key = ((lambda p: (p['changed_files'], p['unfinished_checkouts'])) if sort == 'changes' else
           (lambda p: (p['planfile']['remaining'], p['unfinished_checkouts'], p['changed_files'])))
    projects.sort(key=key, reverse=True)
    return {'schema': 'monag.resume/v1', 'root': str(root),
            'observed_at': datetime.now(timezone.utc).isoformat(),
            'duration_seconds': round(time.monotonic() - started, 2),
            'projects': projects, 'project_count': len(projects),
            'unfinished_projects': sum(any(r['changed_files'] or r['ahead'] for r in p['checkouts']) for p in projects),
            'projects_needing_review': sum(bool(p['unfinished_checkouts']) for p in projects),
            'errors': errors, 'inaccessible_processes': denied,
            'notice': 'Read-only local inventory; no fetch, approval, takeover or automatic resume. '
                      'Backlog is supported local Planfile YAML, not all GitHub issues or SQLite storage. '
                      'No local delta does not prove release completion. Complexity is declared, not inferred.'}


def markdown(data, limit=12, all_projects=False):
    lines = ['# MONAG — wznowienie pracy', '',
             f"Projekty: **{data['project_count']}**; z lokalnymi zmianami/niewłączonymi commitami: "
             f"**{data['unfinished_projects']}**; do sprawdzenia (także brak danych): "
             f"**{data['projects_needing_review']}**; skan: {data['duration_seconds']} s.", '',
             'Brak procesu po restarcie nie zwalnia lease. Lista jest wskazówką do kontroli, nie zgodą na przejęcie.', '',
             '## Projekty / ranking backlogu', '']
    selected = [p for p in data['projects'] if all_projects or p['unfinished_checkouts'] or p['planfile']['remaining']]
    lines.append(table(['Projekt', 'Worktree do sprawdzenia', 'Zmiany', 'Planfile pozostało', 'Konflikty statusów'],
                       [[p['path'], p['unfinished_checkouts'], p['changed_files'],
                         (str(p['planfile']['remaining']) + ('' if p['planfile']['complete'] else ' (niepełne)')) if p['planfile']['available'] else 'brak danych',
                         p['planfile']['conflicting_statuses']] for p in selected[:limit]]))
    rows = [(p, r) for p in selected[:limit] for r in p['checkouts'] if r['unfinished']]
    lines.extend(['', '## Checkouty do wznowienia po kontroli', '',
                  table(['Katalog', 'Ticket', 'Etap', 'Złożoność', 'Stan', 'Lease'],
                        [[r['path'], r['ticket'] or '—', r['stage'], r['complexity'],
                          r['readiness'], r['lease_status']] for p, r in rows[:limit]])])
    if rows:
        r = rows[0][1]
        lines.extend(['', 'Przykład wejścia do pierwszego checkoutu:', '', '```bash', r['command'], '```',
                      '', 'Prompt do agenta (pełne prompty dla każdego checkoutu: `--json`):', '', r['prompt']])
    failures = data['errors'] + [e for p in data['projects'] for e in p['errors']] + [e for p in data['projects'] for r in p['checkouts'] for e in r['errors']]
    lines.extend(['', f'Błędy odczytu: {len(failures)}. Projekty pokazane: {min(limit, len(selected))}/{len(selected)}.',
                  '', 'Złożoność XS/S/M/L pochodzi z intent; unknown oznacza brak deklaracji. '
                  'Etap opisuje Git, nie procent ukończenia. Planfile: bieżący sprint/backlog; '
                  'brak danych nie oznacza zera ticketów. Dane GitHub wymagają osobnej weryfikacji.',
                  '', 'Pełne dane i błędy: `monag --json resume`. Ranking zmian: `monag resume --sort changes`.'])
    return '\n'.join(lines) + '\n'

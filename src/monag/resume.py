"""Read-only restart inventory. Local observations never authorize takeover."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shlex
import time

import yaml

from . import fleet
from .monitor import checkout_agents, command, processes
from .presentation import table

CLOSED = {'done', 'closed', 'cancelled', 'canceled', 'completed', 'merged'}
# planfile.ticket-status/v1 (tests/fixtures) classifies every planfile status;
# tests keep these sets covering it.
# Planfile's own terminal-failure status needs triage like a blocked ticket:
# it stays visible as remaining work but is never ready to pick up.
STALLED = {'blocked', 'failed'}
OPEN = {'open', 'todo', 'backlog', 'planned', 'plan', 'ready', 'in_progress',
        'in-progress', 'active', 'review', 'pending'} | STALLED
PLANFILE_PRIORITIES = ('critical', 'high', 'medium', 'normal', 'low')
PRIORITY_RANK = {value: len(PLANFILE_PRIORITIES) - index
                 for index, value in enumerate(PLANFILE_PRIORITIES)}


def normalize_priority(value):
    """Return a supported Planfile priority or explicit unknown evidence."""
    if not isinstance(value, str):
        return 'unknown'
    value = value.strip().lower()
    return value if value in PRIORITY_RANK else 'unknown'


def priority_rank(value):
    return PRIORITY_RANK.get(normalize_priority(value), -1)


def github_mapping(item):
    """A ticket's own GitHub issue id, from either supported field shape."""
    sync = item.get('sync')
    if isinstance(sync, dict):
        github = sync.get('github')
        if isinstance(github, dict) and github.get('id') not in (None, ''):
            return str(github['id'])
    external_id = item.get('external_id')
    return str(external_id) if external_id not in (None, '') else None


def imported_record_evidence(key, item):
    """Describe missing fields that a GitHub import must not hide."""
    sync = item.get('sync')
    github = sync.get('github') if isinstance(sync, dict) else None
    imported = (str(key).upper().startswith('GITHUB-') or
                item.get('backend') == 'github' or
                item.get('external_id') not in (None, '') or
                isinstance(github, dict))
    if not imported:
        return []
    evidence = []
    if not item.get('id'):
        evidence.append('missing inline id')
    if 'priority' not in item or item.get('priority') in (None, ''):
        evidence.append('missing priority')
    if not (isinstance(github, dict) and github.get('id') not in (None, '')):
        evidence.append('missing sync.github mapping')
    return evidence


class PlanfileDiagnostic(str):
    """Diagnostic message preserving file, ticket, checkout, and historical context."""

    def __new__(cls, message, *, file=None, ticket_id=None, checkout=None, finding=None, kind=None, historical=False):
        obj = super().__new__(cls, str(message))
        obj.file = str(file) if file is not None else None
        obj.ticket_id = str(ticket_id) if ticket_id is not None else None
        obj.checkout = str(checkout) if checkout is not None else None
        obj.finding = finding
        obj.kind = kind
        obj.historical = bool(historical)
        return obj


def planfile(path):
    """Read supported active YAML sources, never projections or historical copies.

    Every `.planfile/sprints/*.yaml` file is read, not just current/backlog:
    a repository can carry additional named active sprints (for example an
    audit sprint), and a ticket that only exists there must still be visible.
    Cache projections (`*.fast.json`) and a nested `.planfile/.planfile/`
    duplicate store are excluded by construction (glob does not descend).
    """
    sprints_dir = path / '.planfile' / 'sprints'
    files = [path / name for name in ('tickets.planfile.yaml', 'planfile.yaml')]
    if sprints_dir.is_dir():
        files.extend(sorted(sprints_dir.glob('*.yaml')))
    result, errors, sources = [], [], []
    locations = {}
    locator = path / '.planfile/index/history-locations.yaml'
    if locator.is_file():
        try:
            if locator.stat().st_size > 5_000_000:
                raise ValueError('history index exceeds read limit')
            data = yaml.safe_load(locator.read_text())
            if not isinstance(data, dict) or not isinstance(data.get('tickets'), dict):
                raise ValueError('invalid history index')
            locations = data['tickets']
        except (OSError, ValueError, yaml.YAMLError):
            errors.append(PlanfileDiagnostic(
                f'{locator}: invalid history ownership index',
                file=locator, checkout=path, finding='invalid history ownership index',
                kind='locator_error',
            ))
    from functools import lru_cache

    @lru_cache(maxsize=128)
    def _load_planfile_yaml_cached(path_str: str, mtime_ns: int):
        del mtime_ns
        return yaml.load(Path(path_str).read_text(), Loader=getattr(yaml, 'CSafeLoader', yaml.SafeLoader))

    for file in files:
        if not file.is_file():
            continue
        sources.append(str(file))
        try:
            st = file.stat()
            if st.st_size > 5_000_000:
                raise ValueError('file exceeds 5 MB read limit')
            data = _load_planfile_yaml_cached(str(file), st.st_mtime_ns)
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
                        errors.append(PlanfileDiagnostic(
                            f'{file}: ticket without stable ID omitted',
                            file=file, checkout=path, finding='missing stable id',
                            kind='omitted_ticket',
                            historical=file.stem.startswith(('history-', 'archive-')),
                        ))
                        continue
                    evidence = imported_record_evidence(key, item)
                    errors.extend(PlanfileDiagnostic(
                        f'{file}: {key}: {finding}',
                        file=file, ticket_id=identity, checkout=path,
                        finding=finding, kind='import_evidence',
                        historical=file.stem.startswith(('history-', 'archive-')),
                    ) for finding in evidence)
                    # Planfile creates tasks as open; a legacy task without a status field
                    # is unstarted work, not an ambiguous state that blocks the whole queue.
                    status = str(item.get('status') or 'open').lower()
                    priority = normalize_priority(item.get('priority'))
                    result.append({'id': str(identity), 'status': status,
                                   'title': str(item.get('name', item.get('title', identity))),
                                   'priority': priority,
                                   'labels': [str(label) for label in item.get('labels', [])]
                                   if isinstance(item.get('labels', []), list) else [],
                                   'import_evidence': evidence,
                                   'source': str(file),
                                   'checkout': str(path),
                                   'history_owner': locations.get(str(identity)),
                                   'historical': file.stem.startswith(('history-', 'archive-')),
                                   'github': github_mapping(item),
                                   'github_binding': (item.get('sync') or {}).get('github', {})
                                   if isinstance(item.get('sync'), dict) else {}})
        except (OSError, ValueError, TypeError, yaml.YAMLError, RecursionError) as error:
            errors.append(PlanfileDiagnostic(
                f'{file}: {type(error).__name__}',
                file=file, checkout=path, finding=type(error).__name__,
                kind='file_error',
                historical=file.stem.startswith(('history-', 'archive-')),
            ))
    for identity, owner in locations.items():
        if any(row['id'] == identity for row in result) and not any(
                row['id'] == identity and Path(row['source']).stem == owner for row in result):
            errors.append(PlanfileDiagnostic(
                f'{locator}: {identity}: canonical history owner unavailable',
                file=locator, ticket_id=identity, checkout=path,
                finding='canonical history owner unavailable',
                kind='missing_history_owner',
            ))
    return result, sources, errors


def external_identity(row):
    binding = row.get('github_binding') or {}
    if not isinstance(binding, dict):
        binding = {}
    key = binding.get('key')
    url = binding.get('url')
    if key:
        return str(key)
    if url:
        match = re.fullmatch(r'https://github.com/([^/]+/[^/]+)/issues/(\d+)/?', str(url))
        if match:
            return match[1] + '#' + match[2]
        return str(url)
    if binding.get('repository') and row.get('github'):
        return str(binding['repository']) + '#' + str(row['github'])
    return str(row['github']) if row.get('github') else None


def identity_bindings(rows):
    identities = {external_identity(r) for r in rows if external_identity(r)}
    # Legacy id-only copies are compatible with one uniquely scoped issue.
    for identity in list(identities):
        if identity.isdigit() and len([x for x in identities if x.endswith('#' + identity)]) == 1:
            identities.remove(identity)
    return sorted(identities)


def reconcile_ticket_sources(items, primary):
    """Prefer the primary store and its locator; retain collisions and provenance."""
    grouped = {}
    for row in items:
        grouped.setdefault(row['id'], []).append(row)
    selected, stale = [], []
    for rows in grouped.values():
        primary_rows = [r for r in rows if r.get('checkout') == str(primary)]
        candidates = primary_rows or rows
        identities = identity_bindings(rows)
        # Conflicting external bindings must never be hidden by source precedence.
        if len(identities) > 1:
            selected.extend(rows)
            continue
        owners = [r for r in candidates if r.get('history_owner') and
                  Path(r['source']).stem == r['history_owner']]
        if owners:
            candidates = owners
        elif not any(r.get('history_owner') for r in candidates):
            active = [r for r in candidates if not r.get('historical')]
            if active:
                candidates = active
        if primary_rows:
            # A locally edited peer store may contain an unsynchronized update,
            # not an inherited stale snapshot. Retain it as conflicting evidence.
            candidates = [*candidates, *(r for r in rows if r not in primary_rows
                                        and r.get('source_changed'))]
        selected.extend(candidates)
        stale.extend(dict(r, exclusion='noncanonical snapshot') for r in rows
                     if not any(r is candidate for candidate in candidates))
    return selected, stale


def _find_checkout(file_path, rows=None, primary=None):
    if not file_path:
        return str(primary) if primary else None
    try:
        fp = Path(file_path).resolve()
        if rows:
            for r in rows:
                rp = Path(r['path']).resolve()
                try:
                    fp.relative_to(rp)
                    return str(r['path'])
                except ValueError:
                    pass
    except Exception:
        pass
    return str(primary) if primary else None


def _parse_diagnostic(diag, rows=None, primary=None):
    if isinstance(diag, PlanfileDiagnostic):
        return diag
    s = str(diag)
    m = re.match(r'^(.*?): ([^:]+): (missing inline id|missing priority|missing sync\.github mapping)$', s)
    if m:
        f, k, finding = m.group(1), m.group(2), m.group(3)
        chk = _find_checkout(f, rows, primary)
        return PlanfileDiagnostic(s, file=f, ticket_id=k, checkout=chk, finding=finding,
                                  kind='import_evidence',
                                  historical=Path(f).stem.startswith(('history-', 'archive-')))
    m = re.match(r'^(.*?): ticket without stable ID omitted$', s)
    if m:
        f = m.group(1)
        chk = _find_checkout(f, rows, primary)
        return PlanfileDiagnostic(s, file=f, ticket_id=None, checkout=chk, finding='missing stable id',
                                  kind='omitted_ticket',
                                  historical=Path(f).stem.startswith(('history-', 'archive-')))
    m = re.match(r'^(.*?): ([^:]+): canonical history owner unavailable$', s)
    if m:
        f, k = m.group(1), m.group(2)
        chk = _find_checkout(f, rows, primary)
        return PlanfileDiagnostic(s, file=f, ticket_id=k, checkout=chk,
                                  finding='canonical history owner unavailable',
                                  kind='missing_history_owner')
    parts = s.split(':', 1)
    f = parts[0].strip() if len(parts) > 1 else None
    chk = _find_checkout(f, rows, primary) if f else (str(primary) if primary else None)
    return PlanfileDiagnostic(s, file=f, ticket_id=None, checkout=chk, kind='general')


def classify_diagnostics(failures, canonical, stale, primary, rows=None):
    """Classify Planfile diagnostics into canonical admission failures and historical warnings.

    Admission failures (blocking):
      - Malformed canonical tickets (import evidence, invalid priority/status).
      - Diagnostics from changed peer stores (source_changed == True).
      - Unresolved external identities or conflicting bindings.
      - Structural index/file failures in authoritative or changed stores.

    Historical diagnostics (warnings):
      - Validation findings on unchanged inherited copies or historical snapshots
        that were excluded as noncanonical snapshots in favor of a valid canonical ticket.
    """
    canonical_errors, historical_diagnostics = [], []
    rows = rows or []
    changed_by_checkout = {str(r['path']): set(r.get('changed_paths', [])) for r in rows}

    def _is_changed(file_str, checkout_str):
        if not file_str or not checkout_str:
            return False
        try:
            rel = str(Path(file_str).resolve().relative_to(Path(checkout_str).resolve()))
        except (ValueError, Exception):
            return False
        changed = changed_by_checkout.get(str(checkout_str), set())
        return any(rel == name or (name.endswith('/') and rel.startswith(name)) for name in changed)

    canonical_by_id = {}
    for r in canonical:
        canonical_by_id.setdefault(str(r.get('id')), []).append(r)

    stale_by_id = {}
    for r in stale:
        stale_by_id.setdefault(str(r.get('id')), []).append(r)

    for item in failures:
        d = _parse_diagnostic(item, rows, primary)
        ticket_id = d.ticket_id

        # Missing history owner and index failures always remain blocking
        if d.kind in ('missing_history_owner', 'locator_error') or 'canonical history owner unavailable' in str(d):
            canonical_errors.append(d)
            continue

        if not ticket_id:
            # File-level errors or tickets without stable ID
            if d.checkout == str(primary) or _is_changed(d.file, d.checkout):
                canonical_errors.append(d)
            else:
                historical_diagnostics.append(d)
            continue

        can_rows = canonical_by_id.get(ticket_id, [])
        stale_rows = stale_by_id.get(ticket_id, [])

        is_stale_source = any(
            (d.file and Path(r.get('source', '')).resolve() == Path(d.file).resolve()) or
            (d.checkout and str(r.get('checkout', '')) == str(d.checkout))
            for r in stale_rows
        )

        file_changed = _is_changed(d.file, d.checkout)

        can_is_valid = bool(can_rows) and all(
            not c.get('import_evidence') and
            c.get('priority') in PLANFILE_PRIORITIES and
            c.get('status') in (OPEN | CLOSED) and
            not c.get('priority_conflict') and
            not c.get('identity_collision')
            for c in can_rows
        )

        all_ticket_records = can_rows + stale_rows
        has_identity_collision = len(identity_bindings(all_ticket_records)) > 1

        is_in_canonical = any(
            (d.file and Path(c.get('source', '')).resolve() == Path(d.file).resolve()) or
            (d.checkout and str(c.get('checkout', '')) == str(d.checkout))
            for c in can_rows
        )

        if (not file_changed and
                can_is_valid and
                not has_identity_collision and
                (is_stale_source or (d.historical and not is_in_canonical))):
            historical_diagnostics.append(d)
        else:
            canonical_errors.append(d)

    return canonical_errors, historical_diagnostics


def summarize_tickets(items, priorities=None):
    """Summarize tickets while retaining deterministic priority evidence.

    A ticket can occur in both the current sprint and backlog. Status and
    priority conflicts remain visible instead of silently choosing a source.
    When duplicate rows disagree, the highest known priority is the effective
    value used for ordering and the conflict counter records the ambiguity.
    """
    grouped = {}
    for item in items:
        row = dict(item)
        row['priority'] = normalize_priority(row.get('priority'))
        grouped.setdefault(str(row['id']), []).append(row)
    selected_priorities = None
    if priorities:
        if isinstance(priorities, str):
            priorities = [priorities]
        selected_priorities = {normalize_priority(value) for value in priorities}
    pending, blocked, conflicts, unknown, priority_conflicts = [], 0, 0, 0, 0
    pending_tickets, identity_collisions = [], []
    included_tickets = 0
    for key in sorted(grouped):
        rows = grouped[key]
        identities = identity_bindings(rows)
        identity_collision = len(identities) > 1
        if identity_collision:
            identity_collisions.append({'id': key, 'github_bindings': identities,
                                        'records': rows})
        statuses = {r['status'] for r in rows}
        row_priorities = {r['priority'] for r in rows}
        known = [value for value in row_priorities if value in PRIORITY_RANK]
        effective_priority = max(known, key=priority_rank) if known else 'unknown'
        if selected_priorities is not None and effective_priority not in selected_priorities:
            continue
        included_tickets += 1
        conflicts += len(statuses) > 1
        priority_conflicts += len(row_priorities) > 1
        unknown += bool(statuses - OPEN - CLOSED)
        if statuses & OPEN:
            pending.append(key)
            blocked += bool(statuses & STALLED)
            labels = sorted({str(label) for row in rows for label in row.get('labels', [])})
            import_evidence = sorted({str(finding) for row in rows
                                      for finding in row.get('import_evidence', [])})
            pending_tickets.append({
                'id': key,
                'status': '/'.join(sorted(statuses)),
                'title': ('identity collision: ' + ' / '.join(identities)) if identity_collision
                         else sorted(str(r.get('title', key)) for r in rows)[0],
                'priority': effective_priority,
                'labels': labels,
                'import_evidence': import_evidence,
                'source': sorted(str(r.get('source', '')) for r in rows)[0],
                'priority_conflict': len(row_priorities) > 1,
                'identity_collision': identity_collision,
                'sources': sorted({str(r.get('source', '')) for r in rows}),
                'github_bindings': identities,
            })
    pending_tickets.sort(key=lambda row: (-priority_rank(row['priority']), row['id']))
    priority_counts = {value: 0 for value in (*PLANFILE_PRIORITIES, 'unknown')}
    for row in pending_tickets:
        priority_counts[row['priority']] += 1
    highest = pending_tickets[0]['priority'] if pending_tickets else 'unknown'
    return {'known_tickets': included_tickets, 'total_known_tickets': len(grouped),
            'remaining': len(pending),
            'blocked': blocked, 'conflicting_statuses': conflicts,
            'unknown_statuses': unknown, 'remaining_ids': sorted(pending),
            'remaining_tickets': pending_tickets,
            'priority_counts': priority_counts,
            'highest_priority': highest,
            'highest_priority_rank': priority_rank(highest),
            'priority_conflicts': priority_conflicts,
            'identity_collisions': identity_collisions,
            'priority_filter': sorted(selected_priorities, key=lambda value: (-priority_rank(value), value))
            if selected_priorities is not None else []}


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


def ticket_identity(value):
    if not isinstance(value, str):
        return None
    match = re.match(r'^ticket[-/]((?:[A-Z][A-Z0-9]*-)?\d+)(?=-|/|$)', value)
    return 'ticket-' + match[1] if match else None


def inspect_checkout(record, primary, base, agent_rows, assignments=None):
    path = Path(record['path'])
    row = dict(record, errors=[])
    def git(*args):
        out, error = command(['git', *args], path)
        if error:
            row['errors'].append(error)
        return out
    output = git('status', '--porcelain=v1', '-z', '--untracked-files=normal')
    fields = output.split('\0'); changed = 0; implementation_changes = 0; conflict = False
    changed_paths = []
    i = 0
    while i < len(fields):
        part = fields[i]; i += 1
        if not part:
            continue
        changed += 1
        name = part[3:]
        changed_paths.append(name)
        if not name.startswith(('project/', '.subactor/', '.planfile/')) and name not in {'TODO.md'}:
            implementation_changes += 1
        conflict |= part[:2] in {'DD', 'AU', 'UD', 'UA', 'DU', 'AA', 'UU'}
        if 'R' in part[:2] or 'C' in part[:2]:
            i += 1
    row.update(changed_files=changed, changed_paths=changed_paths, conflicts=conflict, ahead=None, behind=None)
    if base and record.get('head'):
        counts = git('rev-list', '--left-right', '--count', f'{base}...{record["head"]}').split()
        if len(counts) == 2:
            row['behind'], row['ahead'] = map(int, counts)
    row['agent_pids'] = (assignments if assignments is not None else
                         checkout_agents([str(path)], agent_rows)).get(str(path), [])
    lease = primary / '.subactor/leases' / (path.name + '.json')
    row.update(fleet.lease_observation(lease))
    if row['lease_kind'] == 'invalid':
        row['errors'].append('invalid lease')
    # Fleet refactoring metrics: clone identity, base freshness and lease age are
    # what keep an aggregate from counting delivered work as pending.
    row['remote_identity'] = fleet.remote_identity(path)
    row['base_ref_age_seconds'] = fleet.base_ref_age_seconds(path, base)
    row['base_commit_age_seconds'] = fleet.base_commit_age_seconds(path, base)
    row['remote_observation_freshness'] = 'unknown'
    row['publication_state'] = fleet.publication_state(row)
    row['publication_verified'] = False
    ticket = ticket_identity(record.get('branch', ''))
    path_ticket = ticket_identity(path.name)
    row.update(ticket=ticket, path_ticket=path_ticket, intent_ticket=None,
               complexity='unknown', complexity_source='none')
    if ticket:
        intent = path / 'project' / row['ticket'] / 'intent.json'
        try:
            data = json.loads(intent.read_text())
            row['intent_ticket'] = data.get('ticket')
            complexity = data.get('delivery', {}).get('complexity', 'unknown')
            if complexity in {'XS', 'S', 'M', 'L'}:
                row.update(complexity=complexity, complexity_source='declared intent')
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError):
            row['errors'].append('invalid intent')
    identities = dict(branch=ticket, path=path_ticket,
                      intent=ticket_identity(row['intent_ticket']),
                      lease=ticket_identity(row['lease_ticket']))
    row['ticket_identities'] = identities
    row['ticket_identity_conflict'] = len({value for value in identities.values() if value}) > 1
    if row['ticket_identity_conflict']:
        row['errors'].append('ticket identity disagreement: ' + ', '.join(
            f'{source} {value}' for source, value in identities.items() if value))
    row['unfinished'] = bool(changed or row['ahead'] or row['errors'] or row['ahead'] is None)
    row['stage'] = ('conflict' if conflict else 'started (tracking changes only)' if changed and not implementation_changes and row['ticket'] else 'modified' if changed else
                    'ancestry delta (publication unknown)' if row['ahead'] else 'no local delta' if row['ahead'] == 0 else 'unknown')
    row['readiness'] = ('inspect errors' if row['errors'] else 'resolve conflict' if conflict else
                        'agent present' if row['agent_pids'] else 'review ownership' if row['unfinished'] else 'no local delta')
    row['command'] = 'cd -- ' + shlex.quote(str(path))
    row['prompt'] = (f'Wznów {row["ticket"] or "zadanie"} w {path}. Najpierw odczytaj AGENTS.md, '
                     'Git status, intent, lease, Planfile oraz bieżący PR i CI. Sprawdź właściciela '
                     'i zależności. Zachowaj istniejące zmiany. Przed zapisem potwierdź dopuszczenie '
                     'do tego zakresu; wykonaj następny krok i właściwe testy. Nie resetuj ani nie '
                     'usuwaj worktree na podstawie samego braku procesu po restarcie.')
    return row


def scan(root, depth=2, sort='backlog', priorities=None):
    started = time.monotonic()
    if isinstance(priorities, str):
        priorities = [priorities]
    priority_filter = []
    if priorities:
        priority_filter = sorted({normalize_priority(value) for value in priorities},
                                 key=lambda value: (-priority_rank(value), value))
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
        assignments = checkout_agents([r['path'] for _, records, _ in groups for r in records], agent_rows)
        futures = [(primary, base, [pool.submit(inspect_checkout, r, primary, base, agent_rows, assignments) for r in records])
                   for primary, records, base in groups]
        for primary, base, pending in futures:
            rows = [f.result() for f in pending]
            items, sources, ticket_errors = [], [], []
            for row in rows:
                if row['path'] == str(primary) or row['unfinished']:
                    tickets, files, failures = planfile(Path(row['path']))
                    for ticket in tickets:
                        relative = str(Path(ticket['source']).relative_to(row['path']))
                        ticket['source_changed'] = any(relative == name or (
                            name.endswith('/') and relative.startswith(name)) for name in row['changed_paths'])
                    items.extend(tickets); sources.extend(files); ticket_errors.extend(failures)
            canonical, stale = reconcile_ticket_sources(items, primary)
            canonical_errors, historical_diagnostics = classify_diagnostics(
                ticket_errors, canonical, stale, primary, rows
            )
            summary = summarize_tickets(canonical, priority_filter)
            summary['stale_copies'] = stale
            summary['available'] = bool(sources)
            summary['complete'] = (bool(sources) and not canonical_errors and
                                   not summary['unknown_statuses'] and
                                   not summary['conflicting_statuses'] and
                                   not summary['priority_conflicts'] and not summary['identity_collisions'])
            summary['historical_diagnostics'] = historical_diagnostics
            project = {'path': str(primary), 'checkouts': rows, 'planfile': summary,
                       'planfile_sources': sources, 'errors': canonical_errors,
                       'historical_diagnostics': historical_diagnostics,
                       'priority_filter': priority_filter,
                       'unfinished_checkouts': sum(r['unfinished'] for r in rows),
                       'changed_files': sum(r['changed_files'] for r in rows),
                       'comparison_base': base, 'remote_freshness': 'not fetched',
                       'fleet_metrics': fleet.metrics(rows)}
            projects.append(project)
    if sort == 'changes':
        projects.sort(key=lambda p: (-p['changed_files'], -p['unfinished_checkouts'],
                                     -p['planfile']['remaining'], p['path']))
    elif sort == 'priority':
        projects.sort(key=lambda p: (-p['planfile'].get('highest_priority_rank', -1),
                                     -p['planfile']['remaining'],
                                     -p['unfinished_checkouts'], -p['changed_files'], p['path']))
    else:
        projects.sort(key=lambda p: (-p['planfile']['remaining'], -p['unfinished_checkouts'],
                                     -p['changed_files'], p['path']))
    return {'schema': 'monag.resume/v1', 'root': str(root), 'sort': sort,
            'observed_at': datetime.now(timezone.utc).isoformat(),
            'duration_seconds': round(time.monotonic() - started, 2),
            'projects': projects, 'project_count': len(projects),
            'priority_filter': priority_filter,
            'unfinished_projects': sum(any(r['changed_files'] or r['ahead'] for r in p['checkouts']) for p in projects),
            'projects_needing_review': sum(bool(p['unfinished_checkouts']) for p in projects),
            'errors': errors, 'inaccessible_processes': denied,
            'notice': 'Read-only local inventory; no fetch, approval, takeover or automatic resume. '
                      'Backlog is supported local Planfile YAML, not all GitHub issues or SQLite storage. '
                      'No local delta does not prove release completion. Complexity is declared, not inferred.'}


def markdown(data, limit=12, all_projects=False):
    lines = ['# MONAG — wznowienie pracy', '',
             f"Projekty: **{data['project_count']}**; z lokalnymi zmianami/różnicami historii Git: "
             f"**{data['unfinished_projects']}**; do sprawdzenia (także brak danych): "
             f"**{data['projects_needing_review']}**; skan: {data['duration_seconds']} s.", '',
             'Brak procesu po restarcie nie zwalnia lease. Lista jest wskazówką do kontroli, nie zgodą na przejęcie.', '',
             '## Projekty / ' + {'priority': 'ranking priorytetów',
                                'changes': 'ranking zmian'}.get(data.get('sort', 'backlog'), 'ranking backlogu'), '']
    priority_filter = data.get('priority_filter', [])
    if priority_filter:
        lines.insert(5, 'Filtr priorytetów Planfile: **' + ', '.join(priority_filter) + '** (pozostałe tickety pominięte).')
    selected = [p for p in data['projects'] if all_projects or p['unfinished_checkouts'] or p['planfile']['remaining']]
    lines.append(table(['Projekt', 'Worktree do sprawdzenia', 'Zmiany', 'Planfile pozostało',
                        'Najwyższy priorytet', 'Konflikty statusów', 'Konflikty priorytetów', 'Kolizje ID', 'Stare kopie'],
                       [[p['path'], p['unfinished_checkouts'], p['changed_files'],
                         (str(p['planfile']['remaining']) + ('' if p['planfile']['complete'] else ' (niepełne)')) if p['planfile']['available'] else 'brak danych',
                         p['planfile'].get('highest_priority', 'unknown'),
                         p['planfile']['conflicting_statuses'],
                         p['planfile'].get('priority_conflicts', 0),
                         len(p['planfile'].get('identity_collisions', [])),
                         len(p['planfile'].get('stale_copies', []))] for p in selected[:limit]]))
    ticket_rows = [[p['path'], ticket['id'], ticket['priority'], ticket['status'], ticket['title']]
                   for p in selected[:limit]
                   for ticket in p['planfile'].get('remaining_tickets', [])]
    lines.extend(['', '## Otwarte tickety Planfile', '',
                  table(['Projekt', 'Ticket', 'Priorytet', 'Status', 'Tytuł'], ticket_rows[:limit])])
    if len(ticket_rows) > limit:
        lines.append(f'{len(ticket_rows) - limit} dodatkowych ticketów; użyj `--json`, aby zobaczyć wszystkie.\n')
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
    hist_count = sum(len(p.get('historical_diagnostics', [])) for p in data['projects'])
    failures_text = f'Błędy odczytu: {len(failures)}'
    if hist_count:
        failures_text += f' (ostrzeżenia historyczne: {hist_count})'
    lines.extend(['', f'{failures_text}. Projekty pokazane: {min(limit, len(selected))}/{len(selected)}.',
                  '', 'Złożoność XS/S/M/L pochodzi z intent; unknown oznacza brak deklaracji. '
                  'Etap opisuje Git, nie procent ukończenia. Planfile: bieżący sprint/backlog; '
                  'brak danych nie oznacza zera ticketów. Priorytet Planfile: critical > high > medium > normal > low; '
                  'unknown oznacza brak lub nieznaną wartość. Klasyfikacja Wellmanifest P0–P3 nie jest mapowana. '
                  'Dane GitHub wymagają osobnej weryfikacji. Różnica historii Git nie dowodzi braku scalenia PR; '
                  'wiek commitu nie określa świeżości danych zdalnych.',
                  '', 'Pełne dane i błędy: `monag --json resume`. '
                  'Ranking priorytetów: `monag resume --sort priority`; ranking zmian: `monag resume --sort changes`.'])
    return '\n'.join(lines) + '\n'

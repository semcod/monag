"""Read-only usage table: agent process resources and api-budget account ledgers.

Nothing here writes, reads prompts or environment variables, or guesses state;
every row cites the exact observation source.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from .monitor import command, processes
from .presentation import clean, table

LEDGER_GLOB = 'api-budget-*.json'
LEDGER_SCHEMA = 'subactor.api-budget-state/v1'
DOCKER_MARKER = 'MONAG-FILE:'
# Depth-1 data roots inside a container; keeps the exec bounded and read-only.
DOCKER_GLOBS = '/app/data/*/api-budget-*.json /app/api-budget-*.json'


def resident_bytes(pid, proc=Path('/proc')):
    """RSS of one live process in bytes, or None when it cannot be read."""
    try:
        pages = int((proc / str(pid) / 'statm').read_text().split()[1])
        return pages * os.sysconf('SC_PAGE_SIZE')
    except (OSError, ValueError, IndexError):
        return None


def boot_epoch(proc=Path('/proc')):
    try:
        for line in (proc / 'stat').read_text().splitlines():
            if line.startswith('btime '):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return None


def uptime_seconds(row, proc, now=None):
    """Seconds since the recorded process start, or None when unverifiable."""
    boot = boot_epoch(proc)
    if boot is None or not str(row.get('start', '')).isdigit():
        return None
    return round((now or time.time()) - boot - int(row['start']) / os.sysconf('SC_CLK_TCK'))


def ledger_record(source, path, text):
    """Normalize one api-budget state document; malformed input is an error row."""
    try:
        row = json.loads(text)
    except ValueError:
        return None, f'{source}: {path}: invalid JSON'
    if not isinstance(row, dict) or row.get('schema') != LEDGER_SCHEMA:
        return None, f'{source}: {path}: not a {LEDGER_SCHEMA} document'
    reset_at = row.get('reset_at')
    return {'provider': row.get('provider', 'unknown'),
            'remaining': row.get('remaining') if isinstance(row.get('remaining'), (int, float)) else None,
            'reset_at': reset_at if isinstance(reset_at, (int, float)) else None,
            'reset_in_seconds': (round(reset_at - time.time())
                                 if isinstance(reset_at, (int, float)) else None),
            'last_decision': row.get('last_decision'),
            'observed_at': row.get('observed_at'),
            'source': source, 'path': path}, None


def _docker_ledgers(container):
    script = ('for f in %s; do [ -f "$f" ] && printf "%%s%%s\\n" "%s" "$f" && cat "$f"; done; '
              'exit 0' % (DOCKER_GLOBS, DOCKER_MARKER))
    out, error = command(['docker', 'exec', container, 'sh', '-c', script], timeout=15)
    rows, errors = [], []
    if error:
        return rows, [f'docker:{container}: {error}']
    name, chunks = None, []
    for line in out.split('\n'):
        if line.startswith(DOCKER_MARKER):
            if name is not None:
                rows.append((name, '\n'.join(chunks).strip()))
            name, chunks = line[len(DOCKER_MARKER):].strip(), []
        else:
            chunks.append(line)
    if name is not None:
        rows.append((name, '\n'.join(chunks).strip()))
    return rows, errors


def _docker_auto():
    """Coordinator-style containers visible to this user; empty when docker is absent."""
    out, error = command(['docker', 'ps', '--format', '{{.Names}}'], timeout=10)
    if error:
        return [], [f'docker:auto: {error}']
    return [name.strip() for name in out.splitlines() if 'coordinator' in name], []


def read_ledgers(source):
    """One --ledger source: a file, a directory of ledgers, or docker:NAME|auto."""
    rows, errors = [], []
    if source.startswith('docker:'):
        names = [source[7:]]
        if names == ['auto']:
            names, auto_errors = _docker_auto()
            errors += auto_errors
        for name in names:
            documents, err = _docker_ledgers(name)
            errors += err
            for path, text in documents:
                row, problem = ledger_record(f'docker:{name}', path, text)
                (rows.append(row) if row else errors.append(problem))
        return rows, errors
    path = Path(source).expanduser()
    files = sorted(path.glob(LEDGER_GLOB)) if path.is_dir() else [path]
    if not files:
        errors.append(f'{source}: no {LEDGER_GLOB} found')
    for file in files:
        try:
            text = file.read_text()
        except OSError as e:
            errors.append(f'{file}: {type(e).__name__}')
            continue
        row, problem = ledger_record(source, str(file), text)
        (rows.append(row) if row else errors.append(problem))
    return rows, errors


def scan(root, registry=None, machine=False, all_users=False, ledgers=(), proc=Path('/proc')):
    """One usage observation: agent tree resources plus declared ledger sources."""
    started = time.monotonic()
    agents, denied = processes(root, proc=proc, registry=registry,
                               machine=machine, all_users=all_users)
    now = time.time()
    for agent in agents:
        members = [agent, *agent.get('descendants', [])]
        rss = [resident_bytes(m['pid'], proc) for m in members]
        agent['rss_bytes'] = sum(r for r in rss if r is not None) if any(r is not None for r in rss) else None
        agent['uptime_seconds'] = uptime_seconds(agent, proc, now)
    agents.sort(key=lambda a: -(a.get('cpu_seconds_tree') or 0))
    ledger_rows, errors = [], []
    for source in ledgers:
        rows, err = read_ledgers(source)
        ledger_rows += rows
        errors += err
    return {'root': str(root), 'observed_at': datetime.now(timezone.utc).isoformat(),
            'agents': agents, 'agent_count': len(agents), 'ledgers': ledger_rows,
            'errors': errors, 'inaccessible_processes': denied,
            'duration_seconds': round(time.monotonic() - started, 2)}


def human_bytes(value):
    if value is None:
        return '—'
    if value >= 1 << 30:
        return f'{value / (1 << 30):.1f}GiB'
    return f'{value / (1 << 20):.0f}MiB'


def human_duration(seconds):
    if seconds is None:
        return '—'
    sign = '-' if seconds < 0 else ''
    s = abs(int(seconds))
    days, s = divmod(s, 86400)
    hours, s = divmod(s, 3600)
    minutes, s = divmod(s, 60)
    if days:
        return f'{sign}{days}d{hours}h'
    if hours:
        return f'{sign}{hours}h{minutes}m'
    if minutes:
        return f'{sign}{minutes}m{s}s'
    return f'{sign}{s}s'


def reset_cell(row):
    seconds = row.get('reset_in_seconds')
    if seconds is None:
        return '—'
    return f'in {human_duration(seconds)}' if seconds >= 0 else f'expired {human_duration(-seconds)} ago'


def markdown(data, limit=12):
    parts = ['# MONAG · Usage\n',
             f"{clean(data['observed_at'][:19])} · {clean(data['root'])}\n",
             '## Agents\n',
             table(['#', 'PID', 'Agent', 'State', 'CPU total', 'Memory', 'Uptime', 'Children', 'Directory', 'Task'],
                   ([i + 1, a['pid'], a['kind'], a['state'], f"{a.get('cpu_seconds_tree') or 0:.0f}s",
                     human_bytes(a.get('rss_bytes')), human_duration(a.get('uptime_seconds')),
                     a['children'], a['cwd'], a.get('task', '—')]
                    for i, a in enumerate(data['agents'][:limit])))]
    if len(data['agents']) > limit:
        parts.append(f"{len(data['agents']) - limit} additional agents; increase --limit.\n")
    parts += ['## Account usage\n',
              table(['Provider', 'Remaining', 'Reset', 'Last decision', 'Observed', 'Source'],
                    ([r['provider'], '—' if r['remaining'] is None else int(r['remaining']),
                      reset_cell(r), r.get('last_decision') or '—',
                      (r.get('observed_at') or '—')[:19], r['source']] for r in data['ledgers']))]
    if not data['ledgers']:
        parts.append('Declare ledgers with `--ledger PATH` or `--ledger docker:NAME` '
                     '(`docker:auto` scans coordinator containers).\n')
    for error in data['errors']:
        parts.append(f'observation error: {clean(error)}\n')
    return '\n'.join(parts)


def render(data, limit=12):
    lines = [f"MONAG USAGE | {data['agent_count']} agents | {len(data['ledgers'])} ledgers | {data['observed_at'][:19]}",
             f"{data['root']} | scan {data['duration_seconds']}s", '',
             'AGENTS   #   PID       KIND           STATE  CPU TOTAL    MEMORY     UPTIME   CHILDREN  DIRECTORY']
    for index, agent in enumerate(data['agents'][:limit]):
        lines.append(f"  {index + 1:<3} {agent['pid']:<9} {agent['kind']:<14} {agent['state']:<6} "
                     f"{(agent.get('cpu_seconds_tree') or 0):>8.0f}s {human_bytes(agent.get('rss_bytes')):>10} "
                     f"{human_duration(agent.get('uptime_seconds')):>9} {agent['children']:>8}  {agent['cwd']}")
        task = agent.get('task')
        if task and task != 'unknown (process only)':
            lines.append(f"    task: {task}")
    if len(data['agents']) > limit:
        lines.append(f"  … {len(data['agents']) - limit} more agents; increase --limit")
    if data['agents']:
        lines.append('  open a row: monag open N[t|b|d|o|p]  (pid:NNNN also works)')
    if data['ledgers']:
        lines += ['', 'ACCOUNTS PROVIDER     REMAINING  RESET              LAST DECISION                   SOURCE']
        for row in data['ledgers']:
            remaining = '—' if row['remaining'] is None else str(int(row['remaining']))
            lines.append(f"  {row['provider']:<11} {remaining:>9} {reset_cell(row):<18} "
                         f"{(row.get('last_decision') or '—'):<31} {row['source']}")
    else:
        lines += ['', 'ACCOUNTS  none observed — declare --ledger PATH or --ledger docker:NAME (docker:auto scans coordinators)']
    for error in data['errors']:
        lines.append(f'  observation error: {error}')
    return '\n'.join(clean(line) for line in lines)

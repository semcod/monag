"""Read-only usage table: agent process resources and api-budget account ledgers.

Nothing here writes, reads prompts or environment variables, or guesses state;
every row cites the exact observation source.
"""
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from .monitor import command, processes
from .presentation import clean, table

LEDGER_GLOB = 'api-budget-*.json'
LEDGER_SCHEMA = 'subactor.api-budget-state/v1'
# Agent kind → credential provider namespace used by detect_provider_account.
KIND_PROVIDER = {
    'agy': 'agy', 'agy2': 'agy', 'agy-coding-agent': 'agy',
    'claude': 'claude', 'claude-agent-acp': 'claude',
    'codex': 'codex', 'cursor-agent': 'cursor', 'gemini': 'gemini',
}
DOCKER_MARKER = 'MONAG-FILE:'
# Depth-1 data roots inside a container; keeps the exec bounded and read-only.
DOCKER_GLOBS = '/app/data/*/api-budget-*.json /app/api-budget-*.json'


def detect_provider_account(provider, home=None):
    """Best-effort discovery of logged-in account email for known CLI providers."""
    base = Path(home).expanduser() if home else Path.home()
    try:
        if provider in ('codex', 'openai'):
            codex_auth = base / '.codex' / 'auth.json'
            if codex_auth.is_file():
                data = json.loads(codex_auth.read_text())
                id_token = data.get('tokens', {}).get('id_token')
                if id_token and '.' in id_token:
                    payload = id_token.split('.')[1]
                    payload += '=' * (-len(payload) % 4)
                    claims = json.loads(base64.b64decode(payload).decode('utf-8', errors='ignore'))
                    if claims.get('email'):
                        return claims['email']
        elif provider in ('claude', 'anthropic'):
            claude_json = base / '.claude.json'
            if claude_json.is_file():
                data = json.loads(claude_json.read_text())
                email = data.get('oauthAccount', {}).get('emailAddress')
                if email:
                    return email
                org = data.get('organizationName') or ''
                if '@' in org:
                    return org.split("'s")[0].strip()
        elif provider in ('agy', 'gemini', 'google'):
            gacc = base / '.gemini' / 'google_accounts.json'
            if gacc.is_file():
                data = json.loads(gacc.read_text())
                if data.get('active'):
                    return data['active']
        elif provider == 'cursor':
            cursor_dir = base / '.config' / 'Cursor' / 'User' / 'globalStorage'
            cursor_db = cursor_dir / 'state.vscdb'
            if cursor_db.is_file():
                import sqlite3
                con = sqlite3.connect(str(cursor_db))
                cur = con.cursor()
                cur.execute("SELECT value FROM ItemTable WHERE key = 'cursorAuth/cachedEmail' LIMIT 1;")
                row = cur.fetchone()
                con.close()
                if row and row[0]:
                    return row[0]
    except Exception:
        pass
    return None


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


def ledger_record(source, path, text, home=None):
    """Normalize one api-budget state document; malformed input is an error row."""
    try:
        row = json.loads(text)
    except ValueError:
        return None, f'{source}: {path}: invalid JSON'
    if not isinstance(row, dict) or row.get('schema') != LEDGER_SCHEMA:
        return None, f'{source}: {path}: not a {LEDGER_SCHEMA} document'
    reset_at = row.get('reset_at')
    provider = row.get('provider', 'unknown')
    account = row.get('account') or row.get('email')
    if not account:
        account = detect_provider_account(provider, home=home)
    balance = row.get('balance')
    if balance is None:
        balance = row.get('balance_text')
    return {'provider': provider,
            'account': str(account) if account is not None else None,
            'remaining': row.get('remaining') if isinstance(row.get('remaining'), (int, float)) else None,
            'balance': str(balance) if balance is not None else None,
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


def read_ledgers(source, home=None):
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
                row, problem = ledger_record(f'docker:{name}', path, text, home=home)
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
        row, problem = ledger_record(source, str(file), text, home=home)
        (rows.append(row) if row else errors.append(problem))
    return rows, errors


DEFAULT_LEDGER_DIRS = (
    Path('~/.config/subllm/ledgers'),
    Path('~/.subllm/ledgers'),
)


def default_ledgers(enabled=True, ignore_env=False):
    """Discover local ledger paths when available outside test fixtures."""
    if not enabled:
        return []
    if not ignore_env and (os.getenv('MONAG_NO_DEFAULT_LEDGERS') or os.getenv('PYTEST_CURRENT_TEST')):
        return []
    discovered = []
    for d in DEFAULT_LEDGER_DIRS:
        expanded = Path(d).expanduser()
        if expanded.is_dir() and any(expanded.glob(LEDGER_GLOB)):
            discovered.append(str(expanded))
    return discovered


def agent_accounts(agents, ledgers, home=None):
    """Attach a best-effort provider account email to each agent row.

    Detection reads the CLI's own credential file once per provider; a ledger's
    observed account is the fallback when detection finds nothing.
    """
    ledger_account = {}
    for row in ledgers:
        if row.get('account'):
            ledger_account.setdefault(row['provider'], row['account'])
    detected = {}
    for agent in agents:
        provider = KIND_PROVIDER.get(agent.get('kind'), agent.get('kind'))
        if provider and provider not in detected:
            detected[provider] = (detect_provider_account(provider, home=home)
                                  or ledger_account.get(provider))
        if provider and detected[provider]:
            agent['account'] = detected[provider]


def scan(root, registry=None, machine=False, all_users=False, ledgers=(), proc=Path('/proc'), home=None):
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
    sources = list(ledgers) if ledgers else default_ledgers(enabled=(proc == Path('/proc')))
    ledger_rows, errors = [], []
    for source in sources:
        rows, err = read_ledgers(source, home=home)
        ledger_rows += rows
        errors += err
    agent_accounts(agents, ledger_rows, home=home)
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
             table(['#', 'PID', 'Agent', 'Account', 'State', 'CPU total', 'Memory', 'Uptime', 'Children', 'Directory', 'Task'],
                   ([i + 1, a['pid'], a['kind'], a.get('account') or '—', a['state'],
                     f"{a.get('cpu_seconds_tree') or 0:.0f}s",
                     human_bytes(a.get('rss_bytes')), human_duration(a.get('uptime_seconds')),
                     a['children'], a['cwd'], a.get('task', '—')]
                    for i, a in enumerate(data['agents'][:limit])))]
    if len(data['agents']) > limit:
        parts.append(f"{len(data['agents']) - limit} additional agents; increase --limit.\n")
    if data['agents']:
        parts.append('*open a row: `monag open N[t|b|d|o|p]` (pid:NNNN also works)*\n')
    parts += ['## Account usage\n',
              table(['Provider', 'Account', 'Remaining', 'Balance', 'Reset', 'Last decision', 'Observed', 'Source'],
                    ([r['provider'], r.get('account') or '—',
                      '—' if r['remaining'] is None else int(r['remaining']),
                      r.get('balance') or '—',
                      reset_cell(r), r.get('last_decision') or '—',
                      (r.get('observed_at') or '—')[:19], r['source']] for r in data['ledgers']))]
    if data['ledgers']:
        parts += ['\n## Provider accounts\n',
                  table(['Provider', 'Account', 'Remaining', 'Balance', 'Renewal'],
                        ([r['provider'], r.get('account') or '—',
                          '—' if r['remaining'] is None else int(r['remaining']),
                          r.get('balance') or '—',
                          reset_cell(r)] for r in data['ledgers']))]
    if not data['ledgers']:
        parts.append('Declare ledgers with `--ledger PATH` or `--ledger docker:NAME` '
                     '(`docker:auto` scans coordinator containers).\n')
    for error in data['errors']:
        parts.append(f'observation error: {clean(error)}\n')
    return '\n'.join(parts)


def render(data, limit=12):
    lines = [f"MONAG USAGE | {data['agent_count']} agents | {len(data['ledgers'])} ledgers | {data['observed_at'][:19]}",
             f"{data['root']} | scan {data['duration_seconds']}s", '',
             'AGENTS   #   PID       KIND           ACCOUNT                        STATE  CPU TOTAL    MEMORY     UPTIME   CHILDREN  DIRECTORY']
    for index, agent in enumerate(data['agents'][:limit]):
        account = (agent.get('account') or '—')[:28]
        lines.append(f"  {index + 1:<3} {agent['pid']:<9} {agent['kind']:<14} {account:<30} {agent['state']:<6} "
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
        lines += ['', 'PROVIDERS   PROVIDER     ACCOUNT                        REMAINING  BALANCE       RENEWAL']
        for row in data['ledgers']:
            remaining = '—' if row['remaining'] is None else str(int(row['remaining']))
            account = row.get('account') or '—'
            balance = row.get('balance') or '—'
            lines.append(f"  {row['provider']:<11} {account:<30} {remaining:>9}  {balance:<12}  {reset_cell(row)}")
        lines += ['', 'ACCOUNTS PROVIDER     ACCOUNT                        REMAINING  BALANCE       RESET              LAST DECISION                   SOURCE']
        for row in data['ledgers']:
            remaining = '—' if row['remaining'] is None else str(int(row['remaining']))
            account = row.get('account') or '—'
            balance = row.get('balance') or '—'
            lines.append(f"  {row['provider']:<11} {account:<30} {remaining:>9}  {balance:<12} {reset_cell(row):<18} "
                         f"{(row.get('last_decision') or '—'):<31} {row['source']}")
    else:
        lines += ['', 'ACCOUNTS  none observed — declare --ledger PATH or --ledger docker:NAME (docker:auto scans coordinators)']
    for error in data['errors']:
        lines.append(f'  observation error: {error}')
    return '\n'.join(clean(line) for line in lines)

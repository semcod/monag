"""Read-only Linux process and Git workspace observations; no transcript access."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import time

from .agents import ALIASES, identify
from .cache import run_cached_gh

AGENTS = set(ALIASES)
SKIP = {'.git', '.worktrees', '.subactor', 'node_modules', 'venv', '.venv', '__pycache__', 'build', 'dist'}
# Minimum CPU sampling window; later watch refreshes compare with the previous one.
SAMPLE_SECONDS = 1.0
# A reused repository scan is refreshed after this multiple of its own duration.
REFRESH_FACTOR = 4


def inside(path, root):
    return path == root or root in path.parents


def command(args, cwd=None, timeout=8):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_OPTIONAL_LOCKS='0', GIT_TERMINAL_PROMPT='0', GH_PROMPT_DISABLED='1')
    if args and args[0] == 'gh':
        cached_result = run_cached_gh(args, cwd=cwd, timeout=timeout, env=env)
        if cached_result is not None:
            return cached_result
    try:
        p = subprocess.run(args, cwd=cwd, env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=timeout)
        if p.returncode:
            operation = args[0]
            if args[0] == 'git' and len(args) > 1 and args[1] in {
                    'rev-parse', 'status', 'log', 'show', 'worktree', 'rev-list', 'config'}:
                operation += ' ' + args[1]
            return '', f'{operation} failed (exit {p.returncode})'
        stdout = p.stdout.decode('utf-8', 'replace') if isinstance(p.stdout, (bytes, bytearray)) else str(p.stdout or '')
        return stdout, None
    except (OSError, subprocess.TimeoutExpired) as e:
        return '', f'{args[0]}: {type(e).__name__}'


def agent_name(argv):
    return identify(argv)[0]


def process_record(path, registry=None):
    fields = (path / 'stat').read_text().rsplit(')', 1)[1].split()
    argv = (path / 'cmdline').read_bytes().decode('utf-8', 'replace').strip('\0').split('\0')
    if len(argv) == 1 and ' ' in argv[0] and not Path(argv[0]).exists():
        # Electron and npm rewrite their title into one space-separated string.
        argv = argv[0].split(' ')
    kind, launcher = identify(argv, registry)
    try:
        cwd = str((path / 'cwd').resolve(strict=True))
    except FileNotFoundError:
        cwd = None
    return {'pid': int(path.name), 'ppid': int(fields[1]), 'state': fields[0],
            'start': fields[19], 'kind': kind, 'launcher': launcher,
            'executable': Path(argv[0]).name, 'cwd': cwd,
            # User and system time, including children this process has already reaped.
            'cpu_seconds': sum(int(x) for x in fields[11:15]) / os.sysconf('SC_CLK_TCK')}


def processes(root, proc=Path('/proc'), registry=None, machine=False, all_users=False,
              open_files=False, reported=()):
    records, denied = {}, 0
    for path in proc.iterdir():
        if not path.name.isdigit():
            continue
        try:
            uid = path.stat().st_uid
            if not all_users and uid != os.getuid():
                continue
            row = process_record(path, registry)
            row['uid'] = uid
            records[row['pid']] = row
        except PermissionError:
            denied += 1
        except (OSError, ValueError, IndexError):
            continue
    for task in reported:
        row = records.get(task['pid'])
        if row and row['start'] == task['start'] and task['status'] == 'running':
            row['kind'] = row['kind'] or task.get('agent_kind', 'reported')
            row['reported_task'] = task['task']
    # Only collapse a runtime launcher and its direct same-kind child.
    # Separate native child agents retain their own identities.
    grouped = {}
    for row in records.values():
        parent = records.get(row['ppid'])
        if (row['kind'] and parent and parent.get('launcher') and
                parent['kind'] == row['kind'] and parent['cwd'] == row['cwd']):
            grouped[row['pid']] = parent['pid']
    agent_ids = {p['pid'] for p in records.values() if p['kind'] and p['pid'] not in grouped}
    children = {pid: [] for pid in agent_ids}
    for row in records.values():
        pid, visited = row['pid'], set()
        while pid in records and pid not in visited:
            visited.add(pid)
            if pid in agent_ids:
                if row['pid'] != pid:
                    children[pid].append(row)
                break
            pid = grouped.get(pid, records[pid]['ppid'])
    agents = []
    for pid in sorted(agent_ids):
        row = records[pid]
        if not machine and (not row['cwd'] or not inside(Path(row['cwd']), root)):
            continue
        descendants = children[pid]
        result = dict(row, children=len(descendants), descendants=descendants,
                      child_commands=sorted({p['executable'] for p in descendants}),
                      task=row.get('reported_task', 'unknown (process only)'),
                      working_directories=sorted({p['cwd'] for p in [row, *descendants] if p['cwd']}),
                      cpu_seconds_tree=round(sum(p['cpu_seconds'] for p in [row, *descendants]), 3))
        if open_files:
            files, failures, truncated = set(), 0, False
            for p in [row, *descendants]:
                try:
                    for index, fd in enumerate((proc / str(p['pid']) / 'fd').iterdir()):
                        if index >= 256:
                            truncated = True
                            break
                        try:
                            target = os.readlink(fd)
                            if target.startswith('/'):
                                files.add(target)
                        except OSError:
                            continue
                except PermissionError:
                    failures += 1
                except OSError:
                    continue
            result.update(open_files=sorted(files), open_files_inaccessible=failures,
                          open_files_truncated=truncated)
        agents.append(result)
    return agents, denied


def discover(root, depth=2):
    found = set()
    errors = []
    def visit(path, level):
        if (path / '.git').exists():
            out, error = command(['git', 'worktree', 'list', '--porcelain', '-z'], path)
            if error:
                errors.append(f'{path}: {error}')
            else:
                found.add(path)
            for part in out.split('\0'):
                if part.startswith('worktree '):
                    linked = Path(part[9:])
                    if linked.is_dir() and inside(linked, root):
                        found.add(linked)
            if not error:
                return
        if level >= depth:
            return
        try:
            for child in path.iterdir():
                if child.name not in SKIP and not child.name.startswith('.') and not child.is_symlink() and child.is_dir():
                    visit(child, level + 1)
        except OSError as e:
            errors.append(f'{path}: {type(e).__name__}')
    visit(root, 0)
    return sorted(found), errors


def parse_status(output, path):
    parts = iter(output.split('\0'))
    files = []
    for entry in parts:
        if len(entry) < 4:
            continue
        state, name = entry[:2], entry[3:]
        old = next(parts, None) if 'R' in state or 'C' in state else None
        try:
            modified = (path / name).lstat().st_mtime
        except OSError:
            modified = 0
        files.append({'status': state, 'path': name, 'previous_path': old, 'modified': modified})
    return sorted(files, key=lambda x: x['modified'], reverse=True)


def github_repo(remote):
    match = re.fullmatch(r'(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([^/\s]+/[^/\s]+?)(?:\.git)?/?', remote.strip())
    return match.group(1) if match else None


def inspect_repo(path, since):
    errors = []
    def git(*args):
        out, error = command(['git', *args], path)
        if error:
            errors.append(error)
        return out
    head, head_error = command(['git', 'rev-parse', '--verify', '--quiet', 'HEAD'], path)
    symbolic, _ = command(['git', 'symbolic-ref', '--quiet', '--short', 'HEAD'], path)
    head_state = 'committed'
    if not head:
        any_commit, error = command(['git', 'log', '--all', '-1', '--format=%H'], path)
        head_state = 'unknown' if error or any_commit else 'unborn'
        if head_state == 'unknown':
            errors.append(head_error or 'HEAD unavailable')
    branch = symbolic.strip() or ('HEAD' if head else '(unborn)' if head_state == 'unborn' else 'unknown')
    files = parse_status(git('status', '--porcelain=v1', '-z', '--untracked-files=all'), path)
    log = git('log', '-8', f'--since={since}', '--format=%H%x00%ct%x00%s') if head else ''
    commits = []
    for line in log.splitlines():
        parts = line.split('\0', 2)
        if len(parts) == 3 and parts[1].isdigit():
            commits.append({'sha': parts[0], 'time': int(parts[1]), 'subject': parts[2]})
    recent_files = git('show', '--format=', '--name-only', '-z', '--no-renames', commits[0]['sha']).split('\0') if commits else []
    common = git('rev-parse', '--path-format=absolute', '--git-common-dir').strip()
    remote, _ = command(['git', 'config', '--get', 'remote.origin.url'], path)
    return {'path': str(path), 'branch': branch, 'head_state': head_state, 'files': files, 'commits': commits,
            'github': github_repo(remote), 'common_dir': common, 'errors': errors,
            'recent_committed_files': [f for f in recent_files if f],
            'activity': max([f['modified'] for f in files] + [c['time'] for c in commits] + [0])}


def github_activity(repo, since):
    items, errors = [], []
    for kind in ('issue', 'pr'):
        fields = 'number,title,state,url,updatedAt,closedAt'
        if kind == 'pr':
            fields += ',mergedAt'
        out, error = command(['gh', kind, 'list', '--repo', repo, '--state', 'all',
                              '--search', f'updated:>={since[:10]} sort:updated-desc',
                              '--limit', '20', '--json', fields], timeout=15)
        if error:
            errors.append(f'{repo} {kind}: {error}')
            continue
        try:
            for row in json.loads(out):
                items.append(dict(row, kind=kind, repository=repo))
        except (ValueError, TypeError):
            errors.append(f'{repo}: invalid gh JSON')
    return items, errors


def task_records(state_dir, root, proc=Path('/proc'), machine=False):
    tasks = []
    for path in (state_dir / 'tasks').glob('*.json'):
        try:
            row = json.loads(path.read_text())
            if (not isinstance(row, dict) or not isinstance(row.get('pid'), int)
                    or not isinstance(row.get('start'), str)
                    or not isinstance(row.get('cwd'), str) or not Path(row['cwd']).is_absolute()
                    or not isinstance(row.get('task'), str)
                    or not isinstance(row.get('updated'), (int, float))
                    or row.get('status') not in {'running', 'completed', 'failed'}):
                continue
            if not machine and not inside(Path(row['cwd']), root):
                continue
            if row['status'] == 'running':
                try:
                    current = process_record(proc / str(row['pid']))
                    alive = current['start'] == row['start'] and current['state'] != 'Z'
                except (OSError, ValueError, IndexError):
                    alive = False
                if not alive:
                    row['status'] = 'stale'
            row['id'] = path.stem
            tasks.append(row)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(tasks, key=lambda x: x['updated'], reverse=True)


def checkout_of(cwd, root, machine):
    path = Path(cwd)
    while path != path.parent and (machine or inside(path, root)):
        if (path / '.git').exists():
            out, error = command(['git', 'rev-parse', '--show-toplevel'], path)
            if not error:
                return Path(out.strip())
        path = path.parent
    return None


def repositories(root, depth, since, directories, machine, state):
    """Inspect checkouts; a watch refresh reuses a recent full scan and adds new agent checkouts."""
    if time.monotonic() >= state.get('next', 0):
        started = time.monotonic()
        paths, errors = discover(root, depth)
        state.clear()
        state.update(paths=paths, errors=errors, checkouts={}, rows={}, started=started)
    for cwd in sorted(directories):
        # An agent's shell may work in another checkout than the agent host itself.
        if cwd not in state['checkouts']:
            state['checkouts'][cwd] = checkout_of(cwd, root, machine)
        checkout = state['checkouts'][cwd]
        if checkout and checkout not in state['paths']:
            state['paths'].append(checkout)
    missing = [p for p in state['paths'] if p not in state['rows']]
    with ThreadPoolExecutor(max_workers=8) as pool:
        state['rows'].update(zip(missing, pool.map(lambda p: inspect_repo(p, since), missing)))
    if 'next' not in state:
        # Large workspaces keep repository scanning to a bounded share of watch time.
        state['observed'] = time.monotonic()
        state['next'] = state['observed'] + REFRESH_FACTOR * (state['observed'] - state['started'])
    return [dict(state['rows'][p]) for p in state['paths']], list(state['errors'])


def tree_cpu(agent, proc=Path('/proc')):
    """CPU seconds of a live agent tree, including children its members have reaped."""
    ticks = 0
    for row in [agent, *agent.get('descendants', [])]:
        try:
            fields = (proc / str(row['pid']) / 'stat').read_text().rsplit(')', 1)[1].split()
            if fields[19] == row['start']:
                ticks += sum(int(x) for x in fields[11:15])
        except (OSError, ValueError, IndexError, KeyError):
            continue
    return ticks / os.sysconf('SC_CLK_TCK')


def activity(agents, samples, sampled, proc=Path('/proc')):
    """Set each agent tree's CPU share since its previous sample, or a short first sample."""
    if agents and not samples:
        time.sleep(max(0.0, SAMPLE_SECONDS - (time.monotonic() - sampled)))
    now, current = time.monotonic(), {}
    for agent in agents:
        key = (agent['pid'], agent['start'])
        cpu = tree_cpu(agent, proc)
        since, before = samples.get(key, (sampled, agent.get('cpu_seconds_tree', cpu)))
        window = now - since
        # A process leaving the tree without being reaped by it cannot make activity negative.
        agent['cpu_percent'] = (round(100 * max(0.0, cpu - before) / window, 1)
                                if window > 0 and window >= SAMPLE_SECONDS / 2 else None)
        current[key] = (now, cpu)
    samples.clear()
    samples.update(current)


def checkout_agents(paths, agents):
    """Associate observed host/child directories with their nearest checkout."""
    by_path = {Path(path): [] for path in paths}
    for agent in agents:
        directories = agent.get('working_directories') or [agent.get('cwd')]
        directories = [*directories, *(p.get('cwd') for p in agent.get('descendants', []))]
        for cwd in directories:
            if not cwd:
                continue
            path = Path(cwd)
            nearest = next((p for p in (path, *path.parents) if p in by_path), None)
            if nearest is not None and agent['pid'] not in by_path[nearest]:
                by_path[nearest].append(agent['pid'])
    return {str(path): pids for path, pids in by_path.items()}


def snapshot(root, state_dir, depth=2, since='24 hours ago', github=False, cache=None,
             registry=None, machine=False, all_users=False, open_files=False, agents_only=False):
    """One observation; a cache shared by watch refreshes enables CPU activity and scan reuse."""
    start = time.monotonic()
    persistent = cache is not None
    cache = cache if persistent else {}
    tasks = task_records(state_dir, root, machine=machine)
    agents, denied = processes(root, registry=registry, machine=machine, all_users=all_users,
                               open_files=open_files, reported=tasks)
    sampled = time.monotonic()
    repos, errors, age = [], [], None
    if not agents_only:
        directories = {cwd for a in agents for cwd in a.get('working_directories', [a['cwd']]) if cwd}
        state = cache.setdefault('repositories', {})
        repos, errors = repositories(root, depth, since, directories, machine, state)
        age = round(time.monotonic() - state['observed'], 1)
    if persistent:
        activity(agents, cache.setdefault('cpu', {}), sampled)
    # Most active first, then most recently started: ascending PIDs put new sessions last.
    agents.sort(key=lambda a: (-(a.get('cpu_percent') or 0),
                               -int(a['start']) if str(a.get('start', '')).isdigit() else 0))
    for agent in agents:
        task = next((t for t in tasks if t['pid'] == agent['pid'] and t['start'] == agent['start'] and t['status'] == 'running'), None)
        if task:
            agent['task'] = task['task']
    assignments = checkout_agents([r['path'] for r in repos], agents)
    for repo in repos:
        repo['agents'] = assignments[repo['path']]
    repos.sort(key=lambda r: (bool(r['agents']), r['activity']), reverse=True)
    events = []
    if github:
        names = sorted({r['github'] for r in repos if r['github']})
        def get(name):
            key = (name, since[:10])
            if key not in cache or time.monotonic() - cache[key][0] > 120:
                cache[key] = (time.monotonic(), github_activity(name, since))
            return cache[key][1]
        with ThreadPoolExecutor(max_workers=4) as pool:
            for items, problems in pool.map(get, names):
                events.extend(items)
                errors.extend(problems)
    try:
        boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    except OSError:
        boot_id = 'unknown'
    return {'root': str(root), 'boot_id': boot_id, 'machine': machine,
            'all_users': all_users, 'agents_only': agents_only, 'open_files': open_files, 'observed_at': datetime.now(timezone.utc).isoformat(),
            'agents': agents, 'agent_count': len(agents), 'repositories': repos,
            'repositories_age_seconds': age,
            'tasks': tasks, 'github': sorted(events, key=lambda e: e['updatedAt'], reverse=True),
            'errors': errors, 'inaccessible_processes': denied,
            'duration_seconds': round(time.monotonic() - start, 2)}

"""Open an observed agent session in a terminal or browser.

Selection is by the numbered row of `monag usage` output or an explicit
`pid:NNNN`, optionally followed by an action letter: `open 4t` opens a
terminal (default), `4b`/`4w` a browser route, `4d` the desktop UI,
`4o`/`4f` the working directory in the file manager and `4p` prints the
command without spawning. A bare `monag open` in a terminal shows an
interactive cursor picker instead. IDE-managed ACP adapters are reported,
never respawned.
"""
import contextlib
import os
from pathlib import Path
import re
import select
import shlex
import shutil
import subprocess
import sys

from .agents import ACP

# Verified per-CLI resume entries; a bare executable opens the tool's own
# session picker in the agent's working directory.
TERMINAL = {
    'agy': ['agy', '--continue'],
    'agy2': ['agy', '--continue'],
    'agy-coding-agent': ['agy', '--continue'],
    'claude': ['claude', '--continue'],
    'cursor-agent': ['cursor-agent', '--continue'],
    'codex': ['codex', 'resume'],
    'opencode': ['opencode'],
    'agent': ['agent'],
    'tiny-agents': ['tiny-agents'],
}
# Sessions whose UI lives in a desktop application, not a terminal.
DESKTOP = {'devin': ['devin', 'desktop']}
# Browser routes spawn a local web UI and let it open the browser itself.
BROWSER = {'opencode': ['opencode', 'web']}

ACTION_LETTERS = {
    't': 'terminal', 'b': 'browser', 'w': 'browser',
    'd': 'desktop', 'o': 'files', 'f': 'files', 'p': 'print',
}
ACTIONS = {'terminal', 'browser', 'desktop', 'files', 'print'}


def _wrapped(script):
    return ['sh', '-c', script]


# Terminal launchers ordered by preference; every entry runs a `cd`+`exec`
# script so no per-terminal working-directory flag is needed.
LAUNCHERS = {
    'xdg-terminal-exec': lambda s: ['xdg-terminal-exec', *_wrapped(s)],
    'gnome-terminal': lambda s: ['gnome-terminal', '--', *_wrapped(s)],
    'konsole': lambda s: ['konsole', '-e', *_wrapped(s)],
    'kgx': lambda s: ['kgx', '-e', *_wrapped(s)],
    'alacritty': lambda s: ['alacritty', '-e', *_wrapped(s)],
    'kitty': lambda s: ['kitty', *_wrapped(s)],
    'wezterm': lambda s: ['wezterm', 'start', *_wrapped(s)],
    'xterm': lambda s: ['xterm', '-e', *_wrapped(s)],
    'x-terminal-emulator': lambda s: ['x-terminal-emulator', '-e', *_wrapped(s)],
}
ORDER = tuple(LAUNCHERS)


def parse_target(text):
    """'4', '4t', '4 t', 'pid:2330450b' → (reference, action_letter|None)."""
    parts = str(text).split()
    ref = parts[0] if parts else ''
    letter = ''.join(parts[1:]).lower() or None
    match = re.fullmatch(r'(pid:\d+|\d+)([a-zA-Z])?', ref)
    if match:
        ref = match.group(1)
        letter = letter or (match.group(2).lower() if match.group(2) else None)
    return ref, letter


def resolve_action(letter_or_name, browser=False):
    """Map an action letter or name to a canonical action, or an error."""
    if not letter_or_name:
        return ('browser' if browser else 'terminal'), None
    value = str(letter_or_name).lower()
    action = ACTION_LETTERS.get(value, value)
    if action not in ACTIONS:
        return None, (f'unknown action {letter_or_name!r}; use '
                      't terminal, b/w browser, d desktop, o/f files or p print')
    return action, None


def pick(agents, target):
    """Resolve a usage row number or `pid:NNNN` to one observed agent row."""
    target = str(target).strip()
    if target.startswith('pid:'):
        try:
            pid = int(target[4:])
        except ValueError:
            return None, f'invalid pid reference: {target!r}'
        agent = next((a for a in agents if a['pid'] == pid), None)
        return (agent, None) if agent else (None, f'no observed agent with pid {pid}')
    try:
        index = int(target)
    except ValueError:
        return None, f'expected a row number or pid:NNNN, got {target!r}'
    if 1 <= index <= len(agents):
        return agents[index - 1], None
    agent = next((a for a in agents if a['pid'] == index), None)
    if agent:
        return agent, None
    return None, f'no row {index}; `usage` lists {len(agents)} agents'


AGY_CONVERSATION = re.compile(r'/conversations/([0-9a-f-]{36})\.db$')
AGY_KINDS = {'agy', 'agy2', 'agy-coding-agent'}


def _fd_targets(pid, proc='/proc'):
    """Symlink targets the process holds open; paths only, never file content."""
    directory = Path(proc) / str(pid) / 'fd'
    try:
        entries = os.listdir(directory)
    except OSError:
        return
    for fd in entries:
        try:
            yield os.readlink(directory / fd)
        except OSError:
            continue


def _claude_session(agent, home=None):
    """Newest session file in the cwd's project dir → `claude --resume <id>`.

    Claude does not hold the .jsonl open, so the freshest file in the project
    directory is the best-effort match for the running session.
    """
    base = Path(home).expanduser() if home else Path.home()
    slug = agent.get('cwd', '').rstrip('/').replace('/', '-') or '-'
    try:
        files = list((base / '.claude' / 'projects' / slug).glob('*.jsonl'))
        if not files:
            return None
        newest = max(files, key=lambda f: f.stat().st_mtime)
        return ['claude', '--resume', newest.stem]
    except OSError:
        return None


SOCKET_FD = re.compile(r'socket:\[(\d+)\]')


def _listening_ports(proc='/proc'):
    """inode → 'host:port' for every LISTEN socket in proc/net/tcp{,6}."""
    table = {}
    for name in ('tcp', 'tcp6'):
        try:
            lines = (Path(proc) / 'net' / name).read_text().splitlines()
        except OSError:
            continue
        for line in lines[1:]:
            fields = line.split()
            if len(fields) < 10 or fields[3] != '0A':  # 0A = LISTEN
                continue
            host_hex, port_hex = fields[1].split(':')
            host = host_hex
            if len(host_hex) == 8:  # IPv4 little-endian
                host = '.'.join(str(int(host_hex[i:i + 2], 16))
                                for i in (6, 4, 2, 0))
            table[fields[9]] = f'{host}:{int(port_hex, 16)}'
    return table


def http_endpoint(agent, proc='/proc'):
    """'host:port' the agent process listens on, or None."""
    sockets = set()
    for target in _fd_targets(agent['pid'], proc=proc):
        match = SOCKET_FD.match(target or '')
        if match:
            sockets.add(match.group(1))
    if not sockets:
        return None
    for inode, endpoint in _listening_ports(proc=proc).items():
        if inode in sockets:
            return endpoint
    return None


def _opencode_session(agent, home=None):
    """Newest opencode.db session in the process cwd → `opencode --session <id>`."""
    cwd = agent.get('cwd')
    base = Path(home).expanduser() if home else Path.home()
    db = base / '.local' / 'share' / 'opencode' / 'opencode.db'
    if not cwd or not db.is_file():
        return None
    import sqlite3
    try:
        con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
        try:
            row = con.execute(
                'SELECT id FROM session WHERE directory = ? '
                'ORDER BY time_updated DESC LIMIT 1', (cwd,)).fetchone()
        finally:
            con.close()
    except Exception:
        return None
    return ['opencode', '--session', row[0]] if row and row[0] else None


def session_argv(agent, proc='/proc', home=None):
    """Exact-session resume argv when the running session can be identified."""
    kind = agent.get('kind')
    if kind in AGY_KINDS:
        for target in _fd_targets(agent['pid'], proc=proc):
            match = AGY_CONVERSATION.search(target or '')
            if match:
                return ['agy', '--conversation', match.group(1)]
        return None
    if kind == 'claude':
        return _claude_session(agent, home=home)
    if kind == 'opencode':
        return _opencode_session(agent, home=home)
    return None


def recipe(agent, action='terminal', browser=False, proc='/proc', home=None):
    if browser:
        action = 'browser'
    """Launch argv for one agent row, or (None, reason) when it cannot open."""
    kind = agent.get('kind') or ''
    if action == 'browser':
        if kind == 'opencode':
            endpoint = http_endpoint(agent, proc=proc)
            if endpoint:
                return ['xdg-open', f'http://{endpoint}'], None
        argv = BROWSER.get(kind) or DESKTOP.get(kind)
        if argv:
            return argv, None
        return None, f'no browser route known for {kind or "this agent"}'
    if action == 'desktop':
        argv = DESKTOP.get(kind)
        if argv:
            return argv, None
        return None, f'no desktop route known for {kind or "this agent"}'
    if ACP.fullmatch(kind):
        return None, (f'{kind} is an IDE-managed ACP adapter; '
                      'open the session in its IDE')
    argv = None
    if kind == 'opencode':
        endpoint = http_endpoint(agent, proc=proc)
        if endpoint:
            # Live attach beats session-file resume: the running TUI server
            # already holds this session in memory.
            argv = ['opencode', 'attach', f'http://{endpoint}']
    argv = (argv or session_argv(agent, proc=proc, home=home)
            or TERMINAL.get(kind) or DESKTOP.get(kind))
    if argv:
        return argv, None
    # Unknown kinds still get a best-effort bare relaunch of a native binary.
    if not agent.get('launcher') and agent.get('executable'):
        return [agent['executable']], None
    return None, f'no terminal recipe for {kind or "unidentified"} (pid {agent["pid"]})'


def terminal_argv(script, env=None):
    """First available terminal launcher's argv for a `cd && exec` script."""
    env = os.environ if env is None else env
    override = env.get('MONAG_TERMINAL')
    if override:
        build = LAUNCHERS.get(override)
        return (build or (lambda s: [override, '-e', *_wrapped(s)]))(script)
    for name in ORDER:
        if shutil.which(name, path=env.get('PATH')):
            return LAUNCHERS[name](script)
    return None


def _spawn(spawn, argv, cwd):
    spawn(argv, cwd=cwd, start_new_session=True,
          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_agent(agent, action='terminal', browser=False, dry_run=False, env=None,
               spawn=subprocess.Popen, proc='/proc', home=None):
    if browser:
        action = 'browser'
    """Open one agent row; returns (ok, message)."""
    cwd = agent.get('cwd')
    label = f"{agent.get('kind') or 'agent'} pid {agent['pid']}"
    if not cwd:
        return False, f"pid {agent['pid']}: working directory is unavailable"
    if action == 'files':
        argv = ['xdg-open', cwd]
        if dry_run:
            return True, ' '.join(map(shlex.quote, argv))
        _spawn(spawn, argv, cwd)
        return True, f'opened file manager for {label}: {cwd}'
    argv, problem = recipe(agent, action, proc=proc, home=home)
    if argv is None:
        return False, problem
    if action in {'browser', 'desktop'} or argv in DESKTOP.values():
        if dry_run:
            return True, f"cd {shlex.quote(cwd)} && {' '.join(map(shlex.quote, argv))}"
        _spawn(spawn, argv, cwd)
        return True, f'opened {label}: {" ".join(argv)} in {cwd}'
    script = 'cd %s && exec %s' % (shlex.quote(cwd), ' '.join(map(shlex.quote, argv)))
    if dry_run:
        return True, script
    argv_terminal = terminal_argv(script, env=env)
    if argv_terminal is None:
        return False, f'no terminal emulator found; run manually: {script}'
    spawn(argv_terminal, start_new_session=True,
          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True, f'opened {label} in a terminal: {argv[0]} in {cwd}'


def open_target(agents, target, action=None, browser=False, dry_run=False,
                env=None, spawn=subprocess.Popen, proc='/proc', home=None):
    ref, letter = parse_target(target)
    if action and letter:
        return False, 'action given twice; use either `open N t` or `open Nt`'
    action, problem = resolve_action(action or letter, browser=browser)
    if action is None:
        return False, problem
    if action == 'print':
        action, dry_run = 'terminal', True
    agent, problem = pick(agents, ref)
    if agent is None:
        return False, problem
    return open_agent(agent, action=action, dry_run=dry_run, env=env, spawn=spawn,
                      proc=proc, home=home)


PICKER_HINT = 'arrows/j/k move · t terminal · b browser · d desktop · o files · p print · Enter open · q quit'


def _read_key(stream):
    """One keypress → 'up', 'down', 'enter', 'quit', or a single character."""
    ch = stream.read(1)
    if ch == '\x1b':
        # Arrow keys arrive as ESC [ A/B; a bare Esc means quit. The select
        # guard keeps a lone Esc from blocking on the escape-sequence read.
        if hasattr(stream, 'fileno'):
            try:
                if select.select([stream], [], [], 0.05)[0]:
                    seq = stream.read(2)
                    if seq == '[A':
                        return 'up'
                    if seq == '[B':
                        return 'down'
            except (OSError, ValueError):
                pass
        return 'quit'
    if ch in ('\r', '\n'):
        return 'enter'
    if ch in ('\x03', '\x04'):  # Ctrl-C, Ctrl-D
        return 'quit'
    if ch == 'k':
        return 'up'
    if ch == 'j':
        return 'down'
    if ch == 'q':
        return 'quit'
    return ch


def choose(agents, limit=None, stream=None, out=None, default_action='terminal'):
    """Interactive row picker; returns (agent, action) or (None, None) on quit."""
    rows = list(agents[:limit] if limit else agents)
    if not rows:
        return None, None
    stream = stream or sys.stdin
    out = out or sys.stdout
    index, drawn = 0, 0
    while True:
        lines = [f'  {PICKER_HINT}']
        for i, a in enumerate(rows):
            mark = '>' if i == index else ' '
            account = (a.get('account') or '—')[:28]
            lines.append(f'{mark} {i + 1:<3} {a["pid"]:<9} {a["kind"]:<14} {account:<30} {a["cwd"]}')
        if drawn:
            out.write(f'\x1b[{drawn}F')
        out.write('\n'.join(lines) + '\n')
        out.flush()
        drawn = len(lines)
        key = _read_key(stream)
        if key == 'quit':
            return None, None
        if key == 'up':
            index = (index - 1) % len(rows)
        elif key == 'down':
            index = (index + 1) % len(rows)
        elif key == 'enter':
            return rows[index], default_action
        elif key in ACTION_LETTERS:
            return rows[index], ACTION_LETTERS[key]


@contextlib.contextmanager
def _cbreak(stream):
    """Put a tty in cbreak mode so keypresses arrive without Enter."""
    import termios
    import tty
    fd = stream.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def open_interactive(agents, limit=None, default_action='terminal', dry_run=False,
                     env=None, spawn=subprocess.Popen, stream=None, out=None,
                     proc='/proc', home=None):
    """Cursor-picker entry point for a bare `monag open`."""
    stream = stream or sys.stdin
    if not stream.isatty():
        return False, 'no row given; `monag open N[t|b|d|o|p]` or run in a terminal for the picker'
    with _cbreak(stream):
        agent, action = choose(agents, limit=limit, stream=stream, out=out,
                               default_action=default_action)
    if agent is None:
        return False, 'selection cancelled'
    if action == 'print':
        action, dry_run = 'terminal', True
    return open_agent(agent, action=action, dry_run=dry_run, env=env, spawn=spawn,
                      proc=proc, home=home)

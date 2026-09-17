"""Open an observed agent session in a terminal or browser.

Selection is by the numbered row of `monag usage` output or an explicit
`pid:NNNN`, optionally followed by an action letter: `open 4t` opens a
terminal (default), `4b`/`4w` a browser route, `4d` the desktop UI,
`4o`/`4f` the working directory in the file manager and `4p` prints the
command without spawning. IDE-managed ACP adapters are reported, never
respawned.
"""
import os
import re
import shlex
import shutil
import subprocess

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


def recipe(agent, action='terminal', browser=False):
    if browser:
        action = 'browser'
    """Launch argv for one agent row, or (None, reason) when it cannot open."""
    kind = agent.get('kind') or ''
    if action == 'browser':
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
    argv = TERMINAL.get(kind) or DESKTOP.get(kind)
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


def open_agent(agent, action='terminal', browser=False, dry_run=False, env=None, spawn=subprocess.Popen):
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
    argv, problem = recipe(agent, action)
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
                env=None, spawn=subprocess.Popen):
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
    return open_agent(agent, action=action, dry_run=dry_run, env=env, spawn=spawn)

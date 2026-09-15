"""Terminal dashboard and explicit task wrapper."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid

from .monitor import process_record, snapshot
from .agents import aliases
from . import history
from .doctor import diagnose
from . import presentation


def safe(value):
    # Filenames, commit subjects and titles can contain terminal control sequences.
    return ''.join(c if c.isprintable() else '?' for c in str(value))


def event_line(event):
    stamp = datetime.fromtimestamp(event['observed']).strftime('%m-%d %H:%M:%S')
    subject = event.get('agent') or event.get('process') or event.get('task') or {}
    if not isinstance(subject, dict):
        subject = {'task': subject}
    details = [str(subject.get('pid', event.get('agent_pid', ''))),
               subject.get('kind', subject.get('executable', '')),
               subject.get('cwd', event.get('project', '')),
               event.get('file', event.get('subject', event.get('title', subject.get('task', ''))))]
    return safe(f"{stamp} {event['kind']:<23} " + ' | '.join(str(x) for x in details if x))


def render(data, limit=12):
    lines = [f"MONAG | {data['agent_count']} agent processes | {len(data['repositories'])} checkouts | {data['observed_at'][:19]}",
             f"{data['root']} | scan {data['duration_seconds']}s", '', 'AGENTS / CURRENT DIRECTORIES']
    if not data['agents']:
        lines.append('  No recognized agent processes in this workspace.')
    for a in data['agents']:
        lines.append(f"  PID {a['pid']:<7} {a['kind']:<13} state={a['state']} children={a['children']}  {a['cwd']}")
        lines.append(f"    task: {a['task']}")
        for cwd in a.get('working_directories', []):
            if cwd != a['cwd']:
                lines.append(f'    working directory of child: {cwd}')
        if a.get('cpu_seconds_tree') is not None:
            lines.append(f"    CPU total (live process tree): {a['cpu_seconds_tree']}s")
        for path in a.get('open_files', [])[:4]:
            lines.append(f'    open: {path}')
        if a.get('child_commands'):
            lines.append('    child processes: ' + ', '.join(a['child_commands']))
    lines += ['', 'PROJECTS / WORKTREES (active first, then recent activity)']
    for r in data['repositories'][:limit]:
        overlap = '  !! MULTIPLE AGENTS IN CHECKOUT' if len(r['agents']) > 1 else ''
        lines.append(f"  {r['path']} [{r['branch']}] agents={len(r['agents'])} changed={len(r['files'])}{overlap}")
        for f in r['files'][:4]:
            lines.append(f"    {f['status']} {f['path']}")
        if len(r['files']) > 4:
            lines.append(f"    ... {len(r['files']) - 4} more files (use --json)")
        if r.get('recent_committed_files'):
            lines.append('    latest commit files: ' + ', '.join(r['recent_committed_files'][:3]))
        for error in r['errors']:
            lines.append(f'    observation error: {error}')
    commits = {}
    for r in data['repositories']:
        for c in r['commits']:
            commits.setdefault((r['common_dir'] or r['path'], c['sha']), dict(c, project=r['path']))
    lines += ['', 'RECENT COMMITS (Git evidence; not proof of task completion)']
    for c in sorted(commits.values(), key=lambda c: c['time'], reverse=True)[:limit]:
        stamp = datetime.fromtimestamp(c['time']).strftime('%m-%d %H:%M')
        lines.append(f"  {stamp} {c['sha'][:8]} {c['project']}  {c['subject']}")
    if data['tasks']:
        lines += ['', 'REPORTED TASKS']
        for t in data['tasks'][:limit]:
            lines.append(f"  {t['status']:<9} PID {t['pid']} {t['task']} | {t['cwd']} | issue={t.get('issue') or '-'} PR={t.get('pr') or '-'}")
    if data['github']:
        lines += ['', 'RECENT GITHUB ISSUES / PULL REQUESTS']
        for e in data['github'][:limit]:
            state = 'MERGED' if e.get('mergedAt') else e['state']
            lines.append(f"  {e['repository']} {e['kind']} #{e['number']} {state} {e['title']}")
            lines.append(f"    {e['url']}")
    for error in data['errors']:
        lines.append(f'  observation error: {error}')
    if data['inaccessible_processes']:
        lines.append(f"  Inaccessible processes: {data['inaccessible_processes']}")
    if data.get('events'):
        lines += ['', 'NEW OBSERVATIONS (local history)']
        for event in data['events'][-limit:]:
            lines.append('  ' + event_line(event))
    return '\n'.join(safe(line) for line in lines)


def save_task(path, row):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(row, ensure_ascii=True))
    temp.chmod(0o600)
    temp.replace(path)


def run_task(args):
    argv = args.command
    if argv and argv[0] == '--':
        argv = argv[1:]
    if not argv:
        raise ValueError('run requires a command after --')
    folder = args.state_dir / 'tasks'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / f'{uuid.uuid4().hex}.json'
    child = subprocess.Popen(argv)
    row = {'pid': child.pid, 'start': '', 'cwd': str(Path.cwd()), 'task': args.task,
           'issue': args.issue, 'pr': args.pr, 'agent_kind': args.agent_kind,
           'status': 'running', 'updated': time.time()}
    try:
        row['start'] = process_record(Path('/proc') / str(child.pid))['start']
    except (OSError, ValueError, IndexError):
        pass
    try:
        save_task(path, row)
    except OSError:
        child.terminate()
        child.wait()
        raise
    def forward(signum, frame):
        if child.poll() is None:
            child.send_signal(signum)
    handlers = {s: signal.signal(s, forward) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        code = child.wait()
    finally:
        for s, handler in handlers.items():
            signal.signal(s, handler)
    row.update(status='completed' if code == 0 else 'failed', exit_code=code, updated=time.time())
    save_task(path, row)
    return code if code >= 0 else 128 - code


def main(argv=None):
    parser = argparse.ArgumentParser(description='Monitor local agents and Git workspace activity (Linux). No command: interactive watch in a terminal, otherwise one snapshot.')
    parser.set_defaults(interval=5, no_record=False, retention_days=7)
    parser.add_argument('--root', type=Path, default=Path.home() / 'github')
    parser.add_argument('--state-dir', type=Path, default=Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'monag')
    parser.add_argument('--depth', type=int, default=2, help='repository discovery depth (default: owner/repo)')
    parser.add_argument('--hours', type=float, default=24)
    parser.add_argument('--limit', type=int, default=12, help='rows per section; JSON includes all observed rows')
    parser.add_argument('--github', action='store_true', help='read issues/PRs through authenticated gh; cache for 120s')
    parser.add_argument('--machine', action='store_true', help='include agent processes outside --root')
    parser.add_argument('--all-users', action='store_true', help='include accessible processes of other users')
    parser.add_argument('--agents-only', action='store_true', help='fast process view without repository scanning')
    parser.add_argument('--open-files', action='store_true', help='observe open file paths in agent process trees')
    parser.add_argument('--agent', action='append', default=[], metavar='LABEL=EXECUTABLE', help='register an additional executable name; repeatable')
    formats = parser.add_mutually_exclusive_group()
    formats.add_argument('--format', dest='output', choices=['auto', 'terminal', 'markdown', 'plain', 'json'], default='auto')
    formats.add_argument('--json', dest='output', action='store_const', const='json', help='JSON snapshot, or JSON lines with watch')
    formats.add_argument('--markdown', dest='output', action='store_const', const='markdown', help='export raw Markdown with tables and a text diagram')
    formats.add_argument('--plain', dest='output', action='store_const', const='plain', help='plain text without terminal formatting')
    parser.add_argument('--view', choices=['all', 'agents', 'projects', 'tree', 'history'], default='all', help='section shown in terminal and Markdown reports')
    sub = parser.add_subparsers(dest='mode')
    status = sub.add_parser('status', help='one snapshot and exit')
    status.add_argument('--record', action='store_true', help='save changes to local history')
    sub.add_parser('doctor', help='diagnose dependencies and process visibility')
    resume_parser = sub.add_parser('resume', help='read-only restart inventory of worktrees and local Planfile backlog')
    resume_parser.add_argument('--sort', choices=['backlog', 'priority', 'changes'], default='backlog',
                               help='project ranking (priority uses highest remaining Planfile priority)')
    resume_parser.add_argument('--priority', dest='priorities', action='append',
                               choices=['critical', 'high', 'medium', 'normal', 'low', 'unknown'],
                               help='show only tickets with this Planfile priority; repeat to select several')
    resume_parser.add_argument('--all-projects', action='store_true')
    audit_parser = sub.add_parser('audit', help='read-only report of Planfile ticket coverage against GitHub Issues, '
                                                'for one repository or every repository under --root')
    audit_parser.add_argument('--issue-limit', type=int, default=200,
                              help='GitHub issues fetched per repository via gh (default: 200)')
    sub.add_parser('catalog', help='read-only, local-only catalog of what each repository under --root '
                                   'declares itself to be (description, stack, entry points)')
    panel = sub.add_parser('panel', help='serve a local-only HTTP dashboard (agents, repositories, '
                                         'Planfile backlog, on-demand audit/catalog); Ctrl-C to stop')
    panel.add_argument('--port', type=int, default=8090)
    panel.add_argument('--bind', default='127.0.0.1',
                       help='listen address (default: localhost only; widen only if you mean to)')
    panel.add_argument('--panel-interval', dest='panel_interval', type=float, default=30,
                       help='background refresh seconds for the live snapshot/resume view (default: 30)')
    timeline = sub.add_parser('history', help='read local recorded observations')
    timeline.add_argument('--kind')
    timeline.add_argument('--search')
    watch = sub.add_parser('watch', help='refresh until Ctrl-C (default in a terminal)')
    watch.add_argument('--no-record', action='store_true', help='disable local history recording')
    watch.add_argument('--retention-days', type=int, default=7)
    watch.add_argument('--interval', type=float, default=5)
    run = sub.add_parser('run', help='wrap an agent command with an explicit task description')
    run.add_argument('--agent-kind', default='reported', help='label for an otherwise unknown agent')
    run.add_argument('--task', required=True)
    run.add_argument('--issue')
    run.add_argument('--pr')
    run.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.mode is None:
        args.mode = ('watch' if sys.stdout.isatty() and args.output not in {'json', 'markdown'}
                     else 'status')
    if sys.platform != 'linux':
        parser.error('process monitoring currently requires Linux /proc')
    if args.depth < 0 or args.limit < 1 or not 0 < args.hours < 876000:
        parser.error('depth >= 0, limit >= 1 and 0 < hours < 876000 required')
    if args.mode == 'watch' and not 0.2 <= args.interval < 86400:
        parser.error('interval must be between 0.2 and 86400 seconds')
    if args.mode == 'audit' and args.issue_limit < 1:
        parser.error('issue-limit must be >= 1')
    if args.mode == 'panel' and not (1 <= args.port <= 65535 and 1 <= args.panel_interval < 86400):
        parser.error('port must be 1-65535 and panel-interval must be >= 1 second')
    stack = ExitStack()
    try:
        output_format = args.output
        if output_format == 'auto':
            output_format = 'terminal' if sys.stdout.isatty() and os.environ.get('TERM') != 'dumb' else 'plain'
        console = None
        if output_format == 'terminal':
            from rich.console import Console
            from rich.markdown import Markdown
            from rich.live import Live
            console = Console(highlight=False)
        live = None
        def display_report(document):
            if console is not None:
                console.print(Markdown(document))
            else:
                print(document, end='' if document.endswith('\n') else '\n', flush=True)
        args.state_dir = args.state_dir.expanduser().resolve()
        registry = aliases(args.agent)
        if args.mode == 'watch' and not 1 <= args.retention_days <= 365:
            parser.error('retention-days must be between 1 and 365')
        if args.mode == 'doctor':
            data = diagnose(args.root.expanduser().resolve())
            if output_format in {'terminal', 'markdown'}:
                display_report(presentation.doctor_markdown(data))
            else:
                print(json.dumps(data, indent=2) if output_format == 'json' else '\n'.join(safe(f'{k}: {v}') for k, v in data.items()))
            return int(bool(data['errors']))
        if args.mode == 'history':
            data = history.read(args.state_dir, args.limit, args.kind, args.search, args.hours)
            if output_format in {'terminal', 'markdown'}:
                display_report(presentation.history_markdown(data))
            else:
                print(json.dumps(data, ensure_ascii=True) if output_format == 'json' else '\n'.join(event_line(e) for e in data) or 'No recorded observations.')
            return 0
        if args.mode == 'run':
            return run_task(args)
        root = args.root.expanduser().resolve(strict=True)
        if not root.is_dir():
            parser.error('--root must be a directory')
        if args.mode == 'resume':
            from . import resume
            if output_format != 'json' and sys.stderr.isatty():
                print('MONAG: skanuję repozytoria i worktree; Ctrl-C przerywa bez zmian.', file=sys.stderr, flush=True)
            data = resume.scan(root, args.depth, args.sort, args.priorities)
            if output_format == 'json':
                print(json.dumps(data, ensure_ascii=True))
            else:
                display_report(resume.markdown(data, args.limit, args.all_projects))
            return 0
        if args.mode == 'audit':
            from . import audit
            if output_format != 'json' and sys.stderr.isatty():
                print('MONAG: scanning repositories and querying GitHub via gh; this can take a while.',
                     file=sys.stderr, flush=True)
            data = audit.scan(root, args.depth, args.issue_limit)
            if output_format == 'json':
                print(json.dumps(data, ensure_ascii=True))
            else:
                display_report(audit.markdown(data, args.limit))
            return 0
        if args.mode == 'catalog':
            from . import catalog
            if output_format != 'json' and sys.stderr.isatty():
                print('MONAG: scanning repositories for self-declared metadata (no network calls).',
                     file=sys.stderr, flush=True)
            data = catalog.scan(root, args.depth)
            if output_format == 'json':
                print(json.dumps(data, ensure_ascii=True))
            else:
                display_report(catalog.markdown(data, args.limit))
            return 0
        if args.mode == 'panel':
            from . import panel
            print(f'MONAG: panel serving http://{args.bind}:{args.port}/ (Ctrl-C to stop).',
                 file=sys.stderr, flush=True)
            panel.serve(root, args.state_dir, args.depth, args.bind, args.port, args.panel_interval,
                       registry, args.github, args.machine, args.all_users, args.open_files)
            return 0
        cache = {}
        if console is not None and args.mode == 'watch' and sys.stdout.isatty():
            loading = Markdown('# MONAG\n\nScanning workspace… Press Ctrl-C to exit.')
            live = Live(loading, console=console, screen=True, auto_refresh=False, vertical_overflow='ellipsis')
            stack.callback(live.stop)
            # Rich.stop requires start to finish registering its render hook.
            # Defer Ctrl-C only during this short terminal initialization.
            previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
            try:
                live.start(refresh=True)
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        while True:
            since = (datetime.now(timezone.utc) - timedelta(hours=args.hours)).isoformat()
            # Stable cache key for repeated scans in the same UTC day.
            data = snapshot(root, args.state_dir, args.depth, since, args.github, cache,
                            registry, args.machine, args.all_users, args.open_files, args.agents_only)
            data['detector_scope'] = sorted(args.agent)
            if getattr(args, 'record', False) or (args.mode == 'watch' and not args.no_record):
                data['events'] = history.record(args.state_dir, data, getattr(args, 'retention_days', 7))
            if output_format == 'json':
                print(json.dumps(data, ensure_ascii=True), flush=True)
            elif output_format in {'terminal', 'markdown'}:
                document = presentation.markdown(data, args.limit, args.view)
                if console is not None and args.mode == 'watch' and sys.stdout.isatty():
                    live.update(Markdown(document), refresh=True)
                else:
                    display_report(document)
            else:
                output = render(data, args.limit)
                if args.mode == 'watch' and sys.stdout.isatty():
                    size = shutil.get_terminal_size()
                    output = '\n'.join(line[:size.columns] for line in output.splitlines()[:max(1, size.lines - 1)])
                    print('\033[2J\033[H', end='')
                print(output, flush=True)
            if args.mode != 'watch':
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 0
    except (OSError, ValueError, history.sqlite3.Error) as e:
        parser.exit(1, f'monag: {e}\n')
    finally:
        stack.close()

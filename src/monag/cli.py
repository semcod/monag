"""Terminal dashboard, interactive shell and explicit task wrapper."""
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
from . import __version__


SHELL_COMMANDS = {
    'refresh': 'odśwież status i backlog Planfile',
    'status': 'pokaż jeden snapshot agentów i checkoutów',
    'usage': 'pokaż tabelę zużycia agentów i kont',
    'open': 'otwórz wiersz `usage` (open N, open 4t/4b/4d/4o/4p, open pid:NNNN lub sam open = wybór kursorem)',
    'resume': 'pokaż worktree, lease i otwarte tickety Planfile',
    'audit': 'porównaj lokalne tickety Planfile z GitHub Issues',
    'prs': 'sprawdź status Pull Requestów i gałęzi (open/merged)',
    'pr': 'alias dla prs',
    'merge': 'scal Pull Request (merge N, merge URL lub merge --all)',
    'query': 'zapytanie w języku naturalnym (PL/EN) lub DSL (OBSERVE ...)',
    'catalog': 'pokaż lokalny katalog projektów',
    'history': 'pokaż zapisane obserwacje',
    'report': 'wygeneruj raport email z aktywności workspace',
    'advise': 'rekomendacje kolejnych zadań z wytycznymi na bazie reflex',
    'help': 'pokaż tę pomoc',
    'quit': 'zakończ powłokę',
}


def shell_help():
    """Return a short, stable command reference for the interactive shell."""
    lines = ['MONAG shell — polecenia:']
    lines.extend(f'  {name:<8} {description}' for name, description in SHELL_COMMANDS.items())
    lines.append('  exit     alias dla quit')
    lines.append('')
    lines.append('Możesz także wpisywać zapytania bezpośrednio w języku naturalnym, np.:')
    lines.append('  pokaż niescalone PR')
    lines.append('  stan procesów agentów')
    lines.append('  audyt ticketów Planfile')
    lines.append('  OBSERVE prs STATE open HOURS 12')
    lines.append('')
    lines.append('Raporty są tylko obserwacją. Synchronizację wykonaj jawnie:')
    lines.append('  planfile sync github --direction both')
    return '\n'.join(lines)


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
    parser = argparse.ArgumentParser(prog='monag', description='Monitor local agents and Git workspace activity (Linux). No command: interactive shell in a terminal, otherwise one snapshot.')
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    parser.set_defaults(interval=5, no_record=False, retention_days=7)
    parser.add_argument('--root', type=Path, default=Path.home() / 'github')
    parser.add_argument('--state-dir', type=Path, default=Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'monag')
    parser.add_argument('--depth', type=int, default=2, help='repository discovery depth (default: owner/repo)')
    parser.add_argument('--hours', type=float, default=24)
    parser.add_argument('--limit', type=int, default=30, help='rows per section; JSON includes all observed rows')
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

    common_sub_parser = argparse.ArgumentParser(add_help=False)
    common_sub_parser.add_argument('--root', type=Path, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common_sub_parser.add_argument('--state-dir', type=Path, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common_sub_parser.add_argument('--depth', type=int, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common_sub_parser.add_argument('--format', dest='output', choices=['auto', 'terminal', 'markdown', 'plain', 'json'], default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common_sub_parser.add_argument('--json', dest='output', action='store_const', const='json', default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common_sub_parser.add_argument('--markdown', dest='output', action='store_const', const='markdown', default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common_sub_parser.add_argument('--plain', dest='output', action='store_const', const='plain', default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    sub = parser.add_subparsers(dest='mode')
    status = sub.add_parser('status', parents=[common_sub_parser], help='one snapshot and exit')
    status.add_argument('--record', action='store_true', help='save changes to local history')
    doctor_parser = sub.add_parser('doctor', parents=[common_sub_parser], help='diagnose dependencies, worktrees, and process visibility')
    doctor_parser.add_argument('--fix', action='store_true', help='automatically prune orphaned worktrees, remove merged ticket branches, and run housekeeping')
    usage_parser = sub.add_parser('usage', parents=[common_sub_parser], help='read-only table of agent process usage '
                                              'and api-budget account ledgers')
    usage_parser.add_argument('--ledger', action='append', default=[], metavar='SOURCE',
                              help='api-budget ledger source; repeatable: a state file, a directory '
                                   'of api-budget-*.json, docker:CONTAINER or docker:auto '
                                   '(coordinator containers on this host)')
    open_parser = sub.add_parser('open', parents=[common_sub_parser], help='open one numbered `usage` row; append an action '
                                            'letter (t/b/d/o/p) or use --browser')
    open_parser.add_argument('target', nargs='?',
                             help='row number from `usage`, or pid:NNNN; an action '
                                  'letter may be appended (4t, 4b, 4d, 4o, 4p). '
                                  'Omit for the interactive picker')
    open_parser.add_argument('action', nargs='?',
                             help='action letter or name: t terminal, b/w browser, '
                                  'd desktop, o/f files, p print')
    open_parser.add_argument('--browser', action='store_true',
                             help='use the web/desktop UI route instead of a terminal')
    open_parser.add_argument('--print', dest='print_only', action='store_true',
                             help='print the launch command without spawning anything')
    resume_parser = sub.add_parser('resume', parents=[common_sub_parser], help='read-only restart inventory of worktrees and local Planfile backlog')
    resume_parser.add_argument('--sort', choices=['backlog', 'priority', 'changes'], default='backlog',
                               help='project ranking (priority uses highest remaining Planfile priority)')
    resume_parser.add_argument('--priority', dest='priorities', action='append',
                               choices=['critical', 'high', 'medium', 'normal', 'low', 'unknown'],
                               help='show only tickets with this Planfile priority; repeat to select several')
    resume_parser.add_argument('--all-projects', action='store_true')
    audit_parser = sub.add_parser('audit', parents=[common_sub_parser], help='read-only report of Planfile ticket coverage against GitHub Issues, '
                                                'for one repository or every repository under --root')
    audit_parser.add_argument('--issue-limit', type=int, default=200,
                              help='GitHub issues fetched per repository via gh (default: 200)')
    audit_parser.add_argument('--within', type=float, default=None, metavar='HOURS',
                              help='also list GitHub issues updated within the last N hours '
                                   '(e.g. --within 1 for the last hour); default: off')
    audit_parser.add_argument('--last-hour', dest='last_hour', action='store_true',
                              help='shortcut for --within 1')
    audit_parser.add_argument('--worktrees-only', '--worktrees-summary',
                              dest='worktrees_only', action='store_true',
                              help='report only local worktree activity and uncommitted status; '
                                   'skip GitHub issue queries')
    audit_parser.add_argument('--worktrees-hours', type=float, default=10.0, metavar='HOURS',
                              help='time window in hours for worktree commit recency (default: 10)')
    prs_parser = sub.add_parser('prs', aliases=['pr'], parents=[common_sub_parser],
                                help='read-only audit of GitHub Pull Requests and local branch merge status')
    prs_parser.add_argument('--hours', '--within', dest='hours', type=float, default=24.0, metavar='HOURS',
                            help='time window in hours for PR recency and activity filtering (default: 24)')
    prs_parser.add_argument('--state', choices=['all', 'open', 'merged'], default='all',
                            help='filter PRs by state (default: all)')
    prs_parser.add_argument('--unpushed-only', action='store_true',
                            help='show only local branches with unpushed commits or no PR')
    prs_parser.add_argument('--all-repos', action='store_true',
                            help='query GitHub PRs for all discovered repositories under --root, ignoring recency filter')
    prs_parser.add_argument('--pr-limit', type=int, default=200,
                            help='maximum PRs to fetch per repository via gh (default: 200)')
    prs_parser.add_argument('--merge', action='store_true',
                            help='merge open Pull Requests observed in scan')
    prs_parser.add_argument('--merge-pr', dest='merge_pr', default=None, metavar='TARGET',
                            help='merge a specific Pull Request (PR number, repo#number, or full GitHub PR URL)')
    prs_parser.add_argument('--method', choices=['squash', 'merge', 'rebase'], default='squash',
                            help='merge strategy to apply (default: squash)')
    prs_parser.add_argument('--bypass', action='store_true', default=True,
                            help='bypass branch protection rules if permissions allow (default: True)')
    prs_parser.add_argument('--browser', action='store_true',
                            help='use Browser CDP instead of gh CLI')
    merge_parser = sub.add_parser('merge', parents=[common_sub_parser], help='merge a GitHub Pull Request via gh or browser CDP')
    merge_parser.add_argument('target', nargs='?', default=None,
                             help='PR number, repo#number, or full GitHub PR URL')
    merge_parser.add_argument('--all', dest='merge_all', action='store_true',
                             help='merge all open PRs in active repositories')
    merge_parser.add_argument('--method', choices=['squash', 'merge', 'rebase'], default='squash',
                             help='merge strategy (default: squash)')
    merge_parser.add_argument('--bypass', action='store_true', default=True,
                             help='bypass rules if permissions allow')
    merge_parser.add_argument('--browser', action='store_true',
                             help='use browser CDP')
    sub.add_parser('mcp', parents=[common_sub_parser], help='run Model Context Protocol (MCP) server over stdio for AI agents')
    query_parser = sub.add_parser('query', aliases=['ask'], parents=[common_sub_parser],
                                  help='execute a natural language query or OBSERVE DSL command')
    query_parser.add_argument('query', nargs='+', help='natural language query phrase or OBSERVE DSL command')
    dsl_parser = sub.add_parser('dsl', parents=[common_sub_parser], help='execute one validated OBSERVE statement')
    dsl_parser.add_argument('query', nargs='+', help='canonical OBSERVE DSL')
    sub.add_parser('catalog', parents=[common_sub_parser], help='read-only, local-only catalog of what each repository under --root '
                                   'declares itself to be (description, stack, entry points)')
    export_parser = sub.add_parser('export', parents=[common_sub_parser], help='read-only staging list of candidate work items '
                                                   '(untracked GitHub issues, undescribed repositories) '
                                                   'for human review; creates, imports or claims nothing')
    export_parser.add_argument('--issue-limit', type=int, default=200,
                               help='GitHub issues fetched per repository via gh (default: 200)')
    export_parser.add_argument('--radar', action='store_true',
                               help='size each candidate with subactor/ticket-radar when installed '
                                    '(complexity, score, time estimate, split recommendation); '
                                    'a missing/failing radar leaves a candidate unsized, never guessed')
    export_parser.add_argument('--hygiene', action='store_true',
                               help="add a candidate per repository where semcod/taskill's read-only "
                                    "'status' (never 'run') reports it would update README/CHANGELOG/"
                                    "TODO; a missing/failing taskill checks nothing, never assumes clean")
    report_parser = sub.add_parser('report', parents=[common_sub_parser], help='workspace activity digest sent via email; '
                                                   'collects data from status, prs, audit, resume '
                                                   'and export, then sends a Markdown/HTML email')
    report_parser.add_argument('--email', dest='report_email', action='append', default=[],
                               metavar='ADDR', help='recipient email address; repeatable')
    report_parser.add_argument('--sections', dest='report_sections', default=None,
                               help='comma-separated list of sections to include '
                                    '(status,prs,audit,resume,export,advise); default: all')
    report_parser.add_argument('--advisory-limit', dest='advisory_limit', type=int, default=5,
                               help='number of recommendations to include in the advise section (default: 5)')
    report_parser.add_argument('--smtp-host', dest='smtp_host', default=None,
                               help='SMTP server hostname (env: MONAG_SMTP_HOST, default: localhost)')
    report_parser.add_argument('--smtp-port', dest='smtp_port', type=int, default=None,
                               help='SMTP server port (env: MONAG_SMTP_PORT, default: 587)')
    report_parser.add_argument('--smtp-user', dest='smtp_user', default=None,
                               help='SMTP username (env: MONAG_SMTP_USER)')
    report_parser.add_argument('--smtp-password', dest='smtp_pass', default=None,
                               help='SMTP password (env: MONAG_SMTP_PASSWORD)')
    report_parser.add_argument('--smtp-tls', dest='smtp_tls', action='store_true', default=None,
                               help='use STARTTLS (env: MONAG_SMTP_TLS, default: on for port 587)')
    report_parser.add_argument('--from', dest='smtp_from', default=None,
                               help='sender address (env: MONAG_FROM)')
    report_parser.add_argument('--subject', dest='report_subject', default=None,
                               help='email subject (default: MONAG report — <root> — <timestamp>)')
    report_parser.add_argument('--schedule', dest='report_schedule', default=None, metavar='CRON',
                               help='cron expression for periodic execution (e.g. "0 * * * *")')
    report_parser.add_argument('--install-cron', dest='install_cron', action='store_true',
                               help='install a crontab entry for periodic report delivery')
    report_parser.add_argument('--remove-cron', dest='remove_cron', action='store_true',
                               help='remove the monag:report crontab entry')
    report_parser.add_argument('--dry-run', dest='report_dry_run', action='store_true',
                               help='generate and print the report without sending email')
    report_parser.add_argument('--daemon', dest='report_daemon', action='store_true',
                               help='run continuously in foreground sending reports periodically')
    report_parser.add_argument('--interval', dest='report_interval', type=float, default=3600,
                               help='seconds between reports in daemon mode (default: 3600 / 1 hour)')
    report_parser.add_argument('--issue-limit', type=int, default=200,
                               help='GitHub issues fetched per repository (default: 200)')
    advise_parser = sub.add_parser('advise', parents=[common_sub_parser],
                                   help='architectural guidance and prioritized next tasks '
                                        'synthesized from candidate items and reflex patterns')
    advise_parser.add_argument('--limit', type=int, default=10,
                               help='maximum recommendations to display (default: 10)')
    advise_parser.add_argument('--radar', action='store_true',
                               help='size candidates and estimate split recommendation via ticket-radar')
    advise_parser.add_argument('--hygiene', action='store_true',
                               help='include semcod/taskill doc-drift candidates')
    advise_parser.add_argument('--reflex-source', action='append', default=[],
                               help='extra directories or log files to ingest with subactor.reflex')
    advise_parser.add_argument('--issue-limit', type=int, default=200,
                               help='GitHub issues fetched per repository (default: 200)')
    advise_parser.add_argument('--tier', choices=['all', 'floor', 'mission', 'hygiene', 'backlog'],
                               default='all',
                               help='filter recommendations by Priority DSL tier (default: all)')
    advise_parser.add_argument('--emit-planfile', action='store_true',
                               help='export recommendations as Planfile-importable JSON tickets')
    advise_parser.add_argument('--feed-planfile', action='store_true',
                               help='directly feed recommendations into Planfile backlog via planfile ticket import')
    advise_parser.add_argument('--sprint', default='current',
                               help='target sprint for --feed-planfile (default: current)')
    advise_parser.add_argument('--holistic', action='store_true',
                               help='run holistic multi-org algorithmic triage and guidance engine (algocode + collision detection)')
    triage_parser = sub.add_parser('triage', parents=[common_sub_parser],
                                   help='holistic algorithmic multi-org workspace triage and guidance (algocode)')
    triage_parser.add_argument('--limit', type=int, default=15,
                               help='maximum guidance steps to display (default: 15)')
    triage_parser.add_argument('--emit-planfile', action='store_true',
                               help='export guidance steps as Planfile-importable JSON tickets')
    triage_parser.add_argument('--feed-planfile', action='store_true',
                               help='directly feed guidance steps into Planfile backlog/sprint')
    triage_parser.add_argument('--sprint', default='current',
                               help='target sprint for --feed-planfile (default: current)')
    autodiagnose_parser = sub.add_parser('autodiagnose', parents=[common_sub_parser],
                                         help='autonomous fleet diagnostic engine with SubLLM ticket synthesis and Planfile dispatch')
    autodiagnose_parser.add_argument('--subllm', action='store_true', default=True,
                                     help='use SubLLM to synthesize root causes, AC, and Koru handoffs (default: true)')
    autodiagnose_parser.add_argument('--no-subllm', dest='subllm', action='store_false',
                                     help='disable SubLLM and use deterministic rule-based ticket synthesis')
    autodiagnose_parser.add_argument('--feed-planfile', '--dispatch', dest='feed_planfile', action='store_true',
                                     help='directly write synthesized tickets into target projects .planfile/sprints storage')
    autodiagnose_parser.add_argument('--sync-github', action='store_true', default=False,
                                     help='synchronize dispatched Planfile tickets to GitHub Issues via planfile sync github')
    autodiagnose_parser.add_argument('--sprint', default='current',
                                     help='target sprint for --feed-planfile (default: current)')
    autodiagnose_parser.add_argument('--emit-planfile', action='store_true',
                                     help='print synthesized tickets as Planfile JSON envelope')
    summary_parser = sub.add_parser('summary', aliases=['day'], parents=[common_sub_parser],
                                    help='aggregate daily execution summary: Planfile completed/queued tickets, GitHub PRs, and time estimates')
    summary_parser.add_argument('--no-github', dest='github', action='store_false',
                                help='skip querying GitHub PR metrics for faster execution')
    quality = sub.add_parser('quality', parents=[common_sub_parser],
                             help='read-only semcod/regix quality gate for ONE repository '
                                  '(--root must be a Git checkout, not a workspace); '
                                  'costs roughly a minute per run, never a write command')
    quality.add_argument('--quality-timeout', dest='quality_timeout', type=float, default=180,
                         help='seconds to wait for regix gates (default: 180)')
    panel = sub.add_parser('panel', aliases=['serve', 'dashboard', 'ui'],
                           parents=[common_sub_parser],
                           help='serve a local-only HTTP dashboard (agents, repositories, '
                                'Planfile backlog, on-demand audit/catalog); Ctrl-C to stop')
    panel.add_argument('--port', type=int, default=8090)
    panel.add_argument('--bind', default='127.0.0.1',
                       help='listen address (default: localhost only; widen only if you mean to)')
    panel.add_argument('--panel-interval', dest='panel_interval', type=float, default=30,
                       help='background refresh seconds for the live snapshot/resume view (default: 30)')
    panel.add_argument('--port-attempts', type=int, default=20,
                       help='ports tried after --port before falling back to any free port (default: 20)')
    timeline = sub.add_parser('history', parents=[common_sub_parser], help='read local recorded observations')
    timeline.add_argument('--kind')
    timeline.add_argument('--search')
    watch = sub.add_parser('watch', parents=[common_sub_parser], help='refresh until Ctrl-C (default in a terminal)')
    watch.add_argument('--no-record', action='store_true', help='disable local history recording')
    watch.add_argument('--retention-days', type=int, default=7)
    watch.add_argument('--interval', type=float, default=5)
    sub.add_parser('shell', parents=[common_sub_parser], help='interactive command shell (default in a terminal)')
    run = sub.add_parser('run', parents=[common_sub_parser], help='wrap an agent command with an explicit task description')
    run.add_argument('--agent-kind', default='reported', help='label for an otherwise unknown agent')
    run.add_argument('--task', required=True)
    run.add_argument('--issue')
    run.add_argument('--pr')
    run.add_argument('command', nargs=argparse.REMAINDER)
    for sp in set(sub.choices.values()):
        if '--limit' not in sp._option_string_actions:
            sp.add_argument('--limit', type=int, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        if '--hours' not in sp._option_string_actions:
            sp.add_argument('--hours', type=float, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        if '--github' not in sp._option_string_actions:
            sp.add_argument('--github', action='store_true', default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        if '--open-files' not in sp._option_string_actions:
            sp.add_argument('--open-files', action='store_true', default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        if '--agents-only' not in sp._option_string_actions:
            sp.add_argument('--agents-only', action='store_true', default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        if '--machine' not in sp._option_string_actions:
            sp.add_argument('--machine', action='store_true', default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.mode is None:
        args.mode = ('shell' if sys.stdout.isatty() and args.output not in {'json', 'markdown'}
                     else 'status')
    elif args.mode in ('serve', 'dashboard', 'ui'):
        args.mode = 'panel'
    if sys.platform != 'linux':
        parser.error('process monitoring currently requires Linux /proc')
    if args.depth < 0 or args.limit < 1 or not 0 < args.hours < 876000:
        parser.error('depth >= 0, limit >= 1 and 0 < hours < 876000 required')
    within = getattr(args, 'within', None)
    if within is not None and not 0 < within < 876000:
        parser.error('0 < within < 876000 required')
    worktrees_hours = getattr(args, 'worktrees_hours', 10.0)
    if worktrees_hours is not None and not 0 < worktrees_hours < 876000:
        parser.error('0 < worktrees-hours < 876000 required')
    if args.mode == 'watch' and not 0.2 <= args.interval < 86400:
        parser.error('interval must be between 0.2 and 86400 seconds')
    if args.mode in ('audit', 'export') and args.issue_limit < 1:
        parser.error('issue-limit must be >= 1')
    if args.mode in ('prs', 'pr') and getattr(args, 'pr_limit', 200) < 1:
        parser.error('pr-limit must be >= 1')
    if args.mode == 'panel' and not (0 <= args.port <= 65535 and 1 <= args.panel_interval < 86400
                                     and args.port_attempts >= 0):
        parser.error('port must be 0-65535 (0 = always pick automatically), '
                    'panel-interval must be >= 1 second, port-attempts must be >= 0')
    if args.mode == 'quality' and args.quality_timeout < 1:
        parser.error('quality-timeout must be >= 1 second')
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
            fix = getattr(args, 'fix', False)
            data = diagnose(args.root.expanduser().resolve(), fix=fix)
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
        if args.mode == 'usage':
            from . import usage
            data = usage.scan(root, registry=registry, machine=args.machine,
                              all_users=args.all_users, ledgers=args.ledger)
            if output_format == 'json':
                print(json.dumps(data, ensure_ascii=True))
            elif output_format in {'terminal', 'markdown'}:
                display_report(usage.markdown(data, args.limit))
            else:
                print(usage.render(data, args.limit))
            return 0
        if args.mode == 'open':
            from . import opener, usage
            data = usage.scan(root, registry=registry, machine=args.machine,
                              all_users=args.all_users)
            if args.target:
                ok, message = opener.open_target(data['agents'], args.target,
                                                 action=args.action,
                                                 browser=args.browser,
                                                 dry_run=args.print_only)
            else:
                ok, message = opener.open_interactive(
                    data['agents'], limit=args.limit or None,
                    default_action='browser' if args.browser else 'terminal',
                    dry_run=args.print_only)
            print(message, flush=True)
            return 0 if ok else 2
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
                if getattr(args, 'worktrees_only', False):
                    print('MONAG: scanning worktree checkouts across repositories.',
                          file=sys.stderr, flush=True)
                else:
                    print('MONAG: scanning repositories and querying GitHub via gh; this can take a while.',
                          file=sys.stderr, flush=True)
            data = audit.scan(root, args.depth, args.issue_limit,
                              recent_hours=1 if getattr(args, 'last_hour', False) else args.within,
                              worktrees_hours=getattr(args, 'worktrees_hours', 10.0),
                              worktrees_only=getattr(args, 'worktrees_only', False))
            if output_format == 'json':
                print(json.dumps(data, ensure_ascii=True))
            else:
                display_report(audit.markdown(data, args.limit))
            return 0
        if args.mode == 'merge':
            from . import prs
            target = getattr(args, 'target', None)
            if getattr(args, 'merge_all', False) or (target and target.lower() in ('--all', 'all')):
                if output_format != 'json' and sys.stderr.isatty():
                    print('MONAG: merging all open pull requests across active repositories...',
                          file=sys.stderr, flush=True)
                data = prs.scan(root, args.depth,
                                hours=getattr(args, 'hours', 24.0),
                                state='open',
                                pr_limit=200,
                                unpushed_only=False,
                                all_repos=False)
                results = prs.merge_open_prs(data.get('open_prs', []),
                                             method=getattr(args, 'method', 'squash'),
                                             admin_bypass=getattr(args, 'bypass', True),
                                             use_browser=getattr(args, 'browser', False))
                if output_format == 'json':
                    print(json.dumps({'merged': results}, ensure_ascii=True))
                else:
                    display_report(prs.merge_result_markdown(results))
                return 0
            if not target:
                parser.error('target PR number or full URL required (or use --all)')
            res = prs.merge_pull_request(target, method=getattr(args, 'method', 'squash'),
                                         admin_bypass=getattr(args, 'bypass', True),
                                         use_browser=getattr(args, 'browser', False))
            if output_format == 'json':
                print(json.dumps(res, ensure_ascii=True))
            else:
                display_report(prs.merge_result_markdown([res]))
            return 0 if res.get('ok') else 1

        if args.mode in ('prs', 'pr'):
            from . import prs
            if getattr(args, 'merge_pr', None):
                res = prs.merge_pull_request(args.merge_pr,
                                             method=getattr(args, 'method', 'squash'),
                                             admin_bypass=getattr(args, 'bypass', True),
                                             use_browser=getattr(args, 'browser', False))
                if output_format == 'json':
                    print(json.dumps(res, ensure_ascii=True))
                else:
                    display_report(prs.merge_result_markdown([res]))
                return 0 if res.get('ok') else 1

            if getattr(args, 'merge', False):
                if output_format != 'json' and sys.stderr.isatty():
                    print('MONAG: auditing and merging open pull requests...', file=sys.stderr, flush=True)
                data = prs.scan(root, args.depth,
                                hours=getattr(args, 'hours', 24.0),
                                state='open',
                                pr_limit=getattr(args, 'pr_limit', 200),
                                unpushed_only=False,
                                all_repos=getattr(args, 'all_repos', False))
                results = prs.merge_open_prs(data.get('open_prs', []),
                                             method=getattr(args, 'method', 'squash'),
                                             admin_bypass=getattr(args, 'bypass', True),
                                             use_browser=getattr(args, 'browser', False))
                if output_format == 'json':
                    print(json.dumps({'merged': results}, ensure_ascii=True))
                else:
                    display_report(prs.merge_result_markdown(results))
                return 0

            if output_format != 'json' and sys.stderr.isatty():
                print('MONAG: auditing pull requests and local branches via gh; this can take a while.',
                      file=sys.stderr, flush=True)
            data = prs.scan(root, args.depth,
                            hours=getattr(args, 'hours', 24.0),
                            state=getattr(args, 'state', 'all'),
                            pr_limit=getattr(args, 'pr_limit', 200),
                            unpushed_only=getattr(args, 'unpushed_only', False),
                            all_repos=getattr(args, 'all_repos', False))
            if output_format == 'json':
                print(json.dumps(data, ensure_ascii=True))
            else:
                display_report(prs.markdown(data, args.limit))
            return 0
        if args.mode == 'mcp':
            from . import mcp
            mcp.run_stdio_server(root, depth=args.depth)
            return 0
        if args.mode in ('ask', 'dsl'):
            from . import nl_contract
            result = nl_contract.execute(' '.join(args.query), root,
                                         direct=args.mode == 'dsl', depth=args.depth,
                                         registry=registry)
            if output_format == 'json':
                print(json.dumps(result, ensure_ascii=True))
            elif result['success']:
                display_report(result['meta']['markdown'])
            else:
                print(result['errors'][0]['message'], file=sys.stderr)
            return 0 if result['success'] else 1
        if args.mode == 'query':
            from . import dsl_llm
            query_str = ' '.join(args.query)
            res = dsl_llm.execute(query_str, root, depth=args.depth, registry=registry)
            if output_format == 'json':
                print(json.dumps(res, ensure_ascii=True))
            else:
                if res.get('status') == 'ok':
                    display_report(res['markdown'])
                else:
                    print(f"Error: {res.get('error')}", file=sys.stderr)
                    return 1
            return 0 if res.get('status') == 'ok' else 1
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
        if args.mode == 'export':
            from . import export
            if output_format != 'json' and sys.stderr.isatty():
                print('MONAG: building a candidate-work staging list (audit + catalog + resume); '
                     'nothing is created or queued.', file=sys.stderr, flush=True)
            data = export.scan(root, args.depth, args.issue_limit, args.radar, args.hygiene)
            if output_format == 'json':
                print(json.dumps(data, ensure_ascii=True))
            else:
                display_report(export.markdown(data, args.limit))
            return 0
        if args.mode == 'report':
            from . import report
            if getattr(args, 'remove_cron', False):
                result = report.remove_cron()
                if output_format == 'json':
                    print(json.dumps(result, ensure_ascii=True))
                else:
                    print(f"{'OK' if result['ok'] else 'FAILED'}: {result.get('action', result.get('error'))}",
                          flush=True)
                return 0 if result['ok'] else 1
            sections = None
            if getattr(args, 'report_sections', None):
                sections = [s.strip() for s in args.report_sections.split(',')]

            recipients = list(args.report_email) if args.report_email else []
            if not recipients:
                detected = report.detect_user_email()
                if detected:
                    recipients = [detected]

            if getattr(args, 'report_daemon', False):
                interval = getattr(args, 'report_interval', 3600)
                if not recipients:
                    print("Error: no recipient email specified or detected from gh/git", file=sys.stderr)
                    return 1
                if sys.stderr.isatty():
                    print(f"MONAG: starting report daemon for {', '.join(recipients)} every {interval}s...",
                          file=sys.stderr, flush=True)
                report.run_daemon(
                    root, recipients, interval=interval, depth=args.depth, hours=args.hours,
                    sections=sections, github=args.github, issue_limit=args.issue_limit,
                    registry=registry, machine=args.machine, all_users=args.all_users,
                    state_dir=args.state_dir, advisory_limit=getattr(args, 'advisory_limit', 5))
                return 0

            if output_format != 'json' and sys.stderr.isatty():
                print('MONAG: collecting workspace report data (status, prs, audit, resume, export, advise)...',
                      file=sys.stderr, flush=True)
            data = report.collect(
                root, args.depth, args.hours, sections, args.github,
                args.issue_limit, registry, args.machine, args.all_users,
                args.state_dir, advisory_limit=getattr(args, 'advisory_limit', 5))
            body = report.markdown(data, recipients=recipients)
            if getattr(args, 'report_dry_run', False) or not recipients:
                if output_format == 'json':
                    print(json.dumps(data, ensure_ascii=True))
                else:
                    display_report(body)
                return 0
            smtp_cfg = report._smtp_config(
                args_host=args.smtp_host, args_port=args.smtp_port,
                args_user=args.smtp_user, args_pass=args.smtp_pass,
                args_tls=args.smtp_tls, args_from=args.smtp_from)
            subject = args.report_subject or f'MONAG report — {root.name} — {data["observed_at"][:16]}'
            result = report.send_email(recipients, subject, body, smtp_cfg)
            if output_format == 'json':
                print(json.dumps(result, ensure_ascii=True))
            else:
                if result['ok']:
                    print(f"Report sent to {', '.join(result['recipients'])} via {result['via']}",
                          flush=True)
                else:
                    print(f"Send FAILED: {result['error']}", file=sys.stderr, flush=True)
            if getattr(args, 'install_cron', False) and recipients:
                schedule_expr = getattr(args, 'report_schedule', None) or '0 * * * *'
                cron_result = report.install_cron(
                    recipients[0], root, schedule_expr, sections)
                if output_format == 'json':
                    print(json.dumps(cron_result, ensure_ascii=True))
                else:
                    if cron_result['ok']:
                        print(f"Cron installed: {cron_result['cron_line']}", flush=True)
                    else:
                        print(f"Cron install FAILED: {cron_result['error']}",
                              file=sys.stderr, flush=True)
            return 0 if result['ok'] else 1
        if args.mode in ('advise', 'triage'):
            from . import advise
            holistic = getattr(args, 'holistic', False) or (args.mode == 'triage')
            if holistic:
                from . import triage
                if output_format != 'json' and sys.stderr.isatty():
                    print('MONAG: executing holistic algorithmic multi-org workspace triage...',
                          file=sys.stderr, flush=True)
                data = triage.run_holistic_triage(root, depth=args.depth, limit=args.limit)
                if getattr(args, 'emit_planfile', False):
                    tasks = triage.export_planfile_tasks(data)
                    print(json.dumps(tasks, ensure_ascii=False, indent=2))
                    return 0
                if getattr(args, 'feed_planfile', False):
                    feed_res = triage.feed_to_planfile(data, root=root, sprint=getattr(args, 'sprint', 'current'))
                    if output_format == 'json':
                        print(json.dumps(feed_res, ensure_ascii=False, indent=2))
                    else:
                        print(f"Planfile: potwierdzono zapis {feed_res.get('tasks_count', 0)} ticketów dla sprintu '{args.sprint}'.")
                        for ticket in feed_res.get('tickets', []):
                            print(f"  {ticket['repository']}: {ticket['id']}")
                        for error in feed_res.get('errors', []):
                            print(f"  {error['repository']}: {error['error']}", file=sys.stderr)
                        if not feed_res.get('success'):
                            print(f"Planfile feed FAILED: {feed_res.get('reason')}", file=sys.stderr)
                    return 0 if feed_res.get('success') else 1
                if output_format == 'json':
                    print(json.dumps(data, ensure_ascii=False, indent=2))
                else:
                    display_report(triage.triage_markdown(data))
                return 0

            if output_format != 'json' and sys.stderr.isatty():
                print('MONAG: generating architectural guidance and next task recommendations...',
                      file=sys.stderr, flush=True)
            data = advise.advise(
                root, depth=args.depth, issue_limit=args.issue_limit,
                radar=getattr(args, 'radar', False),
                hygiene=getattr(args, 'hygiene', False),
                reflex_source=getattr(args, 'reflex_source', None),
                state_dir=args.state_dir,
                limit=args.limit,
                tier=getattr(args, 'tier', 'all'))
            if getattr(args, 'emit_planfile', False):
                planfile_payload = advise.export_planfile_tickets(data, tier=getattr(args, 'tier', 'all'))
                print(json.dumps(planfile_payload, ensure_ascii=False, indent=2))
                return 0
            if getattr(args, 'feed_planfile', False):
                feed_res = advise.feed_to_planfile(data, root=root, sprint=getattr(args, 'sprint', 'current'),
                                                   tier=getattr(args, 'tier', 'all'))
                if feed_res.get('ok'):
                    print(f"Planfile: zaimportowano {feed_res.get('count', 0)} ticketów do sprintu '{args.sprint}'.")
                    return 0
                else:
                    print(f"Planfile import FAILED: {feed_res.get('error')}", file=sys.stderr)
                    return 1
            if output_format == 'json':
                print(json.dumps(data, ensure_ascii=False, indent=2))
            else:
                display_report(advise.markdown(data))
            return 0
        if args.mode == 'autodiagnose':
            from . import autodiagnosis
            diag_report = autodiagnosis.diagnose_fleet(root, depth=args.depth)
            runner = autodiagnosis._find_subllm_runner() if getattr(args, 'subllm', True) else None
            tickets = autodiagnosis.synthesize_tickets_with_subllm(diag_report, runner=runner)

            if getattr(args, 'emit_planfile', False):
                payload = {
                    'schema': 'planfile.tickets/v1',
                    'source': 'monag.autodiagnosis',
                    'count': len(tickets),
                    'tickets': tickets,
                }
                print(json.dumps(payload, ensure_ascii=False, indent=2))
                return 0

            if getattr(args, 'feed_planfile', False):
                dispatch_res = autodiagnosis.dispatch_tickets_to_planfile(
                    tickets, root=root, sprint=getattr(args, 'sprint', 'current'),
                    sync_github=getattr(args, 'sync_github', False),
                )
                if output_format == 'json':
                    print(json.dumps(dispatch_res, ensure_ascii=False, indent=2))
                else:
                    print(f"Planfile Dispatch: zapisano {dispatch_res.get('dispatched', 0)}/{dispatch_res.get('total_tickets', 0)} ticketów w {len(dispatch_res.get('repositories_updated', []))} projektach.")
                    for repo, tids in dispatch_res.get('tickets_by_repo', {}).items():
                        print(f"  {repo}: {', '.join(tids)}")
                    for sync_item in dispatch_res.get('github_sync', []):
                        status_str = "OK" if sync_item.get("ok") else f"FAILED ({sync_item.get('error') or sync_item.get('stderr')})"
                        print(f"  GitHub Sync ({Path(sync_item['target']).name}): {status_str}")
                    for err in dispatch_res.get('errors', []):
                        print(f"  ERROR: {err}", file=sys.stderr)
                return 0 if not dispatch_res.get('errors') else 1

            if output_format == 'json':
                print(json.dumps({
                    'diagnosis': diag_report,
                    'tickets': tickets,
                }, ensure_ascii=False, indent=2))
            else:
                lines = [
                    "# MONAG Fleet Autodiagnosis & SubLLM Ticket Generation",
                    "",
                    f"Zbadano {diag_report['repositories_checked']} repozytoriów, wykryto {diag_report['anomalies_count']} anomalii technicznych.",
                    f"Wygenerowano {len(tickets)} biletów gotowych pod Planfile, GitHub i Koru Autonomous.",
                    "",
                ]
                for idx, t in enumerate(tickets, 1):
                    lines.append(f"### {idx}. [{t['priority'].upper()}] {t['title']}")
                    lines.append(f"- **Projekt**: `{t['target_repo']}`")
                    lines.append(f"- **Działanie**: {t.get('action', '—')}")
                    lines.append(f"- **Kryteria ukończenia**: `{t.get('satisfied_when', '—')}`")
                    lines.append("")
                display_report('\n'.join(lines))
            return 0
        if args.mode in ('summary', 'day'):
            from . import summary
            data = summary.gather_summary(
                root,
                hours=getattr(args, 'hours', 24),
                github=getattr(args, 'github', True),
                depth=args.depth,
            )
            if output_format == 'json':
                print(json.dumps(data, ensure_ascii=False, indent=2))
            else:
                display_report(summary.format_markdown(data))
            return 0
        if args.mode == 'quality':
            from . import quality
            if output_format != 'json' and sys.stderr.isatty():
                print('MONAG: running regix gates on this repository; commonly takes about a '
                     'minute (coverage runs the whole test suite). No writes.',
                     file=sys.stderr, flush=True)
            data = quality.scan(root, args.quality_timeout)
            if output_format == 'json':
                print(json.dumps(data, ensure_ascii=True))
            else:
                display_report(quality.markdown(data, args.limit))
            if not data['available']:
                return 2
            return int(data['all_passed'] is False)
        if args.mode == 'panel':
            from . import panel
            def announce(bind, actual_port):
                note = '' if actual_port == args.port else f' (requested {args.port} was unavailable)'
                print(f'MONAG: panel serving http://{bind}:{actual_port}/{note} (Ctrl-C to stop).',
                     file=sys.stderr, flush=True)
            panel.serve(root, args.state_dir, args.depth, args.bind, args.port, args.panel_interval,
                       args.port_attempts, registry, args.github, args.machine, args.all_users,
                       args.open_files, announce)
            return 0
        cache = {}
        if args.mode == 'shell':
            # The shell deliberately uses regular Markdown reports rather than
            # Rich Live's alternate screen.  This keeps the first useful
            # dashboard visible while the user chooses the next observation.
            def show_status():
                since = (datetime.now(timezone.utc) - timedelta(hours=args.hours)).isoformat()
                data = snapshot(root, args.state_dir, args.depth, since, args.github, cache,
                                registry, args.machine, args.all_users, args.open_files, args.agents_only)
                data['detector_scope'] = sorted(args.agent)
                data['events'] = history.record(args.state_dir, data, 7)
                if output_format == 'json':
                    print(json.dumps(data, ensure_ascii=True), flush=True)
                elif output_format in {'terminal', 'markdown'}:
                    display_report(presentation.markdown(data, args.limit, args.view))
                else:
                    print(render(data, args.limit), flush=True)

            def show_resume():
                from . import resume
                data = resume.scan(root, args.depth)
                if output_format == 'json':
                    print(json.dumps(data, ensure_ascii=True), flush=True)
                else:
                    display_report(resume.markdown(data, args.limit, all_projects=True))

            def show_report(command_name):
                if command_name == 'status':
                    show_status()
                elif command_name == 'resume':
                    show_resume()
                elif command_name == 'refresh':
                    show_status()
                    show_resume()
                elif command_name == 'audit':
                    from . import audit
                    data = audit.scan(root, args.depth, 200,
                                      recent_hours=(1 if getattr(args, 'last_hour', False)
                                                    else getattr(args, 'within', None)),
                                      worktrees_hours=getattr(args, 'worktrees_hours', 10.0),
                                      worktrees_only=getattr(args, 'worktrees_only', False))
                    if output_format == 'json':
                        print(json.dumps(data, ensure_ascii=True), flush=True)
                    else:
                        display_report(audit.markdown(data, args.limit))
                elif command_name in ('prs', 'pr'):
                    from . import prs
                    data = prs.scan(root, args.depth,
                                    hours=getattr(args, 'hours', 24.0),
                                    state=getattr(args, 'state', 'all'),
                                    pr_limit=getattr(args, 'pr_limit', 200),
                                    unpushed_only=getattr(args, 'unpushed_only', False))
                    if output_format == 'json':
                        print(json.dumps(data, ensure_ascii=True), flush=True)
                    else:
                        display_report(prs.markdown(data, args.limit))
                elif command_name == 'catalog':
                    from . import catalog
                    data = catalog.scan(root, args.depth)
                    if output_format == 'json':
                        print(json.dumps(data, ensure_ascii=True), flush=True)
                    else:
                        display_report(catalog.markdown(data, args.limit))
                elif command_name == 'usage':
                    from . import usage
                    data = usage.scan(root, registry=registry, machine=args.machine,
                                      all_users=args.all_users,
                                      ledgers=getattr(args, 'ledger', []))
                    if output_format == 'json':
                        print(json.dumps(data, ensure_ascii=True), flush=True)
                    elif output_format in {'terminal', 'markdown'}:
                        display_report(usage.markdown(data, args.limit))
                    else:
                        print(usage.render(data, args.limit), flush=True)
                elif command_name == 'history':
                    data = history.read(args.state_dir, args.limit, None, None, args.hours)
                    if output_format == 'json':
                        print(json.dumps(data, ensure_ascii=True), flush=True)
                    elif output_format in {'terminal', 'markdown'}:
                        display_report(presentation.history_markdown(data))
                    else:
                        print('\n'.join(event_line(e) for e in data) or 'No recorded observations.', flush=True)
                elif command_name == 'advise':
                    from . import advise
                    data = advise.advise(root, depth=args.depth, issue_limit=args.issue_limit,
                                         state_dir=args.state_dir, limit=args.limit)
                    if output_format == 'json':
                        print(json.dumps(data, ensure_ascii=False, indent=2), flush=True)
                    else:
                        display_report(advise.markdown(data))

            print(shell_help(), flush=True)
            show_report('refresh')
            while True:
                try:
                    command_line = input('monag> ').strip()
                except (EOFError, OSError):
                    print('\nMONAG shell zakończony.', flush=True)
                    return 0
                if not command_line:
                    continue
                command_name = command_line.split(maxsplit=1)[0].lower()
                if command_name in {'quit', 'exit'}:
                    print('MONAG shell zakończony.', flush=True)
                    return 0
                if command_name in {'help', '?'}:
                    print(shell_help(), flush=True)
                    continue
                if command_name == 'query':
                    from . import dsl_llm
                    parts = command_line.split(maxsplit=1)
                    q = parts[1].strip() if len(parts) > 1 else ''
                    if q:
                        res = dsl_llm.execute(q, root, depth=args.depth, registry=registry)
                        if res.get('status') == 'ok':
                            display_report(res['markdown'])
                        else:
                            print(f"Błąd: {res.get('error')}", flush=True)
                    else:
                        print("Wpisz zapytanie po 'query', np.: query pokaż otwarte PR", flush=True)
                    continue
                if command_name not in SHELL_COMMANDS:
                    from . import dsl_llm
                    res = dsl_llm.execute(command_line, root, depth=args.depth, registry=registry)
                    if res.get('status') == 'ok' and res.get('markdown'):
                        display_report(res['markdown'])
                        continue
                    print(f'Nieznane polecenie: {command_name}. Wpisz help lub zapytaj w języku naturalnym.', flush=True)
                    continue
                if command_name == 'open':
                    from . import opener, usage
                    parts = command_line.split(maxsplit=1)
                    target = parts[1].strip() if len(parts) > 1 else ''
                    opened = usage.scan(root, registry=registry, machine=args.machine,
                                        all_users=args.all_users)
                    if target:
                        print(opener.open_target(opened['agents'], target)[1], flush=True)
                    else:
                        print(opener.open_interactive(opened['agents'],
                                                      limit=args.limit or None)[1], flush=True)
                    continue
                if command_name == 'merge':
                    from . import prs
                    parts = command_line.split(maxsplit=1)
                    target = parts[1].strip() if len(parts) > 1 else ''
                    if not target or target.lower() in ('all', '--all'):
                        data = prs.scan(root, args.depth, hours=args.hours, state='open', pr_limit=200)
                        results = prs.merge_open_prs(data.get('open_prs', []))
                        display_report(prs.merge_result_markdown(results))
                    else:
                        res = prs.merge_pull_request(target)
                        display_report(prs.merge_result_markdown([res]))
                    continue
                show_report(command_name)
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

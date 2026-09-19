"""Markdown reports rendered identically for terminal display and file export."""
from collections import Counter, defaultdict
from datetime import datetime
import re


def clean(value):
    return ''.join(c if c.isprintable() else '?' for c in str(value if value is not None else '—'))


def cell(value):
    # Treat process names, paths and remote titles as data, never Markdown/HTML.
    text = clean(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return re.sub(r'([\\`*_{}\[\]()#+.!|~-])', r'\\\1', text)


def table(headers, rows):
    rows = list(rows)
    if not rows:
        return '_No observations._\n'
    return '\n'.join(['| ' + ' | '.join(cell(c) for c in headers) + ' |',
                       '| ' + ' | '.join('---' for _ in headers) + ' |',
                       *['| ' + ' | '.join(cell(c) for c in row) + ' |' for row in rows]]) + '\n'


def tree(data, limit=12):
    """Bounded Unicode tree; recursion is limited and malformed cycles are harmless."""
    lines = ['Agent process trees']
    agents = data['agents'][:limit]
    for index, agent in enumerate(agents):
        last = index == len(agents) - 1
        lines.append(('└── ' if last else '├── ') + clean(f"{agent['kind']} · PID {agent['pid']} · {agent['cwd']}"))
        prefix = '    ' if last else '│   '
        descendants = agent.get('descendants', [])
        by_parent = defaultdict(list)
        known = {agent['pid'], *(p['pid'] for p in descendants)}
        for process in descendants:
            parent = process.get('ppid', agent['pid'])
            by_parent[parent if parent in known else agent['pid']].append(process)
        visited = {agent['pid']}
        budget = [limit]
        def branch(pid, indent, depth):
            children = by_parent[pid]
            for n, child in enumerate(children):
                if budget[0] == 0 or depth > 5:
                    return
                if child['pid'] in visited:
                    continue
                visited.add(child['pid'])
                budget[0] -= 1
                end = n == len(children) - 1
                lines.append(indent + ('└── ' if end else '├── ') + clean(
                    f"{child['executable']} · PID {child['pid']} · {child.get('cwd', '—')}"))
                branch(child['pid'], indent + ('    ' if end else '│   '), depth + 1)
        branch(agent['pid'], prefix, 1)
        remaining = len(descendants) - len(visited) + 1
        if remaining > 0:
            lines.append(prefix + f'… {remaining} more processes (use --json for all)')
    if len(data['agents']) > limit:
        lines.append(f"… {len(data['agents']) - limit} more agents; increase --limit")
    if not agents:
        lines.append('└── No recognized agents')
    return '\n'.join(lines)


def fenced(text):
    # Prevent a filename containing backticks from closing the exported block.
    longest = max((len(m.group()) for m in re.finditer(r'`+', text)), default=0)
    fence = '`' * max(3, longest + 1)
    return f'{fence}text\n{text}\n{fence}\n'


def history_markdown(events):
    rows = []
    for event in events:
        subject = event.get('agent') or event.get('process') or event.get('task') or {}
        if not isinstance(subject, dict):
            subject = {'task': subject}
        rows.append([datetime.fromtimestamp(event['observed']).strftime('%m-%d %H:%M:%S'),
                     event['kind'], subject.get('pid', event.get('agent_pid', '—')),
                     subject.get('cwd', event.get('project', '—')),
                     event.get('file', event.get('subject', event.get('title', subject.get('task', '—'))))])
    return '# MONAG · Activity history\n\n' + table(['Time', 'Observation', 'PID', 'Directory', 'Detail'], rows)


def doctor_markdown(data):
    return '# MONAG · Diagnostics\n\n' + table(['Check', 'Result'],
        ((k, '; '.join(map(str, v)) if isinstance(v, list) else v) for k, v in data.items()))


def cpu(agent):
    # Activity needs two samples; a single snapshot without one has no rate.
    return '—' if agent.get('cpu_percent') is None else f"{agent['cpu_percent']:.0f}%"


def markdown(data, limit=12, view='all'):
    agents, repos = data['agents'], data['repositories']
    scan = f"{data['duration_seconds']}s"
    if (data.get('repositories_age_seconds') or 0) >= 1:
        scan += f" (checkouts {data['repositories_age_seconds']:.0f}s old)"
    parts = ['# MONAG · Agent activity\n',
             f"{cell(data['observed_at'][:19])} · {cell(data['root'])}\n",
             table(['Agents', 'Checkouts', 'Concurrent checkouts', 'Scan'], [[data['agent_count'], len(repos),
                    sum(len(r['agents']) > 1 for r in repos), scan]])]
    types = Counter(a['kind'] for a in agents)
    if types:
        parts.append(' · '.join(f'**{cell(k)}**: {n}' for k, n in sorted(types.items())) + '\n')
    if view in ('all', 'agents'):
        parts += ['## Agents (most active first)\n', table(['PID', 'Agent', 'CPU', 'State', 'Children', 'Directory', 'Task'],
                  ([a['pid'], a['kind'], cpu(a), a['state'], a['children'], a['cwd'], a['task']] for a in agents[:limit]))]
        if len(agents) > limit:
            parts.append(f'{len(agents) - limit} additional agents; increase --limit.\n')
        opened = [(a['pid'], path) for a in agents for path in a.get('open_files', [])]
        if opened:
            parts += ['## Open file paths\n', table(['Agent PID', 'Path'], opened[:limit])]
    if view in ('all', 'tree'):
        parts += ['## Process diagram\n', fenced(tree(data, limit))]
    if view in ('all', 'projects'):
        parts += ['## Projects and worktrees\n', table(['Checkout', 'Branch', 'Agent PIDs', 'Changed', 'Concurrency'],
                 ([r['path'], r['branch'], ', '.join(map(str, r['agents'])) or '—', len(r['files']),
                   'MULTIPLE AGENTS' if len(r['agents']) > 1 else '—'] for r in repos[:limit]))]
        if len(repos) > limit:
            parts.append(f'{len(repos) - limit} additional checkouts; increase --limit.\n')
        files = [(r['path'], f['status'], f['path']) for r in repos for f in r['files']]
        parts += ['## Changed files\n', table(['Checkout', 'Git state', 'File'], files[:limit])]
        if len(files) > limit:
            parts.append(f'{len(files) - limit} additional changed files; --json includes all.\n')
        commits = {}
        for repo in repos:
            for c in repo['commits']:
                commits.setdefault((repo['common_dir'], c['sha']), dict(c, project=repo['path']))
        recent = sorted(commits.values(), key=lambda c: c['time'], reverse=True)[:limit]
        parts += ['## Recent commits\n', table(['Commit', 'Checkout', 'Subject'],
                  ([c['sha'][:8], c['project'], c['subject']] for c in recent))]
    if view in ('all', 'history'):
        parts += ['## Reported tasks\n', table(['State', 'PID', 'Task', 'Issue', 'PR'],
                  ([t['status'], t['pid'], t['task'], t.get('issue') or '—', t.get('pr') or '—'] for t in data['tasks'][:limit]))]
        if data['github']:
            parts += ['## GitHub issues and pull requests\n', table(['Repository', 'Type', '#', 'State', 'Title', 'URL'],
                      ([e['repository'], e['kind'], e['number'], 'MERGED' if e.get('mergedAt') else e['state'],
                        e['title'], e['url']] for e in data['github'][:limit]))]
        if data.get('events'):
            parts.append(history_markdown(data['events'][-limit:]).replace('# MONAG · Activity history', '## New observations', 1))
    problems = list(data['errors']) + [f"{r['path']}: {e}" for r in repos for e in r['errors']]
    if data['inaccessible_processes']:
        problems.append(f"Inaccessible processes: {data['inaccessible_processes']}")
    for a in agents:
        if a.get('open_files_truncated') or a.get('open_files_inaccessible'):
            problems.append(f"PID {a['pid']}: open file observation incomplete")
    if problems:
        parts += ['## Observation gaps\n', table(['Detail'], ([p] for p in dict.fromkeys(problems)))]
    parts.append('_Observed processes and Git changes do not establish task completion or file authorship._\n')
    return '\n'.join(parts)

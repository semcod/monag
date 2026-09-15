"""Private SQLite observation history with bounded retention and atomic snapshots."""
import json
from pathlib import Path
import sqlite3
import time


def connect(state_dir):
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = state_dir / 'history.sqlite3'
    # Pre-create with restrictive permissions, before SQLite writes any content.
    import os
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    os.fchmod(fd, 0o600)
    os.close(fd)
    db = sqlite3.connect(path, timeout=10)
    db.execute('CREATE TABLE IF NOT EXISTS snapshots (scope TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, observed REAL NOT NULL, scope TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL)')
    db.execute('CREATE INDEX IF NOT EXISTS events_time ON events(observed)')
    return db


def scope_of(data):
    return json.dumps([data['root'], data.get('machine', False), data.get('all_users', False),
                       data.get('agents_only', False), data.get('open_files', False), data.get('detector_scope', [])])


def compact(data):
    agents = {}
    for a in data['agents']:
        key = f"{data.get('boot_id', 'unknown')}:{a['pid']}:{a['start']}"
        agents[key] = {k: a.get(k) for k in ('pid', 'kind', 'cwd', 'task', 'uid')}
        agents[key]['open_files'] = a.get('open_files', [])
        agents[key]['children'] = {f"{p['pid']}:{p['start']}":
                                  {k: p.get(k) for k in ('pid', 'executable', 'cwd')}
                                  for p in a.get('descendants', [])}
    repos = {}
    commits = {}
    for r in data['repositories']:
        if r['errors']:
            continue
        repos[r['path']] = {'branch': r['branch'], 'files': {f['path']: [f['status'], f['modified']]
                                                          for f in r['files']}}
        for c in r['commits']:
            commits[f"{r['common_dir']}:{c['sha']}"] = dict(c, project=r['path'])
    return {'agents': agents, 'repos': repos, 'commits': commits,
            'github': {e['url']: e for e in data['github']},
            'tasks': {t.get('id', f"{t['pid']}:{t['start']}"): t for t in data.get('tasks', [])}}


def record(state_dir, data, retention_days=7):
    current = compact(data)
    scope, now = scope_of(data), time.time()
    db = connect(state_dir)
    events = []
    def emit(kind, payload):
        events.append({**payload, 'kind': kind, 'observed': now})
        db.execute('INSERT INTO events(observed,scope,kind,payload) VALUES(?,?,?,?)',
                   (now, scope, kind, json.dumps(payload, ensure_ascii=True)))
    try:
        with db:
            # Serialize the read/compare/write transaction across monitoring shells.
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT payload FROM snapshots WHERE scope=?', (scope,)).fetchone()
            previous = json.loads(row[0]) if row else {'agents': {}, 'repos': {}, 'commits': {}, 'github': {}, 'tasks': {}}
            if data['inaccessible_processes']:
                # Visibility gaps do not become disappearance events.
                current['agents'] = {**previous['agents'], **current['agents']}
            for key, agent in current['agents'].items():
                old = previous['agents'].get(key)
                if old is None:
                    emit('agent_observed', {'agent': agent})
                else:
                    if any(agent[k] != old[k] for k in ('cwd', 'task')):
                        emit('agent_changed', {'agent': agent, 'previous_cwd': old['cwd']})
                    for child, process in agent['children'].items():
                        if child not in old.get('children', {}):
                            emit('child_observed', {'agent_pid': agent['pid'], 'process': process})
                        elif process != old['children'][child]:
                            emit('child_changed', {'agent_pid': agent['pid'], 'process': process})
                    for child, process in old.get('children', {}).items():
                        if child not in agent['children']:
                            emit('child_disappeared', {'agent_pid': agent['pid'], 'process': process})
                for path in set(agent.get('open_files', [])) - set((old or {}).get('open_files', [])):
                    emit('open_file_observed', {'agent_pid': agent['pid'], 'file': path})
            for key, agent in previous['agents'].items():
                if key not in current['agents']:
                    emit('agent_disappeared', {'agent': agent})
            for path, repo in current['repos'].items():
                old = previous['repos'].get(path)
                if old and old['branch'] != repo['branch']:
                    emit('branch_changed', {'project': path, 'before': old['branch'], 'after': repo['branch']})
                for file, state in repo['files'].items():
                    if old is None or old['files'].get(file) != state:
                        emit('file_observed', {'project': path, 'file': file, 'status': state[0]})
                if old:
                    for file in old['files'].keys() - repo['files'].keys():
                        emit('file_no_longer_dirty', {'project': path, 'file': file})
            for key, commit in current['commits'].items():
                if key not in previous['commits']:
                    emit('commit_observed', commit)
            for key, item in current['github'].items():
                if previous['github'].get(key) != item:
                    emit('github_observed', item)
            for key, task in current['tasks'].items():
                if previous.get('tasks', {}).get(key) != task:
                    emit('task_observed', {'task': task})
            # Keep cached entities across incomplete scans; never infer a completed task.
            current['repos'] = {**previous['repos'], **current['repos']}
            current['github'] = {**previous['github'], **current['github']}
            db.execute('INSERT OR REPLACE INTO snapshots VALUES(?,?)', (scope, json.dumps(current)))
            db.execute('DELETE FROM events WHERE observed < ?', (now - retention_days * 86400,))
            # Bound stored data even for a high-churn workspace.
            db.execute('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 100000)')
            db.execute('DELETE FROM snapshots WHERE scope NOT IN (SELECT scope FROM snapshots ORDER BY rowid DESC LIMIT 64)')
    finally:
        db.close()
    return events


def read(state_dir, limit=50, kind=None, search=None, hours=24):
    path = state_dir / 'history.sqlite3'
    if not path.exists():
        return []
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        query = 'SELECT observed,kind,payload FROM events WHERE observed>=?'
        values = [time.time() - hours * 3600]
        if kind:
            query += ' AND kind=?'
            values.append(kind)
        if search:
            query += ' AND instr(payload,?)>0'
            values.append(search)
        query += ' ORDER BY id DESC LIMIT ?'
        values.append(limit)
        return [dict(json.loads(payload), observed=when, kind=event_kind)
                for when, event_kind, payload in db.execute(query, values)]
    finally:
        db.close()

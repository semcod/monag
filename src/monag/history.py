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
                    task_payload = {
                        'task': task,
                        'ticket': task.get('ticket'),
                        'attempt': task.get('attempt'),
                        'sha': task.get('sha'),
                        'outcome': task.get('outcome', task.get('status')),
                        'execution_duration_seconds': task.get('execution_duration_seconds'),
                        'queue_duration_seconds': task.get('queue_duration_seconds'),
                        'receipt': task.get('receipt'),
                    }
                    emit('task_observed', task_payload)
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


def coverage(state_dir, hours=24, now=None):
    """Compute history coverage, observation gaps, and task telemetry status."""
    path = Path(state_dir) / 'history.sqlite3'
    now_ts = time.time() if now is None else float(now)
    window_start = now_ts - float(hours) * 3600

    if not path.is_file():
        return {
            'store_status': 'unavailable',
            'total_events': 0,
            'latest_observed': None,
            'latest_observed_iso': None,
            'last_sample_age_seconds': None,
            'window_hours': float(hours),
            'window_events': 0,
            'observation_gap': True,
            'observation_gap_seconds': None,
            'task_events': 0,
            'task_events_window': 0,
            'completed_tasks': 0,
            'failed_tasks': 0,
            'running_tasks': 0,
            'task_telemetry_status': 'unavailable',
            'activity_status': 'unavailable',
            'metadata_churn': {'file_events': 0, 'file_observed': 0, 'file_no_longer_dirty': 0, 'open_file_observed': 0, 'total': 0},
        }

    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        row = db.execute('SELECT COUNT(*), MIN(observed), MAX(observed) FROM events').fetchone()
        total_events = row[0] if row else 0
        latest_observed = row[2] if row and row[2] is not None else None

        if total_events == 0 or latest_observed is None:
            return {
                'store_status': 'empty',
                'total_events': 0,
                'latest_observed': None,
                'latest_observed_iso': None,
                'last_sample_age_seconds': None,
                'window_hours': float(hours),
                'window_events': 0,
                'observation_gap': False,
                'observation_gap_seconds': None,
                'task_events': 0,
                'task_events_window': 0,
                'completed_tasks': 0,
                'failed_tasks': 0,
                'running_tasks': 0,
                'task_telemetry_status': 'zero_tasks',
                'activity_status': 'no_events',
                'metadata_churn': {'file_events': 0, 'file_observed': 0, 'file_no_longer_dirty': 0, 'open_file_observed': 0, 'total': 0},
            }

        last_sample_age = round(now_ts - latest_observed, 1)
        from datetime import datetime, timezone
        latest_iso = datetime.fromtimestamp(latest_observed, timezone.utc).isoformat()

        w_row = db.execute('SELECT COUNT(*) FROM events WHERE observed >= ?', (window_start,)).fetchone()
        window_events = w_row[0] if w_row else 0

        kinds_all = dict(db.execute('SELECT kind, COUNT(*) FROM events GROUP BY kind').fetchall())
        kinds_window = dict(db.execute('SELECT kind, COUNT(*) FROM events WHERE observed >= ? GROUP BY kind', (window_start,)).fetchall())

        task_events_total = kinds_all.get('task_observed', 0)
        task_events_window = kinds_window.get('task_observed', 0)

        if task_events_total == 0:
            task_telemetry_status = 'missing'
        elif task_events_window == 0:
            task_telemetry_status = 'zero_tasks'
        else:
            task_telemetry_status = 'available'

        completed_tasks = 0
        failed_tasks = 0
        running_tasks = 0
        task_rows = db.execute("SELECT payload FROM events WHERE kind='task_observed' AND observed >= ?", (window_start,)).fetchall()
        for (payload_str,) in task_rows:
            try:
                p = json.loads(payload_str)
                task_obj = p.get('task') if isinstance(p.get('task'), dict) else p
                status = (task_obj.get('outcome') or task_obj.get('status') or '').lower()
                if status == 'completed':
                    completed_tasks += 1
                elif status == 'failed':
                    failed_tasks += 1
                elif status == 'running':
                    running_tasks += 1
            except (ValueError, TypeError):
                pass

        fo = kinds_window.get('file_observed', 0)
        fnld = kinds_window.get('file_no_longer_dirty', 0)
        ofo = kinds_window.get('open_file_observed', 0)
        churn_total = fo + fnld + ofo

        observation_gap = latest_observed < window_start
        observation_gap_seconds = round(now_ts - latest_observed, 1) if observation_gap else None

        if observation_gap:
            activity_status = 'gap_detected'
        elif window_events == 0:
            activity_status = 'no_activity'
        else:
            activity_status = 'active'

        return {
            'store_status': 'available',
            'total_events': total_events,
            'latest_observed': latest_observed,
            'latest_observed_iso': latest_iso,
            'last_sample_age_seconds': last_sample_age,
            'window_hours': float(hours),
            'window_events': window_events,
            'observation_gap': observation_gap,
            'observation_gap_seconds': observation_gap_seconds,
            'task_events': task_events_total,
            'task_events_window': task_events_window,
            'completed_tasks': completed_tasks,
            'failed_tasks': failed_tasks,
            'running_tasks': running_tasks,
            'task_telemetry_status': task_telemetry_status,
            'activity_status': activity_status,
            'metadata_churn': {
                'file_events': fo + fnld,
                'file_observed': fo,
                'file_no_longer_dirty': fnld,
                'open_file_observed': ofo,
                'total': churn_total,
            },
        }
    finally:
        db.close()


def read(state_dir, limit=50, kind=None, search=None, hours=24, now=None, exclude_metadata_churn=False):
    path = state_dir / 'history.sqlite3'
    if not path.exists():
        return []
    now_ts = time.time() if now is None else float(now)
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        query = 'SELECT observed,kind,payload FROM events WHERE observed>=?'
        values = [now_ts - hours * 3600]
        if kind:
            query += ' AND kind=?'
            values.append(kind)
        elif exclude_metadata_churn:
            query += " AND kind NOT IN ('file_observed', 'file_no_longer_dirty', 'open_file_observed')"
        if search:
            query += ' AND instr(payload,?)>0'
            values.append(search)
        query += ' ORDER BY id DESC LIMIT ?'
        values.append(limit)
        rows = db.execute(query, values).fetchall()
        return [dict(json.loads(payload), observed=when, kind=event_kind)
                for when, event_kind, payload in rows]
    finally:
        db.close()

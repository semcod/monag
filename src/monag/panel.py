"""Local-only HTTP dashboard over monag's own read-only observations.

Serves the live agent/repository snapshot and Planfile backlog (refreshed on
a background timer, same data `status`/`resume` already compute) plus the
Planfile/GitHub audit, project catalog, and candidate-work export reports,
computed lazily on first request and cached briefly, since they call out to
`git`/`gh` per repository. Export is served without --radar/--hygiene (both
shell out per candidate/repository and would make an on-demand refresh slow);
use `monag export --radar --hygiene` directly for the enriched report.

Binds to 127.0.0.1 by default: this shows your own process activity, working
directories and tickets, and is not meant to be reachable from another
machine. Passing --bind widens that; the caller decides what network that
exposes it to, this module never chooses a wider bind on its own.

The preferred port may already be taken by an unrelated service (observed in
practice: another local dashboard already listening on 8090). `bind_server`
never binds to a substitute port silently: it tries the preferred port, then
a bounded number of ports after it, then finally lets the OS assign any free
port, and always reports which port it actually used.
"""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import time
from urllib.parse import parse_qs, urlparse

from . import audit, catalog, export, resume
from .monitor import snapshot as monitor_snapshot
from .presentation import clean

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>monag panel</title>
<style>
body{font-family:system-ui,sans-serif;margin:1.5rem;background:#0b0f14;color:#d6e0ea}
h1{font-size:1.1rem;margin:0 0 .25rem}
.sub{color:#8a9bb0;font-size:.85rem;margin-bottom:1rem}
section{margin-bottom:1.5rem}
h2{font-size:.95rem;color:#8fd3ff;border-bottom:1px solid #223;padding-bottom:.25rem}
table{border-collapse:collapse;width:100%;font-size:.85rem}
td,th{border-bottom:1px solid #1c2733;padding:.3rem .5rem;text-align:left;vertical-align:top}
th{color:#8a9bb0;font-weight:600}
.stale{color:#e0a04a}
.empty{color:#5a6b7d;font-style:italic}
button{background:#16202b;color:#d6e0ea;border:1px solid #2a3a4a;border-radius:4px;
       padding:.3rem .7rem;font-size:.8rem;cursor:pointer}
</style></head>
<body>
<h1>monag panel</h1>
<div class="sub" id="meta">loading…</div>

<section><h2>Agents</h2><table id="agents"><thead><tr>
<th>PID</th><th>Kind</th><th>Task</th><th>Working directory</th></tr></thead>
<tbody></tbody></table></section>

<section><h2>Projects with local changes or open tickets</h2><table id="projects">
<thead><tr><th>Path</th><th>Branch</th><th>Changed files</th><th>Agents</th></tr></thead>
<tbody></tbody></table></section>

<section><h2>Open Planfile tickets</h2><table id="tickets"><thead><tr>
<th>Project</th><th>Ticket</th><th>Priority</th><th>Status</th><th>Title</th></tr></thead>
<tbody></tbody></table></section>

<section><h2>Planfile / GitHub coverage audit
<button onclick="loadAudit()">refresh</button></h2>
<table id="audit"><thead><tr><th>Repository</th><th>GitHub issues</th>
<th>Planfile tickets</th><th>Untracked</th><th>Sync drift</th></tr></thead>
<tbody></tbody></table></section>

<section><h2>Project catalog
<button onclick="loadCatalog()">refresh</button></h2>
<table id="catalog"><thead><tr><th>Name</th><th>Stacks</th>
<th>Description</th></tr></thead><tbody></tbody></table></section>

<section><h2>Candidate work (review only, nothing queued)
<button onclick="loadExport()">refresh</button></h2>
<table id="export"><thead><tr><th>Origin</th><th>Repository</th>
<th>Title</th><th>Evidence</th></tr></thead><tbody></tbody></table></section>

<script>
function row(cells){const tr=document.createElement('tr');
  for(const c of cells){const td=document.createElement('td');td.textContent=c;tr.appendChild(td);}
  return tr;}
function fill(id, rows, empty){const tbody=document.querySelector('#'+id+' tbody');
  tbody.innerHTML='';
  if(!rows.length){const tr=document.createElement('tr');const td=document.createElement('td');
    td.colSpan=8;td.className='empty';td.textContent=empty;tr.appendChild(td);tbody.appendChild(tr);return;}
  for(const r of rows) tbody.appendChild(row(r));}
async function loadLive(){
  const [snap, res] = await Promise.all([
    fetch('/api/snapshot.json').then(r=>r.json()),
    fetch('/api/resume.json').then(r=>r.json())]);
  document.getElementById('meta').textContent =
    snap.observed_at + ' · ' + snap.agents.length + ' agents · ' +
    snap.repositories.length + ' checkouts observed';
  fill('agents', snap.agents.map(a=>[a.pid, a.kind, a.task, a.cwd]), 'No recognized agent processes.');
  const dirty = snap.repositories.filter(r=>r.files.length);
  fill('projects', dirty.map(r=>[r.path, r.branch, r.files.length, r.agents.length]),
       'No checkouts with local changes.');
  const tickets = (res.projects||[]).flatMap(p=>(p.planfile.remaining_tickets||[])
    .map(t=>[p.path, t.id, t.priority, t.status, t.title]));
  fill('tickets', tickets, 'No open Planfile tickets observed.');
}
async function loadAudit(){
  const data = await fetch('/api/audit.json').then(r=>r.json());
  fill('audit', data.repositories.map(r=>[r.repo||r.path,
    r.github_issue_count==null?'-':r.github_issue_count,
    r.planfile_available?r.ticket_count:'-',
    r.untracked_issues.length, r.sync_drift.length]), 'No repositories observed.');
}
async function loadCatalog(){
  const data = await fetch('/api/catalog.json').then(r=>r.json());
  fill('catalog', data.repositories.map(r=>[r.name, r.stacks.join(', ')||'-',
    r.description||'(undeclared)']), 'No repositories observed.');
}
async function loadExport(){
  const data = await fetch('/api/export.json').then(r=>r.json());
  fill('export', data.candidates.map(c=>[c.origin, c.repo||c.path, c.title, c.evidence]),
       'No candidates observed.');
}
loadLive(); loadAudit(); loadCatalog(); loadExport();
setInterval(loadLive, 5000);
</script>
</body></html>"""


class State:
    """Background-refreshed live view, plus lazily-computed, briefly-cached reports."""

    def __init__(self, root, state_dir, depth, registry, github, machine, all_users, open_files):
        self.root, self.state_dir, self.depth = root, state_dir, depth
        self.registry, self.github = registry, github
        self.machine, self.all_users, self.open_files = machine, all_users, open_files
        self.lock = threading.Lock()
        self.snapshot, self.resume = {'agents': [], 'repositories': [], 'observed_at': None}, {'projects': []}
        self._cache = {}
        self._audit, self._audit_at = None, 0.0
        self._catalog, self._catalog_at = None, 0.0
        self._export, self._export_at = None, 0.0
        self._prs, self._prs_at = None, 0.0

    def get_prs(self, ttl=60):
        with self.lock:
            if self._prs is not None and time.monotonic() - self._prs_at < ttl:
                return self._prs
        from . import prs
        data = prs.scan(self.root, self.depth)
        with self.lock:
            self._prs, self._prs_at = data, time.monotonic()
        return data

    def refresh_live(self):
        since = '24 hours ago'
        data = monitor_snapshot(self.root, self.state_dir, self.depth, since, self.github,
                                self._cache, self.registry, self.machine, self.all_users, self.open_files)
        resume_data = resume.scan(self.root, self.depth)
        with self.lock:
            self.snapshot, self.resume = data, resume_data

    def refresh_loop(self, interval, stop_event):
        while not stop_event.is_set():
            try:
                self.refresh_live()
            except (OSError, ValueError):
                pass  # keep serving the last good snapshot rather than crash the panel
            stop_event.wait(interval)

    def get_audit(self, ttl=300):
        with self.lock:
            if self._audit is not None and time.monotonic() - self._audit_at < ttl:
                return self._audit
        data = audit.scan(self.root, self.depth)
        with self.lock:
            self._audit, self._audit_at = data, time.monotonic()
        return data

    def get_catalog(self, ttl=600):
        with self.lock:
            if self._catalog is not None and time.monotonic() - self._catalog_at < ttl:
                return self._catalog
        data = catalog.scan(self.root, self.depth)
        with self.lock:
            self._catalog, self._catalog_at = data, time.monotonic()
        return data

    def get_export(self, ttl=300):
        """Candidates only (radar/hygiene off): both shell out per candidate/
        repository and would make the panel's on-demand refresh slow."""
        with self.lock:
            if self._export is not None and time.monotonic() - self._export_at < ttl:
                return self._export
        data = export.scan(self.root, self.depth)
        with self.lock:
            self._export, self._export_at = data, time.monotonic()
        return data


ROUTES = {'/api/snapshot.json': lambda s: s.snapshot,
          '/api/resume.json': lambda s: s.resume,
          '/api/prs.json': State.get_prs,
          '/api/audit.json': State.get_audit,
          '/api/catalog.json': State.get_catalog,
          '/api/export.json': State.get_export}


def make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'monag-panel/1'

        def log_message(self, *args):
            pass  # served content is local-only observation data; keep stderr quiet

        def _send(self, body, content_type, status=200):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == '/':
                self._send(PAGE.encode(), 'text/html; charset=utf-8')
                return
            if parsed.path in {'/api/query', '/api/query.json'}:
                params = parse_qs(parsed.query)
                q = (params.get('q') or params.get('query') or params.get('nl') or [''])[0]
                if not q:
                    self._send(json.dumps({'error': 'query required in q or query param'}).encode(),
                              'application/json; charset=utf-8', status=400)
                    return
                from . import dsl
                result = dsl.execute(q, state.root, depth=state.depth, registry=state.registry)
                self._send(json.dumps(result, ensure_ascii=True).encode(), 'application/json; charset=utf-8')
                return
            handler = ROUTES.get(parsed.path)
            if handler is None:
                self._send(json.dumps({'error': 'not found', 'path': clean(self.path)}).encode(),
                          'application/json; charset=utf-8', status=404)
                return
            try:
                payload = handler(state)
            except (OSError, ValueError) as error:
                self._send(json.dumps({'error': str(error)}).encode(),
                          'application/json; charset=utf-8', status=500)
                return
            self._send(json.dumps(payload, ensure_ascii=True).encode(), 'application/json; charset=utf-8')

        def do_POST(self):
            parsed = urlparse(self.path)
            if parsed.path in {'/api/query', '/api/query.json'}:
                try:
                    length = int(self.headers.get('Content-Length', 0))
                    raw_data = self.rfile.read(length)
                    body = json.loads(raw_data) if raw_data else {}
                except (ValueError, TypeError, json.JSONDecodeError):
                    self._send(json.dumps({'error': 'invalid json body'}).encode(),
                              'application/json; charset=utf-8', status=400)
                    return
                q = body.get('query') or body.get('q') or body.get('nl') or ''
                if not q:
                    self._send(json.dumps({'error': 'query or nl field required in body'}).encode(),
                              'application/json; charset=utf-8', status=400)
                    return
                from . import dsl
                result = dsl.execute(q, state.root, depth=state.depth, registry=state.registry)
                self._send(json.dumps(result, ensure_ascii=True).encode(), 'application/json; charset=utf-8')
                return
            self._send(json.dumps({'error': 'method not allowed'}).encode(),
                      'application/json; charset=utf-8', status=405)
    return Handler


def bind_server(handler_cls, bind, port, attempts=20):
    """Bind to `port` if free, else scan forward, else let the OS assign one.

    Binding (not a separate probe-then-bind) is the only reliable check --
    a probe followed by a later bind is a race. Every rejected port and its
    error is kept so a genuine permission problem (not just "in use") is
    still visible if every candidate fails.
    """
    candidates = []
    if port:
        if not 1 <= port <= 65535:
            raise ValueError('port must be between 1 and 65535, or 0 for automatic')
        candidates = [p for p in range(port, min(port + attempts, 65536))]
    candidates.append(0)  # last resort: any free port the OS assigns
    errors = []
    for candidate in candidates:
        try:
            return ThreadingHTTPServer((bind, candidate), handler_cls)
        except OSError as error:
            errors.append(f'{candidate}: {error}')
    raise OSError('no available port: ' + '; '.join(errors))


def write_state_file(state_dir, bind, port):
    """Best-effort discoverability record; the server itself is the truth."""
    path = state_dir / 'panel.json'
    try:
        state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = json.dumps({'bind': bind, 'port': port, 'pid': os.getpid(),
                              'url': f'http://{bind}:{port}/', 'started_at': time.time()})
        temp = path.with_suffix('.tmp')
        temp.write_text(payload)
        temp.chmod(0o600)
        temp.replace(path)
    except OSError:
        pass  # discoverability only; the bound server is unaffected


def build_server(root, state_dir, depth=2, bind='127.0.0.1', port=8090, port_attempts=20,
                 registry=None, github=False, machine=False, all_users=False, open_files=False):
    state = State(root, state_dir, depth, registry, github, machine, all_users, open_files)
    server = bind_server(make_handler(state), bind, port, port_attempts)
    return server, state


def serve(root, state_dir, depth=2, bind='127.0.0.1', port=8090, interval=30, port_attempts=20,
         registry=None, github=False, machine=False, all_users=False, open_files=False,
         on_ready=None):
    """Blocks until interrupted; the caller handles Ctrl-C / shutdown.

    `on_ready(bind, actual_port)` is called once binding succeeds -- the
    actual port can differ from the requested one, so callers that need to
    log or display it should read it from here, not echo back `port`.
    """
    server, state = build_server(root, state_dir, depth, bind, port, port_attempts, registry,
                                 github, machine, all_users, open_files)
    actual_port = server.server_address[1]
    write_state_file(state_dir, bind, actual_port)
    if on_ready is not None:
        on_ready(bind, actual_port)
    state.refresh_live()
    stop_event = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(state.refresh_loop, interval, stop_event)
        try:
            server.serve_forever(poll_interval=0.5)
        finally:
            stop_event.set()
            server.shutdown()
    server.server_close()

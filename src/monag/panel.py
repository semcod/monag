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
.badge{display:inline-block;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:600;text-transform:uppercase}
.badge-critical,.badge-floor,.badge-immediate-blocker{background:#da3633;color:#fff}
.badge-high,.badge-mission,.badge-core-foundation{background:#d29922;color:#fff}
.badge-medium,.badge-normal,.badge-hygiene,.badge-operator-ide-alert{background:#1f6feb;color:#fff}
.badge-fleet-health-diagnostic{background:#388bfd;color:#fff}
.badge-strategic-architecture{background:#8957e5;color:#fff}
.badge-low,.badge-backlog,.badge-code-smell-hygiene{background:#8b949e;color:#fff}
.badge-safe{background:#238636;color:#fff}
.badge-collision{background:#da3633;color:#fff}
.badge-warning{background:#d29922;color:#fff}
details summary{cursor:pointer;color:#58a6ff;font-size:.8rem}
details code{background:#16202b;padding:2px 4px;border-radius:3px;font-family:monospace;display:block;margin-top:4px;word-break:break-all}
.live-badge{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:#3fb950;margin-left:14px;font-weight:normal;vertical-align:middle}
.pulse-dot{width:8px;height:8px;border-radius:50%;background:#3fb950;box-shadow:0 0 0 rgba(63,185,80,0.4);animation:pulse 2s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(63,185,80,0.7)}70%{box-shadow:0 0 0 8px rgba(63,185,80,0)}100%{box-shadow:0 0 0 0 rgba(63,185,80,0)}}
.toast{position:fixed;bottom:20px;right:20px;background:#1f6feb;color:#fff;padding:10px 16px;border-radius:6px;box-shadow:0 4px 12px rgba(0,0,0,0.5);z-index:9999;font-size:13px;opacity:0;transition:opacity .3s ease;pointer-events:none}
.toast.show{opacity:1;pointer-events:auto}
.btn-sm{font-size:11px;padding:3px 7px;border-radius:3px;cursor:pointer}
.btn-koru{background:#238636;border:1px solid #2ea043;color:#fff}
.btn-koru:hover{background:#2ea043}
</style></head>
<body>
<h1>monag panel <span class="live-badge"><span class="pulse-dot"></span> <span>LIVE</span> <label style="margin-left:8px;font-size:12px;color:#8a9bb0"><input type="checkbox" id="autorefresh" checked onchange="toggleAutoRefresh(this.checked)"> auto-refresh (<span id="countdown">10s</span>)</label></span></h1>
<div class="sub" id="meta">loading…</div>
<div id="toast" class="toast"></div>

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

<section><h2>Periodic Report & Architectural Advisory
<button onclick="triggerReport()">send now</button>
<button onclick="disableReport()">disable cron</button></h2>
<div id="report-status" class="sub">loading…</div></section>

<section><h2>Fleet Autodiagnosis & Koru Autonomous Delegations
<button onclick="runAutodiagnosis()">run diagnosis</button>
<button onclick="dispatchToKoru()" class="btn-koru">⚡ dispatch all to koru</button>
<button onclick="syncWithGitHub()" style="background:#1f4368;border-color:#388bfd;color:#fff">sync with github</button>
<button onclick="runDailyAutomation()" style="background:#21262d;border:1px solid #30363d;color:#c9d1d9">daily automation</button></h2>
<div id="autodiag-summary" class="sub">loading autodiagnosis…</div>
<table id="autodiagnosis"><thead><tr>
<th>Target Repo</th><th>Tier</th><th>Priority</th><th>Title</th><th>Estimation (semcod)</th><th>Actions</th></tr></thead>
<tbody></tbody></table></section>

<section><h2>Holistic Triage & Agent Worktree Collision Monitor
<button onclick="loadTriage()">refresh</button>
<button onclick="dispatchTriageToKoru()" class="btn-koru">⚡ dispatch safe triage to koru</button></h2>
<div id="triage-summary" class="sub">loading holistic triage…</div>
<table id="triage"><thead><tr>
<th>Step</th><th>Tier</th><th>Repo</th><th>Title</th><th>Score</th><th>Collision Safety</th><th>Suggested Action & Guardrails</th></tr></thead>
<tbody></tbody></table></section>

<script>
function showToast(msg, isError=false){
  const el = document.getElementById('toast');
  if(!el) return;
  el.textContent = msg;
  el.style.background = isError ? '#da3633' : '#238636';
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 3500);
}

function row(cells){const tr=document.createElement('tr');
  for(const c of cells){const td=document.createElement('td');td.textContent=c;tr.appendChild(td);}
  return tr;}
function fill(id, rows, empty){const tbody=document.querySelector('#'+id+' tbody');
  tbody.innerHTML='';
  if(!rows.length){const tr=document.createElement('tr');const td=document.createElement('td');
    td.colSpan=8;td.className='empty';td.textContent=empty;tr.appendChild(td);tbody.appendChild(tr);return;}
  for(const r of rows) tbody.appendChild(row(r));}

let refreshSeconds = 10;
let autoRefreshEnabled = true;

function toggleAutoRefresh(enabled) {
  autoRefreshEnabled = enabled;
  const cd = document.getElementById('countdown');
  if (cd) cd.textContent = enabled ? `${refreshSeconds}s` : 'paused';
}

function tickCountdown() {
  if (!autoRefreshEnabled) return;
  refreshSeconds--;
  if (refreshSeconds <= 0) {
    refreshSeconds = 10;
    loadLive();
  }
  const cd = document.getElementById('countdown');
  if (cd) cd.textContent = `${refreshSeconds}s`;
}

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
async function loadReportStatus(){
  try{
    const res = await fetch('/api/report/status.json').then(r=>r.json());
    document.getElementById('report-status').textContent =
      'Recipient: ' + (res.detected_email || 'none detected') + ' · Local URL: ' + res.server_url;
  }catch(e){}
}
async function triggerReport(){
  const res = await fetch('/api/report/send-now.json').then(r=>r.json());
  showToast(res.status === 'ok' ? 'Report sent!' : 'Send failed: ' + (res.error || JSON.stringify(res.detail)), res.status !== 'ok');
}
async function disableReport(){
  const res = await fetch('/api/report/disable.json').then(r=>r.json());
  showToast(res.status === 'ok' ? 'Schedule disabled!' : 'Disable failed: ' + JSON.stringify(res.detail), res.status !== 'ok');
}
async function loadAutodiagnosis(){
  try{
    const res = await fetch('/api/autodiagnosis.json').then(r=>r.json());
    renderAutodiag(res);
  }catch(e){
    document.getElementById('autodiag-summary').textContent = 'Error loading autodiagnosis: ' + e;
  }
}
function renderAutodiag(res){
  const sum = res.summary || {};
  const cachedStr = sum.repositories_cached ? ` (${sum.repositories_cached} cached)` : '';
  document.getElementById('autodiag-summary').textContent =
    'Inspected: ' + (sum.total_repositories || 0) + ' repos' + cachedStr + ' · Issues: ' + (sum.total_anomalies || 0) + ' · Actionable tickets: ' + ((res.tickets||[]).length);
  const tbody = document.querySelector('#autodiagnosis tbody');
  tbody.innerHTML = '';
  const tickets = res.tickets || [];
  if (!tickets.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 6; td.className = 'empty'; td.textContent = 'No technical anomalies found in workspace.';
    tr.appendChild(td); tbody.appendChild(tr); return;
  }
  for (const t of tickets) {
    const tr = document.createElement('tr');
    const est = t.estimation || {};
    const estStr = est.duration_p90_seconds ? `${est.duration_p90_seconds}s / ${est.peak_rss_mb || 0}MB (${est.confidence || 'none'})` : '-';
    const tier = (t.tier || 'STANDARD').toUpperCase();
    const prio = (t.priority || 'NORMAL').toUpperCase();
    const tierClass = 'badge badge-' + (t.tier || 'backlog').toLowerCase();
    const prioClass = 'badge badge-' + (t.priority || 'normal').toLowerCase();
    const detailsHtml = t.verification_command ? `<details style="margin-top:4px"><summary>verify: <code>${t.verification_command}</code></summary><div style="font-size:11px;margin-top:4px;color:#8a9bb0">${(t.acceptance_criteria||[]).join('<br>')}</div></details>` : '';
    const escapedRepo = encodeURIComponent(t.target_repo || '');
    const escapedTitle = encodeURIComponent(t.title || '');
    tr.innerHTML = `<td><code>${t.target_repo}</code></td>
      <td><span class="${tierClass}">${tier}</span></td>
      <td><span class="${prioClass}">${prio}</span></td>
      <td><strong>${t.title}</strong>${detailsHtml}</td>
      <td>${estStr}</td>
      <td><button class="btn-sm btn-koru" onclick="dispatchSingleToKoru('${escapedRepo}','${escapedTitle}')">⚡ dispatch to koru</button></td>`;
    tbody.appendChild(tr);
  }
}
async function syncWithGitHub(){
  showToast('Synchronizing Planfile tickets with GitHub Issues…');
  try{
    const res = await fetch('/api/autodiagnosis/sync-github.json').then(r=>r.json());
    showToast('✓ GitHub sync completed for ' + (res.synced_repositories || 0) + ' repositories!');
    loadAutodiagnosis();
  }catch(e){
    showToast('GitHub sync failed: ' + e, true);
  }
}
async function runAutodiagnosis(){
  showToast('Running fleet autodiagnosis…');
  try{
    const res = await fetch('/api/autodiagnosis/run.json').then(r=>r.json());
    renderAutodiag(res);
    showToast('✓ Fleet autodiagnosis completed!');
  }catch(e){
    showToast('Autodiagnosis failed: ' + e, true);
  }
}
async function dispatchSingleToKoru(encodedRepo, encodedTitle){
  const repo = decodeURIComponent(encodedRepo);
  const title = decodeURIComponent(encodedTitle);
  showToast('Dispatching ' + repo + ' ticket to Koru…');
  try{
    const res = await fetch('/api/autodiagnosis/dispatch-koru.json', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({repo: repo, title: title})
    }).then(r=>r.json());
    const koruMsg = res.koru_active ? ' (Koru daemon PID ' + res.koru_pids.join(', ') + ' active)' : ' (Queued in Planfile)';
    showToast('✓ Dispatched ' + repo + ' ticket to Planfile' + koruMsg);
    loadAutodiagnosis();
  }catch(e){
    showToast('Dispatch failed: ' + e, true);
  }
}
async function dispatchToKoru(){
  showToast('Dispatching all synthesized tickets to Planfile for Koru…');
  try{
    const res = await fetch('/api/autodiagnosis/dispatch-koru.json', {method: 'POST'}).then(r=>r.json());
    const koruMsg = res.koru_active ? ' (' + res.koru_pids.length + ' Koru processes active)' : '';
    showToast('✓ Dispatched ' + res.dispatched_count + ' tickets to Planfile' + koruMsg);
    loadAutodiagnosis();
  }catch(e){
    showToast('Dispatch failed: ' + e, true);
  }
}
async function runDailyAutomation(){
  showToast('Executing daily automated diagnostic & delegation…');
  try{
    const res = await fetch('/api/autodiagnosis/daily.json').then(r=>r.json());
    showToast('✓ Daily automation completed! Tickets dispatched to Planfile for Koru Autonomous execution.');
    loadAutodiagnosis();
  }catch(e){
    showToast('Daily automation failed: ' + e, true);
  }
}
async function loadTriage(){
  try{
    const data = await fetch('/api/triage.json').then(r=>r.json());
    renderTriage(data);
  }catch(e){
    const el = document.getElementById('triage-summary');
    if(el) el.textContent = 'Failed loading triage: ' + e;
  }
}
function renderTriage(data){
  const el = document.getElementById('triage-summary');
  if(!el) return;
  const pids = (data.active_agent_pids||[]).join(', ');
  el.innerHTML = `<strong>${data.total_candidates||0} candidates</strong> evaluated across <strong>${data.discovered_repos_count||0} repos</strong> · ` +
    `<span style="color:${(data.collision_count||0) > 0 ? '#f85149' : '#3fb950'}">` +
    `<strong>${data.collision_count||0} declared scope conflicts</strong> · <strong>${data.dirty_worktrees_count||0} dirty worktrees</strong></span> · ` +
    `Active agent fleet: <strong>${data.active_agents_count||0}</strong> processes (PIDs: ${pids || 'none'})`;

  const tbody = document.querySelector('#triage tbody');
  if(!tbody) return;
  tbody.innerHTML = '';
  const steps = data.guidance_steps || [];
  if(!steps.length){
    const tr = document.createElement('tr');
    tr.innerHTML = '<td colspan="7" class="empty">No guidance steps generated.</td>';
    tbody.appendChild(tr);
    return;
  }
  for(const s of steps){
    const tr = document.createElement('tr');
    const catClass = 'badge-' + (s.category || 'backlog').replace(/_/g, '-');
    const safetyBadge = s.collision_safe === false
      ? '<span class="badge badge-collision">⚠️ Active Agent / Conflict</span>'
      : (s.collision_safe === true ? '<span class="badge badge-safe">✓ Safe</span>' : '<span class="badge badge-warning">Unverified</span>');
    
    const pidsInfo = (s.active_agent_pids && s.active_agent_pids.length) ? `<br><small style="color:#f85149">PIDs: ${s.active_agent_pids.join(', ')}</small>` : '';
    const guardrails = (s.guardrails||[]).map(g=>`<li>${g}</li>`).join('');
    const guardrailsHtml = guardrails ? `<details style="margin-top:4px"><summary>Guardrails</summary><ul style="margin:2px 0 0 16px;padding:0;font-size:11px;color:#8a9bb0">${guardrails}</ul></details>` : '';

    const safeDispatch = s.collision_safe !== false
      ? `<button class="btn-sm btn-koru" onclick="dispatchSingleToKoru('${encodeURIComponent(s.repo)}', '${encodeURIComponent(s.title)}')">⚡ dispatch</button>`
      : '<span style="color:#da3633;font-size:11px">blocked</span>';

    tr.innerHTML = `
      <td><strong>${s.step}</strong></td>
      <td><span class="badge ${catClass}">${s.category.replace(/_/g, ' ')}</span></td>
      <td><code>${s.repo}</code></td>
      <td>${s.title}${pidsInfo}</td>
      <td><code>${s.score}</code></td>
      <td>${safetyBadge}</td>
      <td>
        <div>${s.action}</div>
        <details style="margin-top:2px"><summary>Command</summary><code>${s.command}</code></details>
        ${guardrailsHtml}
        <div style="margin-top:4px">${safeDispatch}</div>
      </td>
    `;
    tbody.appendChild(tr);
  }
}
async function dispatchTriageToKoru(){
  showToast('Dispatching safe triage steps to Planfile for Koru…');
  try{
    const res = await fetch('/api/triage/dispatch-koru.json', {method: 'POST'}).then(r=>r.json());
    const koruMsg = res.koru_active ? ' (' + res.koru_pids.length + ' Koru processes active)' : '';
    showToast('✓ Dispatched ' + res.dispatched_count + ' triage steps to Planfile' + koruMsg);
    loadTriage();
  }catch(e){
    showToast('Dispatch failed: ' + e, true);
  }
}
loadLive(); loadAudit(); loadCatalog(); loadExport(); loadReportStatus(); loadAutodiagnosis(); loadTriage();
setInterval(tickCountdown, 1000);
</script>
</body></html>"""


class State:
    """Background-refreshed live view, plus lazily-computed, briefly-cached reports."""

    def __init__(self, root, state_dir, depth=2, registry=None, github=False, machine=False,
                 all_users=False, open_files=False, bind='127.0.0.1', port=8090):
        self.root, self.state_dir, self.depth = root, state_dir, depth
        self.registry, self.github = registry or {}, github
        self.machine, self.all_users, self.open_files = machine, all_users, open_files
        self.bind, self.port = bind, port
        self.lock = threading.Lock()
        self.snapshot, self.resume = {'agents': [], 'repositories': [], 'observed_at': None}, {'projects': []}
        self._cache = {}
        self._audit, self._audit_at = None, 0.0
        self._catalog, self._catalog_at = None, 0.0
        self._export, self._export_at = None, 0.0
        self._prs, self._prs_at = None, 0.0
        self._autodiag, self._autodiag_at = None, 0.0
        self._triage, self._triage_at = None, 0.0

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

    def get_advise(self, ttl=300):
        with self.lock:
            if getattr(self, '_advise', None) is not None and time.monotonic() - getattr(self, '_advise_at', 0) < ttl:
                return self._advise
        from . import advise
        data = advise.advise(self.root, depth=self.depth, state_dir=self.state_dir)
        with self.lock:
            self._advise, self._advise_at = data, time.monotonic()
        return data

    def get_report_status(self):
        from . import report
        email_detected = report.detect_user_email()
        return {
            'status': 'ok',
            'detected_email': email_detected,
            'root': str(self.root),
            'server_url': f"http://{self.bind}:{self.port}",
        }

    def report_disable(self):
        from . import report
        res = report.remove_cron()
        return {
            'status': 'ok' if res.get('ok') else 'error',
            'action': 'cron_disabled',
            'detail': res,
        }

    def report_send_now(self):
        from . import report
        email_addr = report.detect_user_email()
        if not email_addr:
            return {'status': 'error', 'error': 'No recipient email detected from gh or git config'}
        data = report.collect(self.root, depth=self.depth, state_dir=self.state_dir)
        body = report.markdown(data, port=self.port, recipients=[email_addr])
        smtp_cfg = report._smtp_config()
        res = report.send_email([email_addr], f"MONAG on-demand report — {self.root.name}", body, smtp_cfg)
        return {'status': 'ok' if res.get('ok') else 'error', 'detail': res}

    def get_autodiagnosis(self, ttl=60):
        with self.lock:
            if getattr(self, '_autodiag', None) is not None and time.monotonic() - getattr(self, '_autodiag_at', 0) < ttl:
                return self._autodiag
        from . import autodiagnosis
        report = autodiagnosis.diagnose_fleet(self.root, depth=self.depth)
        tickets = autodiagnosis.synthesize_tickets_with_subllm(report)
        data = {
            'status': 'ok',
            'summary': report.get('summary', {}),
            'tickets': tickets,
            'timestamp': report.get('timestamp'),
        }
        with self.lock:
            self._autodiag, self._autodiag_at = data, time.monotonic()
        return data

    def autodiagnosis_run(self):
        from . import autodiagnosis
        report = autodiagnosis.diagnose_fleet(self.root, depth=self.depth)
        tickets = autodiagnosis.synthesize_tickets_with_subllm(report)
        data = {
            'status': 'ok',
            'summary': report.get('summary', {}),
            'tickets': tickets,
            'timestamp': report.get('timestamp'),
        }
        with self.lock:
            self._autodiag, self._autodiag_at = data, time.monotonic()
        return data

    def autodiagnosis_dispatch(self):
        from . import autodiagnosis
        data = self.autodiagnosis_run()
        tickets = data.get('tickets', [])
        results = autodiagnosis.dispatch_tickets_to_planfile(tickets, root=self.root)
        return {
            'status': 'ok',
            'dispatched_count': results.get('dispatched', 0),
            'results': results,
        }

    def autodiagnosis_daily_automation(self):
        """Execute automated daily autodiagnosis, dispatch to Planfile and ready for Koru."""
        dispatch_res = self.autodiagnosis_dispatch()
        return {
            'status': 'ok',
            'action': 'daily_automation_completed',
            'dispatched': dispatch_res,
            'koru_ready': True,
        }

    def autodiagnosis_sync_github(self):
        """Run planfile sync github across repositories with .planfile in workspace."""
        from . import autodiagnosis
        repos = []
        if (self.root / ".planfile").exists():
            repos.append(self.root)
        else:
            try:
                for p in self.root.iterdir():
                    if p.is_dir() and not p.name.startswith("."):
                        if (p / ".planfile").exists():
                            repos.append(p)
                        else:
                            for sub in p.iterdir():
                                if sub.is_dir() and not sub.name.startswith(".") and (sub / ".planfile").exists():
                                    repos.append(sub)
            except Exception:
                pass
        results = [autodiagnosis.sync_planfile_github(r) for r in repos]
        return {
            'status': 'ok',
            'synced_repositories': len(repos),
            'results': results,
        }

    def autodiagnosis_dispatch_koru(self, target_repo=None, ticket_id=None):
        """Dispatch autodiagnosis tickets to target repositories' Planfile and notify Koru."""
        from . import autodiagnosis
        data = self.autodiagnosis_run()
        tickets = data.get('tickets', [])
        if target_repo:
            tickets = [t for t in tickets if t.get('target_repo') == target_repo]
        if ticket_id:
            tickets = [t for t in tickets if t.get('ticket_id') == ticket_id or t.get('title') == ticket_id]

        results = autodiagnosis.dispatch_tickets_to_planfile(tickets, root=self.root, sync_github=True)

        koru_pids = []
        try:
            agents = (self.snapshot or {}).get('agents', [])
            for a in agents:
                cmd = (a.get('command') or '') + ' ' + (a.get('kind') or '')
                if 'koru' in cmd.lower():
                    koru_pids.append(a.get('pid'))
        except Exception:
            pass

        return {
            'status': 'ok',
            'action': 'dispatch_to_koru',
            'dispatched_count': results.get('dispatched', 0),
            'koru_active': bool(koru_pids),
            'koru_pids': koru_pids,
            'results': results,
            'target_repo': target_repo,
        }

    def get_triage(self, ttl=60):
        with self.lock:
            if self._triage is not None and time.monotonic() - self._triage_at < ttl:
                return self._triage
        from . import triage
        data = triage.run_holistic_triage(self.root, self.depth)
        with self.lock:
            self._triage, self._triage_at = data, time.monotonic()
        return data

    def get_collisions(self, ttl=30):
        triage_data = self.get_triage(ttl=ttl)
        active_agents = triage_data.get('active_agents_count', 0)
        active_pids = triage_data.get('active_agent_pids', [])
        dirty_wts = triage_data.get('dirty_worktrees_count', 0)
        collisions = triage_data.get('collision_count', 0)
        recs = triage_data.get('recommendations', [])
        colliding_items = [r for r in recs if r.get('collision', {}).get('has_collision') or r.get('collision', {}).get('blocking')]
        return {
            'active_agents_count': active_agents,
            'active_agent_pids': active_pids,
            'dirty_worktrees_count': dirty_wts,
            'collision_count': collisions,
            'colliding_items': colliding_items,
        }

    def triage_dispatch_koru(self, target_repo=None, ticket_id=None):
        """Dispatch collision-safe triage guidance steps to Planfile for Koru execution."""
        from . import triage, autodiagnosis
        data = self.get_triage()
        steps = data.get('guidance_steps', [])
        safe_steps = [s for s in steps if s.get('collision_safe') is not False]
        if target_repo:
            safe_steps = [s for s in safe_steps if s.get('repo') == target_repo]
        if ticket_id:
            safe_steps = [s for s in safe_steps if s.get('title') == ticket_id or str(s.get('step')) == str(ticket_id)]

        tickets = []
        for s in safe_steps:
            tickets.append({
                'target_repo': s.get('repo'),
                'title': s.get('title'),
                'description': s.get('action'),
                'priority': 'high' if s.get('category') in (triage.CATEGORY_IMMEDIATE_BLOCKER, triage.CATEGORY_CORE_FOUNDATION) else 'medium',
                'verify_command': s.get('command'),
                'guardrails': s.get('guardrails'),
            })

        results = autodiagnosis.dispatch_tickets_to_planfile(tickets, root=self.root, sync_github=False)

        koru_pids = []
        try:
            agents = (self.snapshot or {}).get('agents', [])
            for a in agents:
                cmd = (a.get('command') or '') + ' ' + (a.get('kind') or '')
                if 'koru' in cmd.lower():
                    koru_pids.append(a.get('pid'))
        except Exception:
            pass

        return {
            'status': 'ok',
            'action': 'triage_dispatch_koru',
            'dispatched_count': results.get('dispatched', 0),
            'koru_active': bool(koru_pids),
            'koru_pids': koru_pids,
            'results': results,
            'target_repo': target_repo,
        }

    def worktrees_prune_safe(self, target_repo=None, dry_run=False):
        from . import worktrees
        return worktrees.prune_fleet_worktrees_safe(
            self.root, depth=self.depth, dry_run=dry_run, target_repo=target_repo
        )


ROUTES = {'/api/snapshot.json': lambda s: s.snapshot,
          '/api/resume.json': lambda s: s.resume,
          '/api/prs.json': State.get_prs,
          '/api/audit.json': State.get_audit,
          '/api/catalog.json': State.get_catalog,
          '/api/export.json': State.get_export,
          '/api/advise.json': State.get_advise,
          '/api/triage': State.get_triage,
          '/api/triage.json': State.get_triage,
          '/api/collisions': State.get_collisions,
          '/api/collisions.json': State.get_collisions,
          '/api/triage/dispatch-koru': State.triage_dispatch_koru,
          '/api/triage/dispatch-koru.json': State.triage_dispatch_koru,
          '/api/autodiagnosis': State.get_autodiagnosis,
          '/api/autodiagnosis.json': State.get_autodiagnosis,
          '/api/autodiagnosis/run': State.autodiagnosis_run,
          '/api/autodiagnosis/run.json': State.autodiagnosis_run,
          '/api/autodiagnosis/dispatch': State.autodiagnosis_dispatch,
          '/api/autodiagnosis/dispatch.json': State.autodiagnosis_dispatch,
          '/api/autodiagnosis/dispatch-koru': State.autodiagnosis_dispatch_koru,
          '/api/autodiagnosis/dispatch-koru.json': State.autodiagnosis_dispatch_koru,
          '/api/autodiagnosis/daily': State.autodiagnosis_daily_automation,
          '/api/autodiagnosis/daily.json': State.autodiagnosis_daily_automation,
          '/api/autodiagnosis/sync-github': State.autodiagnosis_sync_github,
          '/api/autodiagnosis/sync-github.json': State.autodiagnosis_sync_github,
          '/api/worktrees/prune-safe': State.worktrees_prune_safe,
          '/api/worktrees/prune-safe.json': State.worktrees_prune_safe,
          '/api/report/status': State.get_report_status,
          '/api/report/status.json': State.get_report_status,
          '/api/report/disable': State.report_disable,
          '/api/report/disable.json': State.report_disable,
          '/api/report/send-now': State.report_send_now,
          '/api/report/send-now.json': State.report_send_now}


def render_report_config_page(cfg, updated=False, server_url=''):
    notice = ''
    if updated:
        notice = f'<div style="background:#163820;border:1px solid #2d7a3a;padding:.6rem 1rem;border-radius:4px;margin-bottom:1rem;color:#7ee787">✓ Zaktualizowano konfigurację raportu! Interwał: <strong>{cfg.get("interval")}s</strong>, Odbiorcy: <strong>{", ".join(cfg.get("recipients", []))}</strong></div>'

    interval = cfg.get('interval', 3600)
    recipients = ', '.join(cfg.get('recipients', []))
    enabled = cfg.get('enabled', True)

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>MONAG — Konfiguracja Raportu</title>
<style>
body{{font-family:system-ui,sans-serif;margin:2rem auto;max-width:700px;background:#0b0f14;color:#d6e0ea;line-height:1.5}}
h1{{font-size:1.3rem;margin-bottom:.5rem;color:#8fd3ff}}
.sub{{color:#8a9bb0;font-size:.9rem;margin-bottom:1.5rem}}
.card{{background:#121820;border:1px solid #1c2733;border-radius:6px;padding:1.2rem;margin-bottom:1.5rem}}
.btn{{display:inline-block;background:#1b2633;color:#8fd3ff;border:1px solid #2a3a4a;border-radius:4px;padding:.4rem .8rem;font-size:.85rem;text-decoration:none;margin:.2rem;cursor:pointer}}
.btn:hover{{background:#223244;color:#fff}}
.btn.active{{background:#1f4368;border-color:#388bfd;color:#fff}}
label{{display:block;font-size:.85rem;color:#8a9bb0;margin-top:.8rem;margin-bottom:.3rem}}
input[type="text"]{{width:100%;box-sizing:border-box;background:#0b0f14;border:1px solid #2a3a4a;color:#d6e0ea;padding:.5rem;border-radius:4px}}
input[type="submit"]{{margin-top:1rem;background:#238636;color:#fff;border:none;padding:.5rem 1.2rem;border-radius:4px;cursor:pointer}}
a.back{{color:#8a9bb0;font-size:.85rem;text-decoration:none}}
a.back:hover{{color:#d6e0ea}}
</style></head>
<body>
<a class="back" href="/">&larr; Wróć do panelu monag</a>
<h1>Konfiguracja Raportu Cyklicznego</h1>
<div class="sub">Zarządzaj częstotliwością, odbiorcami i statusem wysyłki.</div>
{notice}

<div class="card">
  <h3>Częstotliwość wysyłki (1-click)</h3>
  <p style="font-size:.85rem;color:#8a9bb0">Wybierz jak często monag ma wysyłać raport na e-mail:</p>
  <a class="btn {'active' if interval == 1800 else ''}" href="/report/config?interval=1800">⏱ Co 30 minut</a>
  <a class="btn {'active' if interval == 3600 else ''}" href="/report/config?interval=3600">⏱ Co 1 godzinę</a>
  <a class="btn {'active' if interval == 7200 else ''}" href="/report/config?interval=7200">⏱ Co 2 godziny</a>
  <a class="btn {'active' if interval == 14400 else ''}" href="/report/config?interval=14400">⏱ Co 4 godziny</a>
  <a class="btn {'active' if interval == 86400 else ''}" href="/report/config?interval=86400">⏱ Raz na dobę (24h)</a>
</div>

<div class="card">
  <h3>Odbiorca i status</h3>
  <form method="GET" action="/report/config">
    <label>Adres e-mail odbiorcy:</label>
    <input type="text" name="email" value="{recipients}" placeholder="np. dev@domain.com" />
    <label>Status wysyłki:</label>
    <select name="enabled" style="background:#0b0f14;border:1px solid #2a3a4a;color:#d6e0ea;padding:.4rem;border-radius:4px">
      <option value="true" {"selected" if enabled else ""}>Aktywna</option>
      <option value="false" {"selected" if not enabled else ""}>Wstrzymana / Wyłączona</option>
    </select>
    <br/>
    <input type="submit" value="Zapisz ustawienia" />
  </form>
</div>
</body></html>"""


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
            if parsed.path in {'/report/config', '/api/report/config', '/api/report/config.json'}:
                params = parse_qs(parsed.query)
                from . import report as report_mod
                cfg = report_mod.load_config(state.state_dir)
                updated = False
                if 'interval' in params:
                    try:
                        cfg['interval'] = int(params['interval'][0])
                        updated = True
                    except ValueError:
                        pass
                if 'email' in params:
                    cfg['recipients'] = [e.strip() for e in params['email'][0].split(',') if e.strip()]
                    updated = True
                if 'enabled' in params:
                    cfg['enabled'] = params['enabled'][0].lower() in {'true', '1', 'yes', 'on'}
                    updated = True
                if 'schedule' in params:
                    cfg['schedule'] = params['schedule'][0].strip()
                    updated = True
                if updated:
                    report_mod.save_config(state.state_dir, cfg)

                accept = self.headers.get('Accept', '')
                if parsed.path == '/report/config' or ('text/html' in accept and not parsed.path.endswith('.json')):
                    html = render_report_config_page(cfg, updated=updated, server_url=f"http://{state.bind}:{state.port}")
                    self._send(html.encode('utf-8'), 'text/html; charset=utf-8')
                    return
                self._send(json.dumps({'status': 'ok', 'updated': updated, 'config': cfg}, ensure_ascii=False).encode(),
                           'application/json; charset=utf-8')
                return
            if parsed.path == '/api/v1/schema':
                from . import nl_contract
                self._send(json.dumps(nl_contract.grammar()).encode(),
                           'application/json; charset=utf-8')
                return
            if parsed.path in {'/api/query', '/api/query.json'}:
                params = parse_qs(parsed.query)
                q = (params.get('q') or params.get('query') or params.get('nl') or [''])[0]
                if not q:
                    self._send(json.dumps({'error': 'query required in q or query param'}).encode(),
                              'application/json; charset=utf-8', status=400)
                    return
                from . import dsl_llm
                result = dsl_llm.execute(q, state.root, depth=state.depth, registry=state.registry)
                self._send(json.dumps(result, ensure_ascii=True).encode(), 'application/json; charset=utf-8')
                return
            if parsed.path in {'/api/autodiagnosis/dispatch-koru', '/api/autodiagnosis/dispatch-koru.json'}:
                params = parse_qs(parsed.query)
                repo = (params.get('repo') or [None])[0]
                ticket_id = (params.get('ticket_id') or params.get('title') or [None])[0]
                res = state.autodiagnosis_dispatch_koru(target_repo=repo, ticket_id=ticket_id)
                self._send(json.dumps(res, ensure_ascii=False).encode(), 'application/json; charset=utf-8')
                return
            if parsed.path in {'/api/triage/dispatch-koru', '/api/triage/dispatch-koru.json'}:
                params = parse_qs(parsed.query)
                repo = (params.get('repo') or [None])[0]
                ticket_id = (params.get('ticket_id') or params.get('title') or [None])[0]
                res = state.triage_dispatch_koru(target_repo=repo, ticket_id=ticket_id)
                self._send(json.dumps(res, ensure_ascii=False).encode(), 'application/json; charset=utf-8')
                return
            if parsed.path in {'/api/worktrees/prune-safe', '/api/worktrees/prune-safe.json'}:
                params = parse_qs(parsed.query)
                repo = (params.get('repo') or [None])[0]
                dry_run = (params.get('dry_run') or ['false'])[0].lower() in {'1', 'true', 'yes'}
                res = state.worktrees_prune_safe(target_repo=repo, dry_run=dry_run)
                self._send(json.dumps(res, ensure_ascii=False).encode(), 'application/json; charset=utf-8')
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
            if parsed.path in {'/report/config', '/api/report/config', '/api/report/config.json'}:
                try:
                    length = int(self.headers.get('Content-Length', 0))
                    raw_data = self.rfile.read(length)
                    body = json.loads(raw_data) if raw_data else {}
                except (ValueError, TypeError, json.JSONDecodeError):
                    body = {}
                from . import report as report_mod
                cfg = report_mod.load_config(state.state_dir)
                updated = False
                if 'interval' in body:
                    try:
                        cfg['interval'] = int(body['interval'])
                        updated = True
                    except (ValueError, TypeError):
                        pass
                if 'email' in body:
                    if isinstance(body['email'], list):
                        cfg['recipients'] = body['email']
                    else:
                        cfg['recipients'] = [e.strip() for e in str(body['email']).split(',') if e.strip()]
                    updated = True
                if 'enabled' in body:
                    cfg['enabled'] = bool(body['enabled'])
                    updated = True
                if 'schedule' in body:
                    cfg['schedule'] = str(body['schedule']).strip()
                    updated = True
                if updated:
                    report_mod.save_config(state.state_dir, cfg)
                self._send(json.dumps({'status': 'ok', 'updated': updated, 'config': cfg}, ensure_ascii=False).encode(),
                           'application/json; charset=utf-8')
                return
            if parsed.path in {'/api/v1/query', '/api/v1/dsl'}:
                from . import nl_contract
                try:
                    length = int(self.headers.get('Content-Length', 0))
                    if not 0 < length <= 65536:
                        raise ValueError('JSON request size must be 1..65536 bytes')
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict):
                        raise ValueError('JSON body must be an object')
                    direct = parsed.path.endswith('/dsl')
                    allowed = {'dsl_command'} if direct else {'query', 'locale', 'allow_llm_fallback'}
                    if set(body) - allowed:
                        raise ValueError('Unsupported request fields')
                    value = body.get('dsl_command' if direct else 'query')
                    result = nl_contract.execute(value, state.root, direct=direct,
                                                 allow_llm_fallback=body.get('allow_llm_fallback', True),
                                                 locale=body.get('locale'), depth=state.depth,
                                                 registry=state.registry)
                except (ValueError, TypeError) as error:
                    result = nl_contract.envelope(success=False, status='VALIDATION_ERROR', error=error)
                code = 200 if result['success'] else (400 if result['status'] == 'VALIDATION_ERROR' else 500)
                self._send(json.dumps(result, ensure_ascii=True).encode(),
                           'application/json; charset=utf-8', status=code)
                return
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
                from . import dsl_llm
                result = dsl_llm.execute(q, state.root, depth=state.depth, registry=state.registry)
                self._send(json.dumps(result, ensure_ascii=True).encode(), 'application/json; charset=utf-8')
                return
            if parsed.path in {'/api/autodiagnosis/dispatch-koru', '/api/autodiagnosis/dispatch-koru.json'}:
                try:
                    length = int(self.headers.get('Content-Length', 0))
                    raw_data = self.rfile.read(length) if length > 0 else b''
                    body = json.loads(raw_data) if raw_data else {}
                except (ValueError, TypeError, json.JSONDecodeError):
                    body = {}
                res = state.autodiagnosis_dispatch_koru(target_repo=body.get('repo'), ticket_id=body.get('ticket_id') or body.get('title'))
                self._send(json.dumps(res, ensure_ascii=False).encode(), 'application/json; charset=utf-8')
                return
            if parsed.path in {'/api/triage/dispatch-koru', '/api/triage/dispatch-koru.json'}:
                try:
                    length = int(self.headers.get('Content-Length', 0))
                    raw_data = self.rfile.read(length) if length > 0 else b''
                    body = json.loads(raw_data) if raw_data else {}
                except (ValueError, TypeError, json.JSONDecodeError):
                    body = {}
                res = state.triage_dispatch_koru(target_repo=body.get('repo'), ticket_id=body.get('ticket_id') or body.get('title'))
                self._send(json.dumps(res, ensure_ascii=False).encode(), 'application/json; charset=utf-8')
                return
            if parsed.path in {'/api/worktrees/prune-safe', '/api/worktrees/prune-safe.json'}:
                try:
                    length = int(self.headers.get('Content-Length', 0))
                    raw_data = self.rfile.read(length) if length > 0 else b''
                    body = json.loads(raw_data) if raw_data else {}
                except (ValueError, TypeError, json.JSONDecodeError):
                    body = {}
                res = state.worktrees_prune_safe(target_repo=body.get('repo'), dry_run=body.get('dry_run', False))
                self._send(json.dumps(res, ensure_ascii=False).encode(), 'application/json; charset=utf-8')
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
    state = State(root, state_dir, depth, registry, github, machine, all_users, open_files, bind=bind, port=port)
    server = bind_server(make_handler(state), bind, port, port_attempts)
    state.port = server.server_address[1]
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

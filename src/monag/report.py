"""Periodic email digest of monag workspace activity.

Collects data from existing monag scan modules (snapshot, audit, resume,
prs, export) and formats it as a Markdown email that can be sent via SMTP.
Uses only stdlib smtplib and email — no new dependencies.

Configuration is via CLI flags and environment variables:

  MONAG_SMTP_HOST     SMTP server hostname (default: localhost)
  MONAG_SMTP_PORT     SMTP server port (default: 587)
  MONAG_SMTP_USER     SMTP username for authentication (optional)
  MONAG_SMTP_PASSWORD SMTP password for authentication (optional)
  MONAG_SMTP_TLS      1 to use STARTTLS (default: 1 when port is 587)
  MONAG_FROM          sender address (default: monag@<hostname>)
"""
from datetime import datetime, timedelta, timezone
import email.mime.multipart
import email.mime.text
import email.utils
import os
import platform
import smtplib
import subprocess
import time

from . import presentation

SCHEMA = 'monag.report/v1'

SECTION_REGISTRY = (
    'status', 'prs', 'audit', 'resume', 'export', 'advise', 'standards',
)


def detect_user_email():
    """Detect user email from gh cli, git config, or environment."""
    try:
        proc = subprocess.run(['gh', 'api', 'user', '--jq', '.email'],
                              capture_output=True, text=True, timeout=5)
        if proc.returncode == 0:
            val = proc.stdout.strip()
            if val and val != 'null':
                return val
    except (OSError, subprocess.TimeoutExpired):
        pass

    try:
        proc = subprocess.run(['git', 'config', '--get', 'user.email'],
                              capture_output=True, text=True, timeout=5)
        if proc.returncode == 0:
            val = proc.stdout.strip()
            if val:
                return val
    except (OSError, subprocess.TimeoutExpired):
        pass

    env_email = os.environ.get('MONAG_EMAIL') or os.environ.get('EMAIL')
    if env_email and env_email.strip():
        return env_email.strip()

    return None


DEFAULT_REPORT_CONFIG = {
    'interval': 3600,
    'schedule': '0 * * * *',
    'recipients': [],
    'sections': list(SECTION_REGISTRY),
    'advisory_limit': 5,
    'enabled': True,
}


def load_config(state_dir=None):
    """Load persistent report configuration from state directory."""
    from pathlib import Path
    import json
    target_dir = Path(state_dir) if state_dir else Path.home() / '.local' / 'state' / 'monag'
    cfg_file = target_dir / 'report_config.json'
    cfg = dict(DEFAULT_REPORT_CONFIG)
    if cfg_file.is_file():
        try:
            data = json.loads(cfg_file.read_text(encoding='utf-8'))
            if isinstance(data, dict):
                cfg.update(data)
        except (json.JSONDecodeError, OSError):
            pass
    if not cfg.get('recipients'):
        detected = detect_user_email()
        if detected:
            cfg['recipients'] = [detected]
    return cfg


def save_config(state_dir, config):
    """Save persistent report configuration to state directory atomically."""
    from pathlib import Path
    import json
    target_dir = Path(state_dir) if state_dir else Path.home() / '.local' / 'state' / 'monag'
    target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    cfg_file = target_dir / 'report_config.json'
    tmp_file = cfg_file.with_suffix('.tmp')
    tmp_file.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding='utf-8')
    tmp_file.chmod(0o600)
    tmp_file.replace(cfg_file)
    return config


def _smtp_config(args_host=None, args_port=None, args_user=None,
                 args_pass=None, args_tls=None, args_from=None):
    host = args_host or os.environ.get('MONAG_SMTP_HOST') or 'localhost'
    port = int(args_port or os.environ.get('MONAG_SMTP_PORT') or '587')
    user = args_user or os.environ.get('MONAG_SMTP_USER') or ''
    auth_pass = args_pass or os.environ.get('MONAG_SMTP_PASSWORD') or ''
    if args_tls is not None:
        tls = args_tls
    else:
        env_tls = os.environ.get('MONAG_SMTP_TLS')
        tls = env_tls == '1' if env_tls is not None else port == 587
    detected = detect_user_email()
    sender = args_from or os.environ.get('MONAG_FROM') or (detected if detected else f'monag@{platform.node()}')
    return {
        'host': host, 'port': port, 'user': user, 'auth_pass': auth_pass,
        'tls': tls, 'from': sender,
    }


def collect(root, depth=2, hours=24, sections=None, github=True,
            issue_limit=200, registry=None, machine=False,
            all_users=False, state_dir=None, advisory_limit=5):
    """Collect workspace data from each requested section.

    Returns a dict with section names as keys and scan results as values,
    plus metadata (root, observed_at, duration).
    """
    started = time.monotonic()
    requested = tuple(sections or SECTION_REGISTRY)
    cache = {}
    result = {
        'schema': SCHEMA, 'root': str(root),
        'observed_at': datetime.now(timezone.utc).isoformat(),
        'requested_sections': list(requested), 'sections': {},
        'errors': [],
    }
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    for section in requested:
        try:
            if section == 'status':
                from .monitor import snapshot
                data = snapshot(root, state_dir, depth, since, github, cache,
                                registry or {}, machine, all_users, False, False)
                result['sections']['status'] = data
            elif section == 'prs':
                from . import prs
                data = prs.scan(root, depth, hours=hours, state='all',
                                pr_limit=200, unpushed_only=False, all_repos=False)
                result['sections']['prs'] = data
            elif section == 'audit':
                from . import audit
                data = audit.scan(root, depth, issue_limit)
                result['sections']['audit'] = data
            elif section == 'resume':
                from . import resume
                data = resume.scan(root, depth)
                result['sections']['resume'] = data
            elif section == 'export':
                from . import export
                data = export.scan(root, depth, issue_limit)
                result['sections']['export'] = data
            elif section == 'advise':
                from . import advise
                cached_export = result['sections'].get('export')
                prs_sec = result['sections'].get('prs')
                audit_sec = result['sections'].get('audit')
                kwargs = {
                    'limit': advisory_limit,
                    'export_data': cached_export,
                    'state_dir': state_dir,
                }
                if prs_sec is not None:
                    kwargs['open_prs_count'] = len(prs_sec.get('open_prs', []))
                if audit_sec is not None:
                    kwargs['worktrees_count'] = audit_sec.get('total_worktrees', len(audit_sec.get('worktrees', [])))
                    kwargs['repos_with_worktrees'] = audit_sec.get('repos_with_worktrees')
                data = advise.advise(root, depth=depth, issue_limit=issue_limit, **kwargs)
                result['sections']['advise'] = data
            elif section == 'standards':
                from . import governance
                result['sections']['standards'] = governance.scan(root, depth=depth)
        except Exception as exc:
            result['errors'].append(f'{section}: {type(exc).__name__}: {exc}')
    result['duration_seconds'] = round(time.monotonic() - started, 2)
    return result


def format_section_status(data):
    lines = []
    agents = data.get('agents', [])
    repos = data.get('repositories', [])
    lines.append(f'**{data.get("agent_count", len(agents))}** agent processes, '
                 f'**{len(repos)}** checkouts.')
    if agents:
        rows = []
        for a in agents[:20]:
            rows.append([a.get('pid', ''), a.get('kind', ''), a.get('state', ''),
                         a.get('cwd', ''), a.get('task', '')])
        lines.append('')
        lines.append(presentation.table(
            ['PID', 'Kind', 'State', 'Directory', 'Task'], rows))
    return '\n'.join(lines)


def format_section_prs(data):
    lines = []
    open_prs = data.get('open_prs', [])
    merged = data.get('merged_prs', [])
    lines.append(f'Open: **{len(open_prs)}** · Merged recently: **{len(merged)}**')
    if open_prs:
        rows = [[pr.get('repo', ''), f"#{pr.get('number', '')}", pr.get('title', ''),
                 pr.get('author', ''), pr.get('created_at', '')[:10] if pr.get('created_at') else '']
                for pr in open_prs[:20]]
        lines.append('')
        lines.append(presentation.table(
            ['Repository', '#', 'Title', 'Author', 'Created'], rows))
    return '\n'.join(lines)


def format_section_audit(data):
    lines = []
    repos = data.get('repositories', [])
    errors = data.get('errors', [])
    total_untracked = sum(len(r.get('untracked_issues', [])) for r in repos)
    lines.append(f'Repositories scanned: **{data.get("repository_count", len(repos))}** · '
                 f'Untracked issues: **{total_untracked}** · Errors: **{len(errors)}**')
    untracked = []
    for r in repos:
        for issue in r.get('untracked_issues', []):
            if issue.get('state') == 'OPEN':
                untracked.append([r.get('repo', r.get('path', '')),
                                  f"#{issue.get('number', '')}",
                                  issue.get('title', ''),
                                  issue.get('url', '')])
    if untracked:
        lines.append('')
        lines.append(presentation.table(
            ['Repository', '#', 'Title', 'URL'], untracked[:30]))
    return '\n'.join(lines)


def format_section_resume(data):
    lines = []
    projects = data.get('projects', [])
    total_tickets = sum(len(p.get('planfile', {}).get('remaining_tickets', []))
                        for p in projects)
    lines.append(f'Projects: **{data.get("project_count", len(projects))}** · '
                 f'Open Planfile tickets: **{total_tickets}**')
    tickets = []
    for p in projects:
        for t in p.get('planfile', {}).get('remaining_tickets', []):
            tickets.append([p.get('path', ''), t.get('id', ''),
                            t.get('priority', ''), t.get('status', ''),
                            t.get('title', '')])
    if tickets:
        lines.append('')
        lines.append(presentation.table(
            ['Project', 'Ticket', 'Priority', 'Status', 'Title'],
            tickets[:30]))
    return '\n'.join(lines)


def format_section_export(data):
    from . import export as export_mod
    return export_mod.markdown(data, limit=30)


def format_section_advise(data):
    lines = []
    summary = data.get('summary', '')
    if summary:
        lines.append(f'> {summary}')
        lines.append('')
    recs = data.get('recommendations', [])
    if recs:
        rows = [[str(r.get('score', 0)), r.get('target', ''), r.get('title', '')[:55],
                 ', '.join(r.get('matched_risks', [])) or '—']
                for r in recs]
        lines.append(presentation.table(['Score', 'Project', 'Task', 'Reflex Risks'], rows))
        lines.append('')
        lines.append('**Key Actionable Guardrails:**')
        for r in recs[:5]:
            lines.append(f"- **{r.get('target')}** ({r.get('score')} pts): {r.get('action')}")
            for g in r.get('guardrails', []):
                lines.append(f"  * {g}")
    else:
        lines.append('No pending recommendations.')
    return '\n'.join(lines)


def format_section_standards(data):
    """Render local Wellmanifest adoption observations without freshness claims."""
    repos = data.get('repositories', [])
    lines = [f"Repositories scanned: **{data.get('repository_count', len(repos))}** · "
             f"Adoption manifests: **{data.get('adoption_manifest_count', 0)}** · "
             f"Workspace pin disagreements: **{len(data.get('drift', []))}**"]
    rows = []
    for repo in repos:
        packs = repo.get('standards', [])
        declared = ', '.join(
            f"{pack.get('id', '?')} ({pack.get('level', '?')})" for pack in packs
        ) or '—'
        rows.append([
            repo.get('name', repo.get('path', '')), repo.get('mode', 'missing'),
            repo.get('profile', '—'), declared,
        ])
    if rows:
        lines.extend(['', presentation.table(['Repository', 'Mode', 'Profile', 'Declared packs'], rows)])
    if data.get('drift'):
        lines.extend(['', '**Workspace-local pin disagreement (not a release-freshness claim):**'])
        for item in data['drift']:
            lines.append(f"- `{item['id']}`: {', '.join(item['revisions'])}")
    for error in data.get('errors', []):
        lines.append(f"- Observation error: {error}")
    return '\n'.join(lines)


_SECTION_FORMATTERS = {
    'status': format_section_status,
    'prs': format_section_prs,
    'audit': format_section_audit,
    'resume': format_section_resume,
    'export': format_section_export,
    'advise': format_section_advise,
    'standards': format_section_standards,
}

_SECTION_TITLES = {
    'status': 'Agent processes and checkouts',
    'prs': 'Pull Requests',
    'audit': 'GitHub Issue audit',
    'resume': 'Planfile backlog and worktrees',
    'export': 'Candidate work items',
    'advise': 'Architectural Advisory & Task Guidance',
    'standards': 'Wellmanifest standards adoption',
}


def footer_management_markdown(recipients=None, port=8090, root=None):
    """Generate management section explaining how to change schedule/email via CLI or local URLs."""
    to_desc = f" do: `{', '.join(recipients)}`" if recipients else ""
    panel_url = f"http://127.0.0.1:{port}"
    lines = [
        "---",
        "",
        "## Zarządzanie raportem i konfiguracja",
        "",
        f"Ten raport jest generowany cyklicznie{to_desc}.",
        "",
        "### Szybka zmiana częstotliwości wysyłki (1-click link):",
        f"- [⏱ Co 30 minut]({panel_url}/api/report/config?interval=1800)",
        f"- [⏱ Co 1 godzinę (domyślne)]({panel_url}/api/report/config?interval=3600)",
        f"- [⏱ Co 2 godziny]({panel_url}/api/report/config?interval=7200)",
        f"- [⏱ Co 4 godziny]({panel_url}/api/report/config?interval=14400)",
        f"- [⏱ Raz na dobę (24h)]({panel_url}/api/report/config?interval=86400)",
        f"- [⚙ Formularz konfiguracji w przeglądarce]({panel_url}/report/config)",
        "",
        "### Zmiana konfiguracji przez CLI:",
        "- **Zmiana harmonogramu / adresu:**",
        '  `monag report --email <nowy-email> --schedule "0 */2 * * *" --install-cron`',
        "- **Zatrzymanie wysyłki cyklicznej:**",
        "  `monag report --remove-cron`",
        "- **Wybór sekcji raportu (np. tylko PR-y i doradztwo):**",
        "  `monag report --sections prs,advise --install-cron`",
        "- **Uruchomienie w tle w kontenerze (daemon):**",
        "  `monag report --daemon --interval 3600`",
        "",
        "### Zarządzanie przez lokalny serwer monag (URL):",
        f"- **Panel monag:** [{panel_url}]({panel_url})",
        f"- **Status raportu:** [{panel_url}/api/report/status]({panel_url}/api/report/status)",
        f"- **Wyłącz wysyłkę (1-click):** [{panel_url}/api/report/disable]({panel_url}/api/report/disable)",
        f"- **Wyślij świeży raport teraz:** [{panel_url}/api/report/send-now]({panel_url}/api/report/send-now)",
        "",
    ]
    return '\n'.join(lines)


def markdown(report_data, port=8090, include_management_footer=True, recipients=None):
    """Format the full report as Markdown suitable for email or terminal."""
    observed = report_data['observed_at'][:19].replace('T', ' ')
    lines = [f'# MONAG workspace report',
             f'',
             f'**{observed} UTC** · root: `{report_data["root"]}` · '
             f'scan: {report_data["duration_seconds"]}s',
             '']

    # High-level overview table: PRs, Worktrees, Planfile, Advise
    prs_sec = report_data['sections'].get('prs') or {}
    open_prs_count = len(prs_sec.get('open_prs', []))
    audit_sec = report_data['sections'].get('audit') or {}
    total_wts = audit_sec.get('total_worktrees', len(audit_sec.get('worktrees', [])))
    resume_sec = report_data['sections'].get('resume') or {}
    total_tickets = sum(len(p.get('planfile', {}).get('remaining_tickets', []))
                        for p in resume_sec.get('projects', []))
    advise_sec = report_data['sections'].get('advise') or {}
    total_recs = len(advise_sec.get('recommendations', []))

    summary_rows = [[
        str(open_prs_count),
        str(total_wts),
        str(total_tickets),
        str(total_recs),
    ]]
    lines.append('## Podsumowanie Workspace')
    lines.append('')
    lines.append(presentation.table(['Otwarte PR', 'Aktywne Worktrees', 'Zadania Planfile', 'Rekomendacje Advise'], summary_rows))
    lines.append('')

    for section_name in report_data['requested_sections']:
        section_data = report_data['sections'].get(section_name)
        if section_data is None:
            continue
        title = _SECTION_TITLES.get(section_name, section_name)
        lines.append(f'## {title}')
        lines.append('')
        formatter = _SECTION_FORMATTERS.get(section_name)
        if formatter:
            lines.append(formatter(section_data))
        lines.append('')
    if report_data['errors']:
        lines.append('## Errors')
        lines.append('')
        for error in report_data['errors']:
            lines.append(f'- {error}')
        lines.append('')
    lines.append('---')
    lines.append(f'*Generated by monag report. Read-only observation, no writes.*')
    lines.append('')
    if include_management_footer:
        lines.append(footer_management_markdown(recipients=recipients, port=port, root=report_data.get('root')))
    return '\n'.join(lines)


def _markdown_to_html(md_text):
    """Basic Markdown to HTML — just enough for email readability."""
    import re as _re
    html_lines = []
    for line in md_text.split('\n'):
        stripped = line.strip()
        if stripped.startswith('### '):
            html_lines.append(f'<h3>{stripped[4:]}</h3>')
        elif stripped.startswith('## '):
            html_lines.append(f'<h3>{stripped[3:]}</h3>')
        elif stripped.startswith('# '):
            html_lines.append(f'<h2>{stripped[2:]}</h2>')
        elif stripped.startswith('---'):
            html_lines.append('<hr/>')
        elif stripped.startswith('|'):
            # Markdown table row — pass through; will be wrapped in <pre>
            # for tables that are more complex. Simple approach: keep raw.
            html_lines.append(stripped + '<br/>')
        elif stripped.startswith('- '):
            item_text = stripped[2:]
            item_text = _re.sub(r'\[(.+?)\]\((https?://[^\)]+)\)', r'<a href="\2">\1</a>', item_text)
            item_text = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', item_text)
            item_text = _re.sub(r'`(.+?)`', r'<code>\1</code>', item_text)
            html_lines.append(f'<li>{item_text}</li>')
        elif stripped.startswith('*') and stripped.endswith('*'):
            html_lines.append(f'<p><em>{stripped.strip("*")}</em></p>')
        elif stripped:
            text = _re.sub(r'\[(.+?)\]\((https?://[^\)]+)\)', r'<a href="\2">\1</a>', stripped)
            text = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
            text = _re.sub(r'`(.+?)`', r'<code>\1</code>', text)
            html_lines.append(f'<p>{text}</p>')
        else:
            html_lines.append('')
    body = '\n'.join(html_lines)
    return (f'<html><head><meta charset="utf-8">'
            f'<style>body{{font-family:monospace,sans-serif;font-size:13px;max-width:900px;margin:auto}}'
            f'table{{border-collapse:collapse}}th,td{{border:1px solid #ccc;padding:4px 8px;text-align:left}}'
            f'h2{{color:#1a73e8}}h3{{color:#333}}code{{background:#f5f5f5;padding:1px 4px}}'
            f'hr{{border:none;border-top:1px solid #ddd;margin:20px 0}}</style></head>'
            f'<body>{body}</body></html>')


def send_email(recipients, subject, body_markdown, smtp_cfg):
    """Send one report email via SMTP. Returns a result dict."""
    body_html = _markdown_to_html(body_markdown)
    msg = email.mime.multipart.MIMEMultipart('alternative')
    msg['From'] = smtp_cfg['from']
    msg['To'] = ', '.join(recipients) if isinstance(recipients, list) else recipients
    msg['Subject'] = subject
    msg['Date'] = email.utils.formatdate(localtime=True)
    msg['Message-ID'] = email.utils.make_msgid(domain=platform.node())
    msg.attach(email.mime.text.MIMEText(body_markdown, 'plain', 'utf-8'))
    msg.attach(email.mime.text.MIMEText(body_html, 'html', 'utf-8'))
    to_list = recipients if isinstance(recipients, list) else [recipients]
    try:
        with smtplib.SMTP(smtp_cfg['host'], smtp_cfg['port'], timeout=30) as server:
            if smtp_cfg['tls']:
                server.starttls()
            if smtp_cfg['user']:
                server.login(smtp_cfg['user'], smtp_cfg['auth_pass'])
            server.sendmail(smtp_cfg['from'], to_list, msg.as_string())
        return {'ok': True, 'recipients': to_list,
                'via': f"{smtp_cfg['host']}:{smtp_cfg['port']}"}
    except (smtplib.SMTPException, OSError) as exc:
        return {'ok': False, 'error': f'{type(exc).__name__}: {exc}',
                'recipients': to_list}


def install_cron(email_addr, root, schedule='0 * * * *', sections=None):
    """Install a crontab entry for periodic monag report.

    Returns a result dict. Only lines tagged ``# monag:report`` are managed;
    existing crontab entries are preserved.
    """
    section_flag = ''
    if sections:
        section_flag = f" --sections {','.join(sections)}"
    command = f'monag report --root {root} --email {email_addr}{section_flag}'
    tag = '# monag:report'
    cron_line = f'{schedule} {command} {tag}'
    try:
        existing = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
        current = existing.stdout if existing.returncode == 0 else ''
    except OSError as exc:
        return {'ok': False, 'error': f'crontab: {exc}'}
    # Remove old monag:report entries
    lines = [line for line in current.splitlines() if tag not in line]
    lines.append(cron_line)
    new_crontab = '\n'.join(lines) + '\n'
    try:
        proc = subprocess.run(['crontab', '-'], input=new_crontab,
                              capture_output=True, text=True, timeout=10)
        if proc.returncode:
            return {'ok': False, 'error': f'crontab install failed: {proc.stderr.strip()}'}
        return {'ok': True, 'cron_line': cron_line, 'action': 'installed'}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'ok': False, 'error': f'crontab: {exc}'}


def remove_cron():
    """Remove the monag:report crontab entry. Returns a result dict."""
    tag = '# monag:report'
    try:
        existing = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
        current = existing.stdout if existing.returncode == 0 else ''
    except OSError as exc:
        return {'ok': False, 'error': f'crontab: {exc}'}
    lines = [line for line in current.splitlines() if tag not in line]
    new_crontab = '\n'.join(lines) + '\n' if lines else ''
    try:
        proc = subprocess.run(['crontab', '-'], input=new_crontab,
                              capture_output=True, text=True, timeout=10)
        if proc.returncode:
            return {'ok': False, 'error': f'crontab removal failed: {proc.stderr.strip()}'}
        return {'ok': True, 'action': 'removed'}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'ok': False, 'error': f'crontab: {exc}'}


def run_daemon(root, emails=None, interval=3600, depth=2, hours=24,
               sections=None, github=True, issue_limit=200,
               registry=None, machine=False, all_users=False,
               state_dir=None, advisory_limit=5, smtp_cfg=None,
               subject_template=None, stop_event=None, max_iterations=None):
    """Run continuous in-process loop sending reports periodically."""
    import threading
    from pathlib import Path
    if stop_event is None:
        stop_event = threading.Event()
    to_list = list(emails) if emails else []
    if not to_list:
        detected = detect_user_email()
        if detected:
            to_list = [detected]
        else:
            raise ValueError('No recipient email specified or detected')

    if smtp_cfg is None:
        smtp_cfg = _smtp_config()

    iterations = 0
    results = []
    while not stop_event.is_set():
        cfg = load_config(state_dir)
        current_enabled = cfg.get('enabled', True)
        current_interval = cfg.get('interval', interval)
        current_recipients = cfg.get('recipients') or to_list
        current_sections = cfg.get('sections') or sections

        if current_enabled:
            data = collect(root, depth=depth, hours=hours, sections=current_sections,
                           github=github, issue_limit=issue_limit, registry=registry,
                           machine=machine, all_users=all_users, state_dir=state_dir,
                           advisory_limit=cfg.get('advisory_limit', advisory_limit))
            body = markdown(data, recipients=current_recipients)
            subject = subject_template or f'MONAG report — {Path(root).name} — {data["observed_at"][:16]}'
            res = send_email(current_recipients, subject, body, smtp_cfg)
            results.append(res)
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break
            stop_event.wait(current_interval)
        else:
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break
            stop_event.wait(min(current_interval, 5))
    return results

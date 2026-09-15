"""Read-only export of candidate work items for a human (or Planfile/koru
intake) to review -- monag never creates, queues or claims a Planfile
ticket itself, and never talks to koru, Planfile, or any other tool.

Merges three existing monag reports into one reviewable list:

- an ``audit-untracked-issue`` candidate for every GitHub Issue that has no
  matching Planfile ticket (from :mod:`monag.audit`);
- a ``catalog-undescribed`` candidate for every repository with no declared
  description anywhere (from :mod:`monag.catalog`) -- a housekeeping signal,
  not a task;
- ``resume-open-ticket`` entries listing the *existing* open Planfile
  backlog (from :mod:`monag.resume`), for context only -- these already
  have an id and are not "candidates" for anything.

Every candidate keeps its own evidence (repository, URL, source report) so
a reviewer can trace it back. Priority is passed through only where a
source already declared one; this module never invents one.

With ``--radar``, each candidate is additionally, optionally sized by the
external, deterministic `subactor/ticket-radar` tool (complexity/score/time
estimate/split recommendation) when it is installed on PATH -- monag still
works identically without it; a missing or failing ticket-radar leaves
``radar: None`` on the candidate, never a guessed size.
"""
from datetime import datetime, timezone
import json
import shutil
import subprocess
import time

from . import audit, catalog, resume

SCHEMA = 'monag.export/v1'
RADAR_BIN = 'ticket-radar'


def audit_candidates(audit_data):
    """Only OPEN untracked issues are work candidates.

    A CLOSED issue with no matching ticket is a data-hygiene fact (the
    Planfile mapping is incomplete), not something left to do; `audit`
    still reports it, this module just does not propose it as work.
    """
    candidates = []
    for repository in audit_data['repositories']:
        label = repository['repo'] or repository['path']
        for issue in repository['untracked_issues']:
            if issue.get('state') != 'OPEN':
                continue
            candidates.append({
                'origin': 'audit-untracked-issue',
                'repo': repository['repo'], 'path': repository['path'],
                'title': issue.get('title') or f"Issue #{issue.get('number')}",
                'priority': 'unknown',
                'url': issue.get('url'),
                'evidence': f"{label} issue #{issue.get('number')} "
                           f"({issue.get('state', 'UNKNOWN')}) has no matching Planfile ticket.",
            })
    return candidates


def catalog_candidates(catalog_data):
    candidates = []
    for repository in catalog_data['repositories']:
        if repository['description']:
            continue
        label = repository['repo'] or repository['path']
        candidates.append({
            'origin': 'catalog-undescribed',
            'repo': repository['repo'], 'path': repository['path'],
            'title': f"{label} has no declared description",
            'priority': 'unknown',
            'url': None,
            'evidence': f"No description in pyproject.toml, package.json or README.md "
                       f"for {repository['path']}.",
        })
    return candidates


def resume_context(resume_data):
    context = []
    for project in resume_data['projects']:
        for ticket in project['planfile'].get('remaining_tickets', []):
            context.append({
                'origin': 'resume-open-ticket',
                'repo': None, 'path': project['path'],
                'id': ticket['id'], 'title': ticket['title'],
                'priority': ticket['priority'], 'status': ticket['status'],
                'url': None,
                'evidence': f"Already an open Planfile ticket in {project['path']}.",
            })
    return context


def radar_available():
    return shutil.which(RADAR_BIN) is not None


def run_radar(args, input_text, timeout=20):
    """Thin, mockable subprocess boundary -- monitor.command() has no stdin support."""
    try:
        proc = subprocess.run(args, input=input_text, capture_output=True,
                              text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, f'{args[0]}: {type(error).__name__}'
    if proc.returncode:
        return None, f'{args[0]} failed (exit {proc.returncode}): {proc.stderr.strip()[:200]}'
    return proc.stdout, None


def radar_assess(candidate, repository_root, timeout=20):
    """One candidate's size/risk from subactor/ticket-radar; (None, error) on any failure.

    ticket-radar is optional and external: a missing binary, a timeout, or
    unparseable output all fall back to (None, error) -- never a guessed size.
    """
    payload = json.dumps({
        'id': candidate.get('id') or (candidate['title'] or 'candidate')[:64],
        'name': candidate['title'],
        'status': 'open',
        **({'priority': candidate['priority']} if candidate.get('priority') not in (None, 'unknown') else {}),
    })
    out, error = run_radar([RADAR_BIN, '--repository-root', str(repository_root), '-'], payload, timeout)
    if error:
        return None, error
    try:
        assessment = json.loads(json.loads(out)['jsonl'])
    except (ValueError, KeyError, TypeError):
        return None, f'{RADAR_BIN}: invalid output'
    estimate = assessment.get('estimate') if isinstance(assessment.get('estimate'), dict) else {}
    split = assessment.get('split') if isinstance(assessment.get('split'), dict) else {}
    return {
        'complexity': assessment.get('complexity'),
        'score': assessment.get('score'),
        'estimated_minutes': estimate.get('minutes'),
        'within_budget': estimate.get('within_budget'),
        'diagnostics': assessment.get('diagnostics', []),
        'split_recommended': bool(split.get('recommended')),
    }, None


def scan(root, depth=2, issue_limit=200, radar=False):
    started = time.monotonic()
    audit_data = audit.scan(root, depth, issue_limit)
    catalog_data = catalog.scan(root, depth)
    resume_data = resume.scan(root, depth)
    candidates = audit_candidates(audit_data) + catalog_candidates(catalog_data)
    radar_errors = []
    if radar:
        if radar_available():
            for candidate in candidates:
                assessment, error = radar_assess(candidate, candidate['path'])
                candidate['radar'] = assessment
                if error:
                    radar_errors.append(f"{candidate['path']}: {candidate['title']}: {error}")
        else:
            radar_errors.append(f'{RADAR_BIN} not found on PATH; candidates left unsized')
    context = resume_context(resume_data)
    return {
        'schema': SCHEMA, 'root': str(root),
        'observed_at': datetime.now(timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - started, 2),
        'candidates': candidates, 'candidate_count': len(candidates),
        'existing_open_tickets': context, 'existing_open_ticket_count': len(context),
        'radar_requested': radar, 'radar_errors': radar_errors,
        'sources': {'audit': {'repository_count': audit_data['repository_count'],
                              'errors': len(audit_data['errors'])},
                   'catalog': {'repository_count': catalog_data['repository_count']},
                   'resume': {'project_count': resume_data['project_count']}},
        'notice': 'Read-only staging list for human review, not an automatic queue. monag '
                  'creates, imports or claims nothing; turning a candidate into a real '
                  'Planfile ticket (or handing it to koru/planfile) is a separate, '
                  'explicitly authorized step outside monag.',
    }


def markdown(data, limit=40):
    from .presentation import table
    lines = ['# MONAG — candidate work export', '',
             f"Candidates: **{data['candidate_count']}** · existing open Planfile tickets: "
             f"**{data['existing_open_ticket_count']}** · scan: {data['duration_seconds']} s.",
             '', 'monag creates, imports or claims nothing here; this is a reviewable list.', '']
    shown = data['candidates'][:limit]
    if data['radar_requested']:
        def radar_cell(c):
            r = c.get('radar')
            if not r:
                return 'unsized'
            return f"{r['complexity']} · score {r['score']} · {r['estimated_minutes']}m" + \
                   (' · split?' if r['split_recommended'] else '')
        lines.append(table(['Origin', 'Repository', 'Title', 'Radar', 'Evidence'],
                           [[c['origin'], c['repo'] or c['path'], c['title'], radar_cell(c), c['evidence']]
                            for c in shown]))
    else:
        lines.append(table(['Origin', 'Repository', 'Title', 'Evidence'],
                           [[c['origin'], c['repo'] or c['path'], c['title'], c['evidence']]
                            for c in shown]))
    if len(data['candidates']) > limit:
        lines.append(f"\n{len(data['candidates']) - limit} more candidates; use `--json`.\n")
    if data['radar_errors']:
        lines.extend(['', f"Radar unavailable for {len(data['radar_errors'])} candidate(s) "
                     "(shown as 'unsized', never guessed); see `--json` for details."])
    context = data['existing_open_tickets'][:limit]
    lines.extend(['', '## Existing open Planfile tickets (context, not candidates)', '',
                 table(['Path', 'Ticket', 'Priority', 'Status', 'Title'],
                       [[c['path'], c['id'], c['priority'], c['status'], c['title']]
                        for c in context])])
    lines.extend(['', data['notice'], '', 'Full data: `monag --json export`.'])
    return '\n'.join(lines) + '\n'

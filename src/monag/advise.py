"""Architectural guidance and next-task advisory engine.

Combines workspace candidate items (monag.export), learning loop failure
patterns (subactor.reflex), task sizing (subactor.ticket-radar), and hygiene
evidence (semcod.taskill) into prioritized next actions with concrete
guidelines and guardrails for developers and autonomous agents.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from . import export, presentation

SCHEMA = 'monag.advisory/v1'

TIER_FLOOR = 'floor'
TIER_MISSION = 'mission'
TIER_HYGIENE = 'hygiene'
TIER_BACKLOG = 'backlog'

TIER_ORDER = [TIER_FLOOR, TIER_MISSION, TIER_HYGIENE, TIER_BACKLOG]

TIER_BASE_SCORES = {
    TIER_FLOOR: 1000,
    TIER_MISSION: 500,
    TIER_HYGIENE: 200,
    TIER_BACKLOG: 50,
}

FAILURE_KEYWORD_MAP = {
    'remote-rate-limit': ('rate limit', '403', '429', 'secondary limit', 'api rate'),
    'timeout-failure': ('timeout', 'timed out', 'deadline exceeded', 'sigkill'),
    'governance-friction': ('governance', 'gov-', 'overlap', 'workstream', 'ticket-0'),
    'dependency-drift': ('dependency', 'pin', 'version', 'incompatible', 'digest'),
    'tool-contract-friction': ('usage:', 'invalid choice', 'contract', '422', 'not found'),
    'contract-schema-drift': ('intract', 'code2schema', 'schema', 'dsl', 'grammar', 'cqrs', 'ast extraction'),
    'test-feedback-friction': ('test failure', 'assertionerror', 'failed test', 'exit code 1'),
}


def _find_reflex_runner():
    """Check if reflex is directly importable or available on PATH / workspace."""
    try:
        import reflex
        return 'import'
    except ImportError:
        pass
    # Check if subactor/reflex is in workspace
    for parent in [Path.cwd(), Path.home() / 'github']:
        reflex_dir = parent / 'subactor' / 'reflex' / 'src'
        if reflex_dir.is_dir() and str(reflex_dir) not in sys.path:
            sys.path.insert(0, str(reflex_dir))
            try:
                import reflex  # noqa: F401
                return 'import'
            except ImportError:
                pass
    import shutil
    if shutil.which('reflex'):
        return 'cli'
    return None


def _find_algocode_runner() -> str | None:
    """Check if semcod/algocode engine is importable or available in workspace."""
    try:
        import algocode.engine  # noqa: F401
        return 'import'
    except ImportError:
        pass
    for parent in [Path.cwd(), Path.home() / 'github', Path.home() / 'github' / 'semcod']:
        algo_dir = parent / 'algocode' / 'src'
        if (algo_dir / 'algocode').is_dir() and str(algo_dir) not in sys.path:
            sys.path.insert(0, str(algo_dir))
            try:
                import algocode.engine  # noqa: F401
                return 'import'
            except ImportError:
                pass
    import shutil
    if shutil.which('algocode'):
        return 'cli'
    return None


def verify_candidate_conflict(candidate: dict[str, Any], root: Path) -> dict[str, Any] | None:
    """Run deterministic conflict check using semcod/algocode if available."""
    runner = _find_algocode_runner()
    if runner != 'import':
        return None

    try:
        import algocode.engine as algo
        repo = candidate.get('repo') or candidate.get('path') or ''
        repo_path = Path(repo) if Path(repo).is_absolute() else root / repo
        if not repo_path.is_dir():
            return None

        manifest_path = None
        for cand in [repo_path / '.governance' / 'manifest.json',
                     repo_path / 'governance' / 'manifest.json',
                     repo_path / 'governance' / 'manifest.hub.json']:
            if cand.is_file():
                manifest_path = cand
                break

        if not manifest_path:
            return None

        report = algo.check_conflict(manifest_path, repo_root=repo_path)
        return report
    except Exception:
        return None



def collect_reflex_patterns(root: Path, state_dir: Path | None = None,
                            extra_sources: list[str] | None = None) -> dict[str, Any]:
    """Extract recurring failure patterns using subactor.reflex if available."""
    sources: list[Path] = []
    if extra_sources:
        for s in extra_sources:
            p = Path(s)
            if p.exists():
                sources.append(p)
    # Automatically scan common evidence locations
    if state_dir and state_dir.is_dir():
        tasks_dir = state_dir / 'tasks'
        if tasks_dir.is_dir():
            sources.append(tasks_dir)
    # Check candidate subactor receipts or sessions in root
    candidate_dirs = [
        root / 'subactor',
        root / 'semcod',
        root,
    ]
    for c in candidate_dirs:
        if not c.is_dir():
            continue
        for child in c.glob('*/.subactor/receipts'):
            if child.is_dir():
                sources.append(child)
        for child in c.glob('*/.subactor/sessions'):
            if child.is_dir():
                sources.append(child)

    if not sources:
        return {'available': False, 'reason': 'no evidence logs found', 'patterns': [], 'proposals': []}

    runner = _find_reflex_runner()
    if runner == 'import':
        try:
            from reflex.ingest import ingest_paths
            from reflex.patterns import analyze
            events = list(ingest_paths(sources[:20], max_lines=5000))
            if not events:
                return {'available': True, 'patterns': [], 'proposals': [], 'event_count': 0}
            analysis = analyze(events, min_repeat=1)
            return {
                'available': True,
                'patterns': analysis.get('patterns', []),
                'proposals': analysis.get('proposals', []),
                'statistics': analysis.get('statistics', {}),
                'event_count': len(events),
            }
        except Exception as exc:
            return {'available': False, 'reason': f'reflex import error: {exc}', 'patterns': [], 'proposals': []}

    if runner == 'cli':
        try:
            cmd = ['reflex', 'analyze']
            for s in sources[:10]:
                cmd.extend(['--source', str(s)])
            cmd.extend(['--min-repeat', '1'])
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if proc.returncode == 0 and proc.stdout:
                data = json.loads(proc.stdout)
                return {
                    'available': True,
                    'patterns': data.get('patterns', []),
                    'proposals': data.get('proposals', []),
                    'statistics': data.get('statistics', {}),
                }
        except Exception as exc:
            return {'available': False, 'reason': f'reflex cli error: {exc}', 'patterns': [], 'proposals': []}

    return {'available': False, 'reason': 'subactor.reflex not installed or in sys.path', 'patterns': [], 'proposals': []}


def _match_reflex_risk(title: str, description: str, reflex_data: dict[str, Any]) -> list[str]:
    """Check if candidate matches any active reflex failure patterns."""
    matched = []
    text = f'{title} {description}'.lower()
    patterns = reflex_data.get('patterns', [])
    active_categories = {p.get('category') for p in patterns if p.get('category')}
    for cat, keywords in FAILURE_KEYWORD_MAP.items():
        if cat in active_categories or any(kw in text for kw in keywords):
            if any(kw in text for kw in keywords):
                matched.append(cat)
    return sorted(set(matched))


def classify_tier(candidate: dict[str, Any], matched_risks: list[str]) -> str:
    """Classify a work candidate into a lexicographic Priority DSL tier.

    Tiers:
    - floor: Critical failures, active governance friction, broken tests/gates,
             or rate-limit blocks that must be resolved first.
    - mission: Direct delivery work, open sprint issues, high-priority features.
    - hygiene: Refactoring, complexity reduction, documentation drift, catalog metadata.
    - backlog: Ideas, low-priority backlog items, general improvements.
    """
    priority = str(candidate.get('priority', '')).lower()
    origin = candidate.get('origin', '')
    title = candidate.get('title', '').lower()

    # Floor conditions: critical priority, active governance or test failure risks, security
    if priority in {'critical', 'p0'}:
        return TIER_FLOOR
    if any(r in matched_risks for r in ('governance-friction', 'test-feedback-friction')):
        return TIER_FLOOR
    if any(term in title for term in ('broken', 'security', 'fail-closed', 'deadlock', 'sigkill')):
        return TIER_FLOOR

    # Mission conditions: active user/github issues, high priority, delivery
    if priority in {'high', 'p1'} or origin == 'audit-untracked-issue':
        return TIER_MISSION
    if any(term in title for term in ('release', 'pr', 'feature', 'delivery')):
        return TIER_MISSION

    # Hygiene conditions: refactoring, complexity, drift, catalog
    if origin in {'taskill-doc-drift', 'catalog-undescribed'}:
        return TIER_HYGIENE
    radar = candidate.get('radar')
    if radar and isinstance(radar, dict) and (radar.get('split_recommended') or radar.get('complexity') == 'high'):
        return TIER_HYGIENE
    if any(term in title for term in ('refactor', 'clean', 'format', 'smell', 'complexity')):
        return TIER_HYGIENE

    if priority in {'medium', 'p2'}:
        return TIER_HYGIENE

    return TIER_BACKLOG


def synthesize_guidelines(candidate: dict[str, Any], matched_risks: list[str],
                          algo_conflict: dict[str, Any] | None = None) -> dict[str, Any]:
    """Generate concrete action, rationale, and guardrails for an item."""
    origin = candidate.get('origin', '')
    title = candidate.get('title', '')
    summary = candidate.get('summary', candidate.get('description', ''))
    repo = candidate.get('repo', candidate.get('path', ''))

    # Determine base action and satisfied_when condition
    if origin == 'audit-untracked-issue':
        issue_num = candidate.get('issue_number', '')
        action = f"Rozpocznij realizację zgłoszenia #{issue_num} w {repo}: stwórz ticket i gałąź roboczą."
        evidence = f"Otwarte zgłoszenie GitHub bez powiązanego ticketu Planfile: '{title}'."
        satisfied_when = f"Zgłoszenie #{issue_num} w {repo} zostało zamknięte lub zintegrowane w PR."
    elif origin == 'catalog-undescribed':
        action = f"Uzupełnij opis projektu i stosu technologicznego w {repo} (README/pyproject.toml/package.json)."
        evidence = f"Katalog repozytoriów wskazuje brak metadanych w {repo}."
        satisfied_when = f"Plik README/pyproject.toml w {repo} zawiera wymagane metadane."
    elif origin == 'taskill-doc-drift':
        action = f"Zsynchronizuj dryf dokumentacji w {repo} (README/CHANGELOG/TODO)."
        evidence = f"Taskill wykrył niezatwierdzone zmiany w dokumentacji po ostatnich commitach."
        satisfied_when = f"Zsynchronizowano dokumentację w {repo} i brak ostrzeżeń taskill."
    else:
        ticket_id = candidate.get('id', candidate.get('ticket', ''))
        action = f"Kontynuuj realizację zadania w {repo}: {title}."
        evidence = f"Zadanie oczekujące w backlogu Planfile ({ticket_id})."
        satisfied_when = f"Ticket {ticket_id} osiągnął status DONE i testy przechodzą."

    # Add guardrails based on detected risks
    guardrails = ["Weryfikuj zgodność z regułami governance repozytorium przed otwarciem PR."]
    if algo_conflict and algo_conflict.get('has_conflict'):
        confs = algo_conflict.get('conflicts', [])
        guardrails.append(f"Algocode Gate: wykryto {len(confs)} kolizji ścieżek/workstreamów w manifest.")
    if 'remote-rate-limit' in matched_risks:
        guardrails.append("Uwaga na limity API: wykorzystaj lokalne procedury CDP lub OneDev zamiast powtarzanych zapytań zdalnych.")
    if 'timeout-failure' in matched_risks:
        guardrails.append("Ustaw jawny timeout HTTP/gniazda; nie polegaj na globalnym limicie procesu.")
    if 'dependency-drift' in matched_risks:
        guardrails.append("Migracja wersji/pinów: sprawdź konsumentów downstream (np. onedev-agent) przed zmianą digestów.")
    if 'governance-friction' in matched_risks:
        guardrails.append("Upewnij się, że modyfikowane ścieżki mieszczą się w jednym workstreamie i dokładnie jednym tickecie.")
    if 'contract-schema-drift' in matched_risks or 'autogrammar' in repo:
        guardrails.append("Weryfikuj zgodność intract / kontraktów semantycznych (autogrammar/intract / code2schema) oraz schematów.")

    return {
        'action': action,
        'evidence': evidence,
        'satisfied_when': satisfied_when,
        'guardrails': guardrails,
    }


def compute_advisory_score(candidate: dict[str, Any], matched_risks: list[str],
                           tier: str | None = None) -> int:
    """Calculate an advisory priority score enforcing Priority DSL lexicographic tiers."""
    if tier is None:
        tier = classify_tier(candidate, matched_risks)

    base = TIER_BASE_SCORES.get(tier, 50)
    priority = str(candidate.get('priority', '')).lower()
    mod = 0
    if priority in {'critical', 'p0'}:
        mod += 40
    elif priority in {'high', 'p1'}:
        mod += 25
    elif priority in {'medium', 'p2'}:
        mod += 10

    # Risk bonus: actively failing patterns require urgent attention within tier
    mod += len(matched_risks) * 15

    # Radar sizing bonus: complex items needing decomposition
    radar = candidate.get('radar')
    if radar and isinstance(radar, dict):
        if radar.get('split_recommended'):
            mod += 15
        if radar.get('complexity') == 'high':
            mod += 10

    return base + mod


def generate_priority_readings(reflex_data: dict[str, Any], recommendations: list[dict[str, Any]],
                               doc_id: str = "monag.advise.priority") -> dict[str, Any]:
    """Emit a compliant wellmanifest.priority/readings/v1 envelope."""
    now_iso = datetime.now(timezone.utc).isoformat()
    patterns = reflex_data.get('patterns', [])
    active_categories = {p.get('category') for p in patterns if p.get('category')}

    tier_counts = {t: 0 for t in TIER_ORDER}
    for r in recommendations:
        t = r.get('tier', TIER_BACKLOG)
        tier_counts[t] = tier_counts.get(t, 0) + 1

    readings = {
        'floor_friction_count': {
            'observedAt': now_iso,
            'producerRef': 'monag.advise/tiers',
            'value': tier_counts[TIER_FLOOR],
        },
        'mission_demand_count': {
            'observedAt': now_iso,
            'producerRef': 'monag.advise/tiers',
            'value': tier_counts[TIER_MISSION],
        },
        'active_failure_patterns': {
            'observedAt': now_iso,
            'producerRef': 'subactor.reflex',
            'value': len(patterns),
        },
        'remote_rate_limit': {
            'observedAt': now_iso,
            'producerRef': 'subactor.reflex',
            'value': 1 if 'remote-rate-limit' in active_categories else 0,
        },
        'governance_friction': {
            'observedAt': now_iso,
            'producerRef': 'subactor.reflex',
            'value': 1 if 'governance-friction' in active_categories else 0,
        },
        'timeout_failure': {
            'observedAt': now_iso,
            'producerRef': 'subactor.reflex',
            'value': 1 if 'timeout-failure' in active_categories else 0,
        },
    }

    return {
        'schema': 'wellmanifest.priority/readings/v1',
        'document': {
            'id': doc_id,
            'version': '0.1.0',
        },
        'observedAt': now_iso,
        'readings': readings,
    }


def to_planfile_ticket(rec: dict[str, Any]) -> dict[str, Any]:
    """Convert an advisory recommendation item into a Planfile ticket dictionary."""
    tier = rec.get('tier', TIER_BACKLOG)
    tier_priority_map = {
        TIER_FLOOR: 'critical',
        TIER_MISSION: 'high',
        TIER_HYGIENE: 'medium',
        TIER_BACKLOG: 'low',
    }
    priority = tier_priority_map.get(tier, 'normal')

    desc_lines = []
    if rec.get('action'):
        desc_lines.append(f"**Action**: {rec['action']}")
    if rec.get('evidence'):
        desc_lines.append(f"**Evidence**: {rec['evidence']}")
    if rec.get('satisfied_when'):
        desc_lines.append(f"**Satisfied When**: {rec['satisfied_when']}")
    if rec.get('guardrails'):
        desc_lines.append("**Guardrails**:")
        for g in rec['guardrails']:
            desc_lines.append(f"- {g}")
    if rec.get('matched_risks'):
        desc_lines.append(f"**Reflex Risks**: {', '.join(rec['matched_risks'])}")

    target = rec.get('target', 'workspace')
    title = rec.get('title', 'Untitled task')
    ticket_title = f"[{target}] {title}" if not title.startswith(f"[{target}]") else title

    labels = ['monag', f'tier:{tier}']
    if rec.get('origin'):
        labels.append(f"origin:{rec['origin']}")
    for r in rec.get('matched_risks', []):
        labels.append(f"risk:{r}")

    return {
        'title': ticket_title,
        'description': '\n\n'.join(desc_lines),
        'priority': priority,
        'labels': labels,
        'tier': tier,
        'target_repo': target,
        'score': rec.get('score', 0),
        'satisfied_when': rec.get('satisfied_when'),
        'source': 'monag',
    }


def export_planfile_tickets(advisory_data: dict[str, Any], tier: str | None = None) -> dict[str, Any]:
    """Format all (or filtered) recommendations as a Planfile-importable JSON dict."""
    recs = advisory_data.get('recommendations', [])
    if tier and tier.lower() != 'all':
        recs = [r for r in recs if r.get('tier') == tier.lower()]
    tickets = [to_planfile_ticket(r) for r in recs]
    return {
        'schema': 'planfile.tickets/v1',
        'source': 'monag',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'count': len(tickets),
        'tickets': tickets,
    }


def feed_to_planfile(advisory_data: dict[str, Any], root: Path, sprint: str = 'current',
                     tier: str | None = None) -> dict[str, Any]:
    """Directly invoke `planfile ticket import --source monag` via subprocess and stdin."""
    export_obj = export_planfile_tickets(advisory_data, tier=tier)
    tickets = export_obj.get('tickets', [])
    if not tickets:
        return {'ok': True, 'count': 0, 'message': 'No recommendations to import.'}

    import shutil
    planfile_bin = shutil.which('planfile')
    if not planfile_bin:
        return {'ok': False, 'error': 'planfile CLI not found on PATH'}

    cmd = [planfile_bin, 'ticket', 'import', '--source', 'monag', '--sprint', sprint]
    input_data = json.dumps(export_obj)
    try:
        proc = subprocess.run(cmd, input=input_data, text=True, capture_output=True,
                              cwd=str(root), timeout=30)
        if proc.returncode == 0:
            return {
                'ok': True,
                'count': len(tickets),
                'stdout': proc.stdout.strip(),
                'stderr': proc.stderr.strip(),
            }
        else:
            return {
                'ok': False,
                'error': f"planfile exit code {proc.returncode}: {proc.stderr.strip() or proc.stdout.strip()}",
            }
    except Exception as exc:
        return {'ok': False, 'error': str(exc)}


def collect_workspace_metrics(root: Path, depth: int = 2) -> dict[str, Any]:
    """Fast local discovery of overall open PRs and active worktrees count."""
    total_wts = 0
    repos_with_wt = 0
    total_prs = 0

    try:
        from . import audit
        mode, paths, _ = audit.targets(root, depth=depth)
        wt_info = audit.collect_worktrees(paths)
        total_wts = len(wt_info.get('worktrees', []))
        repos_with_wt = wt_info.get('repos_with_worktrees', 0)
    except Exception:
        pass

    try:
        from . import prs
        prs_data = prs.scan(root, depth=depth, pr_limit=200, unpushed_only=False, all_repos=False)
        total_prs = len(prs_data.get('open_prs', []))
    except Exception:
        pass

    return {
        'total_open_prs': total_prs,
        'total_worktrees': total_wts,
        'repos_with_worktrees': repos_with_wt,
    }


def advise(root: Path, depth: int = 2, issue_limit: int = 200,
           radar: bool = False, hygiene: bool = False,
           reflex_source: list[str] | None = None,
           state_dir: Path | None = None, limit: int = 15,
           export_data: dict[str, Any] | None = None,
           tier: str | None = None,
           include_metrics: bool = True,
           open_prs_count: int | None = None,
           worktrees_count: int | None = None,
           repos_with_worktrees: int | None = None,
           holistic: bool = False) -> dict[str, Any]:
    """Generate prioritized next actions and architectural guidelines."""
    if holistic:
        from . import triage
        return triage.run_holistic_triage(root=root, depth=depth, limit=limit)

    started = time.monotonic()
    if export_data is None:
        export_data = export.scan(root, depth=depth, issue_limit=issue_limit,
                                  radar=radar, hygiene=hygiene)
    reflex_data = collect_reflex_patterns(root, state_dir=state_dir,
                                          extra_sources=reflex_source)

    candidates = export_data.get('candidates', [])
    recommendations = []

    for c in candidates:
        title = c.get('title', '')
        desc = c.get('summary', c.get('description', ''))
        matched_risks = _match_reflex_risk(title, desc, reflex_data)
        algo_conflict = verify_candidate_conflict(c, root)
        if algo_conflict and algo_conflict.get('has_conflict'):
            if 'governance-friction' not in matched_risks:
                matched_risks.append('governance-friction')
        item_tier = classify_tier(c, matched_risks)
        guidelines = synthesize_guidelines(c, matched_risks, algo_conflict=algo_conflict)
        score = compute_advisory_score(c, matched_risks, tier=item_tier)

        recommendations.append({
            'target': c.get('repo', c.get('path', '')),
            'title': title,
            'origin': c.get('origin', ''),
            'tier': item_tier,
            'score': score,
            'matched_risks': matched_risks,
            'action': guidelines['action'],
            'evidence': guidelines['evidence'],
            'satisfied_when': guidelines['satisfied_when'],
            'guardrails': guidelines['guardrails'],
            'radar': c.get('radar'),
        })

    readings = generate_priority_readings(reflex_data, recommendations)

    # Sort descending by score across all items
    recommendations.sort(key=lambda r: r['score'], reverse=True)

    # Filter by tier if specified
    active_tier = tier.lower() if (tier and tier.lower() != 'all') else 'all'
    if active_tier != 'all':
        filtered = [r for r in recommendations if r['tier'] == active_tier]
    else:
        filtered = recommendations

    capped = filtered[:limit]

    metrics = {
        'total_open_prs': open_prs_count if open_prs_count is not None else 0,
        'total_worktrees': worktrees_count if worktrees_count is not None else 0,
        'repos_with_worktrees': repos_with_worktrees if repos_with_worktrees is not None else 0,
    }
    if include_metrics and (open_prs_count is None or worktrees_count is None):
        discovered = collect_workspace_metrics(root, depth=depth)
        if open_prs_count is None:
            metrics['total_open_prs'] = discovered['total_open_prs']
        if worktrees_count is None:
            metrics['total_worktrees'] = discovered['total_worktrees']
            metrics['repos_with_worktrees'] = discovered['repos_with_worktrees']

    duration = round(time.monotonic() - started, 2)
    tier_suffix = f" (filtr tier: {active_tier})" if active_tier != 'all' else ""
    summary_text = (
        f"{len(capped)} rekomendowanych działań{tier_suffix} na bazie {len(candidates)} kandydatów "
        f"i {len(reflex_data.get('patterns', []))} wzorców reflex."
    )

    return {
        'schema': SCHEMA,
        'root': str(root),
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'duration_seconds': duration,
        'summary': summary_text,
        'tier_filter': active_tier,
        'readings': readings,
        'metrics': metrics,
        'recommendations': capped,
        'total_candidates': len(candidates),
        'reflex': {
            'available': reflex_data.get('available', False),
            'pattern_count': len(reflex_data.get('patterns', [])),
            'proposal_count': len(reflex_data.get('proposals', [])),
            'reason': reflex_data.get('reason'),
        },
        'algocode': {
            'available': _find_algocode_runner() is not None,
            'runner': _find_algocode_runner(),
        },
    }


def markdown(advisory_data: dict[str, Any]) -> str:
    """Format advisory recommendations as GitHub Flavored Markdown."""
    if advisory_data.get('schema') == 'monag.triage/v1':
        from . import triage
        return triage.triage_markdown(advisory_data)

    lines = [
        "# MONAG Architectural Advisory & Task Guidance",
        "",
        f"**{advisory_data['generated_at'][:16].replace('T', ' ')} UTC** · "
        f"root: `{advisory_data['root']}` · czas analizy: {advisory_data['duration_seconds']}s",
        "",
        f"> {advisory_data['summary']}",
        "",
    ]

    readings_env = advisory_data.get('readings')
    floor_val = 0
    mission_val = 0
    if readings_env and isinstance(readings_env, dict):
        r_map = readings_env.get('readings', {})
        floor_val = r_map.get('floor_friction_count', {}).get('value', 0)
        mission_val = r_map.get('mission_demand_count', {}).get('value', 0)
        active_pats = r_map.get('active_failure_patterns', {}).get('value', 0)
        lines.append(f"*Priority DSL readings: Floor friction ({floor_val}) · Mission demand ({mission_val}) · "
                     f"Active failure patterns ({active_pats}).*")
        lines.append("")

    reflex_info = advisory_data.get('reflex', {})
    if reflex_info.get('available'):
        lines.append(f"*Learning Loop: aktywne wzorce Reflex ({reflex_info.get('pattern_count', 0)}) "
                     f"i propozycje usprawnień ({reflex_info.get('proposal_count', 0)}).*")
        lines.append("")
    elif reflex_info.get('reason'):
        lines.append(f"*Uwaga: subactor.reflex niedostępny ({reflex_info.get('reason')}); "
                     f"użyto standardowej heurystyki priorytetów.*")
        lines.append("")

    # Executive Overview Table with total PRs and Worktrees
    metrics = advisory_data.get('metrics', {})
    prs_val = metrics.get('total_open_prs', 0)
    wt_val = metrics.get('total_worktrees', 0)
    repos_wt_val = metrics.get('repos_with_worktrees', 0)
    recs = advisory_data.get('recommendations', [])
    hygiene_val = len([r for r in recs if r.get('tier') == TIER_HYGIENE])

    tier_summary = f"{floor_val} floor, {mission_val} mission, {hygiene_val} hygiene"
    wt_repr = f"{wt_val} ({repos_wt_val} repo)" if repos_wt_val else str(wt_val)
    overview_rows = [[
        str(prs_val),
        wt_repr,
        tier_summary,
        str(advisory_data.get('total_candidates', len(recs))),
    ]]
    lines.append("## Stan Workspace (PRs & Worktrees)")
    lines.append("")
    lines.append(presentation.table(['Otwarte PR', 'Aktywne Worktrees', 'Rekomendacje Tiers', 'Kandydaci Razem'], overview_rows))
    lines.append("")

    if not recs:
        lines.append("_Brak rekomendowanych zadań. Workspace jest w spójnym stanie._\n")
        return '\n'.join(lines)

    table_rows = []
    for r in recs:
        risks_str = ', '.join(r['matched_risks']) if r['matched_risks'] else '—'
        tier_str = r.get('tier', '—').upper()
        table_rows.append([
            tier_str,
            str(r['score']),
            r['target'],
            r['title'],
            risks_str,
        ])

    lines.append("## Rekomendowane Zadania")
    lines.append("")
    lines.append(presentation.table(['Tier', 'Score', 'Projekt', 'Zadanie', 'Wykryte ryzyka (Reflex)'], table_rows))
    lines.append("")
    lines.append("## Szczegółowe wytyczne dla kolejnych zadań")
    lines.append("")

    for idx, r in enumerate(recs, 1):
        tier_tag = f"[{r.get('tier', '').upper()}] " if r.get('tier') else ""
        lines.append(f"### {idx}. {tier_tag}[{r['score']} pkt] {r['target']}: {r['title']}")
        lines.append(f"- **Rekomendowane działanie**: {r['action']}")
        lines.append(f"- **Uzasadnienie / Fakty**: {r['evidence']}")
        if r.get('satisfied_when'):
            lines.append(f"- **Warunek ukończenia (Satisfied When)**: {r['satisfied_when']}")
        if r['matched_risks']:
            lines.append(f"- **Zidentyfikowane wzorce błędów**: `{', '.join(r['matched_risks'])}`")
        if r.get('guardrails'):
            lines.append("- **Wytyczne i ograniczenia (Guardrails)**:")
            for g in r['guardrails']:
                lines.append(f"  * {g}")
        if r.get('radar') and isinstance(r['radar'], dict):
            radar = r['radar']
            lines.append(f"- **Ocena złożoności (Radar)**: {radar.get('complexity', '—')} "
                         f"(szacowany czas: {radar.get('estimated_minutes', '—')} min, "
                         f"podział: {'TAK' if radar.get('split_recommended') else 'NIE'})")
        lines.append("")

    lines.append("---")
    lines.append("*Wygenerowano przez monag advise na bazie faktów kodu, statusu zadań, Priority DSL i śladów reflex.*")
    lines.append("")
    return '\n'.join(lines)



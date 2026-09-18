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

FAILURE_KEYWORD_MAP = {
    'remote-rate-limit': ('rate limit', '403', '429', 'secondary limit', 'api rate'),
    'timeout-failure': ('timeout', 'timed out', 'deadline exceeded', 'sigkill'),
    'governance-friction': ('governance', 'gov-', 'overlap', 'workstream', 'ticket-0'),
    'dependency-drift': ('dependency', 'pin', 'version', 'incompatible', 'digest'),
    'tool-contract-friction': ('usage:', 'invalid choice', 'contract', '422', 'not found'),
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


def synthesize_guidelines(candidate: dict[str, Any], matched_risks: list[str]) -> dict[str, Any]:
    """Generate concrete action, rationale, and guardrails for an item."""
    origin = candidate.get('origin', '')
    title = candidate.get('title', '')
    summary = candidate.get('summary', candidate.get('description', ''))
    repo = candidate.get('repo', candidate.get('path', ''))

    # Determine base action
    if origin == 'audit-untracked-issue':
        action = f"Rozpocznij realizację zgłoszenia #{candidate.get('issue_number', '')} w {repo}: stwórz ticket i gałąź roboczą."
        evidence = f"Otwarte zgłoszenie GitHub bez powiązanego ticketu Planfile: '{title}'."
    elif origin == 'catalog-undescribed':
        action = f"Uzupełnij opis projektu i stosu technologicznego w {repo} (README/pyproject.toml/package.json)."
        evidence = f"Katalog repozytoriów wskazuje brak metadanych w {repo}."
    elif origin == 'taskill-doc-drift':
        action = f"Zsynchronizuj dryf dokumentacji w {repo} (README/CHANGELOG/TODO)."
        evidence = f"Taskill wykrył niezatwierdzone zmiany w dokumentacji po ostatnich commitach."
    else:
        action = f"Kontynuuj realizację zadania w {repo}: {title}."
        evidence = f"Zadanie oczekujące w backlogu Planfile ({candidate.get('id', candidate.get('ticket', ''))})."

    # Add guardrails based on detected risks
    guardrails = ["Weryfikuj zgodność z regułami governance repozytorium przed otwarciem PR."]
    if 'remote-rate-limit' in matched_risks:
        guardrails.append("Uwaga na limity API: wykorzystaj lokalne procedury CDP lub OneDev zamiast powtarzanych zapytań zdalnych.")
    if 'timeout-failure' in matched_risks:
        guardrails.append("Ustaw jawny timeout HTTP/gniazda; nie polegaj na globalnym limicie procesu.")
    if 'dependency-drift' in matched_risks:
        guardrails.append("Migracja wersji/pinów: sprawdź konsumentów downstream (np. onedev-agent) przed zmianą digestów.")
    if 'governance-friction' in matched_risks:
        guardrails.append("Upewnij się, że modyfikowane ścieżki mieszczą się w jednym workstreamie i dokładnie jednym tickecie.")

    return {
        'action': action,
        'evidence': evidence,
        'guardrails': guardrails,
    }


def compute_advisory_score(candidate: dict[str, Any], matched_risks: list[str]) -> int:
    """Calculate an advisory priority score (0-150)."""
    score = 50
    priority = str(candidate.get('priority', '')).lower()
    if priority in {'critical', 'p0'}:
        score += 40
    elif priority in {'high', 'p1'}:
        score += 25
    elif priority in {'medium', 'p2'}:
        score += 10

    # Risk bonus: actively failing patterns require urgent attention
    score += len(matched_risks) * 15

    # Radar sizing bonus: complex items needing decomposition
    radar = candidate.get('radar')
    if radar and isinstance(radar, dict):
        if radar.get('split_recommended'):
            score += 15
        if radar.get('complexity') == 'high':
            score += 10

    return score


def advise(root: Path, depth: int = 2, issue_limit: int = 200,
           radar: bool = False, hygiene: bool = False,
           reflex_source: list[str] | None = None,
           state_dir: Path | None = None, limit: int = 15) -> dict[str, Any]:
    """Generate prioritized next actions and architectural guidelines."""
    started = time.monotonic()
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
        guidelines = synthesize_guidelines(c, matched_risks)
        score = compute_advisory_score(c, matched_risks)

        recommendations.append({
            'target': c.get('repo', c.get('path', '')),
            'title': title,
            'origin': c.get('origin', ''),
            'score': score,
            'matched_risks': matched_risks,
            'action': guidelines['action'],
            'evidence': guidelines['evidence'],
            'guardrails': guidelines['guardrails'],
            'radar': c.get('radar'),
        })

    recommendations.sort(key=lambda r: r['score'], reverse=True)
    capped = recommendations[:limit]

    duration = round(time.monotonic() - started, 2)
    summary_text = (
        f"{len(capped)} rekomendowanych działań na bazie {len(candidates)} kandydatów "
        f"i {len(reflex_data.get('patterns', []))} wzorców reflex."
    )

    return {
        'schema': SCHEMA,
        'root': str(root),
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'duration_seconds': duration,
        'summary': summary_text,
        'recommendations': capped,
        'total_candidates': len(candidates),
        'reflex': {
            'available': reflex_data.get('available', False),
            'pattern_count': len(reflex_data.get('patterns', [])),
            'proposal_count': len(reflex_data.get('proposals', [])),
            'reason': reflex_data.get('reason'),
        },
    }


def markdown(advisory_data: dict[str, Any]) -> str:
    """Format advisory recommendations as GitHub Flavored Markdown."""
    lines = [
        "# MONAG Architectural Advisory & Task Guidance",
        "",
        f"**{advisory_data['generated_at'][:16].replace('T', ' ')} UTC** · "
        f"root: `{advisory_data['root']}` · czas analizy: {advisory_data['duration_seconds']}s",
        "",
        f"> {advisory_data['summary']}",
        "",
    ]

    reflex_info = advisory_data.get('reflex', {})
    if reflex_info.get('available'):
        lines.append(f"*Learning Loop: aktywne wzorce Reflex ({reflex_info.get('pattern_count', 0)}) "
                     f"i propozycje usprawnień ({reflex_info.get('proposal_count', 0)}).*")
        lines.append("")
    elif reflex_info.get('reason'):
        lines.append(f"*Uwaga: subactor.reflex niedostępny ({reflex_info.get('reason')}); "
                     f"użyto standardowej heurystyki priorytetów.*")
        lines.append("")

    recs = advisory_data.get('recommendations', [])
    if not recs:
        lines.append("_Brak rekomendowanych zadań. Workspace jest w spójnym stanie._\n")
        return '\n'.join(lines)

    table_rows = []
    for r in recs:
        risks_str = ', '.join(r['matched_risks']) if r['matched_risks'] else '—'
        table_rows.append([
            str(r['score']),
            r['target'],
            r['title'],
            risks_str,
        ])

    lines.append(presentation.table(['Score', 'Projekt', 'Zadanie', 'Wykryte ryzyka (Reflex)'], table_rows))
    lines.append("")
    lines.append("## Szczegółowe wytyczne dla kolejnych zadań")
    lines.append("")

    for idx, r in enumerate(recs, 1):
        lines.append(f"### {idx}. [{r['score']} pkt] {r['target']}: {r['title']}")
        lines.append(f"- **Rekomendowane działanie**: {r['action']}")
        lines.append(f"- **Uzasadnienie / Fakty**: {r['evidence']}")
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
    lines.append("*Wygenerowano przez monag advise na bazie faktów kodu, statusu zadań i śladów reflex.*")
    lines.append("")
    return '\n'.join(lines)

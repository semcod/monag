"""Tests for monag.advise — architectural guidance and reflex integration."""
from pathlib import Path
from unittest import mock
import pytest

from monag import advise


def test_match_reflex_risk():
    reflex_data = {
        'patterns': [{'category': 'remote-rate-limit'}],
    }
    risks = advise._match_reflex_risk('API rate limit hit in worker', '403 secondary limit', reflex_data)
    assert 'remote-rate-limit' in risks

    timeout_risks = advise._match_reflex_risk('Worker timed out waiting for response', 'sigkill', {})
    assert 'timeout-failure' in timeout_risks

    gov_risks = advise._match_reflex_risk('GOV-SCOPE-001 workstream overlap', '', {})
    assert 'governance-friction' in gov_risks


def test_compute_advisory_score():
    candidate_high = {'priority': 'high'}
    candidate_crit = {'priority': 'critical'}
    candidate_radar = {
        'priority': 'medium',
        'radar': {'split_recommended': True, 'complexity': 'high'},
    }

    score_high = advise.compute_advisory_score(candidate_high, [])
    score_crit = advise.compute_advisory_score(candidate_crit, [])
    score_risky = advise.compute_advisory_score(candidate_high, ['remote-rate-limit', 'timeout-failure'])
    score_radar = advise.compute_advisory_score(candidate_radar, [])

    assert score_crit > score_high
    assert score_risky > score_high
    assert score_radar > advise.compute_advisory_score({'priority': 'medium'}, [])


def test_synthesize_guidelines():
    candidate_issue = {
        'origin': 'audit-untracked-issue',
        'repo': 'subactor/subllm',
        'issue_number': 75,
        'title': 'Fix openai worker timeout',
        'description': 'urllib request hangs without timeout',
    }
    guidelines = advise.synthesize_guidelines(candidate_issue, ['timeout-failure', 'remote-rate-limit'])

    assert '#75' in guidelines['action']
    assert 'subactor/subllm' in guidelines['action']
    assert any('timeout' in g.lower() for g in guidelines['guardrails'])
    assert any('cdp' in g.lower() or 'api' in g.lower() for g in guidelines['guardrails'])


def test_advise_ranking(tmp_path):
    mock_candidates = [
        {'origin': 'catalog-undescribed', 'path': '/repo/low', 'title': 'Undescribed repo', 'priority': 'low'},
        {'origin': 'audit-untracked-issue', 'repo': 'semcod/critical', 'issue_number': 10, 'title': 'Critical failure', 'priority': 'critical'},
    ]

    with mock.patch('monag.export.scan', return_value={'candidates': mock_candidates}), \
         mock.patch('monag.advise.collect_reflex_patterns', return_value={'available': False, 'patterns': []}):

        result = advise.advise(tmp_path, limit=5)

    assert result['schema'] == 'monag.advisory/v1'
    assert len(result['recommendations']) == 2
    # Critical should be ranked first
    assert result['recommendations'][0]['target'] == 'semcod/critical'
    assert result['recommendations'][0]['score'] > result['recommendations'][1]['score']


def test_markdown_formatting():
    data = {
        'schema': 'monag.advisory/v1',
        'root': '/home/tom/github',
        'generated_at': '2026-09-18T20:00:00+00:00',
        'duration_seconds': 0.5,
        'summary': '1 rekomendowane zadanie',
        'total_candidates': 1,
        'reflex': {'available': True, 'pattern_count': 2, 'proposal_count': 1},
        'recommendations': [
            {
                'score': 115,
                'target': 'subactor/subllm',
                'title': 'OpenAI worker timeout',
                'origin': 'audit-untracked-issue',
                'matched_risks': ['timeout-failure'],
                'action': 'Dodaj timeout w urllib.request',
                'evidence': 'Zgłoszenie #75 bez ticketu',
                'guardrails': ['Ustaw jawny timeout HTTP'],
                'radar': {'complexity': 'medium', 'estimated_minutes': 45, 'split_recommended': False},
            }
        ],
    }
    md = advise.markdown(data)
    assert '# MONAG Architectural Advisory' in md
    assert 'subactor/subllm' in md
    assert '115' in md
    assert 'timeout-failure' in md
    assert 'Ustaw jawny timeout HTTP' in md


def test_cli_advise_dispatch(tmp_path):
    from monag.cli import main
    mock_data = {
        'schema': 'monag.advisory/v1', 'root': str(tmp_path),
        'generated_at': '2026-09-18T20:00:00+00:00', 'duration_seconds': 0.1,
        'summary': '0 rekomendacji', 'recommendations': [], 'total_candidates': 0,
        'reflex': {'available': False},
    }
    with mock.patch('monag.advise.advise', return_value=mock_data):
        rc = main(['--root', str(tmp_path), '--plain', 'advise'])
        assert rc == 0


def test_mcp_advise_tool(tmp_path):
    from monag.mcp import handle_tool_call, read_resource
    mock_data = {
        'schema': 'monag.advisory/v1', 'root': str(tmp_path),
        'generated_at': '2026-09-18T20:00:00+00:00', 'duration_seconds': 0.1,
        'summary': 'test summary', 'recommendations': [], 'total_candidates': 0,
        'reflex': {'available': False},
    }
    with mock.patch('monag.advise.advise', return_value=mock_data):
        tool_res = handle_tool_call('monag_advise', {'limit': 5}, tmp_path)
        assert len(tool_res) == 1
        assert '# MONAG Architectural Advisory' in tool_res[0]['text']

        res_text = read_resource('monag://advise', tmp_path)
        assert '# MONAG Architectural Advisory' in res_text


def test_panel_advise_route(tmp_path):
    from monag import panel
    server, state = panel.build_server(tmp_path, tmp_path / 'state', port=0)
    mock_data = {'schema': 'monag.advisory/v1', 'recommendations': []}
    with mock.patch('monag.advise.advise', return_value=mock_data):
        advise_fn = panel.ROUTES['/api/advise.json']
        res = advise_fn(state)
        assert res['schema'] == 'monag.advisory/v1'

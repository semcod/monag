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


def test_synthesize_guidelines_handles_none_repo():
    candidate_none_repo = {
        'origin': 'backlog',
        'repo': None,
        'path': None,
        'title': 'Item without repo',
        'id': 'PLF-999',
    }
    guidelines = advise.synthesize_guidelines(candidate_none_repo, [])
    assert 'PLF-999' in guidelines['satisfied_when']
    assert isinstance(guidelines['guardrails'], list)


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


def test_advise_reuse_export_data(tmp_path):
    cached_candidates = [{'origin': 'test', 'repo': 'autogrammar/intract', 'title': 'Fix schema contract', 'priority': 'high'}]
    cached_export = {'candidates': cached_candidates}

    with mock.patch('monag.export.scan') as mock_scan, \
         mock.patch('monag.advise.collect_reflex_patterns', return_value={'available': False}):

        res = advise.advise(tmp_path, export_data=cached_export, limit=5)
        mock_scan.assert_not_called()
        assert len(res['recommendations']) == 1
        assert res['recommendations'][0]['target'] == 'autogrammar/intract'
        assert any('intract' in g.lower() for g in res['recommendations'][0]['guardrails'])


def test_synthesize_guidelines_autogrammar_contract():
    candidate = {'origin': 'test', 'repo': 'autogrammar/intract', 'title': 'Contract drift', 'description': 'schema mismatch'}
    guidelines = advise.synthesize_guidelines(candidate, ['contract-schema-drift'])
    assert any('intract' in g.lower() or 'code2schema' in g.lower() for g in guidelines['guardrails'])
    assert 'satisfied_when' in guidelines


def test_classify_tier():
    # Floor: critical priority, governance friction, broken keywords
    assert advise.classify_tier({'priority': 'critical', 'title': 'Routine task'}, []) == advise.TIER_FLOOR
    assert advise.classify_tier({'priority': 'low', 'title': 'Routine'}, ['governance-friction']) == advise.TIER_FLOOR
    assert advise.classify_tier({'title': 'Fix broken test suite in CI'}, []) == advise.TIER_FLOOR

    # Mission: high priority, untracked issue, feature/pr/release
    assert advise.classify_tier({'priority': 'high', 'title': 'Add telemetry'}, []) == advise.TIER_MISSION
    assert advise.classify_tier({'origin': 'audit-untracked-issue', 'title': 'Missing feature'}, []) == advise.TIER_MISSION
    assert advise.classify_tier({'title': 'Release v1.2.0 candidate'}, []) == advise.TIER_MISSION

    # Hygiene: doc drift, undescribed catalog, complexity
    assert advise.classify_tier({'origin': 'taskill-doc-drift', 'title': 'Sync docs'}, []) == advise.TIER_HYGIENE
    assert advise.classify_tier({'origin': 'catalog-undescribed', 'title': 'Metadata'}, []) == advise.TIER_HYGIENE
    assert advise.classify_tier({'title': 'Refactor database models'}, []) == advise.TIER_HYGIENE
    assert advise.classify_tier({'priority': 'medium', 'title': 'Normal task'}, []) == advise.TIER_HYGIENE

    # Backlog: low priority or unclassified
    assert advise.classify_tier({'priority': 'low', 'title': 'Investigate idea'}, []) == advise.TIER_BACKLOG


def test_lexicographic_hierarchy_scores():
    # Even with all risk bonuses, hygiene cannot beat mission base score
    floor_item = {'priority': 'critical', 'title': 'Fix broken build'}
    mission_item = {'priority': 'high', 'title': 'Release feature'}
    hygiene_item = {
        'origin': 'taskill-doc-drift',
        'title': 'Refactor complexity',
        'radar': {'split_recommended': True, 'complexity': 'high'},
    }
    backlog_item = {'priority': 'low', 'title': 'Someday idea'}

    score_floor = advise.compute_advisory_score(floor_item, [])
    score_mission = advise.compute_advisory_score(mission_item, ['timeout-failure', 'remote-rate-limit'])
    score_hygiene = advise.compute_advisory_score(hygiene_item, ['tool-contract-friction'])
    score_backlog = advise.compute_advisory_score(backlog_item, [])

    # Floor base is 1000, Mission base is 500, Hygiene base is 200, Backlog base is 50
    assert score_floor > score_mission > score_hygiene > score_backlog
    assert score_floor >= 1000
    assert score_mission >= 500
    assert score_hygiene >= 200
    assert score_backlog >= 50


def test_generate_priority_readings():
    reflex_data = {
        'patterns': [
            {'category': 'remote-rate-limit'},
            {'category': 'governance-friction'},
        ]
    }
    recs = [
        {'tier': advise.TIER_FLOOR, 'title': 'Floor 1'},
        {'tier': advise.TIER_MISSION, 'title': 'Mission 1'},
        {'tier': advise.TIER_MISSION, 'title': 'Mission 2'},
        {'tier': advise.TIER_HYGIENE, 'title': 'Hygiene 1'},
    ]
    envelope = advise.generate_priority_readings(reflex_data, recs)

    assert envelope['schema'] == 'wellmanifest.priority/readings/v1'
    assert envelope['document']['id'] == 'monag.advise.priority'
    assert 'observedAt' in envelope

    readings = envelope['readings']
    assert readings['floor_friction_count']['value'] == 1
    assert readings['mission_demand_count']['value'] == 2
    assert readings['active_failure_patterns']['value'] == 2
    assert readings['remote_rate_limit']['value'] == 1
    assert readings['governance_friction']['value'] == 1
    assert readings['timeout_failure']['value'] == 0


def test_advise_tier_filtering(tmp_path):
    mock_candidates = [
        {'origin': 'audit-untracked-issue', 'repo': 'semcod/critical', 'issue_number': 10, 'title': 'Broken build', 'priority': 'critical'},
        {'origin': 'audit-untracked-issue', 'repo': 'semcod/feature', 'issue_number': 11, 'title': 'New release feature', 'priority': 'high'},
        {'origin': 'taskill-doc-drift', 'repo': 'semcod/docs', 'title': 'Refactor docs', 'priority': 'low'},
    ]

    with mock.patch('monag.export.scan', return_value={'candidates': mock_candidates}), \
         mock.patch('monag.advise.collect_reflex_patterns', return_value={'available': False, 'patterns': []}):

        # All tiers
        all_res = advise.advise(tmp_path, tier='all')
        assert len(all_res['recommendations']) == 3
        assert all_res['tier_filter'] == 'all'
        assert 'readings' in all_res
        assert all_res['readings']['schema'] == 'wellmanifest.priority/readings/v1'

        # Floor only
        floor_res = advise.advise(tmp_path, tier='floor')
        assert len(floor_res['recommendations']) == 1
        assert floor_res['recommendations'][0]['tier'] == 'floor'
        assert floor_res['recommendations'][0]['target'] == 'semcod/critical'
        assert 'satisfied_when' in floor_res['recommendations'][0]

        # Mission only
        mission_res = advise.advise(tmp_path, tier='mission')
        assert len(mission_res['recommendations']) == 1
        assert mission_res['recommendations'][0]['tier'] == 'mission'
        assert mission_res['recommendations'][0]['target'] == 'semcod/feature'

        # Hygiene only
        hygiene_res = advise.advise(tmp_path, tier='hygiene')
        assert len(hygiene_res['recommendations']) == 1
        assert hygiene_res['recommendations'][0]['tier'] == 'hygiene'


def test_cli_advise_tier_argument(tmp_path):
    from monag.cli import main
    mock_data = {
        'schema': 'monag.advisory/v1', 'root': str(tmp_path),
        'generated_at': '2026-09-18T20:00:00+00:00', 'duration_seconds': 0.1,
        'summary': '0 rekomendacji', 'recommendations': [], 'total_candidates': 0,
        'reflex': {'available': False}, 'tier_filter': 'floor',
    }
    with mock.patch('monag.advise.advise', return_value=mock_data) as mock_adv:
        rc = main(['--root', str(tmp_path), '--plain', 'advise', '--tier', 'floor'])
        assert rc == 0
        mock_adv.assert_called_once()
        _, kwargs = mock_adv.call_args
        assert kwargs.get('tier') == 'floor'


def test_mcp_advise_tool_with_tier(tmp_path):
    from monag.mcp import handle_tool_call
    mock_data = {
        'schema': 'monag.advisory/v1', 'root': str(tmp_path),
        'generated_at': '2026-09-18T20:00:00+00:00', 'duration_seconds': 0.1,
        'summary': 'test summary', 'recommendations': [], 'total_candidates': 0,
        'reflex': {'available': False},
    }
    with mock.patch('monag.advise.advise', return_value=mock_data) as mock_adv:
        handle_tool_call('monag_advise', {'limit': 5, 'tier': 'mission'}, tmp_path)
        mock_adv.assert_called_once()
        _, kwargs = mock_adv.call_args
        assert kwargs.get('tier') == 'mission'


def test_find_algocode_runner():
    runner = advise._find_algocode_runner()
    # If algocode is in workspace, it should be discovered as import or None in clean env
    assert runner in {'import', 'cli', None}


def test_synthesize_guidelines_with_algocode_conflict():
    candidate = {
        'origin': 'audit-untracked-issue',
        'repo': 'wellmanifest/new-project',
        'title': 'Overlapping change',
        'issue_number': 99,
    }
    mock_conflict = {
        'has_conflict': True,
        'conflicts': [
            {'type': 'path_overlap', 'message': 'Path overlap on governance/manifest.json'}
        ]
    }
    guidelines = advise.synthesize_guidelines(candidate, [], algo_conflict=mock_conflict)
    assert any('Algocode Gate' in g for g in guidelines['guardrails'])
    assert any('kolizji ścieżek' in g for g in guidelines['guardrails'])


def test_advise_with_algocode_metadata(tmp_path):
    mock_candidates = [
        {'origin': 'catalog-undescribed', 'path': '/repo/test', 'title': 'Test repo', 'priority': 'low'},
    ]
    with mock.patch('monag.export.scan', return_value={'candidates': mock_candidates}), \
         mock.patch('monag.advise.collect_reflex_patterns', return_value={'available': False, 'patterns': []}):
        result = advise.advise(tmp_path, limit=5)

    assert 'algocode' in result
    assert 'available' in result['algocode']


def test_to_planfile_ticket():
    rec_floor = {
        'target': 'semcod/critical',
        'title': 'Broken CI gate',
        'tier': advise.TIER_FLOOR,
        'action': 'Fix pipeline',
        'evidence': 'Exit code 1',
        'satisfied_when': 'Tests pass',
        'guardrails': ['Do not bypass check'],
        'matched_risks': ['governance-friction'],
        'origin': 'audit-untracked-issue',
        'score': 1050,
    }
    ticket = advise.to_planfile_ticket(rec_floor)
    assert ticket['title'] == '[semcod/critical] Broken CI gate'
    assert ticket['priority'] == 'critical'
    assert 'tier:floor' in ticket['labels']
    assert 'monag' in ticket['labels']
    assert 'risk:governance-friction' in ticket['labels']
    assert '**Satisfied When**: Tests pass' in ticket['description']
    assert '**Action**: Fix pipeline' in ticket['description']
    assert ticket['source'] == 'monag'


def test_export_planfile_tickets():
    advisory_data = {
        'recommendations': [
            {'target': 'repo/a', 'title': 'Task 1', 'tier': advise.TIER_FLOOR},
            {'target': 'repo/b', 'title': 'Task 2', 'tier': advise.TIER_MISSION},
        ]
    }
    all_tickets = advise.export_planfile_tickets(advisory_data, tier='all')
    assert all_tickets['schema'] == 'planfile.tickets/v1'
    assert all_tickets['count'] == 2
    assert len(all_tickets['tickets']) == 2

    floor_only = advise.export_planfile_tickets(advisory_data, tier='floor')
    assert floor_only['count'] == 1
    assert floor_only['tickets'][0]['tier'] == 'floor'


def test_feed_to_planfile(tmp_path):
    advisory_data = {
        'recommendations': [
            {'target': 'repo/a', 'title': 'Task 1', 'tier': advise.TIER_MISSION},
        ]
    }
    with mock.patch('shutil.which', return_value='/usr/local/bin/planfile'), \
         mock.patch('subprocess.run') as mock_run:
        mock_run.return_value = mock.Mock(returncode=0, stdout='Imported 1 ticket', stderr='')
        res = advise.feed_to_planfile(advisory_data, root=tmp_path, sprint='sprint-42')
        assert res['ok'] is True
        assert res['count'] == 1
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ['/usr/local/bin/planfile', 'ticket', 'import', '--source', 'monag', '--sprint', 'sprint-42']


def test_collect_workspace_metrics(tmp_path):
    with mock.patch('monag.audit.targets', return_value=('workspace', [tmp_path], [])), \
         mock.patch('monag.audit.collect_worktrees', return_value={'worktrees': [{'path': str(tmp_path)}], 'repos_with_worktrees': 1}), \
         mock.patch('monag.prs.scan', return_value={'open_prs': [{'number': 1}]}):
        metrics = advise.collect_workspace_metrics(tmp_path)
        assert metrics['total_open_prs'] == 1
        assert metrics['total_worktrees'] == 1
        assert metrics['repos_with_worktrees'] == 1


def test_markdown_overview_table():
    data = {
        'schema': 'monag.advisory/v1',
        'root': '/home/tom/github',
        'generated_at': '2026-09-18T20:00:00+00:00',
        'duration_seconds': 0.5,
        'summary': '1 rekomendacja',
        'total_candidates': 5,
        'metrics': {
            'total_open_prs': 3,
            'total_worktrees': 12,
            'repos_with_worktrees': 4,
        },
        'readings': {
            'readings': {
                'floor_friction_count': {'value': 1},
                'mission_demand_count': {'value': 2},
                'active_failure_patterns': {'value': 0},
            }
        },
        'recommendations': [
            {
                'score': 1050,
                'target': 'semcod/critical',
                'title': 'CI failure',
                'origin': 'audit-untracked-issue',
                'tier': 'floor',
                'matched_risks': ['governance-friction'],
                'action': 'Fix pipeline',
                'evidence': 'Exit code 1',
                'satisfied_when': 'Pass',
            }
        ],
    }
    md = advise.markdown(data)
    assert '## Stan Workspace (PRs & Worktrees)' in md
    assert 'Otwarte PR' in md
    assert 'Aktywne Worktrees' in md
    assert '3' in md


def test_cli_planfile_emit_and_feed(tmp_path):
    from monag.cli import main
    mock_data = {
        'schema': 'monag.advisory/v1', 'root': str(tmp_path),
        'generated_at': '2026-09-18T20:00:00+00:00', 'duration_seconds': 0.1,
        'summary': '0 rekomendacji', 'recommendations': [], 'total_candidates': 0,
        'reflex': {'available': False}, 'tier_filter': 'all',
    }
    with mock.patch('monag.advise.advise', return_value=mock_data), \
         mock.patch('monag.advise.export_planfile_tickets', return_value={'tickets': []}) as mock_exp:
        rc = main(['--root', str(tmp_path), '--plain', 'advise', '--emit-planfile'])
        assert rc == 0
        mock_exp.assert_called_once()

    with mock.patch('monag.advise.advise', return_value=mock_data), \
         mock.patch('monag.advise.feed_to_planfile', return_value={'ok': True, 'count': 0}) as mock_feed:
        rc = main(['--root', str(tmp_path), '--plain', 'advise', '--feed-planfile', '--sprint', 's1'])
        assert rc == 0
        mock_feed.assert_called_once()




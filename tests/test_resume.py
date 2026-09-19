import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from monag import resume


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'org' / 'demo'
        self.repo.mkdir(parents=True)
        self.git('init', '-b', 'main')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Test')
        (self.repo / 'README').write_text('base')
        self.git('add', 'README')
        self.git('commit', '-m', 'base')
        self.git('update-ref', 'refs/remotes/origin/main', 'HEAD')

    def git(self, *args, cwd=None):
        return subprocess.check_output(['git', '-C', str(cwd or self.repo), *args], stderr=subprocess.DEVNULL, text=True).strip()

    def scan(self):
        with patch('monag.resume.processes', return_value=([], 0)):
            return resume.scan(self.root)

    def test_dirty_worktree_backlog_and_read_only(self):
        linked = self.repo / '.worktrees' / 'ticket-002--feature'
        self.git('worktree', 'add', '-b', 'ticket/002-feature', str(linked))
        for path in (self.repo, linked):
            (path / '.planfile/sprints').mkdir(parents=True)
            (path / '.planfile/sprints/current.yaml').write_text('sprint:\n  tickets:\n    ONE:\n      status: open\n    DONE:\n      status: done\n')
        (linked / 'project/ticket-002').mkdir(parents=True)
        (linked / 'project/ticket-002/intent.json').write_text(json.dumps({'delivery': {'complexity': 'S'}}))
        before = self.git('status', '--porcelain', cwd=linked)
        data = self.scan()
        self.assertEqual(data['project_count'], 1)
        p = data['projects'][0]
        self.assertEqual(p['planfile']['remaining'], 1)
        self.assertEqual(len(p['checkouts']), 2)
        row = next(r for r in p['checkouts'] if r['path'] == str(linked))
        self.assertEqual(row['complexity'], 'S')
        self.assertEqual(row['readiness'], 'review ownership')
        self.assertIn(str(linked), row['command'])
        self.assertEqual(before, self.git('status', '--porcelain', cwd=linked))

    def test_conflicting_statuses_are_visible(self):
        items = [{'id': 'A', 'status': 'done'}, {'id': 'A', 'status': 'open'}, {'id': 'B', 'status': 'mystery'}]
        result = resume.summarize_tickets(items)
        self.assertEqual(result['remaining'], 1)
        self.assertEqual(result['conflicting_statuses'], 1)
        self.assertEqual(result['unknown_statuses'], 1)

    def test_squash_merged_branch_is_only_an_ancestry_candidate(self):
        linked = self.repo / '.worktrees/ticket-020--squash'
        self.git('worktree', 'add', '-b', 'ticket/020-squash', str(linked))
        (linked / 'feature').write_text('delivered')
        self.git('add', 'feature', cwd=linked)
        self.git('commit', '-m', 'feature', cwd=linked)
        self.git('merge', '--squash', 'ticket/020-squash')
        self.git('commit', '-m', 'squashed delivery')
        self.git('update-ref', 'refs/remotes/origin/main', 'HEAD')
        row = next(r for r in self.scan()['projects'][0]['checkouts'] if r['path'] == str(linked))
        self.assertGreater(row['ahead'], 0)
        self.assertEqual(row['stage'], 'ancestry delta (publication unknown)')
        self.assertFalse(row['publication_verified'])

    def test_canonical_history_overrides_old_primary_and_worktree_copies(self):
        linked = self.repo / '.worktrees/ticket-021--old'
        sprint = self.repo / '.planfile/sprints'
        sprint.mkdir(parents=True)
        (sprint / 'current.yaml').write_text('sprint:\n  tickets:\n    A:\n      status: open\n')
        self.git('add', '.planfile')
        self.git('commit', '-m', 'original ticket snapshot')
        self.git('worktree', 'add', '-b', 'ticket/021-old', str(linked))
        (linked / '.planfile/sprints/backlog.yaml').write_text('sprint:\n  tickets:\n    NEW:\n      status: open\n')
        (self.repo / '.planfile/sprints/history-2026-09-19.yaml').write_text(
            'sprint:\n  tickets:\n    A:\n      status: done\n    BLOCKED:\n      status: blocked\n')
        index = self.repo / '.planfile/index'
        index.mkdir()
        (index / 'history-locations.yaml').write_text(
            'tickets:\n  A: history-2026-09-19\n  BLOCKED: history-2026-09-19\n')
        result = self.scan()['projects'][0]['planfile']
        self.assertEqual(result['remaining_ids'], ['BLOCKED', 'NEW'])
        self.assertEqual(result['conflicting_statuses'], 0)
        self.assertEqual(len(result['stale_copies']), 2)

    def test_locally_changed_worktree_record_is_not_dismissed_as_stale(self):
        items = [dict(id='A', status='done', checkout=str(self.repo), source='current.yaml'),
                 dict(id='A', status='open', checkout='other', source='current.yaml', source_changed=True)]
        selected, stale = resume.reconcile_ticket_sources(items, self.repo)
        self.assertEqual(resume.summarize_tickets(selected)['conflicting_statuses'], 1)
        self.assertEqual(stale, [])

    def test_distinct_external_bindings_are_not_hidden_by_source_precedence(self):
        items = [dict(id='A', status='done', title='First', github='5', checkout=str(self.repo), source='current.yaml'),
                 dict(id='A', status='open', title='Second', github='7', checkout='other', source='backlog.yaml')]
        selected, stale = resume.reconcile_ticket_sources(items, self.repo)
        result = resume.summarize_tickets(selected)
        self.assertEqual(len(result['identity_collisions']), 1)
        self.assertEqual(result['identity_collisions'][0]['github_bindings'], ['5', '7'])
        self.assertIn('identity collision', result['remaining_tickets'][0]['title'])
        self.assertEqual(len(result['identity_collisions'][0]['records']), 2)
        self.assertEqual(stale, [])

    def test_equivalent_external_binding_shapes_do_not_collide(self):
        rows = [dict(id='A', status='open', github='5', github_binding=b) for b in
                ({}, {'key': 'org/repo#5'}, {'url': 'https://github.com/org/repo/issues/5'})]
        self.assertEqual(resume.summarize_tickets(rows)['identity_collisions'], [])

    def test_missing_canonical_history_is_incomplete(self):
        directory = self.repo / '.planfile/index'
        directory.mkdir(parents=True)
        (directory / 'history-locations.yaml').write_text('tickets:\n  A: history-missing\n')
        (self.repo / 'planfile.yaml').write_text('tickets:\n  A:\n    status: open\n')
        result = self.scan()['projects'][0]
        self.assertFalse(result['planfile']['complete'])
        self.assertTrue(any('canonical history owner unavailable' in e for e in result['errors']))

    def test_prefixed_ticket_and_path_disagreement(self):
        self.assertEqual(resume.ticket_identity('ticket/PLF-084-feature'), 'ticket-PLF-084')
        self.assertEqual(resume.ticket_identity('ticket-115--feature'), 'ticket-115')
        self.assertIsNone(resume.ticket_identity('not-ticket/003-feature'))
        linked = self.repo / '.worktrees/ticket-115--feature'
        self.git('worktree', 'add', '-b', 'ticket/096-feature', str(linked))
        row = next(r for r in self.scan()['projects'][0]['checkouts'] if r['path'] == str(linked))
        self.assertEqual(row['ticket'], 'ticket-096')
        self.assertTrue(row['ticket_identity_conflict'])
        self.assertEqual(row['readiness'], 'inspect errors')

    def test_descendant_agent_association_uses_deepest_checkout(self):
        linked = self.repo / '.worktrees/ticket-022--child'
        self.git('worktree', 'add', '-b', 'ticket/022-child', str(linked))
        agent = dict(pid=123, cwd=str(self.root), working_directories=[str(self.root), str(linked)])
        with patch('monag.resume.processes', return_value=([agent], 0)):
            rows = resume.scan(self.root)['projects'][0]['checkouts']
        self.assertEqual(next(r for r in rows if r['path'] == str(self.repo))['agent_pids'], [])
        row = next(r for r in rows if r['path'] == str(linked))
        self.assertEqual(row['agent_pids'], [123])
        self.assertEqual(row['readiness'], 'agent present')

    def test_intent_and_lease_identity_evidence_is_preserved(self):
        linked = self.repo / '.worktrees/ticket-022--identity'
        self.git('worktree', 'add', '-b', 'ticket/022-identity', str(linked))
        intent = linked / 'project/ticket-022/intent.json'
        intent.parent.mkdir(parents=True)
        intent.write_text(json.dumps({'ticket': 'ticket-023', 'delivery': {'complexity': 'S'}}))
        lease = self.repo / '.subactor/leases' / (linked.name + '.json')
        lease.parent.mkdir(parents=True)
        lease.write_text(json.dumps({'schema': 'wellmanifest.change-lease/v1',
                                     'phase': 'editing', 'ticketId': 'ticket-024'}))
        row = next(r for r in self.scan()['projects'][0]['checkouts'] if r['path'] == str(linked))
        self.assertEqual(row['ticket_identities'], dict(branch='ticket-022', path='ticket-022',
                                                       intent='ticket-023', lease='ticket-024'))
        self.assertEqual(row['intent_ticket'], 'ticket-023')
        self.assertEqual(row['lease_ticket'], 'ticket-024')
        self.assertTrue(row['ticket_identity_conflict'])
        self.assertEqual(row['readiness'], 'inspect errors')
        self.assertIsNone(resume.ticket_identity({'ticket': 'ticket-023'}))

    def test_planfile_priorities_are_preserved_and_ranked(self):
        sprint = self.repo / '.planfile/sprints'
        sprint.mkdir(parents=True)
        (sprint / 'current.yaml').write_text(
            'sprint:\n  tickets:\n'
            '    LOW:\n      status: open\n      priority: low\n'
            '    HIGH:\n      status: open\n      priority: high\n'
            '    MISSING:\n      status: open\n')
        items, _, errors = resume.planfile(self.repo)
        self.assertFalse(errors)
        priorities = {item['id']: item['priority'] for item in items}
        self.assertEqual(priorities, {'LOW': 'low', 'HIGH': 'high', 'MISSING': 'unknown'})
        summary = resume.summarize_tickets(items)
        self.assertEqual(summary['highest_priority'], 'high')
        self.assertEqual([row['id'] for row in summary['remaining_tickets']], ['HIGH', 'LOW', 'MISSING'])
        self.assertEqual(summary['priority_counts']['unknown'], 1)

    def test_github_import_fields_and_incomplete_evidence_are_explicit(self):
        sprint = self.repo / '.planfile/sprints'
        sprint.mkdir(parents=True)
        (sprint / 'current.yaml').write_text(
            'sprint:\n  tickets:\n'
            '    GITHUB-16:\n'
            '      id: GITHUB-16\n'
            '      name: Imported defect\n'
            '      status: open\n'
            '      priority: high\n'
            '      labels: [bug, importer]\n'
            '      backend: github\n'
            '      external_id: "16"\n'
            '      sync:\n        github:\n          id: "16"\n'
            '    GITHUB-17:\n'
            '      name: Incomplete import\n'
            '      status: open\n'
            '      labels: [bug]\n')

        items, _, errors = resume.planfile(self.repo)
        imported = next(item for item in items if item['id'] == 'GITHUB-16')
        incomplete = next(item for item in items if item['id'] == 'GITHUB-17')
        self.assertEqual(imported['priority'], 'high')
        self.assertEqual(imported['labels'], ['bug', 'importer'])
        self.assertEqual(imported['github'], '16')
        self.assertEqual(incomplete['labels'], ['bug'])
        self.assertEqual(incomplete['import_evidence'], [
            'missing inline id', 'missing priority', 'missing sync.github mapping'])
        self.assertTrue(any('GITHUB-17: missing inline id' in error for error in errors))
        self.assertTrue(any('GITHUB-17: missing priority' in error for error in errors))
        self.assertTrue(any('GITHUB-17: missing sync.github mapping' in error for error in errors))

    def test_github_import_read_is_idempotent(self):
        sprint = self.repo / '.planfile/sprints'
        sprint.mkdir(parents=True)
        source = sprint / 'current.yaml'
        source.write_text(
            'sprint:\n  tickets:\n    GITHUB-16:\n'
            '      id: GITHUB-16\n      status: open\n'
            '      priority: high\n      labels: [bug]\n'
            '      external_id: "16"\n      backend: github\n'
            '      sync:\n        github:\n          id: "16"\n')
        before = source.read_bytes()
        first = resume.planfile(self.repo)
        second = resume.planfile(self.repo)
        self.assertEqual(first, second)
        self.assertEqual(source.read_bytes(), before)

    def test_priority_conflict_and_filter_remain_explicit(self):
        items = [
            {'id': 'A', 'status': 'open', 'priority': 'low'},
            {'id': 'A', 'status': 'open', 'priority': 'high'},
            {'id': 'B', 'status': 'open', 'priority': 'normal'},
        ]
        result = resume.summarize_tickets(items, ['high'])
        self.assertEqual(result['remaining_ids'], ['A'])
        self.assertEqual(result['highest_priority'], 'high')
        self.assertEqual(result['priority_conflicts'], 1)
        self.assertTrue(result['remaining_tickets'][0]['priority_conflict'])

    def test_markdown_shows_planfile_priority_and_open_tickets(self):
        sprint = self.repo / '.planfile/sprints'
        sprint.mkdir(parents=True)
        (sprint / 'current.yaml').write_text(
            'sprint:\n  tickets:\n'
            '    HIGH:\n      name: Urgent repair\n      status: open\n      priority: high\n')
        document = resume.markdown(self.scan(), all_projects=True)
        self.assertIn('Najwyższy priorytet', document)
        self.assertIn('Otwarte tickety Planfile', document)
        self.assertIn('Urgent repair', document)
        self.assertIn('high', document)

    def test_resume_cli_priority_filter_and_sort(self):
        sprint = self.repo / '.planfile/sprints'
        sprint.mkdir(parents=True)
        (sprint / 'current.yaml').write_text(
            'sprint:\n  tickets:\n'
            '    HIGH:\n      status: open\n      priority: high\n'
            '    LOW:\n      status: open\n      priority: low\n')
        from io import StringIO
        from monag.cli import main
        stream = StringIO()
        with patch('sys.stdout', stream), patch('monag.resume.processes', return_value=([], 0)):
            code = main(['--root', str(self.root), '--json', 'resume', '--sort', 'priority', '--priority', 'high'])
        self.assertEqual(code, 0)
        payload = json.loads(stream.getvalue())
        self.assertEqual(payload['priority_filter'], ['high'])
        self.assertEqual(payload['projects'][0]['planfile']['remaining_ids'], ['HIGH'])
        self.assertIn('ranking priorytetów', resume.markdown(payload, all_projects=True))
        self.assertIn('Filtr priorytetów Planfile: **high**', resume.markdown(payload, all_projects=True))

    def test_missing_and_malformed_planfile(self):
        self.assertFalse(self.scan()['projects'][0]['planfile']['available'])
        (self.repo / 'tickets.planfile.yaml').write_text('tickets: [broken')
        data = self.scan()['projects'][0]
        self.assertTrue(data['errors'])
        self.assertTrue(data['planfile']['available'])

    def test_commits_ahead_and_clean_merged_checkout(self):
        linked = self.root / 'outside-linked'
        self.git('worktree', 'add', '-b', 'ticket/003-feature', str(linked))
        (linked / 'new').write_text('new')
        self.git('add', 'new', cwd=linked)
        self.git('commit', '-m', 'feature', cwd=linked)
        data = self.scan()['projects'][0]
        row = next(r for r in data['checkouts'] if r['path'] == str(linked))
        self.assertEqual(row['ahead'], 1)
        self.assertTrue(row['unfinished'])
        self.git('update-ref', 'refs/remotes/origin/main', row['head'])
        row = next(r for r in self.scan()['projects'][0]['checkouts'] if r['path'] == str(linked))
        self.assertFalse(row['unfinished'])

    def test_deduplicate_primary_found_via_linked(self):
        linked = self.root / 'other' / 'clone'
        linked.parent.mkdir()
        self.git('worktree', 'add', '-b', 'ticket/004-feature', str(linked))
        self.assertEqual(self.scan()['project_count'], 1)

    def test_agent_and_lease_do_not_authorize_resume(self):
        (self.repo / 'dirty').write_text('x')
        with patch('monag.resume.processes', return_value=([{'pid': 123, 'cwd': str(self.repo)}], 0)):
            row = resume.scan(self.root)['projects'][0]['checkouts'][0]
        self.assertEqual(row['readiness'], 'agent present')
        self.assertIn('potwierdź dopuszczenie', row['prompt'])

    def test_markdown_includes_uncertainty_and_scope(self):
        document = resume.markdown(self.scan(), all_projects=True)
        self.assertIn('brak danych', document)
        self.assertIn('nie zgodą', document)
        self.assertIn('nie procent ukończenia', document)

    def test_no_remote_base_is_unknown_not_clean(self):
        self.git('update-ref', '-d', 'refs/remotes/origin/main')
        row = self.scan()['projects'][0]['checkouts'][0]
        self.assertIsNone(row['ahead'])
        self.assertEqual(row['stage'], 'unknown')

    def test_tracking_only_started_stage(self):
        self.git('checkout', '-b', 'ticket/005-start')
        (self.repo / 'project/ticket-005').mkdir(parents=True)
        (self.repo / 'project/ticket-005/intent.json').write_text('{}')
        row = self.scan()['projects'][0]['checkouts'][0]
        self.assertEqual(row['stage'], 'started (tracking changes only)')

    def test_unreadable_backlog_not_reported_as_complete_zero(self):
        (self.repo / 'tickets.planfile.yaml').write_text('tickets: [broken')
        data = self.scan()
        self.assertFalse(data['projects'][0]['planfile']['complete'])
        self.assertIn('niepełne', resume.markdown(data, all_projects=True))

    def test_resume_cli_json_does_not_record_or_run_agent(self):
        from io import StringIO
        from monag.cli import main
        stream = StringIO()
        with patch('sys.stdout', stream), patch('monag.resume.processes', return_value=([], 0)), patch('monag.cli.history.record') as record:
            code = main(['--root', str(self.root), '--json', 'resume'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stream.getvalue())['schema'], 'monag.resume/v1')
        record.assert_not_called()

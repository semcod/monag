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

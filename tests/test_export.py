import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

from monag import export
from monag.monitor import command as real_command


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def git(self, repo, *args):
        subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.DEVNULL, text=True)

    def make_repo(self, relative, remote=None):
        repo = self.root / relative
        repo.mkdir(parents=True)
        self.git(repo, 'init', '-b', 'main')
        self.git(repo, 'config', 'user.email', 'test@example.invalid')
        self.git(repo, 'config', 'user.name', 'Test')
        (repo / '.keep').write_text('base')
        self.git(repo, 'add', '.keep')
        self.git(repo, 'commit', '-m', 'base')
        self.git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
        if remote:
            self.git(repo, 'remote', 'add', 'origin', remote)
        return repo

    def write_sprint(self, repo, name, tickets):
        sprints = repo / '.planfile' / 'sprints'
        sprints.mkdir(parents=True, exist_ok=True)
        (sprints / name).write_text(yaml.safe_dump({'sprint': {'tickets': tickets}}))

    def fake_gh(self, responses):
        def fake(args, cwd=None, timeout=8):
            if args[:3] == ['gh', 'repo', 'view']:
                repo = args[3]
                return responses.get(f'{repo}:metadata', ('{"isFork": false}', None))
            if args[:1] == ['gh']:
                repo = args[args.index('--repo') + 1]
                return responses.get(repo, ('[]', None))
            return real_command(args, cwd=cwd, timeout=timeout)
        return fake

    def test_untracked_issue_and_undescribed_repo_become_candidates(self):
        repo = self.make_repo('org/demo', remote='git@github.com:org/demo.git')
        self.write_sprint(repo, 'current.yaml', {
            'PLF-001': {'status': 'open', 'name': 'Mapped', 'priority': 'high',
                       'sync': {'github': {'id': '10'}}},
        })
        issues = json.dumps([
            {'number': 10, 'title': 'Mapped issue', 'state': 'OPEN'},
            {'number': 11, 'title': 'Untracked issue', 'state': 'OPEN', 'url': 'https://x/11'},
        ])
        with patch('monag.audit.command', side_effect=self.fake_gh({'org/demo': (issues, None)})), \
             patch('monag.catalog.command', side_effect=self.fake_gh({'org/demo': (issues, None)})):
            data = export.scan(repo)
        origins = {c['origin'] for c in data['candidates']}
        self.assertIn('audit-untracked-issue', origins)
        self.assertIn('catalog-undescribed', origins)  # no pyproject/package.json/README paragraph
        untracked = next(c for c in data['candidates'] if c['origin'] == 'audit-untracked-issue')
        self.assertEqual(untracked['title'], 'Untracked issue')
        self.assertEqual(untracked['url'], 'https://x/11')
        self.assertEqual(untracked['priority'], 'unknown')  # never invented

    def test_mapped_ticket_is_not_a_candidate_but_appears_as_context(self):
        repo = self.make_repo('org/demo', remote='git@github.com:org/demo.git')
        self.write_sprint(repo, 'current.yaml', {
            'PLF-001': {'status': 'open', 'name': 'Mapped', 'priority': 'high',
                       'sync': {'github': {'id': '10'}}},
        })
        issues = json.dumps([{'number': 10, 'title': 'Mapped issue', 'state': 'OPEN'}])
        with patch('monag.audit.command', side_effect=self.fake_gh({'org/demo': (issues, None)})), \
             patch('monag.catalog.command', side_effect=self.fake_gh({'org/demo': (issues, None)})):
            data = export.scan(repo)
        self.assertEqual([c for c in data['candidates'] if c['origin'] == 'audit-untracked-issue'], [])
        self.assertEqual(data['existing_open_ticket_count'], 1)
        self.assertEqual(data['existing_open_tickets'][0]['id'], 'PLF-001')
        self.assertEqual(data['existing_open_tickets'][0]['priority'], 'high')

    def test_closed_untracked_issue_is_not_a_work_candidate(self):
        repo = self.make_repo('org/demo', remote='git@github.com:org/demo.git')
        issues = json.dumps([{'number': 9, 'title': 'Old, resolved', 'state': 'CLOSED'}])
        with patch('monag.audit.command', side_effect=self.fake_gh({'org/demo': (issues, None)})), \
             patch('monag.catalog.command', side_effect=self.fake_gh({'org/demo': (issues, None)})):
            data = export.scan(repo)
        self.assertEqual([c for c in data['candidates'] if c['origin'] == 'audit-untracked-issue'], [])

    def test_described_repository_is_not_a_catalog_candidate(self):
        repo = self.make_repo('org/demo')
        (repo / 'pyproject.toml').write_text('[project]\nname = "demo"\ndescription = "Has a description"\n')
        data = export.scan(repo)
        self.assertEqual([c for c in data['candidates'] if c['origin'] == 'catalog-undescribed'], [])

    def test_radar_defaults_off_and_leaves_no_radar_key(self):
        repo = self.make_repo('org/demo', remote='git@github.com:org/demo.git')
        issues = json.dumps([{'number': 11, 'title': 'Untracked', 'state': 'OPEN'}])
        with patch('monag.audit.command', side_effect=self.fake_gh({'org/demo': (issues, None)})), \
             patch('monag.catalog.command', side_effect=self.fake_gh({'org/demo': (issues, None)})):
            data = export.scan(repo)
        self.assertFalse(data['radar_requested'])
        self.assertEqual(data['radar_errors'], [])
        candidate = next(c for c in data['candidates'] if c['origin'] == 'audit-untracked-issue')
        self.assertNotIn('radar', candidate)

    def test_radar_sizes_candidates_when_available(self):
        repo = self.make_repo('org/demo', remote='git@github.com:org/demo.git')
        issues = json.dumps([{'number': 11, 'title': 'Untracked', 'state': 'OPEN'}])
        bundle = json.dumps({'jsonl': json.dumps({
            'complexity': 'S', 'score': 20,
            'estimate': {'minutes': 15, 'within_budget': True},
            'diagnostics': [], 'split': {'recommended': False}})})
        with patch('monag.audit.command', side_effect=self.fake_gh({'org/demo': (issues, None)})), \
             patch('monag.catalog.command', side_effect=self.fake_gh({'org/demo': (issues, None)})), \
             patch('monag.export.radar_available', return_value=True), \
             patch('monag.export.run_radar', return_value=(bundle, None)):
            data = export.scan(repo, radar=True)
        self.assertTrue(data['radar_requested'])
        self.assertEqual(data['radar_errors'], [])
        candidate = next(c for c in data['candidates'] if c['origin'] == 'audit-untracked-issue')
        self.assertEqual(candidate['radar'], {
            'complexity': 'S', 'score': 20, 'estimated_minutes': 15,
            'within_budget': True, 'diagnostics': [], 'split_recommended': False})

    def test_radar_missing_binary_leaves_candidates_unsized_not_guessed(self):
        repo = self.make_repo('org/demo', remote='git@github.com:org/demo.git')
        issues = json.dumps([{'number': 11, 'title': 'Untracked', 'state': 'OPEN'}])
        with patch('monag.audit.command', side_effect=self.fake_gh({'org/demo': (issues, None)})), \
             patch('monag.catalog.command', side_effect=self.fake_gh({'org/demo': (issues, None)})), \
             patch('monag.export.radar_available', return_value=False):
            data = export.scan(repo, radar=True)
        self.assertTrue(data['radar_requested'])
        self.assertEqual(len(data['radar_errors']), 1)
        self.assertIn('not found on PATH', data['radar_errors'][0])
        candidate = next(c for c in data['candidates'] if c['origin'] == 'audit-untracked-issue')
        self.assertNotIn('radar', candidate)

    def test_radar_per_candidate_failure_is_explicit_not_silent(self):
        repo = self.make_repo('org/demo', remote='git@github.com:org/demo.git')
        (repo / 'pyproject.toml').write_text('[project]\nname = "demo"\ndescription = "Has one"\n')
        issues = json.dumps([{'number': 11, 'title': 'Untracked', 'state': 'OPEN'}])
        with patch('monag.audit.command', side_effect=self.fake_gh({'org/demo': (issues, None)})), \
             patch('monag.catalog.command', side_effect=self.fake_gh({'org/demo': (issues, None)})), \
             patch('monag.export.radar_available', return_value=True), \
             patch('monag.export.run_radar', return_value=(None, 'ticket-radar: TimeoutExpired')):
            data = export.scan(repo, radar=True)
        self.assertEqual(len(data['radar_errors']), 1)
        candidate = next(c for c in data['candidates'] if c['origin'] == 'audit-untracked-issue')
        self.assertIsNone(candidate['radar'])

    def test_markdown_renders_radar_column_and_unsized_fallback(self):
        repo = self.make_repo('org/demo', remote='git@github.com:org/demo.git')
        issues = json.dumps([{'number': 11, 'title': 'Untracked', 'state': 'OPEN'}])
        with patch('monag.audit.command', side_effect=self.fake_gh({'org/demo': (issues, None)})), \
             patch('monag.catalog.command', side_effect=self.fake_gh({'org/demo': (issues, None)})), \
             patch('monag.export.radar_available', return_value=False):
            data = export.scan(repo, radar=True)
        text = export.markdown(data)
        self.assertIn('unsized', text)
        self.assertIn('Radar unavailable for', text)

    def fake_taskill(self, responses):
        def fake(args, cwd=None, timeout=8):
            if args[:2] == ['taskill', 'status']:
                path = args[2]
                return responses.get(path, ('{"would_run": false, "reasons": []}', None))
            return real_command(args, cwd=cwd, timeout=timeout)
        return fake

    def test_hygiene_defaults_off(self):
        repo = self.make_repo('org/demo')
        data = export.scan(repo)
        self.assertFalse(data['hygiene_requested'])
        self.assertEqual(data['hygiene_errors'], [])
        self.assertEqual([c for c in data['candidates'] if c['origin'] == 'taskill-doc-drift'], [])

    def test_hygiene_adds_candidate_when_taskill_would_run(self):
        repo = self.make_repo('org/demo', remote='git@github.com:org/demo.git')
        status = json.dumps({'would_run': True, 'reasons': ['50 new commit(s)', 'README.md touched']})
        with patch('monag.export.taskill_available', return_value=True), \
             patch('monag.export.command', side_effect=self.fake_taskill({str(repo): (status, None)})):
            data = export.scan(repo, hygiene=True)
        self.assertTrue(data['hygiene_requested'])
        self.assertEqual(data['hygiene_errors'], [])
        found = next(c for c in data['candidates'] if c['origin'] == 'taskill-doc-drift')
        self.assertIn('50 new commit(s)', found['evidence'])
        self.assertIn('README.md touched', found['evidence'])
        self.assertEqual(found['priority'], 'unknown')

    def test_hygiene_skips_repo_when_taskill_says_clean(self):
        repo = self.make_repo('org/demo', remote='git@github.com:org/demo.git')
        status = json.dumps({'would_run': False, 'reasons': []})
        with patch('monag.export.taskill_available', return_value=True), \
             patch('monag.export.command', side_effect=self.fake_taskill({str(repo): (status, None)})):
            data = export.scan(repo, hygiene=True)
        self.assertEqual([c for c in data['candidates'] if c['origin'] == 'taskill-doc-drift'], [])

    def test_hygiene_missing_binary_records_error_not_silent(self):
        repo = self.make_repo('org/demo', remote='git@github.com:org/demo.git')
        with patch('monag.export.taskill_available', return_value=False):
            data = export.scan(repo, hygiene=True)
        self.assertEqual(len(data['hygiene_errors']), 1)
        self.assertIn('not found on PATH', data['hygiene_errors'][0])
        self.assertEqual([c for c in data['candidates'] if c['origin'] == 'taskill-doc-drift'], [])

    def test_markdown_renders_without_crashing_and_states_nothing_is_created(self):
        repo = self.make_repo('org/demo')
        data = export.scan(repo)
        text = export.markdown(data)
        self.assertIn('candidate work export', text)
        self.assertIn('creates, imports or claims nothing', text)


if __name__ == '__main__':
    unittest.main()

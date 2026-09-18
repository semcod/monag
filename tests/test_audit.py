from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

from monag import audit
from monag.monitor import command as real_command


class AuditTests(unittest.TestCase):
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
        (repo / 'README').write_text('base')
        self.git(repo, 'add', 'README')
        self.git(repo, 'commit', '-m', 'base')
        self.git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
        if remote:
            self.git(repo, 'remote', 'add', 'origin', remote)
        return repo

    def write_sprint(self, repo, name, tickets):
        sprints = repo / '.planfile' / 'sprints'
        sprints.mkdir(parents=True, exist_ok=True)
        (sprints / name).write_text(yaml.safe_dump({'sprint': {'tickets': tickets}}))

    def write_sync(self, repo, mapping):
        sync = repo / '.planfile' / 'sync'
        sync.mkdir(parents=True, exist_ok=True)
        (sync / 'github.state.yaml').write_text(yaml.safe_dump({'ticket_map': mapping}))

    def fake_gh(self, responses):
        # Only `gh` calls are faked; every `git` call goes to the real, local repos.
        def fake(args, cwd=None, timeout=8):
            if args[:3] == ['gh', 'repo', 'view']:
                repo = args[3]
                return responses.get(f'{repo}:metadata', ('{"isFork": false}', None))
            if args[:1] == ['gh']:
                repo = args[args.index('--repo') + 1]
                return responses.get(repo, ('[]', None))
            return real_command(args, cwd=cwd, timeout=timeout)
        return fake

    def test_single_repository_mode_reports_untracked_issue(self):
        repo = self.make_repo('org/demo', remote='git@github.com:org/demo.git')
        self.write_sprint(repo, 'current.yaml', {
            'PLF-001': {'status': 'open', 'name': 'Mapped', 'sync': {'github': {'id': '10'}}},
        })
        issues = json.dumps([
            {'number': 10, 'title': 'Mapped issue', 'state': 'OPEN'},
            {'number': 11, 'title': 'Untracked issue', 'state': 'OPEN'},
        ])
        with patch('monag.audit.command', side_effect=self.fake_gh({'org/demo': (issues, None)})):
            data = audit.scan(repo)
        self.assertEqual(data['mode'], 'repository')
        self.assertEqual(data['repository_count'], 1)
        r = data['repositories'][0]
        self.assertEqual(r['repo'], 'org/demo')
        self.assertEqual(r['ticket_count'], 1)
        self.assertEqual(r['mapped_ticket_count'], 1)
        self.assertEqual([i['number'] for i in r['untracked_issues']], [11])
        self.assertEqual(r['orphan_tickets'], [])
        self.assertEqual(data['total_untracked_issues'], 1)

    def test_fork_repository_is_ignored_before_issue_query(self):
        repo = self.make_repo('org/fork', remote='git@github.com:org/fork.git')
        calls = []

        def fake(args, cwd=None, timeout=8):
            calls.append(args)
            if args[:3] == ['gh', 'repo', 'view']:
                return '{"isFork": true}', None
            if args[:3] == ['gh', 'issue', 'list']:
                self.fail('a confirmed fork must not be queried for Issues')
            return real_command(args, cwd=cwd, timeout=timeout)

        with patch('monag.audit.command', side_effect=fake):
            data = audit.scan(repo)
        self.assertEqual(data['repository_count'], 0)
        self.assertEqual(data['ignored_fork_count'], 1)
        self.assertEqual(data['ignored_forks'], [{'path': str(repo), 'repo': 'org/fork'}])
        self.assertEqual([call[:3] for call in calls if call[:1] == ['gh']],
                         [['gh', 'repo', 'view']])

    def test_fork_metadata_failure_does_not_query_issues(self):
        repo = self.make_repo('org/unknown', remote='git@github.com:org/unknown.git')
        calls = []

        def fake(args, cwd=None, timeout=8):
            calls.append(args)
            if args[:3] == ['gh', 'repo', 'view']:
                return '', 'gh: metadata unavailable'
            if args[:3] == ['gh', 'issue', 'list']:
                self.fail('unknown fork metadata must not fall through to Issue listing')
            return real_command(args, cwd=cwd, timeout=timeout)

        with patch('monag.audit.command', side_effect=fake):
            data = audit.scan(repo)
        report = data['repositories'][0]
        self.assertIsNone(report['is_fork'])
        self.assertIsNone(report['github_issue_count'])
        self.assertTrue(report['github_errors'])
        self.assertEqual(data['ignored_fork_count'], 0)
        self.assertEqual([call[:3] for call in calls if call[:1] == ['gh']],
                         [['gh', 'repo', 'view']])

    def test_malformed_fork_metadata_is_unknown_without_issue_query(self):
        repo = self.make_repo('org/malformed', remote='git@github.com:org/malformed.git')
        calls = []

        def fake(args, cwd=None, timeout=8):
            calls.append(args)
            if args[:3] == ['gh', 'repo', 'view']:
                return '{"isFork": "unknown"}', None
            if args[:3] == ['gh', 'issue', 'list']:
                self.fail('malformed fork metadata must not fall through to Issue listing')
            return real_command(args, cwd=cwd, timeout=timeout)

        with patch('monag.audit.command', side_effect=fake):
            report = audit.scan(repo)['repositories'][0]
        self.assertIsNone(report['is_fork'])
        self.assertIsNone(report['github_issue_count'])
        self.assertIn('invalid gh repository metadata JSON', report['github_errors'][0])
        self.assertEqual([call[:3] for call in calls if call[:1] == ['gh']],
                         [['gh', 'repo', 'view']])

    def test_workspace_mode_discovers_every_repository_under_root(self):
        self.make_repo('org/one', remote='git@github.com:org/one.git')
        self.make_repo('org/two')  # no remote: GitHub side stays unknown, not zero
        with patch('monag.audit.command', side_effect=self.fake_gh({'org/one': ('[]', None)})):
            data = audit.scan(self.root)
        self.assertEqual(data['mode'], 'workspace')
        self.assertEqual(data['repository_count'], 2)
        by_name = {Path(r['path']).name: r for r in data['repositories']}
        self.assertEqual(by_name['one']['repo'], 'org/one')
        self.assertIsNone(by_name['two']['repo'])
        self.assertIsNone(by_name['two']['github_issue_count'])

    def test_sync_index_drift_and_orphan_ticket_are_both_visible(self):
        repo = self.make_repo('org/demo', remote='git@github.com:org/demo.git')
        self.write_sprint(repo, 'current.yaml', {
            'PLF-001': {'status': 'open', 'name': 'Real, but stale in the global index',
                       'sync': {'github': {'id': '5'}}},
            'PLF-002': {'status': 'open', 'name': 'Mapped to a missing issue', 'external_id': '99'},
        })
        self.write_sync(repo, {'PLF-001': '999'})  # global index disagrees with the ticket's own mapping
        issues = json.dumps([{'number': 5, 'title': 'Real issue', 'state': 'OPEN'}])
        with patch('monag.audit.command', side_effect=self.fake_gh({'org/demo': (issues, None)})):
            data = audit.scan(repo)
        r = data['repositories'][0]
        self.assertEqual(r['sync_drift'], [
            {'id': 'PLF-001', 'github': '5', 'in_sync_index': False},
            {'id': 'PLF-002', 'github': '99', 'in_sync_index': False},
        ])
        self.assertEqual(r['orphan_tickets'], [{'id': 'PLF-002', 'github': '99'}])

    def test_missing_sync_index_file_is_not_reported_as_drift(self):
        repo = self.make_repo('org/demo', remote='git@github.com:org/demo.git')
        self.write_sprint(repo, 'current.yaml', {
            'PLF-001': {'status': 'open', 'name': 'Mapped', 'sync': {'github': {'id': '5'}}},
        })
        issues = json.dumps([{'number': 5, 'title': 'Real issue', 'state': 'OPEN'}])
        with patch('monag.audit.command', side_effect=self.fake_gh({'org/demo': (issues, None)})):
            data = audit.scan(repo)
        self.assertEqual(data['repositories'][0]['sync_drift'], [])

    def test_missing_planfile_and_failed_gh_call_stay_explicit_not_zero(self):
        repo = self.make_repo('org/demo', remote='git@github.com:org/demo.git')
        with patch('monag.audit.command', side_effect=self.fake_gh({'org/demo': ('', 'gh: not authenticated')})):
            data = audit.scan(repo)
        r = data['repositories'][0]
        self.assertFalse(r['planfile_available'])
        self.assertIsNone(r['github_issue_count'])
        self.assertTrue(r['github_errors'])
        self.assertEqual(r['untracked_issues'], [])
        self.assertEqual(r['orphan_tickets'], [])

    def test_custom_named_sprint_files_are_all_read(self):
        repo = self.make_repo('org/demo')
        self.write_sprint(repo, 'current.yaml', {'PLF-001': {'status': 'open', 'name': 'A'}})
        self.write_sprint(repo, 'wellmanifest-audit-20260915.yaml', {'PLF-002': {'status': 'open', 'name': 'B'}})
        from monag.resume import planfile
        items, sources, errors = planfile(repo)
        self.assertFalse(errors)
        self.assertEqual({i['id'] for i in items}, {'PLF-001', 'PLF-002'})
        self.assertEqual(len(sources), 2)

    def test_recent_window_filters_issues_by_updated_at(self):
        repo = self.make_repo('org/demo', remote='git@github.com:org/demo.git')
        now = datetime.now(timezone.utc)
        issues = json.dumps([
            {'number': 1, 'title': 'Fresh', 'state': 'OPEN',
             'updatedAt': (now - timedelta(minutes=30)).isoformat()},
            {'number': 2, 'title': 'Stale', 'state': 'CLOSED',
             'updatedAt': (now - timedelta(hours=3)).isoformat()},
            {'number': 3, 'title': 'No timestamp', 'state': 'OPEN'},
            {'number': 4, 'title': 'Bad timestamp', 'state': 'OPEN', 'updatedAt': 'soon'},
        ])
        with patch('monag.audit.command', side_effect=self.fake_gh({'org/demo': (issues, None)})):
            data = audit.scan(repo, recent_hours=1)
        r = data['repositories'][0]
        self.assertEqual([i['number'] for i in r['recent_issues']], [1])
        self.assertEqual(data['total_recent_issues'], 1)
        self.assertEqual(data['recent_hours'], 1)

    def test_recent_window_off_leaves_recent_fields_empty(self):
        repo = self.make_repo('org/demo', remote='git@github.com:org/demo.git')
        now = datetime.now(timezone.utc)
        issues = json.dumps([{'number': 1, 'title': 'Fresh', 'state': 'OPEN',
                              'updatedAt': now.isoformat()}])
        with patch('monag.audit.command', side_effect=self.fake_gh({'org/demo': (issues, None)})):
            data = audit.scan(repo)
        self.assertEqual(data['repositories'][0]['recent_issues'], [])
        self.assertIsNone(data['total_recent_issues'])
        self.assertIsNone(data['recent_hours'])

    def test_markdown_renders_recent_section_when_window_set(self):
        repo = self.make_repo('org/demo', remote='git@github.com:org/demo.git')
        now = datetime.now(timezone.utc)
        issues = json.dumps([{'number': 7, 'title': 'Just now', 'state': 'OPEN',
                              'updatedAt': now.isoformat()}])
        with patch('monag.audit.command', side_effect=self.fake_gh({'org/demo': (issues, None)})):
            data = audit.scan(repo, recent_hours=1)
        text = audit.markdown(data)
        self.assertIn('updated in the last 1 h', text)
        self.assertIn('#7', text)
        self.assertIn('Updated', text)

    def test_markdown_renders_every_section_without_crashing(self):
        repo = self.make_repo('org/demo', remote='git@github.com:org/demo.git')
        self.write_sprint(repo, 'current.yaml', {'PLF-001': {'status': 'open', 'name': 'A'}})
        issues = json.dumps([{'number': 1, 'title': 'X', 'state': 'OPEN'}])
        with patch('monag.audit.command', side_effect=self.fake_gh({'org/demo': (issues, None)})):
            data = audit.scan(repo)
        text = audit.markdown(data)
        self.assertIn('Planfile / GitHub coverage audit', text)
        self.assertIn('org/demo', text)
        self.assertIn('ignored GitHub forks', text)


if __name__ == '__main__':
    unittest.main()

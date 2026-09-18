from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from monag import prs
from monag.cli import main
from monag.monitor import command as real_command


class Output(StringIO):
    def __init__(self, terminal):
        super().__init__()
        self.terminal = terminal

    def isatty(self):
        return self.terminal


class PrsTests(unittest.TestCase):
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
        (repo / '.gitignore').write_text('/.worktrees/\n')
        self.git(repo, 'add', '.gitignore')
        (repo / 'README').write_text('base')
        self.git(repo, 'add', 'README')
        self.git(repo, 'commit', '-m', 'base commit')
        self.git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
        if remote:
            self.git(repo, 'remote', 'add', 'origin', remote)
        return repo

    def test_inspect_branches_detects_ahead_and_clean_branches(self):
        repo = self.make_repo('org/repo1', remote='git@github.com:org/repo1.git')
        # Create a branch with a commit ahead of main
        self.git(repo, 'checkout', '-b', 'feature-ahead')
        (repo / 'FEATURE').write_text('feature content')
        self.git(repo, 'add', 'FEATURE')
        self.git(repo, 'commit', '-m', 'feat: add feature')

        # Create a branch at main (0 commits ahead)
        self.git(repo, 'checkout', 'main')
        self.git(repo, 'checkout', '-b', 'feature-clean')

        branches, current, errors = prs.inspect_branches(repo)
        self.assertEqual(errors, [])
        self.assertEqual(current, 'feature-clean')
        branch_map = {b['name']: b for b in branches}

        self.assertIn('main', branch_map)
        self.assertIn('feature-ahead', branch_map)
        self.assertIn('feature-clean', branch_map)

        self.assertGreater(branch_map['feature-ahead']['ahead'], 0)
        self.assertEqual(branch_map['feature-clean']['ahead'], 0)

    def test_inspect_working_tree_clean_and_dirty(self):
        repo = self.make_repo('org/repo_dirty')
        clean, dirty_files, errors = prs.inspect_working_tree(repo)
        self.assertTrue(clean)
        self.assertEqual(dirty_files, [])

        (repo / 'dirty.txt').write_text('uncommitted')
        clean, dirty_files, errors = prs.inspect_working_tree(repo)
        self.assertFalse(clean)
        self.assertIn('?? dirty.txt', dirty_files)

    def test_scan_with_open_and_merged_prs(self):
        repo = self.make_repo('org/repo2', remote='git@github.com:org/repo2.git')
        # Create branch for open PR
        self.git(repo, 'checkout', '-b', 'branch-open')
        (repo / 'FILE1').write_text('1')
        self.git(repo, 'add', 'FILE1')
        self.git(repo, 'commit', '-m', 'feat: open pr commit')

        # Checkout main and create clean branch
        self.git(repo, 'checkout', 'main')

        now = datetime.now(timezone.utc)
        recent_iso = (now - timedelta(hours=1)).isoformat()

        fake_prs = [
            {
                'number': 101, 'title': 'PR 101 Open', 'state': 'OPEN',
                'url': 'https://github.com/org/repo2/pull/101',
                'headRefName': 'branch-open', 'baseRefName': 'main',
                'createdAt': recent_iso, 'updatedAt': recent_iso,
                'author': {'login': 'dev1'}
            },
            {
                'number': 102, 'title': 'PR 102 Merged', 'state': 'MERGED',
                'url': 'https://github.com/org/repo2/pull/102',
                'headRefName': 'branch-merged', 'baseRefName': 'main',
                'createdAt': recent_iso, 'updatedAt': recent_iso,
                'mergedAt': recent_iso,
                'author': {'login': 'dev2'}
            }
        ]

        def fake_cmd(args, cwd=None, timeout=25):
            if args[:3] == ['gh', 'pr', 'list']:
                return json.dumps(fake_prs), None
            return real_command(args, cwd=cwd, timeout=timeout)

        with patch('monag.prs.command', side_effect=fake_cmd):
            data = prs.scan(repo, hours=24.0)

        self.assertEqual(data['total_open_prs'], 1)
        self.assertEqual(data['open_prs'][0]['number'], 101)
        self.assertEqual(data['total_merged_prs'], 1)
        self.assertEqual(data['merged_prs'][0]['number'], 102)
        self.assertFalse(data['all_merged'])

        md = prs.markdown(data)
        self.assertIn('ACTIVE UNMERGED WORK', md)
        self.assertIn('## Open GitHub Pull Requests', md)
        self.assertIn('#101', md)
        self.assertIn('## Merged Pull Requests', md)
        self.assertIn('#102', md)

    def test_scan_all_merged_verdict(self):
        repo = self.make_repo('org/repo3', remote='git@github.com:org/repo3.git')
        now = datetime.now(timezone.utc)
        recent_iso = (now - timedelta(hours=2)).isoformat()

        fake_prs = [
            {
                'number': 201, 'title': 'Already Merged PR', 'state': 'MERGED',
                'url': 'https://github.com/org/repo3/pull/201',
                'headRefName': 'ticket/001', 'baseRefName': 'main',
                'createdAt': recent_iso, 'mergedAt': recent_iso,
                'updatedAt': recent_iso,
                'author': {'login': 'tom'}
            }
        ]

        def fake_cmd(args, cwd=None, timeout=25):
            if args[:3] == ['gh', 'pr', 'list']:
                return json.dumps(fake_prs), None
            return real_command(args, cwd=cwd, timeout=timeout)

        with patch('monag.prs.command', side_effect=fake_cmd):
            data = prs.scan(repo, hours=24.0)

        self.assertTrue(data['all_merged'])
        self.assertEqual(data['total_open_prs'], 0)
        self.assertEqual(data['total_merged_prs'], 1)
        self.assertEqual(data['total_unpushed_branches'], 0)

        md = prs.markdown(data)
        self.assertIn('ALL MERGED', md)
        self.assertIn('Already Merged PR', md)

    def test_cli_prs_dispatch_plain_and_json(self):
        repo = self.make_repo('org/repo4', remote='git@github.com:org/repo4.git')

        def fake_cmd(args, cwd=None, timeout=25):
            if args[:3] == ['gh', 'pr', 'list']:
                return '[]', None
            return real_command(args, cwd=cwd, timeout=timeout)

        # Test plain output
        stdout_plain = Output(False)
        with patch('monag.prs.command', side_effect=fake_cmd), patch('sys.stdout', stdout_plain):
            code = main(['--plain', '--root', str(repo), 'prs'])
            self.assertEqual(code, 0)
        self.assertIn('MONAG — Pull Requests & Unpushed Branches Audit', stdout_plain.getvalue())
        self.assertIn('ALL MERGED', stdout_plain.getvalue())

        # Test json output
        stdout_json = Output(False)
        with patch('monag.prs.command', side_effect=fake_cmd), patch('sys.stdout', stdout_json):
            code = main(['--json', '--root', str(repo), 'prs'])
            self.assertEqual(code, 0)
        payload = json.loads(stdout_json.getvalue())
        self.assertEqual(payload['schema'], prs.SCHEMA)
        self.assertTrue(payload['all_merged'])


if __name__ == '__main__':
    unittest.main()

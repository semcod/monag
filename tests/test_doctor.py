from pathlib import Path
import subprocess
import tempfile
import unittest

from monag.doctor import diagnose, find_git_repositories, audit_worktrees, audit_merged_branches
from monag.cli import main


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def git(self, repo, *args):
        return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.DEVNULL, text=True)

    def make_repo(self, relative):
        repo = self.root / relative
        repo.mkdir(parents=True)
        self.git(repo, 'init', '-b', 'main')
        self.git(repo, 'config', 'user.email', 'test@example.invalid')
        self.git(repo, 'config', 'user.name', 'Test')
        (repo / 'README.md').write_text('init\n')
        self.git(repo, 'add', 'README.md')
        self.git(repo, 'commit', '-m', 'initial')
        return repo

    def test_diagnose_basic(self):
        data = diagnose(self.root)
        self.assertIn('python', data)
        self.assertIn('git', data)
        self.assertIn('ecosystem_tools', data)
        self.assertFalse(data['fix_mode'])
        self.assertEqual(data['errors'], [])

    def test_find_git_repositories(self):
        repo1 = self.make_repo('org/repo1')
        repo2 = self.make_repo('org/repo2')
        repos = find_git_repositories(self.root)
        self.assertEqual(len(repos), 2)
        self.assertIn(repo1, repos)
        self.assertIn(repo2, repos)

    def test_stale_worktree_detection_and_fix(self):
        repo = self.make_repo('service-a')
        
        # Create a ticket branch and linked worktree
        wt_dir = repo / '.worktrees' / 'ticket-101'
        self.git(repo, 'worktree', 'add', '-b', 'ticket/101-feature', str(wt_dir), 'main')
        
        # Commit in worktree
        (wt_dir / 'feature.txt').write_text('feature\n')
        self.git(wt_dir, 'add', 'feature.txt')
        self.git(wt_dir, 'commit', '-m', 'add feature')
        
        # Merge ticket branch into main
        self.git(repo, 'merge', 'ticket/101-feature')
        
        # Diagnose without fix
        diag = diagnose(repo, fix=False)
        self.assertEqual(diag['worktrees_audited'], 1)
        self.assertEqual(diag['stale_worktrees_detected'], 1)
        self.assertFalse(diag['fix_mode'])
        self.assertTrue(wt_dir.exists())

        # Diagnose with fix
        diag_fixed = diagnose(repo, fix=True)
        self.assertTrue(diag_fixed['fix_mode'])
        self.assertEqual(diag_fixed['remediated_worktrees'], 1)
        self.assertEqual(diag_fixed['remediated_branches'], 1)
        self.assertFalse(wt_dir.exists())

        # Verify worktrees and merged branches are clean after single-pass fix
        wts_after = audit_worktrees(repo)
        self.assertEqual(len([w for w in wts_after if not w.get('is_primary')]), 0)
        self.assertEqual(len(audit_merged_branches(repo)), 0)

    def test_discover_broken_gitdir_handling(self):
        from monag.monitor import discover
        # Create a broken linked worktree directory pointing to non-existent gitdir
        broken_dir = self.root / 'broken-worktree'
        broken_dir.mkdir(parents=True)
        (broken_dir / '.git').write_text('gitdir: /nonexistent/path/worktrees/broken\n')

        # Create a stray empty .git folder
        stray_dir = self.root / 'stray-git'
        (stray_dir / '.git').mkdir(parents=True)

        found, errors = discover(self.root)
        self.assertEqual(errors, [])
        self.assertNotIn(broken_dir, found)
        self.assertNotIn(stray_dir, found)

    def test_cli_doctor_fix_invocation(self):
        repo = self.make_repo('service-b')
        code = main(['doctor', '--root', str(repo), '--json'])
        self.assertEqual(code, 0)

        code_fix = main(['doctor', '--root', str(repo), '--fix'])
        self.assertEqual(code_fix, 0)


if __name__ == '__main__':
    unittest.main()

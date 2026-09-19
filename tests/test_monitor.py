import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from monag.cli import render, safe
from monag.monitor import agent_name, command, discover, github_repo, inspect_repo, parse_status, processes, snapshot, task_records


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def git(self, path, *args):
        p = subprocess.run(['git', '-C', str(path), *args], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def repo(self):
        path = self.root / 'org/repo'
        path.mkdir(parents=True)
        self.git(path, 'init', '-b', 'main')
        self.git(path, 'config', 'user.name', 'Test')
        self.git(path, 'config', 'user.email', 'test@example.invalid')
        (path / 'file.txt').write_text('initial')
        self.git(path, 'add', '.')
        self.git(path, 'commit', '-m', 'initial')
        return path

    def fake_process(self, proc, pid, parent, argv, cwd, start='123'):
        p = proc / str(pid)
        p.mkdir(parents=True)
        fields = ['S', str(parent)] + ['0'] * 17 + [start]
        (p / 'stat').write_text(f'{pid} (name with ) spaces) ' + ' '.join(fields))
        (p / 'cmdline').write_bytes('\0'.join(argv).encode() + b'\0')
        (p / 'cwd').symlink_to(cwd)

    def test_agent_detection_ignores_prompts_and_shells(self):
        self.assertEqual(agent_name(['node', '/tools/codex.js']), 'codex')
        self.assertEqual(agent_name(['/bin/claude', 'secret prompt']), 'claude')
        self.assertIsNone(agent_name(['bash', '-c', 'codex']))
        self.assertIsNone(agent_name(['python', 'script.py', 'claude']))

    def test_processes_collapse_launcher_keep_parallel_agents(self):
        proc = self.root / 'proc'
        cwd = self.root / 'workspace'
        cwd.mkdir()
        self.fake_process(proc, 10, 1, ['node', '/x/codex.js'], cwd)
        self.fake_process(proc, 11, 10, ['/x/codex'], cwd)
        self.fake_process(proc, 20, 1, ['/x/codex'], cwd)
        self.fake_process(proc, 30, 1, ['bash', '-c', 'claude'], cwd)
        rows, denied = processes(cwd, proc)
        self.assertEqual({r['pid'] for r in rows}, {10, 20})
        self.assertEqual(denied, 0)
        self.assertNotIn('argv', rows[0])

    def test_git_scan_includes_hidden_linked_checkout_and_changed_files(self):
        repo = self.repo()
        worktree = repo / '.worktrees/ticket-001--test'
        self.git(repo, 'worktree', 'add', '--relative-paths', '-b', 'ticket/001-test', str(worktree))
        (worktree / 'file.txt').write_text('changed')
        (worktree / 'new\nfile.txt').write_text('new')
        paths, errors = discover(self.root)
        self.assertEqual(set(paths), {repo, worktree})
        row = inspect_repo(worktree, '2000-01-01')
        self.assertEqual({f['path'] for f in row['files']}, {'file.txt', 'new\nfile.txt'})
        self.assertEqual(row['commits'][0]['subject'], 'initial')
        self.assertEqual(row['recent_committed_files'], ['file.txt'])
        self.assertFalse(errors)

    def test_invalid_git_marker_does_not_hide_descendant_repositories(self):
        repo = self.repo()
        (self.root / '.git').mkdir()
        paths, errors = discover(self.root)
        self.assertIn(repo, paths)
        self.assertNotIn(self.root, paths)
        self.assertTrue(errors)

    def test_unborn_repository_preserves_branch_and_changes_without_git_errors(self):
        repo = self.root / 'empty'
        repo.mkdir()
        self.git(repo, 'init', '-b', 'main')
        (repo / 'new.txt').write_text('new')
        row = inspect_repo(repo, '2000-01-01')
        self.assertEqual(row['head_state'], 'unborn')
        self.assertEqual(row['branch'], 'main')
        self.assertEqual(row['commits'], [])
        self.assertEqual(row['errors'], [])
        self.assertEqual([r['path'] for r in row['files']], ['new.txt'])

    def test_command_failure_preserves_safe_operation_context(self):
        from monag.monitor import command
        _, error = command(['git', 'status', '--short'], self.root)
        self.assertIn('git status failed', error)

    def test_status_rename_and_deleted_file(self):
        files = parse_status('R  target\0source\0 D deleted\0', self.root)
        self.assertEqual(files[0]['previous_path'], 'source')
        self.assertEqual(files[1]['path'], 'deleted')

    def test_remote_parsing(self):
        for remote in ['git@github.com:semcod/monag.git', 'https://github.com/semcod/monag', 'ssh://git@github.com/semcod/monag.git']:
            self.assertEqual(github_repo(remote), 'semcod/monag')
        self.assertIsNone(github_repo('https://token@github.com/a/b'))
        self.assertIsNone(github_repo('https://github.com.evil/a/b'))

    def test_no_terminal_escape_in_rendered_untrusted_text(self):
        self.assertNotIn('\x1b', safe('\x1b[2Jdanger\n'))

    def test_run_records_exit_and_task_without_command_arguments(self):
        state = self.root / 'state'
        cmd = [sys.executable, '-m', 'monag', '--state-dir', str(state), 'run', '--task', 'task description', '--issue', '42', '--', sys.executable, '-c', 'raise SystemExit(7)']
        p = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(p.returncode, 7, p.stderr)
        row = json.loads(next((state / 'tasks').glob('*.json')).read_text())
        self.assertEqual(row['status'], 'failed')
        self.assertEqual(row['issue'], '42')
        self.assertNotIn('SystemExit', json.dumps(row))

    def test_pid_reuse_marks_task_stale(self):
        proc = self.root / 'proc'
        self.fake_process(proc, 20, 1, ['claude'], self.root, start='new')
        state = self.root / 'state/tasks'
        state.mkdir(parents=True)
        (state / 'task.json').write_text(json.dumps(dict(pid=20, start='old', cwd=str(self.root), task='work', status='running', updated=1)))
        self.assertEqual(task_records(state.parent, self.root, proc)[0]['status'], 'stale')

    def test_github_cache_survives_watch_refresh_and_reports_errors(self):
        repo = self.repo()
        self.git(repo, 'remote', 'add', 'origin', 'git@github.com:semcod/monag.git')
        cache = {}
        with patch('monag.monitor.github_activity', return_value=([], ['gh unavailable'])) as fetch:
            a = snapshot(self.root, self.root / 'state', since='2026-09-14T01:00:00', github=True, cache=cache)
            snapshot(self.root, self.root / 'state', since='2026-09-14T01:00:05', github=True, cache=cache)
        self.assertEqual(fetch.call_count, 1)
        self.assertIn('gh unavailable', a['errors'])

    def test_nested_worktree_process_is_not_counted_in_primary(self):
        repo = self.repo()
        wt = repo / '.worktrees/ticket-002--task'
        self.git(repo, 'worktree', 'add', '--relative-paths', '-b', 'ticket/002-task', str(wt))
        agents = [dict(pid=1, start='1', kind='codex', cwd=str(wt), state='S', children=0, task='unknown'),
                  dict(pid=2, start='2', kind='claude', cwd=str(wt), state='S', children=0, task='unknown')]
        with patch('monag.monitor.processes', return_value=(agents, 0)):
            data = snapshot(self.root, self.root / 'state')
        counts = {r['path']: len(r['agents']) for r in data['repositories']}
        self.assertEqual(counts[str(repo)], 0)
        self.assertEqual(counts[str(wt)], 2)
        self.assertIn('MULTIPLE AGENTS', render(data))
        self.assertEqual(render(data).count('initial'), 1)

    def test_report_deduplicates_identical_gaps_but_keeps_distinct_operations(self):
        repo = self.repo()
        data = snapshot(self.root, self.root / 'state')
        error = f'{repo}: git log failed (exit 128)'
        data['errors'] = [error, error, f'{repo}: git status failed (exit 128)']
        data['repositories'][0]['errors'] = ['git log failed (exit 128)']
        from monag.presentation import markdown
        rendered = markdown(data)
        self.assertEqual(rendered.count('git log failed'), 1)
        self.assertEqual(rendered.count('git status failed'), 1)

    def test_watch_refresh_reuses_recent_scan_and_inspects_new_agent_checkout(self):
        repo = self.repo()
        deep = self.root / 'a/b/c'
        deep.mkdir(parents=True)
        self.git(deep, 'init', '-b', 'main')
        agent = dict(pid=999999999, start='9', kind='codex', cwd=str(deep), state='S', children=0, task='unknown')
        cache = {}
        with patch('monag.monitor.REFRESH_FACTOR', 10**6), patch('monag.monitor.SAMPLE_SECONDS', 0), \
             patch('monag.monitor.processes', side_effect=[([], 0), ([agent], 0)]), \
             patch('monag.monitor.discover', wraps=discover) as scans, \
             patch('monag.monitor.inspect_repo', wraps=inspect_repo) as inspections:
            first = snapshot(self.root, self.root / 'state', cache=cache)
            second = snapshot(self.root, self.root / 'state', cache=cache)
        self.assertEqual(scans.call_count, 1)
        self.assertEqual(inspections.call_count, 2)
        self.assertEqual([r['path'] for r in first['repositories']], [str(repo)])
        self.assertEqual(second['repositories'][0]['agents'], [999999999])
        self.assertEqual(first['repositories'][0].get('agents'), [])

    def test_git_environment_does_not_redirect_scan(self):
        repo = self.repo()
        with patch.dict(os.environ, {'GIT_DIR': '/nonexistent'}):
            out, error = command(['git', 'rev-parse', '--show-toplevel'], repo)
        self.assertEqual(out.strip(), str(repo))
        self.assertIsNone(error)

    def test_invalid_interval_is_rejected(self):
        p = subprocess.run([sys.executable, '-m', 'monag', 'watch', '--interval', 'nan'], capture_output=True)
        self.assertEqual(p.returncode, 2)


if __name__ == '__main__':
    unittest.main()

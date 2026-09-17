import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from monag.agents import aliases, identify
from monag.history import record, read
from monag.monitor import activity, processes, snapshot, task_records


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def process(self, pid, parent, argv, cwd=None, start='100'):
        path = self.root / 'proc' / str(pid)
        path.mkdir(parents=True)
        fields = ['S', str(parent)] + ['0'] * 17 + [start]
        (path / 'stat').write_text(f'{pid} (process) ' + ' '.join(fields))
        (path / 'cmdline').write_bytes('\0'.join(argv).encode() + b'\0')
        (path / 'cwd').symlink_to(cwd or self.root)
        return path

    def data(self):
        return dict(root=str(self.root), boot_id='boot1', inaccessible_processes=0,
                    agents=[dict(pid=42, start='100', kind='claude', cwd=str(self.root), task='unknown',
                                 uid=1000, descendants=[])], repositories=[], github=[], tasks=[])

    def test_native_child_is_a_separate_agent(self):
        self.process(1, 0, ['codex'])
        self.process(2, 1, ['codex'])
        self.process(3, 2, ['bash'])
        self.process(4, 3, ['git'])
        agents, _ = processes(self.root, self.root / 'proc')
        self.assertEqual([a['pid'] for a in agents], [1, 2])
        self.assertEqual(agents[0]['children'], 0)
        self.assertEqual({p['pid'] for p in agents[1]['descendants']}, {3, 4})

    def test_child_checkout_is_attributed_to_its_agent(self):
        first, second = self.root / 'one', self.root / 'two'
        first.mkdir(); second.mkdir()
        a = dict(pid=1, start='1', cwd=str(first), kind='codex', task='unknown',
                 working_directories=[str(first), str(second)])
        def inspect(path, since):
            return dict(path=str(path), agents=[], errors=[], activity=0, github=None,
                        files=[], commits=[], common_dir=str(path / '.git'))
        with patch('monag.monitor.processes', return_value=([a], 0)), \
             patch('monag.monitor.discover', return_value=([first, second], [])), \
             patch('monag.monitor.inspect_repo', side_effect=inspect):
            d = snapshot(self.root, self.root / 'state')
        self.assertEqual([r['agents'] for r in d['repositories']], [[1], [1]])

    def test_machine_mode_detects_outside_root_and_deleted_cwd(self):
        self.process(1, 0, ['claude'], cwd=self.root.parent)
        self.process(2, 0, ['codex'], cwd=self.root / 'deleted')
        agents, _ = processes(self.root, self.root / 'proc')
        self.assertEqual(agents, [])
        agents, _ = processes(self.root, self.root / 'proc', machine=True)
        self.assertEqual(len(agents), 2)
        self.assertIsNone(agents[1]['cwd'])

    def test_custom_script_and_runtime_detection(self):
        registry = aliases(['my-agent=worker'])
        self.assertEqual(identify(['python3.13', '/x/worker.py'], registry), ('my-agent', True))
        self.assertEqual(identify(['node', '/x/@anthropic-ai/claude-code/cli.js'])[0], 'claude')
        self.assertIsNone(identify(['bash', '-c', 'claude'])[0])
        self.assertIsNone(identify(['node', 'app.js', '/x/@openai/codex/cli.js'])[0])
        with self.assertRaises(ValueError):
            aliases(['agent=/usr/bin/worker'])

    def test_ide_acp_agents_and_helper_modes(self):
        self.assertEqual(identify(['/opt/devin-desktop/extensions/windsurf/devin/bin/devin', 'acp']), ('devin', False))
        self.assertEqual(identify(['node', '/x/node_modules/.bin/claude-agent-acp']), ('claude-agent-acp', True))
        self.assertEqual(identify(['node', '/x/glm-acp-agent/1.8.0/node_modules/.bin/glm-acp-agent'])[0], 'glm-acp-agent')
        self.assertIsNone(identify(['/x/claude', '--chrome-native-host'])[0])
        # A positional prompt is never interpreted as a helper subcommand.
        self.assertEqual(identify(['claude', 'login']), ('claude', False))

    def test_antigravity_and_wrapper_agent_executables(self):
        self.assertEqual(identify(['agy']), ('agy', False))
        self.assertEqual(identify(['/usr/local/bin/agy', '--dangerously-skip-permissions']), ('agy', False))
        self.assertEqual(identify(['agy-coding-agent', '--print-timeout', '35m']), ('agy-coding-agent', False))
        self.assertEqual(identify(['agy2']), ('agy2', False))
        self.assertEqual(identify(['agent']), ('agent', False))
        self.assertEqual(identify(['tiny-agents', 'run']), ('tiny-agents', False))

    def test_rewritten_electron_and_npm_titles_are_split(self):
        self.process(1, 0, ['/opt/devin-desktop/devin-desktop --type=renderer --user-data-dir=/home/u/.config/devin'])
        self.process(2, 0, ['npm exec @agentclientprotocol/claude-agent-acp@0.76.0'])
        self.process(3, 2, ['node', '/x/node_modules/.bin/claude-agent-acp'])
        agents, _ = processes(self.root, self.root / 'proc')
        self.assertEqual([(a['pid'], a['kind']) for a in agents], [(3, 'claude-agent-acp')])

    def test_cpu_includes_reaped_children_and_activity_is_not_negative(self):
        path = self.process(1, 0, ['codex'])
        fields = ['S', '0'] + ['0'] * 9 + ['100', '50', '200', '0'] + ['0'] * 4 + ['100']
        (path / 'stat').write_text('1 (codex) ' + ' '.join(fields))
        agents, _ = processes(self.root, self.root / 'proc')
        tick = os.sysconf('SC_CLK_TCK')
        self.assertAlmostEqual(agents[0]['cpu_seconds'], 350 / tick)
        now = time.monotonic()
        samples = {(1, '100'): (now - 2, 350 / tick - 1)}
        activity(agents, samples, now, self.root / 'proc')
        self.assertTrue(45 <= agents[0]['cpu_percent'] <= 51, agents[0]['cpu_percent'])
        samples[(1, '100')] = (now - 2, 1000)
        activity(agents, samples, now, self.root / 'proc')
        self.assertEqual(agents[0]['cpu_percent'], 0)

    def test_first_activity_sample_waits_and_agents_sort_by_activity_then_start(self):
        self.process(1, 0, ['codex'])
        agents, _ = processes(self.root, self.root / 'proc')
        with patch('monag.monitor.time.sleep') as sleep:
            activity(agents, {}, time.monotonic(), self.root / 'proc')
        self.assertGreater(sleep.call_args[0][0], 0)
        rows = [dict(pid=1, start='900', kind='codex', cwd=None, cpu_percent=None),
                dict(pid=2, start='100', kind='claude', cwd=None, cpu_percent=40.0),
                dict(pid=3, start='500', kind='devin', cwd=None, cpu_percent=None)]
        with patch('monag.monitor.processes', return_value=(rows, 0)):
            data = snapshot(self.root, self.root / 'state', agents_only=True)
        self.assertEqual([a['pid'] for a in data['agents']], [2, 1, 3])

    def test_open_file_paths_include_descendants_without_reading_content(self):
        p = self.process(1, 0, ['codex'])
        (p / 'fd').mkdir()
        secret = self.root / 'test.txt'
        secret.write_text('never collect these contents')
        (p / 'fd/1').symlink_to(secret)
        agents, _ = processes(self.root, self.root / 'proc', open_files=True)
        self.assertEqual(agents[0]['open_files'], [str(secret)])
        self.assertNotIn('never collect', json.dumps(agents))

    def test_concurrent_writers_do_not_duplicate_events(self):
        data = self.data()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: record(self.root, data), range(2)))
        self.assertEqual(sum(len(r) for r in results), 1)
        self.assertEqual(len(read(self.root)), 1)

    def test_history_deduplicates_and_records_pid_reuse(self):
        d = self.data()
        state = self.root / 'state'
        self.assertEqual(record(state, d)[0]['kind'], 'agent_observed')
        self.assertEqual(record(state, d), [])
        d['agents'][0]['start'] = '200'
        events = record(state, d)
        self.assertEqual({e['kind'] for e in events}, {'agent_observed', 'agent_disappeared'})
        self.assertEqual(len(read(state)), 3)
        self.assertEqual((state / 'history.sqlite3').stat().st_mode & 0o777, 0o600)

    def test_history_gaps_do_not_report_disappearance(self):
        d = self.data()
        state = self.root / 'state'
        record(state, d)
        d.update(agents=[], inaccessible_processes=1)
        self.assertEqual(record(state, d), [])
        d['inaccessible_processes'] = 0
        self.assertEqual(record(state, d)[0]['kind'], 'agent_disappeared')

    def test_history_scope_and_parameterized_search(self):
        d = self.data()
        state = self.root / 'state'
        record(state, d)
        d.update(agents=[], machine=True)
        self.assertEqual(record(state, d), [])
        self.assertEqual(read(state, search="' OR 1=1 --"), [])
        self.assertEqual(len(read(state, kind='agent_observed')), 1)

    def test_history_files_and_completion_are_not_conflated(self):
        d = self.data()
        r = dict(path='/repo', branch='main', files=[dict(path='a.py', status=' M', modified=1)],
                 commits=[], common_dir='/repo/.git', errors=[])
        d['repositories'] = [r]
        record(self.root, d)
        r['files'] = []
        events = record(self.root, d)
        self.assertEqual([e['kind'] for e in events], ['file_no_longer_dirty'])

    def test_record_task_completion_and_github_event_type(self):
        d = self.data()
        d['github'] = [dict(url='https://github.com/org/repo/pull/1', kind='pr', state='OPEN')]
        task = dict(id='task1', pid=4, start='4', task='tests', status='running')
        d['tasks'] = [task]
        events = record(self.root, d)
        self.assertIn('github_observed', [e['kind'] for e in events])
        task['status'] = 'completed'
        self.assertEqual(record(self.root, d)[0]['kind'], 'task_observed')

    def test_malformed_task_record_is_ignored(self):
        folder = self.root / 'tasks'
        folder.mkdir()
        for n, row in enumerate([[], dict(cwd=str(self.root), status='completed'), {'updated': 'bad'}]):
            (folder / f'{n}.json').write_text(json.dumps(row))
        self.assertEqual(task_records(self.root, self.root), [])

    def test_registered_unknown_process_is_detected(self):
        self.process(1, 0, ['custom-service'])
        tasks = [dict(pid=1, start='100', status='running', task='fix', agent_kind='custom')]
        agents, _ = processes(self.root, self.root / 'proc', reported=tasks)
        self.assertEqual(agents[0]['kind'], 'custom')
        self.assertEqual(agents[0]['task'], 'fix')

    def test_history_child_directory_changes_are_visible(self):
        d = self.data()
        child = dict(pid=50, start='5', executable='bash', cwd='/one')
        d['agents'][0]['descendants'] = [child]
        record(self.root, d)
        child['cwd'] = '/two'
        self.assertEqual(record(self.root, d)[0]['kind'], 'child_changed')

    def test_history_read_does_not_create_state(self):
        state = self.root / 'missing'
        self.assertEqual(read(state), [])
        self.assertFalse(state.exists())

    def test_live_wrapper_visible_for_unknown_command(self):
        state = self.root / 'state'
        env = dict(os.environ)
        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src')
        child = subprocess.Popen([sys.executable, '-m', 'monag', '--state-dir', str(state),
                                  'run', '--agent-kind', 'custom', '--task', 'integration', '--',
                                  sys.executable, '-c', 'import time; time.sleep(30)'], cwd=self.root,
                                 env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 5
            while not list((state / 'tasks').glob('*.json')) and time.monotonic() < deadline:
                time.sleep(.02)
            data = snapshot(self.root, state, agents_only=True)
            self.assertEqual(len(data['agents']), 1)
            self.assertEqual(data['agents'][0]['task'], 'integration')
        finally:
            child.terminate()
            _, err = child.communicate(timeout=5)
        self.assertEqual(child.returncode, 143, err)
        self.assertEqual(task_records(state, self.root)[0]['status'], 'failed')


if __name__ == '__main__':
    unittest.main()

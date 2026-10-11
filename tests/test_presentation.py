from io import StringIO
import json
import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from rich.console import Console
from rich.markdown import Markdown
from monag.presentation import markdown, tree, history_markdown, doctor_markdown


def sample():
    return dict(root='/workspace', observed_at='2026-09-14T20:00:00Z', agent_count=2, duration_seconds=.1,
        agents=[dict(pid=10, kind='codex', state='S', children=2, cwd='/workspace/demo', task='Fix a bug',
                     descendants=[dict(pid=11, ppid=10, executable='bash', cwd='/workspace/demo'),
                                  dict(pid=12, ppid=11, executable='git', cwd='/workspace/demo')]),
                dict(pid=20, kind='claude', state='S', children=0, cwd='/workspace/demo', task='Review', descendants=[])],
        repositories=[dict(path='/workspace/demo', branch='ticket/001-demo', agents=[10,20],
                           files=[dict(status=' M', path='app.py', modified=1)], errors=[],
                           common_dir='/workspace/demo/.git', commits=[dict(sha='a'*40, time=1, subject='Fix parser')])],
        tasks=[], github=[], errors=[], inaccessible_processes=0)


class PresentationTests(unittest.TestCase):
    def test_tables_and_real_process_hierarchy(self):
        report = markdown(sample())
        self.assertIn('| PID | Agent |', report)
        self.assertIn('MULTIPLE AGENTS', report)
        diagram = tree(sample())
        self.assertIn('│   └── bash', diagram)
        self.assertIn('│       └── git', diagram)
        self.assertIn('app', report)

    def test_render_in_narrow_terminal_respects_width_and_no_color(self):
        stream = StringIO()
        console = Console(file=stream, width=44, height=25, force_terminal=True, no_color=True, color_system=None)
        console.print(Markdown(markdown(sample())))
        result = stream.getvalue()
        self.assertIn('codex', result)
        self.assertIn('└──', result)
        self.assertNotIn('\x1b', result)
        self.assertTrue(all(len(line) <= 44 for line in result.splitlines()))

    def test_untrusted_markdown_and_terminal_controls_remain_data(self):
        data = sample()
        data['agents'][0]['task'] = '| [red](https://invalid.test) <script> **bold** \x1b[2J'
        data['agents'][0]['cwd'] = '/tmp/```/file'
        report = markdown(data)
        self.assertIn(r'\|', report)
        self.assertIn('&lt;script&gt;', report)
        self.assertNotIn('\x1b', report)
        self.assertIn('````text', report)
        out = StringIO()
        Console(file=out, width=160).print(Markdown(report))
        self.assertIn('[red](https://invalid.test)', out.getvalue())
        self.assertIn('<script>', out.getvalue())

    def test_limits_and_selected_view_are_explicit(self):
        report = markdown(sample(), limit=1, view='tree')
        self.assertNotIn('## Agents', report)
        self.assertIn('1 more agents', report)
        self.assertIn('1 more processes', report)
        self.assertNotIn('## Changed files', report)

    def test_observation_gaps_are_not_hidden_by_view_selection(self):
        data = sample()
        data['errors'] = ['gh unavailable']
        data['inaccessible_processes'] = 2
        report = markdown(data, view='tree')
        self.assertIn('gh unavailable', report)
        self.assertIn('Inaccessible processes: 2', report)

    def test_empty_history_and_diagnostics(self):
        self.assertIn('No observations', history_markdown([]))
        self.assertIn('| Check | Result |', doctor_markdown({'git':'2.51'}))

    def test_history_markdown_observation_gap_warning_and_task_telemetry(self):
        cov_gap = {
            'store_status': 'available',
            'activity_status': 'gap_detected',
            'task_telemetry_status': 'missing',
            'total_events': 12000,
            'window_hours': 24.0,
            'window_events': 0,
            'latest_observed': 100000.0,
            'latest_observed_iso': '2026-10-09T20:00:00+00:00',
            'last_sample_age_seconds': 144000.0,
            'observation_gap': True,
            'observation_gap_seconds': 57600.0,
            'metadata_churn': {'file_events': 11700, 'total': 11700}
        }
        report = history_markdown([], coverage=cov_gap)
        self.assertIn('> [!WARNING] Observation gap detected', report)
        self.assertIn('> [!NOTE] Task telemetry missing', report)
        self.assertIn('11700 file transitions', report)

    def test_history_markdown_rich_task_correlation(self):
        events = [{
            'observed': 100000.0,
            'kind': 'task_observed',
            'task': {
                'task': 'Implement Ticket-111',
                'status': 'completed',
                'outcome': 'completed',
                'ticket': 'ticket-111',
                'attempt': 1,
                'sha': '6dd35febc1234567890abcdef1234567890abcdef',
                'execution_duration_seconds': 12.3,
                'queue_duration_seconds': 1.5,
                'receipt': 'hash:abc1234',
                'pid': 1234,
                'cwd': '/repo'
            }
        }]
        cov_ok = {
            'store_status': 'available',
            'activity_status': 'active',
            'task_telemetry_status': 'available',
            'total_events': 1,
            'window_hours': 24.0,
            'window_events': 1,
            'latest_observed': 100000.0,
            'latest_observed_iso': '2026-10-11T12:00:00+00:00',
            'last_sample_age_seconds': 60.0,
            'observation_gap': False,
            'observation_gap_seconds': 0,
            'metadata_churn': {'file_events': 0, 'total': 0}
        }
        report = history_markdown(events, coverage=cov_ok)
        self.assertIn('ticket\\-111', report)
        self.assertIn('6dd35feb', report)
        self.assertIn('outcome: completed', report)

    def test_cli_export_is_markdown_and_json_remains_parseable(self):
        with tempfile.TemporaryDirectory() as root:
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
            cmd = [sys.executable, '-m', 'monag', '--root', root, '--agents-only']
            result = subprocess.run(cmd + ['--markdown', 'status'], capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout.startswith('# MONAG'))
            self.assertNotIn('\x1b', result.stdout)
            result = subprocess.run(cmd + ['--json', 'status'], capture_output=True, text=True, env=env)
            self.assertIn('agents', json.loads(result.stdout))
            result = subprocess.run(cmd + ['--json', '--markdown', 'status'], capture_output=True, env=env)
            self.assertEqual(result.returncode, 2)

    def test_live_terminal_restores_screen_after_interrupt(self):
        with tempfile.TemporaryDirectory() as root:
            master, slave = pty.openpty()
            env = dict(os.environ, TERM='xterm-256color', COLUMNS='100', LINES='30',
                       PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
            child = subprocess.Popen([sys.executable, '-m', 'monag', '--root', root,
                                      '--agents-only', '--format', 'terminal', '--view', 'tree',
                                      'watch', '--no-record', '--interval', '.2'],
                                     stdout=slave, stderr=slave, env=env)
            os.close(slave)
            chunks = b''
            try:
                deadline = time.monotonic() + 10
                while b'\x1b[?1049h' not in chunks and time.monotonic() < deadline:
                    if select.select([master], [], [], .1)[0]:
                        chunks += os.read(master, 65536)
                self.assertIn(b'\x1b[?1049h', chunks)
                child.send_signal(signal.SIGINT)
                while time.monotonic() < deadline:
                    if select.select([master], [], [], .1)[0]:
                        try:
                            more = os.read(master, 65536)
                            if not more:
                                break
                            chunks += more
                        except OSError:
                            break
                self.assertEqual(child.wait(timeout=3), 130, chunks.decode('utf-8', 'replace'))
                self.assertIn(b'\x1b[?1049l', chunks)
                self.assertNotIn(b'Traceback', chunks)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()
                os.close(master)

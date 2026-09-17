import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from monag import usage


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def fake_process(self, proc, pid, parent, argv, cwd, start='123', ticks=(100, 50, 10, 10),
                     resident_pages=250):
        p = proc / str(pid)
        p.mkdir(parents=True)
        fields = ['S', str(parent)] + ['0'] * 9 + [str(t) for t in ticks] + ['0'] * 4 + [start]
        (p / 'stat').write_text(f'{pid} (name with ) spaces) ' + ' '.join(fields))
        (p / 'statm').write_text(f'1000 {resident_pages} 0 0 0 0 0')
        (p / 'cmdline').write_bytes('\0'.join(argv).encode() + b'\0')
        (p / 'cwd').symlink_to(cwd)

    def fake_proc(self, btime=1700000000):
        proc = self.root / 'proc'
        proc.mkdir()
        (proc / 'stat').write_text(f'cpu  1 2 3\nbtime {btime}\n')
        return proc

    def ledger(self, directory, name='api-budget-github.json', **overrides):
        directory.mkdir(parents=True, exist_ok=True)
        row = {'schema': 'subactor.api-budget-state/v1', 'provider': 'github',
               'remaining': 245, 'reset_at': 1789660247,
               'last_decision': 'conserve:reserve_publication_budget:0',
               'observed_at': '2026-09-17T15:30:00Z'}
        row.update(overrides)
        (directory / name).write_text(json.dumps(row))
        return directory / name

    def test_scan_reports_tree_cpu_memory_and_uptime(self):
        proc = self.fake_proc()
        cwd = self.root / 'workspace'
        cwd.mkdir()
        self.fake_process(proc, 20, 1, ['/x/codex'], cwd)
        self.fake_process(proc, 21, 20, ['bash'], cwd, resident_pages=10)
        data = usage.scan(cwd, proc=proc)
        self.assertEqual(data['agent_count'], 1)
        agent = data['agents'][0]
        self.assertEqual(agent['pid'], 20)
        self.assertEqual(agent['kind'], 'codex')
        self.assertEqual(agent['cpu_seconds_tree'], 340 / os.sysconf('SC_CLK_TCK'))
        self.assertEqual(agent['rss_bytes'], 260 * os.sysconf('SC_PAGE_SIZE'))
        self.assertIsNotNone(agent['uptime_seconds'])

    def test_scan_sorts_agents_by_tree_cpu(self):
        proc = self.fake_proc()
        cwd = self.root / 'workspace'
        cwd.mkdir()
        self.fake_process(proc, 20, 1, ['/x/codex'], cwd, ticks=(0, 0, 0, 0))
        self.fake_process(proc, 30, 1, ['/x/claude'], cwd, ticks=(500, 0, 0, 0))
        data = usage.scan(cwd, proc=proc)
        self.assertEqual([a['pid'] for a in data['agents']], [30, 20])

    def test_ledger_directory_reads_budget_state(self):
        state = self.root / 'state'
        self.ledger(state)
        rows, errors = usage.read_ledgers(str(state))
        self.assertEqual(errors, [])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['provider'], 'github')
        self.assertEqual(row['remaining'], 245)
        self.assertEqual(row['reset_at'], 1789660247)
        self.assertIsNotNone(row['reset_in_seconds'])
        self.assertEqual(row['last_decision'], 'conserve:reserve_publication_budget:0')

    def test_ledger_rejects_foreign_json_and_missing_dir(self):
        state = self.root / 'state'
        state.mkdir()
        (state / 'api-budget-other.json').write_text('{"hello": 1}')
        rows, errors = usage.read_ledgers(str(state))
        self.assertEqual(rows, [])
        self.assertEqual(len(errors), 1)
        self.assertIn('not a subactor.api-budget-state', errors[0])
        rows, errors = usage.read_ledgers(str(self.root / 'missing'))
        self.assertEqual(rows, [])
        self.assertTrue(errors)

    def test_ledger_file_source_and_invalid_json(self):
        state = self.root / 'state'
        path = self.ledger(state, remaining=None, reset_at=None)
        rows, errors = usage.read_ledgers(str(path))
        self.assertEqual(errors, [])
        self.assertIsNone(rows[0]['remaining'])
        self.assertIsNone(rows[0]['reset_in_seconds'])
        path.write_text('not json')
        rows, errors = usage.read_ledgers(str(path))
        self.assertEqual(rows, [])
        self.assertIn('invalid JSON', errors[0])

    def test_docker_source_parses_marked_documents(self):
        payload = ('junk\n'
                   'MONAG-FILE:/app/data/pr-state/api-budget-github.json\n'
                   '{"schema": "subactor.api-budget-state/v1", "provider": "github",'
                   ' "remaining": 9, "reset_at": 1, "last_decision": "recovery:scan:1"}\n'
                   'MONAG-FILE:/app/data/pr-state/api-budget-other.json\n'
                   '{"schema": "subactor.api-budget-state/v1", "provider": "other"}\n')
        with patch('monag.usage.command', return_value=(payload, None)) as call:
            rows, errors = usage.read_ledgers('docker:ifuri-onedev-pr-coordinator-1')
        self.assertEqual(errors, [])
        self.assertEqual(call.call_args[0][0][:2], ['docker', 'exec'])
        self.assertEqual([r['provider'] for r in rows], ['github', 'other'])
        self.assertEqual(rows[0]['source'], 'docker:ifuri-onedev-pr-coordinator-1')
        self.assertEqual(rows[0]['path'], '/app/data/pr-state/api-budget-github.json')

    def test_docker_source_reports_errors_and_auto_discovers(self):
        with patch('monag.usage.command', return_value=('', 'docker failed (exit 1)')):
            rows, errors = usage.read_ledgers('docker:gone')
        self.assertEqual(rows, [])
        self.assertIn('docker:gone', errors[0])
        calls = []

        def fake_command(args, **kwargs):
            calls.append(args)
            if args[1] == 'ps':
                return 'ifuri-onedev-pr-coordinator-1\nother-svc\n', None
            return 'MONAG-FILE:/app/data/pr-state/api-budget-github.json\n' \
                   '{"schema": "subactor.api-budget-state/v1", "provider": "github"}\n', None

        with patch('monag.usage.command', side_effect=fake_command):
            rows, errors = usage.read_ledgers('docker:auto')
        self.assertEqual(errors, [])
        self.assertEqual(len(rows), 1)
        self.assertTrue(any(a[:3] == ['docker', 'ps', '--format'] for a in calls))
        self.assertEqual(sum(1 for a in calls if a[:2] == ['docker', 'exec']), 1)

    def test_reset_cell_and_human_formats(self):
        self.assertEqual(usage.human_bytes(None), '—')
        self.assertEqual(usage.human_bytes(3 << 30), '3.0GiB')
        self.assertEqual(usage.human_duration(90061), '1d1h')
        self.assertEqual(usage.reset_cell({'reset_in_seconds': 600}), 'in 10m0s')
        self.assertEqual(usage.reset_cell({'reset_in_seconds': -90}), 'expired 1m30s ago')
        self.assertEqual(usage.reset_cell({'reset_in_seconds': None}), '—')

    def test_markdown_and_render_contain_sections(self):
        proc = self.fake_proc()
        cwd = self.root / 'workspace'
        cwd.mkdir()
        self.fake_process(proc, 20, 1, ['/x/devin'], cwd)
        state = self.root / 'state'
        self.ledger(state)
        data = usage.scan(cwd, proc=proc, ledgers=[str(state)])
        document = usage.markdown(data)
        self.assertIn('## Agents', document)
        self.assertIn('## Account usage', document)
        self.assertIn('## Provider accounts', document)
        self.assertIn('| Provider | Account | Remaining | Balance | Renewal |', document)
        self.assertIn('monag open N[t|b|d|o|p]', document)
        text = usage.render(data)
        self.assertIn('MONAG USAGE', text)
        self.assertIn('PROVIDERS', text)
        self.assertIn('ACCOUNT', text)
        self.assertIn('BALANCE', text)
        self.assertIn('ACCOUNTS', text)
        self.assertIn('github', text)

    def test_ledger_explicit_account(self):
        proc = self.fake_proc()
        cwd = self.root / 'workspace'
        cwd.mkdir()
        state = self.root / 'state'
        self.ledger(state, account='team@example.com')
        data = usage.scan(cwd, proc=proc, ledgers=[str(state)])
        self.assertEqual(len(data['ledgers']), 1)
        self.assertEqual(data['ledgers'][0]['account'], 'team@example.com')
        text = usage.render(data)
        self.assertIn('team@example.com', text)
        doc = usage.markdown(data)
        self.assertIn('team@example\\.com', doc)

    def test_ledger_explicit_balance(self):
        proc = self.fake_proc()
        cwd = self.root / 'workspace'
        cwd.mkdir()
        state = self.root / 'state'
        self.ledger(state, balance='$10.50')
        data = usage.scan(cwd, proc=proc, ledgers=[str(state)])
        self.assertEqual(len(data['ledgers']), 1)
        self.assertEqual(data['ledgers'][0]['balance'], '$10.50')
        text = usage.render(data)
        self.assertIn('$10.50', text)
        doc = usage.markdown(data)
        self.assertIn('$10\\.50', doc)

    def test_detect_provider_account_from_home(self):
        fake_home = self.root / 'fakehome'
        fake_home.mkdir()
        # Fake .gemini/google_accounts.json
        gemini_dir = fake_home / '.gemini'
        gemini_dir.mkdir()
        (gemini_dir / 'google_accounts.json').write_text(json.dumps({'active': 'user@google.com'}))
        self.assertEqual(usage.detect_provider_account('agy', home=fake_home), 'user@google.com')

        # Fake .claude.json
        (fake_home / '.claude.json').write_text(json.dumps({
            'oauthAccount': {'emailAddress': 'user@claude.ai'}
        }))
        self.assertEqual(usage.detect_provider_account('claude', home=fake_home), 'user@claude.ai')

    def test_agents_table_shows_account_email(self):
        proc = self.fake_proc()
        cwd = self.root / 'workspace'
        cwd.mkdir()
        self.fake_process(proc, 20, 1, ['/x/claude'], cwd)
        fake_home = self.root / 'fakehome'
        fake_home.mkdir()
        (fake_home / '.claude.json').write_text(json.dumps({
            'oauthAccount': {'emailAddress': 'user@claude.ai'}
        }))
        data = usage.scan(cwd, proc=proc, ledgers=[], home=fake_home)
        self.assertEqual(data['agents'][0]['account'], 'user@claude.ai')
        self.assertIn('user@claude.ai', usage.render(data))
        self.assertIn('Account', usage.markdown(data))

    def test_agent_account_falls_back_to_ledger(self):
        proc = self.fake_proc()
        cwd = self.root / 'workspace'
        cwd.mkdir()
        self.fake_process(proc, 20, 1, ['/x/claude'], cwd)
        state = self.root / 'state'
        self.ledger(state, provider='claude', account='team@example.com')
        empty_home = self.root / 'emptyhome'
        empty_home.mkdir()
        data = usage.scan(cwd, proc=proc, ledgers=[str(state)], home=empty_home)
        self.assertEqual(data['agents'][0].get('account'), 'team@example.com')

    def test_default_ledgers_discovery(self):
        state = self.root / 'ledgers'
        self.ledger(state)
        with patch('monag.usage.DEFAULT_LEDGER_DIRS', (state,)):
            discovered = usage.default_ledgers(enabled=True, ignore_env=True)
            self.assertEqual(discovered, [str(state)])


if __name__ == '__main__':
    unittest.main()

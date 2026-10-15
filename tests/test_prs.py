from datetime import datetime, timedelta, timezone
from io import StringIO
import hashlib
import json
import os
import sys
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
    def test_normalize_rest_pr(self):
        raw_rest_open = {
            'number': 42,
            'title': 'Add feature',
            'head': {'ref': 'feature/x'},
            'base': {'ref': 'main'},
            'html_url': 'https://github.com/org/repo/pull/42',
            'draft': False,
            'state': 'open',
            'user': {'login': 'alice'},
            'updated_at': '2026-09-18T10:00:00Z',
            'created_at': '2026-09-18T09:00:00Z',
            'merged_at': None,
        }
        normalized = prs._normalize_rest_pr(raw_rest_open)
        self.assertEqual(normalized['number'], 42)
        self.assertEqual(normalized['headRefName'], 'feature/x')
        self.assertEqual(normalized['baseRefName'], 'main')
        self.assertEqual(normalized['state'], 'OPEN')
        self.assertFalse(normalized['isDraft'])
        self.assertEqual(normalized['author'], {'login': 'alice'})

        raw_rest_merged = {
            'number': 43,
            'title': 'Fix bug',
            'head': {'ref': 'fix/y'},
            'base': {'ref': 'main'},
            'html_url': 'https://github.com/org/repo/pull/43',
            'draft': False,
            'state': 'closed',
            'user': {'login': 'bob'},
            'updated_at': '2026-09-18T11:00:00Z',
            'created_at': '2026-09-18T10:00:00Z',
            'merged_at': '2026-09-18T10:30:00Z',
        }
        normalized_merged = prs._normalize_rest_pr(raw_rest_merged)
        self.assertEqual(normalized_merged['number'], 43)
        self.assertEqual(normalized_merged['state'], 'MERGED')

    def test_github_open_prs_rest_fallback_on_graphql_error(self):
        def fake_cmd(args, cwd=None, timeout=25):
            if args[:3] == ['gh', 'pr', 'list']:
                return '', 'GraphQL: API rate limit already exceeded for user ID 5669657.'
            if args[:3] == ['gh', 'api', 'repos/org/repo/pulls?state=all&per_page=100']:
                rest_payload = [
                    {
                        'number': 100,
                        'title': 'REST fallback PR',
                        'head': {'ref': 'ticket/100'},
                        'base': {'ref': 'main'},
                        'html_url': 'https://github.com/org/repo/pull/100',
                        'draft': False,
                        'state': 'open',
                        'user': {'login': 'dev'},
                        'updated_at': '2026-09-18T12:00:00Z',
                        'created_at': '2026-09-18T11:00:00Z',
                        'merged_at': None,
                    }
                ]
                return json.dumps(rest_payload), None
            return real_command(args, cwd=cwd, timeout=timeout)

        with patch('monag.prs.command', side_effect=fake_cmd):
            prs_list, errors = prs.github_open_prs('org/repo')

        self.assertEqual(errors, [])
        self.assertIsNotNone(prs_list)
        self.assertEqual(len(prs_list), 1)
        self.assertEqual(prs_list[0]['number'], 100)
        self.assertEqual(prs_list[0]['title'], 'REST fallback PR')
        self.assertEqual(prs_list[0]['state'], 'OPEN')

    def publication_fixture(self, exit_code=0):
        protected = self.root / 'protected'
        (protected / 'bin').mkdir(parents=True)
        marker = self.root / 'adapter-observation.json'
        adapter = protected / 'bin/run-local-direct-pr.sh'
        adapter.write_text(
            '#!' + sys.executable + '\nimport json,os,sys\nfrom pathlib import Path\n'
            + f'Path({str(marker)!r}).write_text(json.dumps({{"args":sys.argv[1:],'
            + '"root":os.environ.get("VALIDATOR_ROOT"),'
            + '"authorityMode":os.environ.get("DIRECT_PR_AUTHORITY_MODE"),'
            + '"unselected":"MONAG_TEST_PRIVATE_SENTINEL" in os.environ}))\n'
            + f'print("LOCAL_DIRECT_PR_REPORT path={self.root / "receipt.json"}")\n'
            + f'raise SystemExit({exit_code})\n'
        )
        adapter.chmod(0o755)
        environment = self.root / 'protected.env'
        environment.write_text(f'VALIDATOR_ROOT={protected}\n'
                               'DIRECT_PR_AUTHORITY_MODE=attested-sqlite-authority\n'
                               'MONAG_TEST_PRIVATE_SENTINEL=never-export\n')
        config = self.root / 'host-publication.json'
        config.write_text(json.dumps({'environmentFile': str(environment),
                                      'adapterSha256': hashlib.sha256(adapter.read_bytes()).hexdigest()}))
        patcher = patch.dict(os.environ, {'MONAG_PUBLICATION_CONFIG': str(config)})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop('MONAG_TEST_PRIVATE_SENTINEL', None)
        return config, adapter, marker

    def pr_observation(self, **changes):
        return json.dumps({'number': 42, 'state': 'OPEN', 'isDraft': False,
                           'headRefName': 'ticket/116-independent-publication-adapter',
                           'headRefOid': 'a' * 40, **changes})

    def test_independent_publication_binds_exact_head_and_reads_back_merge(self):
        config, adapter, marker = self.publication_fixture()
        with patch('monag.prs.command', side_effect=[(self.pr_observation(), None),
                   (self.pr_observation(state='MERGED'), None)]) as query:
            result = prs.merge_pull_request('https://github.com/maskservice/.github/pull/42')
        self.assertTrue(result['ok'])
        self.assertEqual(result['via'], 'independent-validator')
        self.assertEqual(result['head'], 'a' * 40)
        self.assertEqual(result['ticket'], 'ticket-116')
        self.assertEqual(result['receipt_path'], str(self.root / 'receipt.json'))
        observed = json.loads(marker.read_text())
        self.assertEqual(observed['args'], ['--repository', 'maskservice/.github', '--pull-request', '42',
                         '--ticket', 'ticket-116', '--expected-head-sha', 'a' * 40, '--apply', '--merge'])
        self.assertFalse(observed['unselected'])
        self.assertEqual(observed['authorityMode'], 'attested-sqlite-authority')
        self.assertEqual(observed['root'], str(adapter.parent.parent))
        self.assertTrue(all(call.args[0][:3] == ['gh', 'pr', 'view'] for call in query.call_args_list))

    def test_publication_rate_limit_never_switches_transport(self):
        self.publication_fixture()
        with patch('monag.prs.command', return_value=('', 'API rate limit exceeded')), \
                patch('monag.prs.subprocess.run') as adapter, \
                patch('monag.prs.merge_via_browser_cdp') as browser:
            result = prs.merge_pull_request('semcod/monag#42')
        self.assertEqual(result['status'], 'PR_OBSERVATION_FAILED')
        self.assertTrue(result['retry_pending'])
        adapter.assert_not_called()
        browser.assert_not_called()

    def test_adapter_refusal_preserves_blocked_result_without_fallback(self):
        config, adapter, marker = self.publication_fixture(exit_code=17)
        with patch('monag.prs.command', return_value=(self.pr_observation(), None)) as query, \
                patch('monag.prs.merge_via_browser_cdp') as browser:
            result = prs.merge_pull_request('semcod/monag#42')
        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 'PUBLICATION_BLOCKED')
        self.assertEqual(result['return_code'], 17)
        self.assertTrue(marker.exists())
        self.assertEqual(query.call_count, 1)
        browser.assert_not_called()

    def test_changed_head_is_not_reported_as_success(self):
        self.publication_fixture()
        with patch('monag.prs.command', side_effect=[(self.pr_observation(), None),
                   (self.pr_observation(state='MERGED', headRefOid='b' * 40), None)]):
            result = prs.merge_pull_request('semcod/monag#42')
        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 'HEAD_CHANGED_AFTER_PUBLICATION')

    def test_changed_adapter_bytes_cannot_execute(self):
        config, adapter, marker = self.publication_fixture()
        adapter.write_text(adapter.read_text() + '# changed\n')
        with patch('monag.prs.command') as query:
            result = prs.merge_pull_request('semcod/monag#42')
        self.assertEqual(result['status'], 'PUBLICATION_CONFIG_INVALID')
        self.assertFalse(marker.exists())
        query.assert_not_called()

    def test_bad_host_config_cannot_execute(self):
        config, adapter, marker = self.publication_fixture()
        originals = config.read_text()
        for text in ['{}', '[]', 'x' * 65537,
                     '{"environmentFile":"a","environmentFile":"b","adapterSha256":"x"}',
                     json.dumps({'environmentFile': 'relative.env', 'adapterSha256': 'a' * 64})]:
            with self.subTest(text=text[:40]), patch('monag.prs.command') as query:
                config.write_text(text)
                result = prs.merge_pull_request('semcod/monag#42')
                self.assertEqual(result['status'], 'PUBLICATION_CONFIG_INVALID')
                query.assert_not_called()
                self.assertFalse(marker.exists())
        config.write_text(originals)

    def test_symlinked_publication_inputs_cannot_execute(self):
        config, adapter, marker = self.publication_fixture()
        for target in [config, self.root / 'protected.env', adapter, adapter.parent]:
            original = target.with_name(target.name + '.original')
            target.rename(original)
            try:
                target.symlink_to(original, target_is_directory=original.is_dir())
            except OSError:
                original.rename(target)
                self.skipTest('symlinks unavailable')
            with patch('monag.prs.command') as query:
                result = prs.merge_pull_request('semcod/monag#42')
            self.assertEqual(result['status'], 'PUBLICATION_CONFIG_INVALID')
            query.assert_not_called()
            self.assertFalse(marker.exists())
            target.unlink()
            original.rename(target)

    def test_candidate_configuration_is_not_discovered(self):
        config, adapter, marker = self.publication_fixture()
        candidate = self.root / 'candidate'
        (candidate / '.config/monag').mkdir(parents=True)
        (candidate / '.config/monag/publication.json').write_bytes(config.read_bytes())
        previous = Path.cwd()
        try:
            os.chdir(candidate)
            with patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.root / 'missing-host-config')}), \
                    patch('monag.prs.command') as query:
                os.environ.pop('MONAG_PUBLICATION_CONFIG', None)
                result = prs.merge_pull_request('semcod/monag#42')
        finally:
            os.chdir(previous)
        self.assertEqual(result['status'], 'PUBLICATION_CONFIG_INVALID')
        self.assertFalse(marker.exists())
        query.assert_not_called()

    def test_personal_and_browser_overrides_never_reach_mutation(self):
        with patch('monag.prs.command') as query, patch('monag.prs.subprocess.run') as adapter, \
                patch.object(prs.BrowserCDPMerger, '_get_page_targets') as tabs:
            for override in [{'admin_bypass': True}, {'use_browser': True}, {'method': 'squash'}]:
                self.assertFalse(prs.merge_pull_request('semcod/monag#42', **override)['ok'])
            self.assertFalse(prs.merge_via_browser_cdp('https://github.com/semcod/monag/pull/42')['ok'])
            self.assertFalse(prs.BrowserCDPMerger().merge_pr_page('https://github.com/semcod/monag/pull/42')['ok'])
        query.assert_not_called()
        adapter.assert_not_called()
        tabs.assert_not_called()

    def test_ticket_mismatch_cannot_execute_adapter(self):
        self.publication_fixture()
        with patch('monag.prs.command', return_value=(self.pr_observation(), None)), \
                patch('monag.prs.subprocess.run') as adapter:
            result = prs.merge_pull_request('semcod/monag#42', ticket='ticket-999')
        self.assertEqual(result['status'], 'TICKET_HEAD_MISMATCH')
        adapter.assert_not_called()

    def test_merged_pr_still_requires_independent_historical_verification(self):
        config, adapter, marker = self.publication_fixture()
        with patch('monag.prs.command', return_value=(self.pr_observation(state='MERGED'), None)):
            result = prs.merge_pull_request('semcod/monag#42')
        self.assertTrue(marker.exists())
        self.assertTrue(result['historical'])
        self.assertEqual(result['status'], 'MERGED_VERIFIED')

    def test_explicit_planfile_ticket_reaches_independent_adapter(self):
        config, adapter, marker = self.publication_fixture()
        with patch('monag.prs.command', side_effect=[
                (self.pr_observation(headRefName='feature/legacy'), None),
                (self.pr_observation(state='MERGED'), None)]):
            result = prs.merge_pull_request('semcod/monag#42', ticket='PLF-42')
        self.assertTrue(result['ok'])
        self.assertIn('PLF-42', json.loads(marker.read_text())['args'])

    def test_cli_personal_override_fails_without_gh_or_browser(self):
        stdout = Output(False)
        with patch('monag.prs.command') as query, patch('sys.stdout', stdout):
            code = main(['--root', str(self.root), 'merge', 'semcod/monag#42', '--browser'])
        self.assertEqual(code, 1)
        query.assert_not_called()

    def test_bulk_publication_preserves_failure_exit(self):
        stdout = Output(False)
        with patch('monag.prs.scan', return_value={'open_prs': []}), \
                patch('monag.prs.merge_open_prs', return_value=[{'ok': False, 'status': 'PUBLICATION_BLOCKED'}]), \
                patch('sys.stdout', stdout):
            code = main(['--root', str(self.root), 'merge', '--all'])
        self.assertEqual(code, 1)

    def test_rate_limited_bulk_defers_remaining_without_more_requests(self):
        with patch('monag.prs.merge_pull_request', return_value={
                'ok': False, 'status': 'PR_OBSERVATION_FAILED', 'retry_pending': True}) as publish:
            results = prs.merge_open_prs([{'repo': 'semcod/monag', 'number': 42},
                                         {'repo': 'semcod/monag', 'number': 43}])
        self.assertEqual(publish.call_count, 1)
        self.assertEqual(results[1]['status'], 'PUBLICATION_DEFERRED')
        self.assertFalse(results[1]['ok'])

    def test_merge_open_prs_and_markdown(self):
        open_prs = [
            {'repo': 'semcod/monag', 'number': 56, 'url': 'https://github.com/semcod/monag/pull/56'},
            {'repo': 'semcod/planfile', 'number': 141, 'url': 'https://github.com/semcod/planfile/pull/141'},
        ]
        with patch('monag.prs.merge_pull_request') as mock_merge:
            mock_merge.side_effect = [
                {'repo': 'semcod/monag', 'number': 56, 'ok': True, 'status': 'MERGED', 'via': 'independent-validator'},
                {'repo': 'semcod/planfile', 'number': 141, 'ok': False, 'status': 'CONFLICTING', 'via': 'independent-validator', 'error': 'conflicts'},
            ]
            results = prs.merge_open_prs(open_prs)
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0]['status'], 'MERGED')
            self.assertEqual(results[1]['status'], 'CONFLICTING')

            md = prs.merge_result_markdown(results)
            self.assertIn('Pull Request Merge Report', md)
            self.assertIn('semcod/monag', md)
            self.assertIn('semcod/planfile', md)
            self.assertIn('141', md)
            self.assertIn('CONFLICTING', md)

    def test_cli_merge_subcommand(self):
        stdout = Output(False)
        with patch('monag.prs.merge_pull_request') as mock_merge, patch('sys.stdout', stdout):
            mock_merge.return_value = {
                'ok': True,
                'status': 'MERGED',
                'repo': 'semcod/monag',
                'number': 56,
                'via': 'independent-validator',
                'output': 'Merged',
            }
            code = main(['--root', str(self.root), 'merge', 'semcod/monag#56'])
            self.assertEqual(code, 0)
            mock_merge.assert_called_once_with('semcod/monag#56', ticket=None, method=None, admin_bypass=False, use_browser=False)
            self.assertIn('semcod/monag', stdout.getvalue())
            self.assertIn('56', stdout.getvalue())
            self.assertIn('MERGED', stdout.getvalue())


if __name__ == '__main__':
    unittest.main()

import io
import os
from pathlib import Path
import tempfile
import unittest

from monag import opener


def agent(pid=100, kind='agy', cwd='/work/repo', launcher=False, executable=None):
    return {'pid': pid, 'kind': kind, 'cwd': cwd, 'launcher': launcher,
            'executable': executable or kind, 'children': 0}


class PickTest(unittest.TestCase):
    def setUp(self):
        self.agents = [agent(11), agent(22, 'claude'), agent(33, 'devin')]

    def test_row_number_and_pid_reference(self):
        self.assertEqual(opener.pick(self.agents, '2')[0]['pid'], 22)
        self.assertEqual(opener.pick(self.agents, 'pid:33')[0]['pid'], 33)
        # A number beyond the row count still resolves a live pid.
        self.assertEqual(opener.pick(self.agents, '33')[0]['pid'], 33)

    def test_unknown_target_is_an_error(self):
        agent_row, problem = opener.pick(self.agents, '7')
        self.assertIsNone(agent_row)
        self.assertIn('no row 7', problem)
        self.assertIsNone(opener.pick(self.agents, 'bogus')[0])
        self.assertIsNone(opener.pick(self.agents, 'pid:999')[0])


class ParseTargetTest(unittest.TestCase):
    def test_bare_number_and_pid(self):
        self.assertEqual(opener.parse_target('4'), ('4', None))
        self.assertEqual(opener.parse_target('pid:22'), ('pid:22', None))

    def test_appended_and_separate_letters(self):
        self.assertEqual(opener.parse_target('4t'), ('4', 't'))
        self.assertEqual(opener.parse_target('4 t'), ('4', 't'))
        self.assertEqual(opener.parse_target('pid:22b'), ('pid:22', 'b'))
        self.assertEqual(opener.parse_target('4 browser'), ('4', 'browser'))

    def test_unparseable_reference_passes_through(self):
        self.assertEqual(opener.parse_target('bogus'), ('bogus', None))


class ResolveActionTest(unittest.TestCase):
    def test_letters_and_names(self):
        self.assertEqual(opener.resolve_action('t')[0], 'terminal')
        self.assertEqual(opener.resolve_action('b')[0], 'browser')
        self.assertEqual(opener.resolve_action('w')[0], 'browser')
        self.assertEqual(opener.resolve_action('d')[0], 'desktop')
        self.assertEqual(opener.resolve_action('o')[0], 'files')
        self.assertEqual(opener.resolve_action('f')[0], 'files')
        self.assertEqual(opener.resolve_action('p')[0], 'print')
        self.assertEqual(opener.resolve_action('browser')[0], 'browser')

    def test_defaults_and_unknown(self):
        self.assertEqual(opener.resolve_action(None)[0], 'terminal')
        self.assertEqual(opener.resolve_action(None, browser=True)[0], 'browser')
        action, problem = opener.resolve_action('x')
        self.assertIsNone(action)
        self.assertIn('unknown action', problem)


class RecipeTest(unittest.TestCase):
    def test_terminal_recipes(self):
        self.assertEqual(opener.recipe(agent(kind='agy'))[0], ['agy', '--continue'])
        self.assertEqual(opener.recipe(agent(kind='claude'))[0], ['claude', '--continue'])
        self.assertEqual(opener.recipe(agent(kind='cursor-agent'))[0],
                         ['cursor-agent', '--continue'])
        self.assertEqual(opener.recipe(agent(kind='codex'))[0], ['codex', 'resume'])

    def test_desktop_and_browser_routes(self):
        self.assertEqual(opener.recipe(agent(kind='devin'))[0], ['devin', 'desktop'])
        self.assertEqual(opener.recipe(agent(kind='devin'), action='desktop')[0],
                         ['devin', 'desktop'])
        self.assertEqual(opener.recipe(agent(kind='opencode'), action='browser')[0],
                         ['opencode', 'web'])
        argv, problem = opener.recipe(agent(kind='agy'), action='browser')
        self.assertIsNone(argv)
        self.assertIn('no browser route', problem)
        argv, problem = opener.recipe(agent(kind='agy'), action='desktop')
        self.assertIsNone(argv)
        self.assertIn('no desktop route', problem)

    def test_acp_adapter_is_never_respawned(self):
        argv, problem = opener.recipe(agent(kind='claude-agent-acp',
                                          executable='claude-agent-acp'))
        self.assertIsNone(argv)
        self.assertIn('IDE-managed', problem)

    def test_unknown_kinds_fall_back_or_report(self):
        self.assertEqual(opener.recipe(agent(kind='gemini', executable='gemini'))[0],
                         ['gemini'])
        argv, problem = opener.recipe(agent(kind='custom-llm', executable='node',
                                            launcher=True))
        self.assertIsNone(argv)
        self.assertIn('no terminal recipe', problem)


class OpenAgentTest(unittest.TestCase):
    def test_dry_run_terminal_prints_cd_and_exec(self):
        ok, message = opener.open_agent(agent(), dry_run=True)
        self.assertTrue(ok)
        self.assertEqual(message, 'cd /work/repo && exec agy --continue')

    def test_dry_run_browser_prints_plain_command(self):
        ok, message = opener.open_agent(agent(kind='opencode'), action='browser',
                                        dry_run=True)
        self.assertTrue(ok)
        self.assertEqual(message, 'cd /work/repo && opencode web')

    def test_files_action_opens_directory(self):
        calls = []
        ok, message = opener.open_agent(agent(), action='files',
                                        spawn=lambda *a, **k: calls.append((a, k)))
        self.assertTrue(ok)
        self.assertEqual(calls[0][0][0], ['xdg-open', '/work/repo'])
        ok, message = opener.open_agent(agent(), action='files', dry_run=True)
        self.assertTrue(ok)
        self.assertEqual(message, 'xdg-open /work/repo')

    def test_missing_cwd_blocks_launch(self):
        ok, message = opener.open_agent(agent(cwd=None))
        self.assertFalse(ok)
        self.assertIn('working directory is unavailable', message)

    def test_terminal_launcher_env_override(self):
        argv = opener.terminal_argv('cd /x && exec y', env={'MONAG_TERMINAL': 'gnome-terminal'})
        self.assertEqual(argv[:2], ['gnome-terminal', '--'])
        self.assertIn('cd /x && exec y', argv[-1])
        argv = opener.terminal_argv('s', env={'MONAG_TERMINAL': 'my-term'})
        self.assertEqual(argv[:2], ['my-term', '-e'])

    def test_spawn_terminal_uses_discovered_launcher(self):
        calls = []
        env = {'MONAG_TERMINAL': 'gnome-terminal', 'PATH': ''}
        ok, message = opener.open_agent(agent(), env=env,
                                        spawn=lambda *a, **k: calls.append(a[0]))
        self.assertTrue(ok)
        self.assertEqual(calls[0][0], 'gnome-terminal')
        self.assertIn('opened agy pid 100', message)

    def test_no_terminal_reports_manual_command(self):
        env = {'PATH': '/nonexistent'}
        ok, message = opener.open_agent(agent(), env=env)
        self.assertFalse(ok)
        self.assertIn('no terminal emulator', message)

    def test_desktop_spawns_without_terminal(self):
        calls = []
        ok, _ = opener.open_agent(agent(kind='devin'),
                                  spawn=lambda *a, **k: calls.append((a, k)))
        self.assertTrue(ok)
        self.assertEqual(calls[0][0][0], ['devin', 'desktop'])
        self.assertEqual(calls[0][1]['cwd'], '/work/repo')

    def test_open_target_composes_pick_and_open(self):
        agents = [agent(11), agent(22, 'claude'), agent(33, 'opencode')]
        ok, message = opener.open_target(agents, '2', dry_run=True)
        self.assertTrue(ok)
        self.assertIn('claude --continue', message)
        ok, message = opener.open_target(agents, '9')
        self.assertFalse(ok)

    def test_open_target_action_letters(self):
        agents = [agent(11), agent(22, 'claude'), agent(33, 'opencode')]
        ok, message = opener.open_target(agents, '3b', dry_run=True)
        self.assertTrue(ok)
        self.assertIn('opencode web', message)
        ok, message = opener.open_target(agents, '2', action='p')
        self.assertTrue(ok)
        self.assertIn('cd /work/repo', message)
        ok, message = opener.open_target(agents, 'pid:22t', dry_run=True)
        self.assertTrue(ok)
        self.assertIn('claude --continue', message)
        ok, message = opener.open_target(agents, '1x')
        self.assertFalse(ok)
        self.assertIn('unknown action', message)
        ok, message = opener.open_target(agents, '1t', action='b')
        self.assertFalse(ok)
        self.assertIn('given twice', message)


class ChooseTest(unittest.TestCase):
    def test_choose_moves_and_picks_action(self):
        agents = [agent(11), agent(22, 'claude'), agent(33, 'opencode')]
        out = io.StringIO()
        picked, action = opener.choose(agents, stream=io.StringIO('jjb'), out=out)
        self.assertEqual(picked['pid'], 33)
        self.assertEqual(action, 'browser')
        self.assertIn('opencode', out.getvalue())

    def test_enter_uses_default_action(self):
        agents = [agent(11)]
        picked, action = opener.choose(agents, stream=io.StringIO('\r'),
                                       out=io.StringIO())
        self.assertEqual(picked['pid'], 11)
        self.assertEqual(action, 'terminal')
        _, action = opener.choose(agents, stream=io.StringIO('\r'), out=io.StringIO(),
                                  default_action='browser')
        self.assertEqual(action, 'browser')

    def test_up_wraps_to_last_row(self):
        agents = [agent(11), agent(22)]
        picked, _ = opener.choose(agents, stream=io.StringIO('k\r'), out=io.StringIO())
        self.assertEqual(picked['pid'], 22)

    def test_quit_cancels(self):
        picked, action = opener.choose([agent(11)], stream=io.StringIO('q'),
                                       out=io.StringIO())
        self.assertIsNone(picked)
        self.assertIsNone(action)

    def test_empty_list_returns_none(self):
        picked, action = opener.choose([], stream=io.StringIO(''), out=io.StringIO())
        self.assertIsNone(picked)
        self.assertIsNone(action)

    def test_open_interactive_requires_tty(self):
        ok, message = opener.open_interactive([agent(11)], stream=io.StringIO('q'))
        self.assertFalse(ok)
        self.assertIn('no row given', message)


class SessionArgvTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _fd_link(self, pid, name, target):
        fd_dir = self.root / 'proc' / str(pid) / 'fd'
        fd_dir.mkdir(parents=True, exist_ok=True)
        os.symlink(target, fd_dir / name)

    def test_agy_conversation_from_open_file(self):
        conv = ('/home/u/.gemini/antigravity-cli/conversations/'
                '6d668bd0-166c-40d7-b0bc-76a10cf5cccd.db')
        self._fd_link(100, '7', conv)
        self._fd_link(100, '8', '/dev/null')
        row = agent(pid=100, kind='agy')
        self.assertEqual(
            opener.session_argv(row, proc=self.root / 'proc'),
            ['agy', '--conversation', '6d668bd0-166c-40d7-b0bc-76a10cf5cccd'])
        self.assertEqual(
            opener.recipe(row, proc=self.root / 'proc')[0],
            ['agy', '--conversation', '6d668bd0-166c-40d7-b0bc-76a10cf5cccd'])

    def test_agy_without_conversation_falls_back(self):
        self._fd_link(100, '1', '/dev/null')
        row = agent(pid=100, kind='agy')
        self.assertIsNone(opener.session_argv(row, proc=self.root / 'proc'))
        self.assertEqual(opener.recipe(row, proc=self.root / 'proc')[0],
                         ['agy', '--continue'])

    def test_claude_newest_session_file(self):
        home = self.root / 'home'
        project = home / '.claude' / 'projects' / '-work-repo'
        project.mkdir(parents=True)
        old = project / 'aaaa-1111.jsonl'
        new = project / 'bbbb-2222.jsonl'
        old.write_text('x')
        new.write_text('x')
        os.utime(old, (1, 1))
        row = agent(kind='claude')
        self.assertEqual(opener.session_argv(row, home=home),
                         ['claude', '--resume', 'bbbb-2222'])

    def test_claude_without_project_dir_falls_back(self):
        home = self.root / 'home'
        home.mkdir()
        row = agent(kind='claude')
        self.assertIsNone(opener.session_argv(row, home=home))
        self.assertEqual(opener.recipe(row, home=home)[0],
                         ['claude', '--continue'])

    def test_other_kinds_have_no_session_probe(self):
        self.assertIsNone(opener.session_argv(agent(kind='opencode')))
        self.assertIsNone(opener.session_argv(agent(kind='devin')))


if __name__ == '__main__':
    unittest.main()

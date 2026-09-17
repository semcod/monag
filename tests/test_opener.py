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


class RecipeTest(unittest.TestCase):
    def test_terminal_recipes(self):
        self.assertEqual(opener.recipe(agent(kind='agy'))[0], ['agy', '--continue'])
        self.assertEqual(opener.recipe(agent(kind='claude'))[0], ['claude', '--continue'])
        self.assertEqual(opener.recipe(agent(kind='cursor-agent'))[0],
                         ['cursor-agent', '--continue'])
        self.assertEqual(opener.recipe(agent(kind='codex'))[0], ['codex', 'resume'])

    def test_desktop_and_browser_routes(self):
        self.assertEqual(opener.recipe(agent(kind='devin'))[0], ['devin', 'desktop'])
        self.assertEqual(opener.recipe(agent(kind='opencode'), browser=True)[0],
                         ['opencode', 'web'])
        argv, problem = opener.recipe(agent(kind='agy'), browser=True)
        self.assertIsNone(argv)
        self.assertIn('no browser route', problem)

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
        ok, message = opener.open_agent(agent(kind='opencode'), browser=True,
                                        dry_run=True)
        self.assertTrue(ok)
        self.assertEqual(message, 'cd /work/repo && opencode web')

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
        agents = [agent(11), agent(22, 'claude')]
        ok, message = opener.open_target(agents, '2', dry_run=True)
        self.assertTrue(ok)
        self.assertIn('claude --continue', message)
        ok, message = opener.open_target(agents, '9')
        self.assertFalse(ok)


if __name__ == '__main__':
    unittest.main()

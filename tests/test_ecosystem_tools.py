import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from monag import ecosystem
from monag.ecosystem import (
    audit_ecosystem_tools,
    audit_local_services,
    get_ecosystem_overview,
    render_markdown,
    render_terminal,
    ToolCapability,
    ServiceCapability,
)
from monag.cli import main


class EcosystemTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        services = [ServiceCapability('Fixture MCP', 'mcp', 'available', 'fixture', 'Local fixture')]
        fixtures = [
            patch.dict(os.environ, {'PATH': str(self.bin)}),
            patch('monag.ecosystem.shutil.which', side_effect=lambda name: str(self.bin / name)
                  if name in {'git', 'monag'} else None),
            patch('monag.ecosystem.importlib.util.find_spec', return_value=None),
            patch('monag.ecosystem.audit_local_services', return_value=services),
            patch('monag.ecosystem._check_tcp_port', return_value=False),
            patch('monag.autoupdate.check_for_updates'),
        ]
        for fixture in fixtures:
            fixture.start()
            self.addCleanup(fixture.stop)

    def test_audit_ecosystem_tools_finds_core_tools(self):
        tools = audit_ecosystem_tools()
        self.assertIn("git", tools)
        self.assertIn("monag", tools)
        self.assertIn("subllm", tools)
        self.assertIn("koru", tools)

        git_tool = tools["git"]
        self.assertIsInstance(git_tool, ToolCapability)
        self.assertTrue(git_tool.available)
        self.assertEqual(git_tool.via, "PATH")

    def test_audit_local_services(self):
        inactive = subprocess.CompletedProcess([], 3, 'inactive\n', '')
        with patch('monag.ecosystem.subprocess.run', return_value=inactive) as query, \
                patch('monag.ecosystem.os.getuid', return_value=123456789):
            services = audit_local_services()
        self.assertTrue(all(call.args[0][:3] == ['systemctl', '--user', 'is-active']
                            for call in query.call_args_list))
        self.assertIsInstance(services, list)
        for s in services:
            self.assertIsInstance(s, ServiceCapability)
            self.assertIn(s.kind, {"http", "systemd", "socket", "mcp"})

    def test_unknown_discovered_executable_never_starts(self):
        marker = self.root / 'unexpected-startup'
        executable = self.bin / 'subactor-side-effect-fixture'
        executable.write_text('#!' + sys.executable + '\nfrom pathlib import Path\n'
                              + f'Path({str(marker)!r}).touch()\n')
        executable.chmod(0o755)
        with patch.object(ecosystem, 'KNOWN_TOOLS', {}), \
                patch('monag.ecosystem.subprocess.run', wraps=subprocess.run) as launch:
            tools = audit_ecosystem_tools()
        self.assertTrue(tools[executable.name].available)
        self.assertEqual(tools[executable.name].path, str(executable))
        self.assertIsNone(tools[executable.name].version)
        self.assertFalse(marker.exists())
        launch.assert_not_called()

    def test_distribution_record_must_own_the_observed_path(self):
        owned = self.root / 'entry'
        owned.write_text('fixture')
        other = self.root / 'unrelated'
        other.write_text('fixture')
        distribution = SimpleNamespace(files=[Path('entry')], version='1.2.3',
                                       locate_file=lambda name: self.root / name)
        with patch('monag.ecosystem.importlib.metadata.distribution', return_value=distribution), \
                patch('monag.ecosystem.subprocess.run') as launch:
            self.assertEqual(ecosystem._distribution_version('fixture', str(owned)), '1.2.3')
            self.assertIsNone(ecosystem._distribution_version('fixture', str(other)))
        launch.assert_not_called()

    def test_missing_metadata_does_not_fall_back_to_executable(self):
        with patch('monag.ecosystem.importlib.metadata.distribution',
                   side_effect=ecosystem.importlib.metadata.PackageNotFoundError('fixture')), \
                patch('monag.ecosystem.subprocess.run') as launch:
            self.assertIsNone(ecosystem._distribution_version('fixture', str(self.bin / 'fixture')))
        launch.assert_not_called()

    def test_get_ecosystem_overview(self):
        overview = get_ecosystem_overview()
        self.assertIn("tools_total", overview)
        self.assertIn("tools_installed", overview)
        self.assertIn("tools_missing", overview)
        self.assertIn("services_active", overview)
        self.assertIn("tools", overview)
        self.assertIn("services", overview)
        self.assertGreater(overview["tools_total"], 20)

    def test_render_terminal_and_markdown(self):
        overview = get_ecosystem_overview()
        term = render_terminal(overview)
        self.assertIn("MONAG ECOSYSTEM", term)
        self.assertIn("INSTALLED TOOLS:", term)

        md = render_markdown(overview)
        self.assertIn("# Ecosystem Tools & API Discovery", md)
        self.assertIn("## Installed Ecosystem CLI Tools", md)

    def test_cli_tools_invocation(self):
        code_json = main(["tools", "--json"])
        self.assertEqual(code_json, 0)

        code_md = main(["tools", "--markdown"])
        self.assertEqual(code_md, 0)

        code_plain = main(["tools", "--plain"])
        self.assertEqual(code_plain, 0)

        # Test alias 'apis'
        code_apis = main(["apis", "--json"])
        self.assertEqual(code_apis, 0)


if __name__ == "__main__":
    unittest.main()

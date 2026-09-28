import unittest
from unittest.mock import patch, MagicMock

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
        services = audit_local_services()
        self.assertIsInstance(services, list)
        for s in services:
            self.assertIsInstance(s, ServiceCapability)
            self.assertIn(s.kind, {"http", "systemd", "socket", "mcp"})

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

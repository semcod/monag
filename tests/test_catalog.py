from pathlib import Path
import subprocess
import tempfile
import unittest

from monag import catalog


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def git(self, repo, *args):
        subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.DEVNULL, text=True)

    def make_repo(self, relative, remote=None, commit=True):
        repo = self.root / relative
        repo.mkdir(parents=True)
        self.git(repo, 'init', '-b', 'main')
        self.git(repo, 'config', 'user.email', 'test@example.invalid')
        self.git(repo, 'config', 'user.name', 'Test')
        if remote:
            self.git(repo, 'remote', 'add', 'origin', remote)
        if commit:
            (repo / '.keep').write_text('')
            self.git(repo, 'add', '.keep')
            self.git(repo, 'commit', '-m', 'initial commit')
        return repo

    def test_description_prefers_pyproject_over_readme(self):
        repo = self.make_repo('org/pydemo')
        (repo / 'pyproject.toml').write_text(
            '[project]\nname = "pydemo"\ndescription = "A tiny Python tool"\n')
        (repo / 'README.md').write_text('# pydemo\n\nThis would be the README paragraph.\n')
        info = catalog.describe_repo(repo)
        self.assertEqual(info['description'], 'A tiny Python tool')
        self.assertEqual(info['description_source'], 'pyproject.toml')
        self.assertIn('python', info['stacks'])

    def test_description_falls_back_to_package_json_then_readme(self):
        node_repo = self.make_repo('org/nodedemo')
        (node_repo / 'package.json').write_text('{"name": "nodedemo", "description": "A node service"}')
        info = catalog.describe_repo(node_repo)
        self.assertEqual(info['description'], 'A node service')
        self.assertEqual(info['description_source'], 'package.json')
        self.assertIn('node', info['stacks'])

        readme_repo = self.make_repo('org/readmedemo')
        (readme_repo / 'README.md').write_text(
            '# readmedemo\n\n![badge](https://example.invalid/badge.svg)\n\n'
            'Turns raw logs into a single readable timeline.\n\nMore details below.\n')
        info = catalog.describe_repo(readme_repo)
        self.assertEqual(info['description'], 'Turns raw logs into a single readable timeline.')
        self.assertEqual(info['description_source'], 'README.md')

    def test_readme_paragraph_skips_headings_badges_and_blockquotes(self):
        repo = self.make_repo('org/skipdemo')
        (repo / 'README.md').write_text(
            '# skipdemo\n\n> **skipdemo** does the thing\n\n'
            'Actually turns inputs into deterministic outputs.\n')
        info = catalog.describe_repo(repo)
        self.assertEqual(info['description'],
                         'Actually turns inputs into deterministic outputs.')

    def test_undeclared_description_is_reported_as_none_not_guessed(self):
        repo = self.make_repo('org/bare')
        info = catalog.describe_repo(repo)
        self.assertIsNone(info['description'])
        self.assertIsNone(info['description_source'])

    def test_entry_points_from_pyproject_and_package_json(self):
        repo = self.make_repo('org/tool')
        (repo / 'pyproject.toml').write_text(
            '[project]\nname = "tool"\n\n[project.scripts]\ntool = "tool.cli:main"\nother = "tool.cli:other"\n')
        info = catalog.describe_repo(repo)
        self.assertEqual(info['entry_points'], ['other', 'tool'])

    def test_docs_tests_changelog_and_last_commit_are_observed(self):
        repo = self.make_repo('org/full')
        (repo / 'docs').mkdir()
        (repo / 'tests').mkdir()
        (repo / 'CHANGELOG.md').write_text('# Changelog\n')
        self.git(repo, 'add', '-A')
        self.git(repo, 'commit', '-m', 'add docs, tests, changelog')
        info = catalog.describe_repo(repo)
        self.assertTrue(info['has_docs'])
        self.assertTrue(info['has_tests'])
        self.assertTrue(info['has_changelog'])
        self.assertIsNotNone(info['last_commit_at'])
        self.assertEqual(info['last_commit_subject'], 'add docs, tests, changelog')

    def test_workspace_scan_discovers_every_repository_and_counts_described(self):
        described = self.make_repo('org/one')
        (described / 'pyproject.toml').write_text('[project]\nname = "one"\ndescription = "Described"\n')
        self.make_repo('org/two')  # no description anywhere
        data = catalog.scan(self.root)
        self.assertEqual(data['mode'], 'workspace')
        self.assertEqual(data['repository_count'], 2)
        self.assertEqual(data['described_count'], 1)
        self.assertEqual(data['undescribed_count'], 1)

    def test_single_repository_mode(self):
        repo = self.make_repo('org/solo')
        (repo / 'README.md').write_text('# solo\n\nA solo repository under test.\n')
        data = catalog.scan(repo)
        self.assertEqual(data['mode'], 'repository')
        self.assertEqual(data['repository_count'], 1)
        self.assertEqual(data['repositories'][0]['description'],
                         'A solo repository under test.')

    def test_markdown_renders_without_crashing(self):
        repo = self.make_repo('org/demo')
        (repo / 'pyproject.toml').write_text('[project]\nname = "demo"\ndescription = "Demo project"\n')
        data = catalog.scan(repo)
        text = catalog.markdown(data)
        self.assertIn('project catalog', text)
        self.assertIn('demo', text)


if __name__ == '__main__':
    unittest.main()

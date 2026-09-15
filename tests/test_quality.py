from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from monag import quality


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def git(self, *args):
        subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.DEVNULL, text=True)

    def make_repo(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.git('init', '-b', 'main')

    def test_workspace_mode_is_refused_not_attempted(self):
        workspace = self.root  # no .git here: not a repository
        data = quality.scan(workspace)
        self.assertFalse(data['available'])
        self.assertIn('single repository', data['error'])

    def test_missing_regix_binary_is_explicit(self):
        self.make_repo()
        with patch('monag.quality.regix_available', return_value=False):
            data = quality.scan(self.root)
        self.assertFalse(data['available'])
        self.assertIn('not found on PATH', data['error'])

    def test_successful_gates_are_reported(self):
        self.make_repo()
        output = (
            '{"ref": "HEAD", "all_passed": false, "errors": 2, "warnings": 3, '
            '"violations": [{"metric": "cc", "value": 12, "threshold": 10.0, '
            '"operator": "le", "passed": false, "source": "snapshot", '
            '"severity": "warning", "file": "src/x.py", "symbol": "f"}]}'
        )
        with patch('monag.quality.regix_available', return_value=True), \
             patch('monag.quality.run_regix', return_value=(output, None)):
            data = quality.scan(self.root)
        self.assertTrue(data['available'])
        self.assertEqual(data['ref'], 'HEAD')
        self.assertFalse(data['all_passed'])
        self.assertEqual(data['error_count'], 2)
        self.assertEqual(data['warning_count'], 3)
        self.assertEqual(data['violation_count'], 1)

    def test_regix_failure_is_explicit_not_silent(self):
        self.make_repo()
        with patch('monag.quality.regix_available', return_value=True), \
             patch('monag.quality.run_regix', return_value=(None, 'regix: TimeoutExpired')):
            data = quality.scan(self.root)
        self.assertFalse(data['available'])
        self.assertEqual(data['error'], 'regix: TimeoutExpired')

    def test_invalid_output_is_explicit_not_silent(self):
        self.make_repo()
        with patch('monag.quality.regix_available', return_value=True), \
             patch('monag.quality.run_regix', return_value=('not json', None)):
            data = quality.scan(self.root)
        self.assertFalse(data['available'])
        self.assertIn('invalid output', data['error'])

    def test_markdown_renders_unavailable_and_available_without_crashing(self):
        self.make_repo()
        unavailable = quality.scan(self.root / 'nope')
        text = quality.markdown(unavailable)
        self.assertIn('quality gate', text)
        self.assertIn('single repository', text)

        output = '{"ref": "HEAD", "all_passed": true, "errors": 0, "warnings": 0, "violations": []}'
        with patch('monag.quality.regix_available', return_value=True), \
             patch('monag.quality.run_regix', return_value=(output, None)):
            data = quality.scan(self.root)
        text = quality.markdown(data)
        self.assertIn('all passed: **True**', text)


if __name__ == '__main__':
    unittest.main()

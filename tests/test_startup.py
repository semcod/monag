from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from monag.cli import main
from test_presentation import sample


class Output(StringIO):
    def __init__(self, terminal):
        super().__init__()
        self.terminal = terminal

    def isatty(self):
        return self.terminal


class StartupTests(unittest.TestCase):
    def test_bare_command_opens_shell_and_shows_dashboard(self):
        stream = Output(True)
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / 'github').mkdir()
            with patch('monag.cli.Path.home', return_value=base), \
                 patch('sys.stdout', stream), patch.dict('os.environ', {'TERM': 'xterm'}), \
                 patch('monag.cli.snapshot', return_value=sample()) as snapshots, \
                 patch('monag.cli.history.record', return_value=[]) as records, \
                 patch('builtins.input', return_value='quit'):
                self.assertEqual(main([]), 0)
            self.assertEqual(snapshots.call_count, 1)
            self.assertEqual(records.call_count, 1)
            self.assertIn('MONAG shell', stream.getvalue())
            self.assertIn('Agent activity', stream.getvalue())
            self.assertIn('MONAG shell zakończony', stream.getvalue())

    def test_shell_dispatches_reports_until_exit(self):
        stream = Output(True)
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / 'github').mkdir()
            with patch('monag.cli.Path.home', return_value=base), \
                 patch('sys.stdout', stream), patch.dict('os.environ', {'TERM': 'xterm'}), \
                 patch('monag.cli.snapshot', return_value=sample()) as snapshots, \
                 patch('monag.cli.history.record', return_value=[]), \
                 patch('builtins.input', side_effect=['help', 'status', 'quit']):
                self.assertEqual(main(['shell']), 0)
            self.assertEqual(snapshots.call_count, 2)
            self.assertNotIn('Nieznane', stream.getvalue())
            self.assertIn('pokaż worktree', stream.getvalue())

    def test_explicit_status_exports_and_pipes_remain_one_shot(self):
        for argv, terminal in [(['status'], True), (['--json'], True),
                               (['--markdown'], True), ([], False)]:
            with self.subTest(argv=argv, terminal=terminal), tempfile.TemporaryDirectory() as folder:
                base = Path(folder)
                (base / 'github').mkdir()
                with patch('monag.cli.Path.home', return_value=base), \
                     patch('sys.stdout', Output(terminal)), \
                     patch('monag.cli.snapshot', return_value=sample()) as snapshots, \
                     patch('monag.cli.history.record') as records, \
                     patch('monag.cli.time.sleep') as sleep:
                    self.assertEqual(main(argv), 0)
                self.assertEqual(snapshots.call_count, 1)
                records.assert_not_called()
                sleep.assert_not_called()

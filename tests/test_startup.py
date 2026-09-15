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
    def test_bare_command_refreshes_and_shows_screen_before_scanning(self):
        stream = Output(True)
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / 'github').mkdir()
            def scan(*args):
                self.assertIn('\x1b[?1049h', stream.getvalue())
                return sample()
            with patch('monag.cli.Path.home', return_value=base), \
                 patch('sys.stdout', stream), patch.dict('os.environ', {'TERM': 'xterm'}), \
                 patch('monag.cli.snapshot', side_effect=scan) as snapshots, \
                 patch('monag.cli.history.record', return_value=[]) as records, \
                 patch('monag.cli.time.sleep', side_effect=[None, KeyboardInterrupt]) as sleep:
                self.assertEqual(main([]), 130)
            self.assertEqual(snapshots.call_count, 2)
            self.assertEqual(records.call_count, 2)
            sleep.assert_called_with(5)
            self.assertIn('\x1b[?1049l', stream.getvalue())

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

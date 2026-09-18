import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from monag import dsl
from monag.monitor import command as real_command


class DslTests(unittest.TestCase):
    def test_parse_dsl_canonical(self):
        q = dsl.parse('OBSERVE prs STATE open HOURS 12 UNPUSHED_ONLY')
        self.assertIsNotNone(q)
        self.assertEqual(q.target, 'prs')
        self.assertEqual(q.state, 'open')
        self.assertEqual(q.hours, 12.0)
        self.assertTrue(q.unpushed_only)
        self.assertEqual(q.to_dsl(), 'OBSERVE prs HOURS 12 STATE open UNPUSHED_ONLY')

    def test_parse_natural_language_polish(self):
        # PR queries
        q1 = dsl.parse('pokaż niescalone PR z ostatnich 10h')
        self.assertIsNotNone(q1)
        self.assertEqual(q1.target, 'prs')
        self.assertEqual(q1.state, 'open')
        self.assertEqual(q1.hours, 10.0)

        # Audit query
        q2 = dsl.parse('zrób audyt ticketów planfile')
        self.assertIsNotNone(q2)
        self.assertEqual(q2.target, 'audit')

        # Agents query
        q3 = dsl.parse('jaki jest stan procesów agentów?')
        self.assertIsNotNone(q3)
        self.assertEqual(q3.target, 'status')

        # Usage query
        q4 = dsl.parse('ile tokenów zużyły konta i agenci?')
        self.assertIsNotNone(q4)
        self.assertEqual(q4.target, 'usage')

        # Resume query
        q5 = dsl.parse('pokaż aktywne worktree i backlog')
        self.assertIsNotNone(q5)
        self.assertEqual(q5.target, 'resume')

    def test_parse_natural_language_english(self):
        q1 = dsl.parse('show unmerged pull requests in last 48 hours')
        self.assertIsNotNone(q1)
        self.assertEqual(q1.target, 'prs')
        self.assertEqual(q1.state, 'open')
        self.assertEqual(q1.hours, 48.0)

        q2 = dsl.parse('check ticket coverage against github issues')
        self.assertIsNotNone(q2)
        self.assertEqual(q2.target, 'audit')

        q3 = dsl.parse('inspect agent processes and snapshot')
        self.assertIsNotNone(q3)
        self.assertEqual(q3.target, 'status')

    def test_execute_query(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            # Mock prs.scan and prs.markdown
            with patch('monag.prs.scan', return_value={'total_open_prs': 0}) as mock_scan, \
                 patch('monag.prs.markdown', return_value='# PR Markdown') as mock_md:
                res = dsl.execute('pokaż niescalone PR', root=root)

            self.assertEqual(res['status'], 'ok')
            self.assertEqual(res['target'], 'prs')
            self.assertIn('# PR Markdown', res['markdown'])
            mock_scan.assert_called_once()
            mock_md.assert_called_once()

    def test_unrecognized_query_returns_error(self):
        res = dsl.execute('losowe nieznane polecenie xzy123', root='/tmp')
        self.assertEqual(res['status'], 'error')
        self.assertIn('Unrecognized query', res['error'])


if __name__ == '__main__':
    unittest.main()

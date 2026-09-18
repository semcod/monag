import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from monag import dsl, dsl_llm


def fake_runner(answer, delay=0):
    """Return a run_provider substitute printing `answer` on stdout."""
    def runner(prompt, command, timeout=10.0):
        if delay:
            import time
            time.sleep(delay)
        return answer
    return runner


class ExtractTests(unittest.TestCase):
    def test_extracts_single_line(self):
        self.assertEqual(dsl_llm.extract_observe_line('OBSERVE prs STATE open'),
                         'OBSERVE prs STATE open')

    def test_strips_fences_and_prose(self):
        answer = '```\nOBSERVE status HOURS 6\n```\nsome explanation'
        self.assertEqual(dsl_llm.extract_observe_line(answer),
                         'OBSERVE status HOURS 6')

    def test_rejects_multiple_candidates(self):
        self.assertIsNone(
            dsl_llm.extract_observe_line('OBSERVE prs\nOBSERVE audit'))

    def test_rejects_empty(self):
        self.assertIsNone(dsl_llm.extract_observe_line(''))
        self.assertIsNone(dsl_llm.extract_observe_line('no observe here'))


class ResolveTests(unittest.TestCase):
    def test_rule_engine_first_no_provider_call(self):
        with patch.object(dsl_llm, 'run_provider',
                          side_effect=AssertionError('must not run')):
            query, prov = dsl_llm.resolve('pokaż otwarte PR z ostatnich 5h')
        self.assertEqual(query.target, 'prs')
        self.assertEqual(query.state, 'open')
        self.assertEqual(prov['engine'], 'rule')

    def test_provider_translates_unmappable(self):
        phrase = 'podsumuj co słychać w naszych sprawach'
        self.assertIsNone(dsl.parse(phrase))
        with patch.object(dsl_llm, 'run_provider',
                          fake_runner('OBSERVE prs UNPUSHED_ONLY')):
            query, prov = dsl_llm.resolve(phrase, command='fake-llm')
        self.assertIsNotNone(query)
        self.assertEqual(query.target, 'prs')
        self.assertTrue(query.unpushed_only)
        self.assertEqual(prov['engine'], 'llm')
        self.assertEqual(prov['dsl'], 'OBSERVE prs UNPUSHED_ONLY')
        self.assertEqual(prov['raw_input'], phrase)

    def test_observe_none_is_failure(self):
        with patch.object(dsl_llm, 'run_provider',
                          fake_runner('OBSERVE none')):
            query, prov = dsl_llm.resolve('zrób mi kawę', command='fake-llm')
        self.assertIsNone(query)
        self.assertEqual(prov['engine'], 'none')

    def test_unparseable_output_is_failure(self):
        with patch.object(dsl_llm, 'run_provider',
                          fake_runner('OBSERVE nonsense domain')):
            query, prov = dsl_llm.resolve('zrób mi kawę', command='fake-llm')
        self.assertIsNone(query)
        self.assertEqual(prov['engine'], 'none')

    def test_provider_crash_or_timeout_is_failure(self):
        with patch.object(dsl_llm, 'run_provider', return_value=None):
            query, prov = dsl_llm.resolve('zrób mi kawę', command='llm cmd')
        self.assertIsNone(query)
        self.assertEqual(prov['engine'], 'none')

    def test_disabled_by_default(self):
        env = {k: v for k, v in os.environ.items()
               if k not in {'MONAG_LLM_COMMAND', 'MONAG_LLM_TIMEOUT'}}
        with patch.dict(os.environ, env, clear=True), \
                patch.object(dsl_llm, 'run_provider',
                             side_effect=AssertionError('must not run')):
            query, prov = dsl_llm.resolve('zrób mi kawę')
        self.assertIsNone(query)
        self.assertEqual(prov['engine'], 'none')

    def test_zero_timeout_rejects(self):
        with patch.dict(os.environ, {'MONAG_LLM_TIMEOUT': '0'}), \
                patch.object(dsl_llm, 'run_provider',
                             side_effect=AssertionError('must not run')):
            query, prov = dsl_llm.resolve('zrób mi kawę',
                                          command='llm cmd')
        self.assertIsNone(query)


class ExecuteTests(unittest.TestCase):
    def test_error_envelope_carries_provenance(self):
        with patch.dict(os.environ, {}, clear=True):
            res = dsl_llm.execute('complete gibberish αβγ',
                                  Path(tempfile.mkdtemp()))
        self.assertEqual(res['schema'], dsl_llm.SCHEMA)
        self.assertEqual(res['status'], 'error')
        self.assertEqual(res['provenance']['engine'], 'none')

    def test_query_object_passthrough(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('monag.catalog.scan', return_value={'projects': []}), \
                    patch('monag.catalog.markdown', return_value='# Catalog'):
                res = dsl_llm.execute(dsl.Query('catalog'), Path(folder))
        self.assertEqual(res['status'], 'ok')
        self.assertEqual(res['provenance']['engine'], 'rule')

    def test_provider_path_executes_validated_query(self):
        phrase = 'podsumuj co słychać w naszych sprawach'
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(dsl_llm, 'run_provider',
                              fake_runner('OBSERVE catalog')), \
                    patch('monag.catalog.scan', return_value={'projects': []}), \
                    patch('monag.catalog.markdown', return_value='# Catalog'):
                res = dsl_llm.execute(phrase, Path(folder), command='fake-llm')
        self.assertEqual(res['status'], 'ok')
        self.assertEqual(res['provenance']['engine'], 'llm')
        self.assertEqual(res['provenance']['dsl'], 'OBSERVE catalog')
        self.assertEqual(res['query']['target'], 'catalog')


class ProviderTests(unittest.TestCase):
    def test_run_provider_executes_command(self):
        res = dsl_llm.run_provider('hello', 'cat', timeout=5)
        self.assertEqual(res.strip(), 'hello')

    def test_run_provider_missing_command(self):
        self.assertIsNone(dsl_llm.run_provider('x', 'definitely-missing-cmd-xyz'))

    def test_run_provider_timeout(self):
        self.assertIsNone(
            dsl_llm.run_provider('x', 'sleep 5', timeout=0.2))

    def test_run_provider_nonzero_exit(self):
        self.assertIsNone(dsl_llm.run_provider('x', 'false'))


if __name__ == '__main__':
    unittest.main()

"""Behavioral conformance of the shared read-only NL/DSL/MCP interface."""
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from monag import dsl, dsl_llm, mcp, nl_contract, panel


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {'MONAG_LLM_COMMAND': ''}).start()

    def tool(self, name, arguments):
        return mcp.process_message({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                    'params': {'name': name, 'arguments': arguments}}, self.root)['result']

    def assert_envelope(self, result, success=True):
        self.assertEqual(set(result), {'success', 'status', 'data', 'errors', 'meta'})
        self.assertEqual(result['success'], success)
        self.assertEqual(bool(result['errors']), not success)
        self.assertGreaterEqual(result['meta']['executionTimeMs'], 0)
        self.assertIn(result['meta']['sourceLayer'], {'direct_dsl', 'nl_fast_path', 'llm_fallback'})
        self.assertTrue(result['meta']['traceId'])

    def test_tools_and_resource_publish_same_closed_schema(self):
        self.assertTrue({'execute_dsl', 'nl_ask', 'describe_grammar'} <= {t['name'] for t in mcp.TOOLS})
        grammar = self.tool('describe_grammar', {})['structuredContent']
        schema = json.loads(mcp.read_resource('schema://current', self.root))
        self.assertEqual(schema, grammar['commandSchema'])
        self.assertEqual(grammar['sourceRevision'], nl_contract.STANDARD_REVISION)
        grammar['commandSchema']['properties'].clear()
        self.assertIn('entity', nl_contract.grammar()['commandSchema']['properties'])

    def test_direct_and_multilingual_fast_paths_never_invoke_provider(self):
        with patch.object(dsl_llm, 'run_provider', side_effect=AssertionError('unexpected LLM')):
            for tool, key, value, layer in [
                ('execute_dsl', 'dsl_command', 'OBSERVE catalog', 'direct_dsl'),
                ('nl_ask', 'query', 'pokaż katalog', 'nl_fast_path'),
                ('nl_ask', 'query', 'show catalog', 'nl_fast_path'),
            ]:
                with self.subTest(tool=tool, value=value):
                    result = self.tool(tool, {key: value})
                    self.assertFalse(result['isError'])
                    envelope = result['structuredContent']
                    self.assert_envelope(envelope)
                    self.assertEqual(json.loads(result['content'][0]['text']), envelope)
                    self.assertEqual(envelope['meta']['sourceLayer'], layer)
                    self.assertEqual(envelope['meta']['canonicalDsl'], 'OBSERVE catalog')
                    self.assertEqual(envelope['meta']['provenance']['engine'], 'rule')

    def test_invalid_dsl_is_rejected_before_provider_or_scanner(self):
        invalid = ['OBSERVE catalog SURPRISE', 'OBSERVE catalog LIMIT',
                   'OBSERVE catalog LIMIT xyz', 'OBSERVE catalog LIMIT -1',
                   'OBSERVE catalog STATE unexpected', 'OBSERVE catalog HOURS NaN',
                   'OBSERVE catalog HOURS inf', 'OBSERVE catalog HOURS -1',
                   'OBSERVE catalog LIMIT 1 LIMIT 2',
                   'OBSERVE catalog; OBSERVE prs', 'OBSERVE catalog\nOBSERVE prs',
                   'OBSERVE unknown', 'show catalog']
        with patch.object(dsl_llm, 'run_provider', side_effect=AssertionError('unexpected LLM')):
            with patch.object(dsl, 'execute', side_effect=AssertionError('unexpected scan')):
                for value in invalid:
                    with self.subTest(value=value):
                        result = self.tool('execute_dsl', {'dsl_command': value})
                        self.assertTrue(result['isError'])
                        self.assert_envelope(result['structuredContent'], False)
                self.assertIsNone(dsl.parse('OBSERVE catalog LIMIT garbage'))
                self.assertIsNone(dsl_llm.resolve('OBSERVE catalog LIMIT garbage', command='fixture')[0])

    def test_tool_argument_validation(self):
        for name, args in [('nl_ask', {}), ('nl_ask', []), ('nl_ask', None),
                           ('nl_ask', {'query': 5}), ('nl_ask', {'query': 'catalog', 'extra': True}),
                           ('nl_ask', {'query': 'catalog', 'allow_llm_fallback': 'false'}),
                           ('monag_status', {'limit': True}), ('monag_audit', {'issue_limit': 0}),
                           ('monag_advise', {'tier': 'invalid'}), (['invalid'], {})]:
            with self.subTest(name=name, args=args):
                result = self.tool(name, args)
                self.assertTrue(result['isError'])
                self.assert_envelope(result['structuredContent'], False)

    def test_unknown_query_error_and_provenance_survive_legacy_adapter(self):
        result = self.tool('monag_query', {'query': 'qqzz_unknown_123'})
        self.assertTrue(result['isError'])
        self.assertTrue(result['content'][0]['text'].startswith('Error:'))
        self.assert_envelope(result['structuredContent'], False)
        success = self.tool('monag_query', {'query': 'OBSERVE catalog'})
        self.assertIn('# MONAG', success['content'][0]['text'])
        self.assertEqual(success['structuredContent']['meta']['provenance']['engine'], 'rule')

    def test_provider_translation_validates_and_can_be_disabled_per_call(self):
        with patch.dict(os.environ, {'MONAG_LLM_COMMAND': 'fixture-provider'}):
            with patch.object(dsl_llm, 'run_provider', return_value='OBSERVE catalog') as provider:
                disabled = self.tool('nl_ask', {'query': 'qqzz_unknown_123', 'allow_llm_fallback': False})
                self.assertTrue(disabled['isError'])
                provider.assert_not_called()
                enabled = self.tool('nl_ask', {'query': 'qqzz_unknown_123'})
                self.assertFalse(enabled['isError'])
                self.assertEqual(enabled['structuredContent']['meta']['sourceLayer'], 'llm_fallback')
                provider.assert_called_once()
            with patch.object(dsl_llm, 'run_provider', return_value='OBSERVE catalog EXTRA'):
                rejected = self.tool('nl_ask', {'query': 'qqzz_unknown_123'})
                self.assertTrue(rejected['isError'])
                self.assertEqual(rejected['structuredContent']['meta']['sourceLayer'], 'llm_fallback')
                self.assertEqual(rejected['structuredContent']['meta']['provenance']['engine'], 'none')

    def test_observer_exception_is_execution_error(self):
        with patch('monag.catalog.scan', side_effect=OSError('fixture failure')):
            result = self.tool('execute_dsl', {'dsl_command': 'OBSERVE catalog'})
        self.assertTrue(result['isError'])
        self.assertEqual(result['structuredContent']['status'], 'EXECUTION_ERROR')

    def test_advisory_and_issue_limit_use_validated_dsl(self):
        with patch('monag.advise.advise', return_value={'recommendations': []}) as observer:
            with patch('monag.advise.markdown', return_value='advice'):
                with patch.object(dsl, 'execute', wraps=dsl.execute) as executor:
                    result = self.tool('monag_advise', {'limit': 3, 'radar': True, 'tier': 'floor'})
        self.assertFalse(result['isError'])
        executor.assert_called_once()
        self.assertEqual(executor.call_args.args[0].target, 'advise')
        self.assertEqual(observer.call_args.kwargs['limit'], 3)
        self.assertTrue(observer.call_args.kwargs['radar'])
        with patch('monag.audit.scan', return_value={}) as scan:
            with patch('monag.audit.markdown', return_value='audit'):
                self.assertFalse(self.tool('monag_audit', {'issue_limit': 7})['isError'])
        self.assertEqual(scan.call_args.kwargs['issue_limit'], 7)

    def test_structured_commands_and_mutated_query_objects_are_validated(self):
        result = nl_contract.execute({'entity': 'catalog', 'operation': 'query'}, self.root, direct=True)
        self.assert_envelope(result)
        for value in [{'entity': 'catalog', 'operation': 'delete'},
                      {'entity': 'catalog', 'operation': 'query', 'arguments': {'limit': True}},
                      {'entity': 'catalog', 'operation': 'query', 'extra': 1}]:
            self.assert_envelope(nl_contract.execute(value, self.root, direct=True), False)
        query = dsl.Query('catalog')
        query.limit = -1
        with self.assertRaises(ValueError):
            dsl.execute(query, self.root)

    def start_http(self):
        server, _ = panel.build_server(self.root, self.root / 'state', port=0)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def request(self, server, path, body=None):
        connection = http.client.HTTPConnection(*server.server_address, timeout=5)
        self.addCleanup(connection.close)
        connection.request('GET' if body is None else 'POST', path,
                           body=None if body is None else json.dumps(body),
                           headers={'Content-Type': 'application/json'})
        response = connection.getresponse()
        return response.status, json.loads(response.read())

    def test_cli_http_and_mcp_share_success_and_error_contract(self):
        server = self.start_http()
        code, schema = self.request(server, '/api/v1/schema')
        self.assertEqual(code, 200)
        self.assertEqual(schema, nl_contract.grammar())
        for valid in (True, False):
            text = 'OBSERVE catalog' if valid else 'OBSERVE catalog BAD'
            code, http = self.request(server, '/api/v1/dsl', {'dsl_command': text})
            rpc = self.tool('execute_dsl', {'dsl_command': text})['structuredContent']
            cli = subprocess.run([sys.executable, '-m', 'monag', '--root', str(self.root),
                                  '--json', 'dsl', text], capture_output=True, text=True, timeout=20)
            self.assertEqual(cli.returncode, 0 if valid else 1, cli.stderr)
            cli_result = json.loads(cli.stdout)
            for result in (http, rpc, cli_result):
                self.assert_envelope(result, valid)
                self.assertEqual(result['status'], rpc['status'])
                self.assertEqual(result['meta']['canonicalDsl'], rpc['meta']['canonicalDsl'])
            self.assertEqual(code, 200 if valid else 400)
        code, result = self.request(server, '/api/v1/query', {'query': 'pokaż katalog', 'locale': 'pl'})
        self.assertEqual(code, 200)
        self.assertEqual(result['meta']['sourceLayer'], 'nl_fast_path')
        for body in [[], {'query': 4}, {'query': 'catalog', 'extra': 1}]:
            code, result = self.request(server, '/api/v1/query', body)
            self.assertEqual(code, 400)
            self.assert_envelope(result, False)
        with patch('monag.catalog.scan', side_effect=OSError('fixture failure')):
            code, result = self.request(server, '/api/v1/dsl', {'dsl_command': 'OBSERVE catalog'})
            self.assertEqual(code, 500)
            self.assert_envelope(result, False)

    def test_cli_ask_uses_standard_envelope_and_legacy_query_keeps_format(self):
        for mode in ('ask', 'query'):
            process = subprocess.run([sys.executable, '-m', 'monag', '--root', str(self.root),
                                      '--json', mode, 'show catalog'],
                                     capture_output=True, text=True, timeout=20)
            self.assertEqual(process.returncode, 0, process.stderr)
            result = json.loads(process.stdout)
            if mode == 'ask':
                self.assert_envelope(result)
                self.assertEqual(result['meta']['sourceLayer'], 'nl_fast_path')
            else:
                self.assertEqual(result['status'], 'ok')
        process = subprocess.run([sys.executable, '-m', 'monag', '--root', str(self.root),
                                  '--json', 'query', 'qqzz_unknown_123'],
                                 capture_output=True, text=True, timeout=20)
        self.assertEqual(process.returncode, 1)

    def test_real_stdio_transports_schema_result_and_error(self):
        messages = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize'},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'resources/read', 'params': {'uri': 'schema://current'}},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
             'params': {'name': 'execute_dsl', 'arguments': {'dsl_command': 'OBSERVE catalog'}}},
            {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call',
             'params': {'name': 'monag_query', 'arguments': {'query': 'qqzz_unknown_123'}}},
        ]
        process = subprocess.run([sys.executable, '-m', 'monag', '--root', str(self.root), 'mcp'],
                                 input='\n'.join(map(json.dumps, messages)) + '\n',
                                 capture_output=True, text=True, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr)
        replies = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual([r['id'] for r in replies], [1, 2, 3, 4])
        self.assertEqual(replies[1]['result']['contents'][0]['mimeType'], 'application/json')
        self.assertFalse(replies[2]['result']['isError'])
        self.assertTrue(replies[3]['result']['isError'])


if __name__ == '__main__':
    unittest.main()

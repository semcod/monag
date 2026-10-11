from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from monag import mcp


class McpTests(unittest.TestCase):
    def test_initialize(self):
        req = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}}
        resp = mcp.process_message(req, root=Path('/tmp'))
        self.assertEqual(resp['id'], 1)
        result = resp['result']
        self.assertEqual(result['protocolVersion'], mcp.MCP_PROTOCOL_VERSION)
        self.assertIn('tools', result['capabilities'])
        self.assertIn('resources', result['capabilities'])
        self.assertEqual(result['serverInfo']['name'], mcp.SERVER_NAME)

    def test_tools_list(self):
        req = {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}}
        resp = mcp.process_message(req, root=Path('/tmp'))
        self.assertEqual(resp['id'], 2)
        tools = resp['result']['tools']
        tool_names = [t['name'] for t in tools]
        self.assertIn('monag_prs', tool_names)
        self.assertIn('monag_audit', tool_names)
        self.assertIn('monag_status', tool_names)
        self.assertIn('monag_query', tool_names)

    def test_tools_call_monag_prs(self):
        req = {
            'jsonrpc': '2.0',
            'id': 3,
            'method': 'tools/call',
            'params': {
                'name': 'monag_prs',
                'arguments': {'hours': 12, 'state': 'open'},
            },
        }
        with patch('monag.dsl.execute', return_value={'status': 'ok', 'markdown': '# PR Report'}) as mock_exec:
            resp = mcp.process_message(req, root=Path('/tmp'))

        self.assertEqual(resp['id'], 3)
        content = resp['result']['content']
        self.assertEqual(content[0]['type'], 'text')
        self.assertEqual(content[0]['text'], '# PR Report')
        mock_exec.assert_called_once()

    def test_tools_call_monag_query(self):
        req = {
            'jsonrpc': '2.0',
            'id': 4,
            'method': 'tools/call',
            'params': {
                'name': 'monag_query',
                'arguments': {'query': 'pokaż niescalone PR'},
            },
        }
        with patch('monag.dsl.execute', return_value={'status': 'ok', 'markdown': '# NL Query Result'}) as mock_exec:
            resp = mcp.process_message(req, root=Path('/tmp'))

        self.assertEqual(resp['id'], 4)
        content = resp['result']['content']
        self.assertEqual(content[0]['text'], '# NL Query Result')

    def test_tools_call_monag_advise_emit_planfile(self):
        req = {
            'jsonrpc': '2.0',
            'id': 14,
            'method': 'tools/call',
            'params': {
                'name': 'monag_advise',
                'arguments': {'emit_planfile': True},
            },
        }
        mock_advise = {'schema': 'monag.advisory/v1', 'recommendations': [{'target': 'a', 'title': 'b', 'tier': 'floor'}]}
        with patch('monag.advise.advise', return_value=mock_advise):
            resp = mcp.process_message(req, root=Path('/tmp'))

        self.assertEqual(resp['id'], 14)
        content = resp['result']['content']
        payload = json.loads(content[0]['text'])
        self.assertEqual(payload['schema'], 'planfile.tickets/v1')
        self.assertEqual(payload['count'], 1)
        self.assertEqual(payload['tickets'][0]['tier'], 'floor')

    def test_resources_list_and_read(self):
        req_list = {'jsonrpc': '2.0', 'id': 5, 'method': 'resources/list', 'params': {}}
        resp_list = mcp.process_message(req_list, root=Path('/tmp'))
        uris = [r['uri'] for r in resp_list['result']['resources']]
        self.assertIn('monag://prs', uris)

        req_read = {'jsonrpc': '2.0', 'id': 6, 'method': 'resources/read', 'params': {'uri': 'monag://prs'}}
        with patch('monag.dsl.execute', return_value={'status': 'ok', 'markdown': '# PRS Resource Content'}):
            resp_read = mcp.process_message(req_read, root=Path('/tmp'))

        self.assertEqual(resp_read['id'], 6)
        contents = resp_read['result']['contents']
        self.assertEqual(contents[0]['uri'], 'monag://prs')
        self.assertEqual(contents[0]['text'], '# PRS Resource Content')

    def test_run_stdio_server_loop(self):
        # Prepare simulated stdin with initialize, ping, and EOF
        input_lines = (
            json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize'}) + '\n' +
            json.dumps({'jsonrpc': '2.0', 'id': 2, 'method': 'ping'}) + '\n'
        )
        in_stream = StringIO(input_lines)
        out_stream = StringIO()

        mcp.run_stdio_server('/tmp', in_stream=in_stream, out_stream=out_stream)

        output_lines = [json.loads(line) for line in out_stream.getvalue().splitlines() if line.strip()]
        self.assertEqual(len(output_lines), 2)
        self.assertEqual(output_lines[0]['id'], 1)
        self.assertEqual(output_lines[0]['result']['serverInfo']['name'], mcp.SERVER_NAME)
        self.assertEqual(output_lines[1]['id'], 2)
        self.assertEqual(output_lines[1]['result'], {})

    def test_monag_health_tool_and_resource(self):
        # Test tool call (markdown default)
        req_tool_md = {
            'jsonrpc': '2.0',
            'id': 10,
            'method': 'tools/call',
            'params': {
                'name': 'monag_health',
                'arguments': {},
            },
        }
        resp_tool_md = mcp.process_message(req_tool_md, root=Path('/tmp'))
        self.assertEqual(resp_tool_md['id'], 10)
        content_md = resp_tool_md['result']['content'][0]['text']
        self.assertIn('MONAG · MCP Transport & Session Health', content_md)
        self.assertIn('CLI Fallbacks', content_md)

        # Test tool call with as_json=True
        req_tool_json = {
            'jsonrpc': '2.0',
            'id': 11,
            'method': 'tools/call',
            'params': {
                'name': 'monag_health',
                'arguments': {'as_json': True},
            },
        }
        resp_tool_json = mcp.process_message(req_tool_json, root=Path('/tmp'))
        content_json = resp_tool_json['result']['content'][0]['text']
        data = json.loads(content_json)
        self.assertEqual(data['schema'], 'monag.mcp/health/v1')
        self.assertEqual(data['status'], 'healthy')
        self.assertIn('cli_fallbacks', data)
        self.assertIn('monag_status', data['cli_fallbacks'])

        # Test resource read
        req_res = {
            'jsonrpc': '2.0',
            'id': 12,
            'method': 'resources/read',
            'params': {'uri': 'monag://health'},
        }
        resp_res = mcp.process_message(req_res, root=Path('/tmp'))
        self.assertEqual(resp_res['id'], 12)
        text = resp_res['result']['contents'][0]['text']
        self.assertIn('MONAG · MCP Transport & Session Health', text)
        self.assertIn('Bounded Read-Only CLI Fallbacks', text)

    def test_tool_exception_containment(self):
        session = mcp.MCPSession()
        req = {
            'jsonrpc': '2.0',
            'id': 20,
            'method': 'tools/call',
            'params': {
                'name': 'monag_prs',
                'arguments': {},
            },
        }
        with patch('monag.dsl.execute', side_effect=RuntimeError('Database disk I/O failure')):
            resp = mcp.process_message(req, root=Path('/tmp'), session=session)

        self.assertEqual(resp['id'], 20)
        self.assertTrue(resp['result']['isError'])
        err_text = resp['result']['content'][0]['text']
        self.assertIn('Database disk I/O failure', err_text)
        self.assertIn('CLI fallback', err_text)
        self.assertEqual(session.errors_total, 1)
        self.assertIn('Database disk I/O failure', session.last_error['message'])

    def test_client_reconnect_lifecycle(self):
        session = mcp.MCPSession()
        self.assertEqual(session.state, mcp.SessionState.UNINITIALIZED)
        self.assertEqual(session.reconnect_count, 0)

        # First init
        req1 = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}}
        resp1 = mcp.process_message(req1, root=Path('/tmp'), session=session)
        self.assertEqual(resp1['id'], 1)
        self.assertEqual(session.state, mcp.SessionState.ACTIVE)
        self.assertEqual(session.reconnect_count, 0)

        # Reconnect init
        req2 = {'jsonrpc': '2.0', 'id': 2, 'method': 'initialize', 'params': {}}
        resp2 = mcp.process_message(req2, root=Path('/tmp'), session=session)
        self.assertEqual(resp2['id'], 2)
        self.assertEqual(session.state, mcp.SessionState.ACTIVE)
        self.assertEqual(session.reconnect_count, 1)

        # Close
        session.close()
        self.assertEqual(session.state, mcp.SessionState.CLOSED)

        # Terminate
        session.terminate('Forced teardown')
        self.assertEqual(session.state, mcp.SessionState.TERMINATED)
        self.assertEqual(session.last_error['message'], 'Forced teardown')

    def test_diagnose_server(self):
        result = mcp.diagnose_server(root='/tmp')
        self.assertEqual(result['schema'], 'monag.mcp/diagnostics/v1')
        self.assertTrue(result['ok'])
        self.assertEqual(len(result['steps']), 6)
        self.assertTrue(all(s['ok'] for s in result['steps']))
        self.assertIn('PASS', result['markdown'])

    def test_cli_mcp_health_and_diagnose(self):
        from monag import cli
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root_args = ['--root', workspace.name, '--state-dir', str(Path(workspace.name) / 'state')]

        # Test mcp --health
        out_buf = StringIO()
        with patch('sys.stdout', out_buf):
            ret = cli.main([*root_args, 'mcp', '--health', '--json'])
        self.assertEqual(ret, 0)
        health_data = json.loads(out_buf.getvalue())
        self.assertEqual(health_data['schema'], 'monag.mcp/health/v1')

        # Test mcp --diagnose
        out_buf_diag = StringIO()
        with patch('sys.stdout', out_buf_diag):
            ret_diag = cli.main([*root_args, 'mcp', '--diagnose', '--json'])
        self.assertEqual(ret_diag, 0)
        diag_data = json.loads(out_buf_diag.getvalue())
        self.assertTrue(diag_data['ok'])

    def test_run_stdio_server_error_containment(self):
        # Feed malformed JSON, then request triggering unhandled error, then valid ping
        input_lines = (
            '{not valid json\n' +
            json.dumps({'jsonrpc': '2.0', 'id': 50, 'method': 'nonexistent_call'}) + '\n' +
            json.dumps({'jsonrpc': '2.0', 'id': 51, 'method': 'ping'}) + '\n'
        )
        in_stream = StringIO(input_lines)
        out_stream = StringIO()

        mcp.run_stdio_server('/tmp', in_stream=in_stream, out_stream=out_stream)

        output_lines = [json.loads(line) for line in out_stream.getvalue().splitlines() if line.strip()]
        self.assertEqual(len(output_lines), 3)

        # 1. Parse error
        self.assertEqual(output_lines[0]['error']['code'], -32700)
        self.assertIn('Parse error', output_lines[0]['error']['message'])

        # 2. Method not found error
        self.assertEqual(output_lines[1]['id'], 50)
        self.assertEqual(output_lines[1]['error']['code'], -32601)

        # 3. Valid ping response (server remained alive and responsive)
        self.assertEqual(output_lines[2]['id'], 51)
        self.assertEqual(output_lines[2]['result'], {})


if __name__ == '__main__':
    unittest.main()

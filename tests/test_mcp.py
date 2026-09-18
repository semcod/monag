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


if __name__ == '__main__':
    unittest.main()

import http.client
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

from monag import dsl, panel


class ConversationalAssistantTests(unittest.TestCase):
    def setUp(self):
        os.environ['MONAG_DISABLE_SUBLLM'] = '1'
        self.addCleanup(os.environ.pop, 'MONAG_DISABLE_SUBLLM', None)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'org' / 'demo'
        self.repo.mkdir(parents=True)
        self.git('init', '-b', 'main')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Test')
        (self.repo / 'README').write_text('base')
        self.git('add', 'README')
        self.git('commit', '-m', 'base')

    def git(self, *args):
        subprocess.check_output(['git', '-C', str(self.repo), *args], stderr=subprocess.DEVNULL, text=True)

    def start(self):
        server, state = panel.build_server(self.root, self.root / 'state', port=0)
        state.refresh_live()
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        return server, state

    def request(self, server, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection(server.server_address[0], server.server_address[1], timeout=5)
        try:
            req_headers = headers or {}
            if body and 'Content-Type' not in req_headers:
                req_headers['Content-Type'] = 'application/json'
            conn.request(method, path, body=body, headers=req_headers)
            response = conn.getresponse()
            res_body = response.read()
            return response.status, response.getheader('Content-Type'), res_body
        finally:
            conn.close()

    def test_panel_html_contains_assistant_and_voice(self):
        server, _ = self.start()
        status, content_type, body = self.request(server, 'GET', '/')
        self.assertEqual(status, 200)
        self.assertIn('text/html', content_type)
        html = body.decode('utf-8')
        self.assertIn('Fleet Voice &amp; NL Assistant', html)
        self.assertIn('id="assistant-section"', html)
        self.assertIn('id="option-network-pills"', html)
        self.assertIn('id="assistant-input"', html)
        self.assertIn('id="mic-btn"', html)
        self.assertIn('id="assistant-chat"', html)
        self.assertIn('initSpeechRecognition', html)
        self.assertIn('sendAssistantPrompt', html)

    def test_assistant_api_get_endpoints(self):
        server, state = self.start()
        # Seed mock agents and repo
        state.snapshot['agents'] = [{'pid': 4321, 'kind': 'koru', 'task': 'Refactor models', 'cwd': str(self.repo)}]

        # 1. Agents query
        status, _, body = self.request(server, 'GET', '/api/assistant?q=kto+pracuje%3F')
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['target'], 'agents')
        self.assertIn('4321', str(data['cards']))

        # 2. Triage / Collisions query
        status, _, body = self.request(server, 'GET', '/api/assistant?q=czy+s%C4%85+kolizje%3F')
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['target'], 'triage')

        # 3. Autodiagnosis query
        status, _, body = self.request(server, 'GET', '/api/assistant?q=uruchom+autodiagnoz%C4%99')
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['target'], 'autodiagnosis')

        # 4. Tickets query
        status, _, body = self.request(server, 'GET', '/api/assistant?q=otwarte+zadania')
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['target'], 'tickets')

    def test_assistant_api_post_endpoint(self):
        server, state = self.start()
        state.snapshot['agents'] = [{'pid': 9999, 'kind': 'antigravity', 'task': 'Fleet audit', 'cwd': str(self.repo)}]
        payload = json.dumps({'query': 'pokaż aktywnych agentów'})
        status, _, body = self.request(server, 'POST', '/api/assistant', body=payload)
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['target'], 'agents')
        self.assertIn('9999', str(data['cards']))

    def test_assistant_api_empty_query(self):
        server, _ = self.start()
        status, _, body = self.request(server, 'GET', '/api/assistant?q=')
        self.assertEqual(status, 400)
        data = json.loads(body)
        self.assertEqual(data['status'], 'error')

        status, _, body = self.request(server, 'POST', '/api/assistant', body='{}')
        self.assertEqual(status, 400)
        data = json.loads(body)
        self.assertEqual(data['status'], 'error')

    def test_dsl_natural_language_polish_queries(self):
        self.assertEqual(dsl.parse('pokaż agentów').target, 'status')
        self.assertEqual(dsl.parse('kto pracuje?').target, 'status')
        self.assertEqual(dsl.parse('otwarte tickety').target, 'resume')
        self.assertEqual(dsl.parse('zadania w toku').target, 'resume')
        self.assertEqual(dsl.parse('autodiagnoza floty').target, 'advise')
        self.assertEqual(dsl.parse('pokaż pull requesty').target, 'prs')
        self.assertEqual(dsl.parse('audyt planfile').target, 'audit')


if __name__ == '__main__':
    unittest.main()

import http.client
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

from monag import panel


class PanelTests(unittest.TestCase):
    def setUp(self):
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

    def get(self, server, path):
        conn = http.client.HTTPConnection(server.server_address[0], server.server_address[1], timeout=5)
        try:
            conn.request('GET', path)
            response = conn.getresponse()
            body = response.read()
            return response.status, response.getheader('Content-Type'), body
        finally:
            conn.close()

    def test_binds_to_localhost_by_default(self):
        server, _ = self.start()
        self.assertEqual(server.server_address[0], '127.0.0.1')

    def test_root_serves_html_page(self):
        server, _ = self.start()
        status, content_type, body = self.get(server, '/')
        self.assertEqual(status, 200)
        self.assertIn('text/html', content_type)
        self.assertIn(b'monag panel', body)

    def test_snapshot_and_resume_endpoints_serve_refreshed_state(self):
        server, state = self.start()
        status, _, body = self.get(server, '/api/snapshot.json')
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn('agents', data)
        self.assertEqual(data['repositories'][0]['path'], state.snapshot['repositories'][0]['path'])

        status, _, body = self.get(server, '/api/resume.json')
        self.assertEqual(status, 200)
        self.assertIn('projects', json.loads(body))

    def test_audit_and_catalog_are_computed_lazily_and_cached(self):
        server, state = self.start()
        self.assertIsNone(state._audit)
        status, _, body = self.get(server, '/api/audit.json')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['repository_count'], 1)
        first_at = state._audit_at
        # A second request inside the TTL window must reuse the cached report,
        # not re-run the per-repository git/gh calls.
        self.get(server, '/api/audit.json')
        self.assertEqual(state._audit_at, first_at)

        status, _, body = self.get(server, '/api/catalog.json')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['repository_count'], 1)

    def test_unknown_path_is_404_json(self):
        server, _ = self.start()
        status, content_type, body = self.get(server, '/nope')
        self.assertEqual(status, 404)
        self.assertIn('application/json', content_type)
        self.assertEqual(json.loads(body)['error'], 'not found')


if __name__ == '__main__':
    unittest.main()

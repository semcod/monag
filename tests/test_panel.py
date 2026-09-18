import http.client
import json
from pathlib import Path
import socket
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

    def test_export_is_computed_lazily_cached_and_never_enriched(self):
        server, state = self.start()
        self.assertIsNone(state._export)
        status, _, body = self.get(server, '/api/export.json')
        self.assertEqual(status, 200)
        data = json.loads(body)
        # The panel's on-demand refresh never shells out per candidate/repository.
        self.assertFalse(data['radar_requested'])
        self.assertFalse(data['hygiene_requested'])
        first_at = state._export_at
        self.get(server, '/api/export.json')
        self.assertEqual(state._export_at, first_at)

    def test_unknown_path_is_404_json(self):
        server, _ = self.start()
        status, content_type, body = self.get(server, '/nope')
        self.assertEqual(status, 404)
        self.assertIn('application/json', content_type)
        self.assertEqual(json.loads(body)['error'], 'not found')

    def test_bind_server_falls_back_when_preferred_port_is_taken(self):
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        blocker.bind(('127.0.0.1', 0))
        blocker.listen(1)
        occupied_port = blocker.getsockname()[1]
        try:
            handler = panel.make_handler(panel.State(self.root, self.root / 'state', 2, None,
                                                      False, False, False, False))
            server = panel.bind_server(handler, '127.0.0.1', occupied_port, attempts=5)
            try:
                self.assertNotEqual(server.server_address[1], occupied_port)
                self.assertGreater(server.server_address[1], 0)
            finally:
                server.server_close()
        finally:
            blocker.close()

    def test_bind_server_port_zero_always_gets_a_free_port(self):
        handler = panel.make_handler(panel.State(self.root, self.root / 'state', 2, None,
                                                  False, False, False, False))
        server = panel.bind_server(handler, '127.0.0.1', 0)
        try:
            self.assertGreater(server.server_address[1], 0)
        finally:
            server.server_close()

    def test_write_state_file_records_the_actual_bound_port(self):
        state_dir = self.root / 'state'
        panel.write_state_file(state_dir, '127.0.0.1', 54321)
        recorded = json.loads((state_dir / 'panel.json').read_text())
        self.assertEqual(recorded['port'], 54321)
        self.assertEqual(recorded['bind'], '127.0.0.1')
        self.assertEqual(recorded['url'], 'http://127.0.0.1:54321/')

    def test_build_server_with_preferred_port_taken_matches_bind_server_fallback(self):
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        blocker.bind(('127.0.0.1', 0))
        blocker.listen(1)
        occupied_port = blocker.getsockname()[1]
        try:
            server, _ = panel.build_server(self.root, self.root / 'state', port=occupied_port, port_attempts=3)
            try:
                self.assertNotEqual(server.server_address[1], occupied_port)
            finally:
                server.server_close()
        finally:
            blocker.close()


    def post(self, server, path, body_dict):
        conn = http.client.HTTPConnection(server.server_address[0], server.server_address[1], timeout=5)
        try:
            payload = json.dumps(body_dict).encode()
            conn.request('POST', path, body=payload, headers={'Content-Type': 'application/json'})
            response = conn.getresponse()
            body = response.read()
            return response.status, response.getheader('Content-Type'), body
        finally:
            conn.close()

    def test_prs_endpoint_serves_prs_report(self):
        server, state = self.start()
        status, content_type, body = self.get(server, '/api/prs.json')
        self.assertEqual(status, 200)
        self.assertIn('application/json', content_type)
        data = json.loads(body)
        self.assertIn('scanned_repos_count', data)

    def test_query_endpoint_get_and_post(self):
        server, state = self.start()
        # Test GET with ?q=
        status, content_type, body = self.get(server, '/api/query?q=status')
        self.assertEqual(status, 200)
        self.assertIn('application/json', content_type)
        data = json.loads(body)
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['target'], 'status')

        # Test POST with body
        status, content_type, body = self.post(server, '/api/query', {'query': 'OBSERVE prs'})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['target'], 'prs')


if __name__ == '__main__':
    unittest.main()


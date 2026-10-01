"""HTTP contract for the workbench transport: conditional GET, gzip, asset cache.

These exercise the real ``serve`` handler over a loopback socket. No model call
and no DSH process is started; only the acquisition seed is stubbed out.
"""
import gzip
import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from agent import Store
from workbench import serve


class WorkbenchHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        self.document = self.store.document(
            'https://example.org/original', 'Original source title',
            'Original paragraph about ontology and enterprise delivery. ' * 40,
            'body_fetched_not_semantically_verified')
        for stub in (patch('pipeline.Pipeline.seed', return_value={'added': 0}),
                     patch('builtins.print')):
            stub.start()
            self.addCleanup(stub.stop)
        self.ready = threading.Event()
        self.server = None
        self.server_errors = []

        def create_server(address, handler):
            self.server = ThreadingHTTPServer(address, handler)
            self.ready.set()
            return self.server

        factory = patch('workbench.ThreadingHTTPServer', side_effect=create_server)
        factory.start()
        self.addCleanup(factory.stop)

        def run():
            try:
                serve(self.store, {}, port=0)
            except Exception as exc:
                self.server_errors.append(exc)
                self.ready.set()

        self.thread = threading.Thread(target=run, name='workbench-http-test', daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.assertTrue(self.ready.wait(5), 'Test HTTP server did not initialize')
        if self.server_errors:
            raise self.server_errors[0]
        self.port = self.server.server_port

    def close_server(self):
        if self.server:
            self.server.shutdown()
        if self.thread.is_alive():
            self.thread.join(5)

    def request(self, method, path, headers=None, body=None):
        connection = HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            raw = response.read()
            return response.status, raw, dict(response.getheaders())
        finally:
            connection.close()

    def test_state_etag_is_stable_and_revalidates_to_not_modified(self):
        first = self.request('GET', '/api/state')
        second = self.request('GET', '/api/state')
        self.assertEqual(first[0], 200)
        self.assertEqual(second[0], 200)
        etag = first[2]['ETag']
        self.assertTrue(etag)
        # generatedAt changes on every call; the validator must not.
        self.assertNotEqual(json.loads(first[1])['generatedAt'], json.loads(second[1])['generatedAt'])
        self.assertEqual(second[2]['ETag'], etag)
        code, raw, headers = self.request('GET', '/api/state', {'If-None-Match': etag})
        self.assertEqual(code, 304)
        self.assertEqual(raw, b'')
        self.assertEqual(headers['ETag'], etag)

    def test_state_etag_changes_when_the_library_changes(self):
        etag = self.request('GET', '/api/state')[2]['ETag']
        self.store.document('https://example.org/new', 'New title', 'New evidence body.',
                            'body_fetched_not_semantically_verified')
        code, raw, headers = self.request('GET', '/api/state', {'If-None-Match': etag})
        self.assertEqual(code, 200)
        self.assertNotEqual(headers['ETag'], etag)
        self.assertEqual(len(json.loads(raw)['documents']), 2)

    def test_state_gzip_when_accepted_and_body_length_matches(self):
        code, raw, headers = self.request('GET', '/api/state', {'Accept-Encoding': 'gzip'})
        self.assertEqual(code, 200)
        self.assertEqual(headers.get('Content-Encoding'), 'gzip')
        self.assertEqual(int(headers['Content-Length']), len(raw))
        self.assertIn('Accept-Encoding', headers.get('Vary', ''))
        payload = json.loads(gzip.decompress(raw))
        self.assertEqual(len(payload['documents']), 1)
        self.assertEqual(payload['documents'][0]['title'], 'Original source title')

    def test_static_asset_revalidates_without_being_stored(self):
        code, raw, headers = self.request('GET', '/style.css')
        self.assertEqual(code, 200)
        self.assertEqual(headers.get('Cache-Control'), 'no-cache')
        etag = headers['ETag']
        code, raw, headers = self.request('GET', '/style.css', {'If-None-Match': etag})
        self.assertEqual(code, 304)
        self.assertEqual(raw, b'')

    def test_api_state_stays_uncached(self):
        self.assertEqual(self.request('GET', '/api/state')[2].get('Cache-Control'), 'no-store')


if __name__ == '__main__':
    unittest.main()

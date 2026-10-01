"""HTTP integration for reading controls; no DSH process or model call is started."""
import hashlib
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from agent import Store
from workbench import serve


class WorkbenchReadingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        self.original = ('Original paragraph, ontology and enterprise delivery.\n' * 500) + '最后一段保持原样。'
        self.document = self.store.document('https://example.org/original', 'Original source title',
                                            self.original, 'body_fetched_not_semantically_verified')
        self.sentinel = 'TEST_ONLY_CREDENTIAL_VALUE_MUST_NOT_REACH_BROWSER'
        self.config = {'provider': 'test-provider', 'model': 'test-model',
                       'api_key': self.sentinel, 'credentialFile': 'TEST_PRIVATE_CREDENTIAL_PATH'}
        self.reading = MagicMock()
        self.summary = {'id': 'reading-fixture', 'documentId': self.document['id'],
                        'sha256': self.document['sha256'], 'mode': 'translate',
                        'status': 'RUNNING', 'completedChunks': 1, 'totalChunks': 3,
                        'processedChars': 1000, 'totalChars': len(self.original)}
        self.reading.list_tasks.return_value = [self.summary]
        self.reading.start.return_value = self.summary
        self.reading.get.return_value = dict(self.summary, content='第一段译文')
        self.reading.cancel.return_value = dict(self.summary, status='CANCELLED')
        for stub in (patch('reading.ReadingService', return_value=self.reading),
                     patch('pipeline.Pipeline.seed', return_value={'added': 0}),
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
                serve(self.store, self.config, port=0)
            except Exception as exc:
                self.server_errors.append(exc)
                self.ready.set()

        self.thread = threading.Thread(target=run, name='reading-api-test-server', daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.assertTrue(self.ready.wait(5), 'Test HTTP server did not initialize')
        if self.server_errors:
            raise self.server_errors[0]
        self.port = self.server.server_port
        code, data, _ = self.request('GET', '/api/session')
        self.assertEqual(code, 200)
        self.token = data['token']

    def close_server(self):
        if self.server:
            self.server.shutdown()
        if self.thread.is_alive():
            self.thread.join(5)

    def request(self, method, path, data=None, token=True, origin=None):
        headers = {}
        if origin:
            headers['Origin'] = origin
        if method == 'POST' and token and hasattr(self, 'token'):
            headers['X-Radar-Token'] = self.token
        if data is not None:
            headers['Content-Type'] = 'application/json'
        connection = HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            connection.request(method, path, body=json.dumps(data) if data is not None else None, headers=headers)
            response = connection.getresponse()
            body = response.read().decode('utf-8')
            content_type = response.getheader('Content-Type', '')
            value = json.loads(body) if 'application/json' in content_type else body
            return response.status, value, dict(response.getheaders())
        finally:
            connection.close()

    def test_manifest_assets_load_in_declared_order_and_private_files_stay_private(self):
        import re
        from workbench import ROOT, WEB_SCRIPTS
        code, html, _ = self.request('GET', '/')
        self.assertEqual(code, 200)
        scripts = re.findall(r'<script src="([^"]+)" defer>', html)
        self.assertEqual(tuple(name.lstrip('/') for name in scripts), WEB_SCRIPTS)
        self.assertEqual(len(WEB_SCRIPTS), len(set(WEB_SCRIPTS)))
        for name in WEB_SCRIPTS:
            code, body, headers = self.request('GET', '/' + name)
            self.assertEqual(code, 200, name)
            self.assertIn('application/javascript', headers['Content-Type'])
            self.assertEqual(body.encode('utf-8'), (ROOT / 'web' / name).read_bytes())
        for path in ('/config.json', '/assets.json', '/../config.json', '/test_reader.js', '/test_support/load_ui.cjs'):
            self.assertEqual(self.request('GET', path)[0], 404, path)

    def test_translate_and_explain_post_get_routes_pass_document_and_mode(self):
        for mode in ('translate', 'explain'):
            with self.subTest(mode=mode):
                self.reading.start.return_value = dict(self.summary, mode=mode)
                self.reading.get.return_value = dict(self.summary, mode=mode, content='Fixture ' + mode)
                code, value, _ = self.request('POST', '/api/reading', {'documentId': self.document['id'], 'mode': mode})
                self.assertEqual(code, 200)
                self.assertEqual(value['mode'], mode)
                self.reading.start.assert_called_with(self.document['id'], mode)
                code, value, _ = self.request('GET', '/api/reading?documentId=' + self.document['id'] + '&mode=' + mode)
                self.assertEqual(code, 200)
                self.assertEqual(value['content'], 'Fixture ' + mode)
                self.reading.get.assert_called_with(self.document['id'], mode)

    def test_reading_cancel_route_and_service_validation(self):
        code, value, _ = self.request('POST', '/api/reading/cancel', {'id': self.summary['id']})
        self.assertEqual(code, 200)
        self.assertEqual(value['status'], 'CANCELLED')
        self.reading.cancel.assert_called_once_with(self.summary['id'])
        self.reading.start.side_effect = ValueError('INVALID_READING_MODE')
        code, value, _ = self.request('POST', '/api/reading', {'documentId': self.document['id'], 'mode': 'invalid'})
        self.assertEqual(code, 400)
        self.assertEqual(value['error'], 'INVALID_READING_MODE')

    def test_plugin_reading_paginates_on_server_and_disables_resume(self):
        self.reading.get.return_value = dict(self.summary, content='中😀' * 500000,
                                             chunks=[{'index': 0, 'content': '中😀' * 500000}])
        code, value, _ = self.request('GET', '/api/plugin/reading?documentId=' + self.document['id'] + '&mode=translate&offset=14000')
        self.assertEqual(code, 200)
        self.assertEqual(len(value['content']), 14000)
        self.assertEqual(value['nextOffset'], 28000)
        self.assertNotIn('content', value['chunks'][0])
        self.assertLess(len(json.dumps(value).encode()), 200000)
        self.reading.get.assert_called_with(self.document['id'], 'translate', resume=False)

    def test_plugin_generation_keeps_authentication_and_bounded_receipt(self):
        code, _, _ = self.request('POST', '/api/plugin/reading', token=False)
        self.assertEqual(code, 403)
        self.reading.start.assert_not_called()
        self.reading.start.return_value = dict(self.summary, content='large cached translation', chunks=[{'content': 'large cached translation'}])
        code, value, _ = self.request('POST', '/api/plugin/reading', {'documentId': self.document['id'], 'mode': 'translate'})
        self.assertEqual(code, 200)
        self.assertEqual(value['id'], self.summary['id'])
        self.assertNotIn('content', value)
        self.assertNotIn('chunks', value)

    def test_state_exposes_reading_summaries_without_config_credentials(self):
        code, value, _ = self.request('GET', '/api/state')
        self.assertEqual(code, 200)
        self.assertEqual(value['readings'], [self.summary])
        self.reading.list_tasks.assert_called_once_with()
        serialized = json.dumps(value, ensure_ascii=False)
        self.assertNotIn(self.sentinel, serialized)
        self.assertNotIn('TEST_PRIVATE_CREDENTIAL_PATH', serialized)
        self.assertNotIn('config', value)
        self.assertNotIn('content', value['readings'][0])

    def test_document_api_keeps_full_source_text_hash_and_quality_scope(self):
        code, value, _ = self.request('GET', '/api/document?id=' + self.document['id'])
        self.assertEqual(code, 200)
        self.assertGreater(value['chars'], 14000)
        self.assertEqual(value['content'], self.original)
        self.assertEqual(value['chars'], len(self.original))
        self.assertEqual(value['sha256'], hashlib.sha256(self.original.encode('utf-8')).hexdigest())
        self.assertEqual(value['title'], 'Original source title')
        self.assertEqual(value['quality'], 'evidence_text')
        self.assertTrue(value['contentScope'])
        abstract = self.store.document('https://arxiv.org/abs/2404.06571', 'Original abstract',
                                       'Original abstract text only.', 'body_fetched_not_semantically_verified')
        code, value, _ = self.request('GET', '/api/document?id=' + abstract['id'])
        self.assertEqual(code, 200)
        self.assertEqual(value['quality'], 'metadata_only')
        self.assertIn('摘要', value['contentScope'])
        self.assertEqual(value['content'], abstract['content'])

    def test_unauthorized_or_cross_origin_requests_cannot_start_reading(self):
        # Authentication runs before parsing the body. Sending no body avoids a
        # Windows TCP reset when a server rejects and closes unread request data.
        code, _, _ = self.request('POST', '/api/reading', token=False)
        self.assertEqual(code, 403)
        code, _, _ = self.request('POST', '/api/reading', origin='https://untrusted.example')
        self.assertEqual(code, 403)
        self.reading.start.assert_not_called()

    def test_browser_assets_do_not_contain_credential_configuration(self):
        for path in ('/', '/app.js', '/style.css'):
            with self.subTest(path=path):
                code, text, headers = self.request('GET', path)
                self.assertEqual(code, 200)
                self.assertNotIn(self.sentinel, text)
                self.assertNotIn('TEST_PRIVATE_CREDENTIAL_PATH', text)
                self.assertNotIn('DEEPSEEK_API_KEY', text)
                self.assertNotIn('credentialFile', text)
                self.assertIn("connect-src 'self'", headers['Content-Security-Policy'])


if __name__ == '__main__':
    unittest.main()

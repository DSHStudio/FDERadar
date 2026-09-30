import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from agent import Store
from workbench import Workbench
from plugin_api import PluginAPI


class PluginAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name))
        self.app = Workbench(self.store, {})
        self.api = PluginAPI(self.app)
        self.text = 'Raw 20% source <script>data only</script>\n' + 'paragraph\n' * 1800
        self.doc = self.store.document('https://example.org/fde', 'Original title', self.text, 'body_fetched_not_semantically_verified')

    def tearDown(self):
        self.tmp.cleanup()

    def test_identity_has_no_credentials(self):
        value = self.api.info()
        self.assertEqual((value['product'], value['apiVersion']), ('fde-radar', 1))
        self.assertEqual(value['counts']['documents'], 1)
        self.assertNotIn('token', value)
        self.assertNotIn('config', value)

    def test_library_preserves_original_and_pagination(self):
        self.store.document('https://example.org/b', 'Second', 'other', 'metadata_only')
        one = self.api.library({'kind': 'documents', 'limit': '1'})
        two = self.api.library({'kind': 'documents', 'offset': '1', 'limit': '1'})
        self.assertEqual(one['total'], 2)
        self.assertTrue(one['hasMore'])
        self.assertFalse(two['hasMore'])
        self.assertNotEqual(one['items'][0]['id'], two['items'][0]['id'])
        hit = self.api.library({'kind': 'documents', 'query': '%'})
        self.assertEqual([r['title'] for r in hit['items']], ['Original title'])
        self.assertNotIn('content', hit['items'][0])

    def test_read_is_exact_paginated_source(self):
        first = self.api.read({'id': self.doc['id'], 'sha256': self.doc['sha256']})
        second = self.api.read({'id': self.doc['id'], 'offset': first['nextOffset']})
        self.assertEqual(first['content'] + second['content'], self.text)
        self.assertIn('<script>data only</script>', first['content'])
        self.assertEqual(first['title'], 'Original title')
        self.assertIn('contentScope', first)

    def test_read_rejects_version_drift(self):
        with self.assertRaisesRegex(ValueError, 'SOURCE_VERSION_MISMATCH'):
            self.api.read({'id': self.doc['id'], 'sha256': 'not-current'})

    def test_invalid_input_and_unknown_endpoint(self):
        for query in ({'limit': '0'}, {'offset': '-1'}, {'limit': '51'}, {'limit': 'xx'}, {'kind': 'secrets'}, {'query': 'x' * 501}):
            with self.assertRaises(ValueError):
                self.api.library(query)
        with self.assertRaises(ValueError):
            self.api.dispatch('/api/plugin/delete', {})

    def test_tasks_dont_call_not_found_success(self):
        value = self.api.tasks({'id': 'analysis-not-existing'})
        self.assertEqual(value['status'], 'not_found')
        self.assertEqual(value['items'], [])

    def test_active_task_and_failure_are_preserved(self):
        self.app.active['a'] = {'id': 'a', 'status': 'RUNNING'}
        self.assertEqual(self.api.tasks({'id': 'a'})['items'][0]['status'], 'RUNNING')
        self.app.active['a']['status'] = 'FAILED'
        self.assertEqual(self.api.tasks({'id': 'a'})['items'][0]['status'], 'FAILED')

    def test_github_readme_identifiers_are_kept(self):
        self.app.github.state = lambda: {'resources': [{'fullName': 'org/repo', 'readmeDocumentId': self.doc['id'], 'readmeSha256': self.doc['sha256']}]}
        result = self.api.library({'kind': 'github'})['items'][0]
        self.assertEqual(result['readmeDocumentId'], self.doc['id'])
        self.assertEqual(result['readmeSha256'], self.doc['sha256'])

    def test_staged_notes_are_not_exposed_as_completed(self):
        run = self.store.start('test')
        self.store.submit(run, {'track': 'theory', 'title': 'AI note', 'summary': 'Summary', 'analysis': 'Analysis',
            'limitations': 'Not verified', 'nextStep': 'Check', 'documentId': self.doc['id'], 'sha256': self.doc['sha256'], 'quote': 'Raw 20% source'})
        self.assertEqual(self.api.library({'kind': 'notes'})['total'], 0)

    def reading_fixture(self, task_id, created, status='SUCCEEDED'):
        with self.store.db() as db:
            db.execute('''INSERT INTO reading_tasks(id,documentId,sha256,mode,status,sourceTitle,sourceUrl,
                sourceScope,sourceQuality,totalChars,totalChunks,createdAt,config)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (task_id, task_id + '-document', 'hash', 'translate', status, 'Source', 'https://example.org',
                 'body', 'evidence_text', 100, 0, created, '{}'))

    def test_recent_tasks_do_not_hide_new_reading_behind_old_background_tasks(self):
        self.app.active.update({f'old-{n}': {'id': f'old-{n}', 'status': 'SUCCEEDED',
                                'createdAt': '2020-01-01T00:00:00Z'} for n in range(35)})
        self.reading_fixture('reading-latest', '2026-09-29T00:00:00Z')
        result = self.api.tasks({})
        self.assertEqual(result['items'][0]['id'], 'reading-latest')
        self.assertLessEqual(len(result['items']), 30)

    def test_lookup_finds_reading_outside_recent_100(self):
        self.reading_fixture('reading-old', '2020-01-01T00:00:00Z')
        for n in range(101):
            self.reading_fixture(f'reading-new-{n}', '2026-09-29T00:00:00Z')
        self.assertEqual(self.api.tasks({'id': 'reading-old'})['items'][0]['id'], 'reading-old')

    def queued_reading(self):
        self.app.reading.config = {'sdkVersion': '0.1.5rc1', 'provider': 'deepseek-official',
            'model': 'test', 'baseUrl': 'https://api.deepseek.com', 'credentialEnvironment': 'UNUSED_TEST_KEY'}
        with patch.object(self.app.reading, '_launch_worker'):
            return self.app.reading.start(self.doc['id'], 'translate')

    def test_cache_only_plugin_reading_never_launches_queued_worker(self):
        self.queued_reading()
        with patch.object(self.app.reading, '_launch_worker') as launch:
            value = self.api.dispatch('/api/plugin/reading', {'documentId': self.doc['id'], 'mode': 'translate'})
            self.assertEqual(value['status'], 'QUEUED')
            launch.assert_not_called()

    def test_long_translation_is_paged_before_http_serialization(self):
        task = self.queued_reading()
        text = '中文😀' * 350000
        with self.store.db() as db:
            db.execute("UPDATE reading_chunks SET status='SUCCEEDED',content=? WHERE taskId=? AND position=0", (text, task['id']))
            db.execute("UPDATE reading_tasks SET status='FAILED' WHERE id=?", (task['id'],))
        value = self.api.dispatch('/api/plugin/reading', {'documentId': self.doc['id'], 'mode': 'translate', 'offset': '14000'})
        self.assertEqual(value['content'], text[14000:28000])
        self.assertEqual(value['offset'], 14000)
        self.assertEqual(value['nextOffset'], 28000)
        self.assertTrue(value['hasMore'])
        self.assertTrue(value['partial'])
        self.assertLess(len(json.dumps(value, ensure_ascii=False).encode()), 100000)
        self.assertNotIn('content', value['chunks'][0])

    def test_reusing_completed_reading_returns_small_receipt(self):
        with patch.object(self.app.reading, 'start', return_value={
                'id': 'reading-completed', 'status': 'SUCCEEDED', 'content': '中' * 1500000,
                'chunks': [{'content': '中' * 1500000}]}):
            value = self.app.post('/api/plugin/reading', {'documentId': self.doc['id'], 'mode': 'translate'})
        self.assertEqual(value['status'], 'SUCCEEDED')
        self.assertNotIn('content', value)
        self.assertNotIn('chunks', value)


class PluginRunReceiptTests(unittest.TestCase):
    def execute_mock(self, response=None, error=None):
        import dsh_plugin
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {'baseUrl': 'https://api.deepseek.com', 'provider': 'test', 'model': 'test',
                      'maxOutputTokens': 1024, 'turnTimeoutSeconds': 10}
            (root / 'config.json').write_text(json.dumps(config), encoding='utf-8')
            harness = MagicMock()
            harness.__enter__.return_value = harness
            harness.run.return_value = response
            harness.run.side_effect = error
            with patch.object(dsh_plugin, 'ROOT', root), patch.object(dsh_plugin, 'install', return_value={
                    'endpoint': 'http://127.0.0.1:8765/', 'home': str(root), 'patch': 'test-only'}), \
                    patch.object(dsh_plugin, 'service_info'), patch('agent.key_for', return_value='test-secret-only'), \
                    patch('deepseek_harness.DeepSeekHarness', return_value=harness):
                result = dsh_plugin.run('read-only test')
            receipt = json.loads((root / 'var' / 'dsh-plugin-runs' / (result['sessionId'] + '.json')).read_text(encoding='utf-8'))
            self.assertEqual(result, receipt)
            self.assertNotIn('test-secret-only', json.dumps(receipt))
            return result

    def test_terminal_error_is_recorded_without_secret(self):
        result = self.execute_mock(SimpleNamespace(finish_reason='error', final_response='', events=[
            {'type': 'turn/end', 'data': {'reason': {'code': 'TRANSPORT', 'message': 'failed test-secret-only'}}}]))
        self.assertEqual(result['finishReason'], 'error')
        self.assertEqual(result['termination'][0]['data']['reason']['code'], 'TRANSPORT')

    def test_exception_also_leaves_failed_receipt(self):
        result = self.execute_mock(error=RuntimeError('failed test-secret-only'))
        self.assertEqual(result['finishReason'], 'error')
        self.assertEqual(result['error'], 'RuntimeError')
        self.assertEqual(result['toolCalls'], [])


if __name__ == '__main__':
    unittest.main()

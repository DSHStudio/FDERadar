import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from agent import Store
from pipeline import Pipeline, normalize_url


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))
        self.calls = []
        self.url = 'https://example.org/source'
        self.response = dict(title='Original source title', content='This is source text. It stays exactly as supplied.',
                             access='body_fetched_not_semantically_verified', statusCode=200,
                             etag='"v1"', lastModified='Mon, 28 Sep 2026 08:00:00 GMT',
                             links=[], metadata={'format': 'html'})

        def acquire(url, **kwargs):
            self.calls.append((url, kwargs))
            return dict(self.response, url=url, finalUrl=url)

        self.pipeline = Pipeline(self.store, acquire)

    def tearDown(self):
        self.temp.cleanup()

    def run_one(self, force=True):
        queued = self.pipeline.enqueue([self.url], force=force)
        return self.pipeline.run_job(queued['id'])

    def test_conditional_get_and_hash_dedup_preserve_original(self):
        first = self.run_one()
        second = self.run_one()
        self.assertEqual(first['counts']['succeeded'], 1)
        self.assertEqual(second['counts']['unchanged'], 1)
        self.assertEqual(self.calls[1][1]['etag'], '"v1"')
        self.assertEqual(self.calls[1][1]['last_modified'], self.response['lastModified'])
        with self.store.db() as db:
            docs = db.execute('SELECT * FROM documents').fetchall()
            self.assertEqual(len(docs), 1)
            self.assertEqual(docs[0]['content'], self.response['content'])
            self.assertEqual(docs[0]['title'], self.response['title'])
            events = db.execute('SELECT kind FROM events').fetchall()
        self.assertIn('pipeline_fetch', [r['kind'] for r in events])
        self.assertNotIn('fetch', [r['kind'] for r in events])
        self.assertFalse(second['items'][0]['result']['independentlyVerified'])

    def test_304_needs_prior_document_and_updates_freshness(self):
        self.response.update(content='', access='not_modified', statusCode=304)
        failed = self.run_one()
        self.assertEqual(failed['counts']['failed'], 1)
        self.assertEqual(failed['items'][0]['result']['access'], 'cache_missing')
        self.assertEqual(self.pipeline.coverage()['urlsWithFullText'], 0)
        self.response.update(content='A verified stored version.', access='body_fetched_not_semantically_verified', statusCode=200)
        success = self.run_one()
        self.response.update(content='', access='not_modified', statusCode=304)
        cached = self.run_one()
        self.assertEqual(cached['counts']['unchanged'], 1)
        self.assertEqual(success['items'][0]['documentId'], cached['items'][0]['documentId'])

    def test_failures_partial_and_backoff_are_not_no_updates(self):
        self.response.update(content='', access='access_restricted', statusCode=403, error='Sign in required')
        failed = self.run_one()
        source = self.pipeline.sources()[0]
        self.assertEqual(failed['status'], 'COMPLETED_WITH_WARNINGS')
        self.assertEqual(failed['counts']['failed'], 1)
        self.assertIsNone(source['lastSuccess'])
        self.assertEqual(source['attempts'], 1)
        self.assertIsNotNone(source['nextDue'])
        skipped = self.pipeline.enqueue([self.url])
        self.assertEqual(skipped['status'], 'COMPLETED_EMPTY')
        self.response.update(content='Partial body is not a complete source.', access='body_partial', statusCode=200)
        partial = self.run_one()
        self.assertEqual(partial['counts']['partial'], 1)
        self.assertIsNotNone(partial['items'][0]['documentId'])
        self.assertEqual(self.pipeline.coverage()['urlsWithFullText'], 0)

    def test_changed_content_creates_new_version_without_overwriting_old(self):
        first = self.run_one()
        self.response['content'] = 'A different original source version.'
        second = self.run_one()
        self.assertNotEqual(first['items'][0]['documentId'], second['items'][0]['documentId'])
        self.assertEqual(second['counts']['succeeded'], 1)
        self.assertEqual(self.pipeline.coverage()['documentVersions'], 2)

    def test_new_body_without_validators_does_not_keep_old_etag(self):
        self.run_one()
        self.response.update(content='Changed source without caching validators.', etag=None, lastModified=None)
        self.run_one()
        self.run_one()
        self.assertIsNone(self.calls[-1][1]['etag'])
        self.assertIsNone(self.calls[-1][1]['last_modified'])

    def test_seeding_is_idempotent_and_does_not_reset_user_configuration(self):
        with self.store.db() as db:
            db.execute('INSERT INTO sources VALUES(?,?)', ('registry', json.dumps({'name': 'Docs', 'urls': [self.url], 'cadence': '每周'})))
            db.execute('INSERT INTO sources VALUES(?,?)', ('search_api', json.dumps({'urls': ['https://tool.example.org/'], 'source_kind': 'acquisition_tool'})))
            db.execute('INSERT INTO records VALUES(?,?,?)', ('case1', 'case', json.dumps({'title': 'A case', 'references': [{'sourceUrl': 'https://example.org/case'}]})))
        candidate = Path(self.temp.name) / 'candidates.json'
        candidate.write_text(json.dumps({'candidates': [{'id': 'test', 'url': 'https://example.org/candidate'}]}), encoding='utf-8')
        self.assertEqual(self.pipeline.seed([candidate])['added'], 3)
        self.pipeline.update_source({'url': self.url, 'enabled': False, 'cadenceHours': 72})
        self.assertEqual(self.pipeline.seed([candidate])['added'], 0)
        sources = {s['url']: s for s in self.pipeline.sources()}
        self.assertEqual(len(sources), 3)
        self.assertFalse(sources[self.url]['enabled'])
        self.assertEqual(sources[self.url]['cadenceHours'], 72)
        self.assertTrue(sources['https://example.org/candidate']['candidate'])
        self.assertEqual(self.pipeline.coverage()['attemptedUrls'], 0)

    def test_feed_discovery_is_bounded_and_does_not_recursively_fetch(self):
        self.pipeline.update_source({'url': self.url, 'discoveryLimit': 2})
        self.response.update(metadata={'format': 'rss'}, links=[
            {'href': f'https://example.org/story/{i}', 'kind': 'entry'} for i in range(5)])
        self.run_one()
        sources = self.pipeline.sources()
        self.assertEqual(len(sources), 3)
        self.assertEqual(len(self.calls), 1)
        discovered = [s for s in sources if s['discoveredFrom']]
        self.assertTrue(all(s['candidate'] and s['discoveryLimit'] == 0 and not s['lastAttempt'] for s in discovered))
        queued = self.pipeline.enqueue(limit=10)
        self.assertEqual(queued['total'], 2)

    def test_real_corpus_list_track_and_nested_title_do_not_drop_urls(self):
        with self.store.db() as db:
            db.execute('INSERT INTO records VALUES(?,?,?)', ('U011', 'media', json.dumps({
                'title': {'label': 'Video talk'}, 'track': ['理论学习', '项目案例'],
                'url': self.url, 'related_media': [{'url': 'https://player.vimeo.com/video/123'}]})))
        result = self.pipeline.seed([], include_records=True)
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['added'], 2)
        self.assertTrue(all(isinstance(s['channel'], str) for s in self.pipeline.sources()))
        self.assertEqual(self.pipeline.seed([])['errors'], [])

    def test_feed_media_enclosure_is_not_treated_as_article_text(self):
        self.response.update(metadata={'format': 'rss'}, links=[
            {'href': 'https://example.org/episode.mp3', 'kind': 'media'},
            {'href': 'https://example.org/episode', 'kind': 'entry'}])
        self.run_one()
        urls = [source['url'] for source in self.pipeline.sources()]
        self.assertIn('https://example.org/episode', urls)
        self.assertNotIn('https://example.org/episode.mp3', urls)

    def test_generic_navigation_links_are_not_crawled(self):
        self.response['links'] = [{'href': 'https://example.org/unrelated', 'kind': 'related'}]
        self.run_one()
        self.assertEqual(len(self.pipeline.sources()), 1)

    def test_cancellation_stops_new_requests_and_keeps_results(self):
        cancel = threading.Event()

        def acquire(url, **kwargs):
            cancel.set()
            return dict(self.response, url=url)

        self.pipeline.acquire_callable = acquire
        job = self.pipeline.enqueue([self.url, 'https://example.org/second', 'https://example.org/third'])
        result = self.pipeline.run_job(job['id'], cancel=cancel, max_workers=1)
        self.assertEqual(result['status'], 'CANCELLED')
        self.assertEqual(result['counts']['succeeded'], 1)
        self.assertEqual(result['counts']['cancelled'], 2)
        self.assertEqual(result['counts']['running'], 0)

    def test_restart_recovers_running_item(self):
        job = self.pipeline.enqueue([self.url])
        with self.store.db() as db:
            db.execute("UPDATE pipeline_jobs SET status='RUNNING' WHERE id=?", (job['id'],))
            db.execute("UPDATE pipeline_items SET status='RUNNING' WHERE jobId=?", (job['id'],))
        restarted = Pipeline(self.store, self.pipeline.acquire_callable)
        result = restarted.run_job(job['id'])
        self.assertEqual(result['status'], 'SUCCEEDED')
        self.assertEqual(len(self.calls), 1)

    def test_duplicate_pending_urls_are_not_enqueued_twice(self):
        one = self.pipeline.enqueue([self.url], force=True)
        two = self.pipeline.enqueue([self.url], force=True)
        self.assertEqual(one['total'], 1)
        self.assertEqual(two['total'], 0)
        self.pipeline.cancel_job(one['id'])
        three = self.pipeline.enqueue([self.url], force=True)
        self.assertEqual(three['total'], 1)

    def test_concurrent_requests_record_all_results(self):
        active = 0
        peak = 0
        lock = threading.Lock()
        overlap = threading.Event()

        def acquire(url, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                if active >= 2:
                    overlap.set()
            # Require actual overlap; a short sleep is flaky on a loaded host.
            if not overlap.wait(5):
                raise TimeoutError('No concurrent request entered')
            with lock:
                active -= 1
            if url.endswith('/3'):
                raise TimeoutError('Fixture timeout')
            return dict(self.response, url=url)

        self.pipeline.acquire_callable = acquire
        queued = self.pipeline.enqueue([f'https://example.org/{i}' for i in range(8)])
        result = self.pipeline.run_job(queued['id'], max_workers=4)
        self.assertEqual(result['counts']['succeeded'], 7)
        self.assertEqual(result['counts']['failed'], 1)
        self.assertGreater(peak, 1)
        self.assertLessEqual(peak, 4)
        self.assertEqual(self.pipeline.coverage()['attemptedUrls'], 8)

    def test_accepting_note_preserves_citation_and_does_not_self_verify(self):
        run = self.store.start('review test')
        doc = self.store.document(self.url, 'Original title', 'An exact original sentence for citation.', 'body_fetched_not_semantically_verified')
        note = self.store.submit(run, dict(track='theory', title='Theory', summary='AI note', analysis='Analysis', limitations='Unverified', nextStep='Read more',
                               documentId=doc['id'], sha256=doc['sha256'], quote='exact original sentence'))
        self.store.finish(run, True, {})
        accepted = self.pipeline.review(note['id'], 'accepted')
        self.assertFalse(accepted['independentlyVerified'])
        with self.store.db() as db:
            row = db.execute('SELECT * FROM notes WHERE id=?', (note['id'],)).fetchone()
            self.assertFalse(json.loads(row['payload'])['independentlyVerified'])
            db.execute('DELETE FROM documents WHERE id=?', (doc['id'],))
        with self.assertRaisesRegex(ValueError, 'CITATION_MISMATCH'):
            self.pipeline.review(note['id'], 'accepted')
        self.pipeline.review(note['id'], 'rejected')

    def test_url_validation_and_canonical_identity(self):
        self.assertEqual(normalize_url('https://EXAMPLE.org:443/a#section'), 'https://example.org/a')
        for value in ('file:///C:/data.txt', 'https://user:secret@example.org', 'http://localhost/', 'http://127.0.0.1/', 'http://169.254.169.254/'):
            with self.assertRaises(ValueError):
                self.pipeline.update_source({'url': value})


if __name__ == '__main__':
    unittest.main()

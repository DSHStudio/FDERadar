import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from agent import Store
from github_resources import GitHubResources, collection_lock, discovery_exclusion, fetch_public


class Clock:
    def __init__(self):
        self.value = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.value


class Fixture:
    def __init__(self):
        self.calls = []
        self.metadata_status = 200
        self.metadata_headers = {'etag': 'meta-v1', 'last-modified': 'Mon, 28 Sep 2026 10:00:00 GMT'}
        self.readme_status = 200
        self.readme = '# Actual source\n\nThis README is an original fixture explaining schemas, objects, governance and deployment.\n' * 2
        self.license = {'spdx_id': 'Apache-2.0', 'name': 'Apache License 2.0'}
        self.search_status = 200
        self.search_items = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if '/search/repositories?' in url:
            return {'status': self.search_status, 'headers': {}, 'body': json.dumps({'total_count': 145,
                    'incomplete_results': True, 'items': self.search_items}).encode(), 'url': url}
        if url.startswith('https://api.github.com/'):
            name = url.split('/repos/')[1]
            body = json.dumps({'full_name': name, 'private': False, 'description': 'Original description 未改写',
                               'default_branch': 'main', 'license': self.license, 'archived': False, 'fork': False,
                               'stargazers_count': 12, 'forks_count': 3, 'language': 'Python',
                               'pushed_at': '2026-09-25T12:00:00Z', 'topics': ['ontology']}).encode()
            return {'status': self.metadata_status, 'headers': self.metadata_headers, 'body': body, 'url': url}
        return {'status': self.readme_status, 'headers': {'etag': 'readme-v1', 'last-modified': 'Mon, 28 Sep 2026 11:00:00 GMT'},
                'body': self.readme.encode(), 'url': url}


class GitHubResourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'var')
        self.config = self.root / 'resources.json'
        self.config.write_text(json.dumps({'resources': [{'fullName': 'example/ontology', 'category': 'ontology',
                         'kind': 'framework', 'selectionReason': '编辑选入，不是项目证据'}], 'queries': []}), encoding='utf-8')
        self.fixture = Fixture()
        self.clock = Clock()
        self.collector = GitHubResources(self.store, self.config, self.fixture, self.clock)

    def tearDown(self):
        self.temp.cleanup()

    def test_actual_readme_document_raw_snapshot_and_metadata_are_separate(self):
        receipt = self.collector.refresh()
        self.assertEqual(receipt['status'], 'COMPLETED')
        state = self.collector.state()
        self.assertEqual(state['stats']['registered'], 1)
        self.assertEqual(state['stats']['metadataFetched'], 1)
        self.assertEqual(state['stats']['readmeFetched'], 1)
        repo = state['resources'][0]
        self.assertEqual(repo['description'], 'Original description 未改写')
        self.assertEqual(repo['license'], 'Apache-2.0')
        self.assertEqual(repo['readmeSha256'], hashlib.sha256(self.fixture.readme.encode()).hexdigest())
        document = self.store.read(repo['readmeDocumentId'])
        self.assertEqual(document['access'], 'github_readme')
        self.assertEqual(document['content'], self.fixture.readme)
        snapshot = self.store.directory / repo['metadataSnapshot']['path']
        self.assertEqual(json.loads(snapshot.read_bytes())['full_name'], 'example/ontology')
        self.assertTrue(repo['readmeSnapshot']['path'].endswith('.md'))

    def test_weekly_due_persists_across_instances_and_only_refreshes_when_due(self):
        self.collector.refresh()
        calls = len(self.fixture.calls)
        replacement = GitHubResources(self.store, self.config, self.fixture, self.clock)
        self.assertEqual(replacement.refresh()['status'], 'NOT_DUE')
        self.assertEqual(len(self.fixture.calls), calls)
        self.clock.value += timedelta(days=7)
        self.assertEqual(replacement.refresh()['status'], 'COMPLETED')
        self.assertGreater(len(self.fixture.calls), calls)

    def test_304_reuses_original_document_and_sends_both_validators(self):
        self.collector.refresh()
        old = self.collector.state()['resources'][0]
        self.fixture.metadata_status = self.fixture.readme_status = 304
        receipt = self.collector.refresh(force=True)
        self.assertEqual(receipt['items'][0]['status'], 'UNCHANGED')
        self.assertEqual(self.collector.state()['resources'][0]['readmeDocumentId'], old['readmeDocumentId'])
        for _, options in self.fixture.calls[-2:]:
            self.assertIn('If-None-Match', options['headers'])
            self.assertIn('If-Modified-Since', options['headers'])
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM documents').fetchone()[0], 1)

    def test_changed_readme_preserves_history_and_hashes(self):
        self.collector.refresh()
        original = self.collector.state()['resources'][0]
        self.fixture.readme += '\nA second version with changed source text.\n'
        self.collector.refresh(force=True)
        current = self.collector.state()['resources'][0]
        self.assertTrue(current['readmeChanged'])
        self.assertNotEqual(original['readmeDocumentId'], current['readmeDocumentId'])
        self.assertEqual(self.store.read(original['readmeDocumentId'])['content'], self.fixture.readme.split('\nA second version')[0])
        self.assertTrue((self.store.directory / original['readmeSnapshot']['path']).exists())

    def test_no_license_and_noassertion_never_claim_open_source_license(self):
        for license_value in [None, {'spdx_id': 'NOASSERTION', 'name': 'Other'}, {'spdx_id': 'NONE'}]:
            self.fixture.license = license_value
            self.collector.refresh(force=True)
            repo = self.collector.state()['resources'][0]
            self.assertIsNone(repo['license'])
            self.assertEqual(repo['licenseStatus'], 'unknown')

    def test_http_200_placeholder_is_not_readme_acquisition(self):
        self.fixture.readme = '<html><body>Loading...</body></html>'
        receipt = self.collector.refresh()
        self.assertEqual(receipt['status'], 'COMPLETED_WITH_GAPS')
        state = self.collector.state()
        self.assertEqual(state['stats']['metadataFetched'], 1)
        self.assertEqual(state['stats']['readmeFetched'], 0)
        self.assertEqual(state['resources'][0]['readmeStatus'], 'README_INSUFFICIENT')

    def test_rate_limit_persists_and_force_does_not_bypass_reset(self):
        self.fixture.metadata_status = 403
        self.fixture.metadata_headers = {'x-ratelimit-remaining': '0',
                    'x-ratelimit-reset': str(int((self.clock.value + timedelta(hours=2)).timestamp())),
                    'retry-after': '30'}
        first = self.collector.refresh()
        self.assertEqual(first['items'][0]['status'], 'PARTIAL')
        self.assertEqual(self.collector.state()['stats']['readmeFetched'], 1)
        api_before = len([u for u, _ in self.fixture.calls if u.startswith('https://api.')])
        replacement = GitHubResources(self.store, self.config, self.fixture, self.clock)
        replacement.refresh(force=True)
        self.assertEqual(len([u for u, _ in self.fixture.calls if u.startswith('https://api.')]), api_before)
        self.assertEqual(replacement.state()['resources'][0]['metadataStatus'], 'RATE_LIMITED')
        self.clock.value += timedelta(hours=3)
        self.fixture.metadata_status = 200
        self.fixture.metadata_headers = {}
        self.assertEqual(replacement.refresh(force=True)['items'][0]['status'], 'SUCCEEDED')

    def test_failed_refresh_keeps_previous_evidence_without_claiming_current_success(self):
        self.collector.refresh()
        old = self.collector.state()['resources'][0]
        self.fixture.metadata_status = self.fixture.readme_status = 404
        receipt = self.collector.refresh(force=True)
        current = self.collector.state()['resources'][0]
        self.assertEqual(receipt['items'][0]['status'], 'FAILED')
        self.assertEqual(current['lastSuccess'], old['lastSuccess'])
        self.assertEqual(current['readmeDocumentId'], old['readmeDocumentId'])
        self.assertEqual(current['readmeStatus'], 'README_NOT_FOUND')

    def test_invalid_source_does_not_issue_any_request(self):
        self.config.write_text(json.dumps({'resources': [{'fullName': 'https://localhost/private', 'category': 'fde'}]}))
        with self.assertRaisesRegex(ValueError, 'INVALID_GITHUB_REPOSITORY'):
            GitHubResources(self.store, self.config, self.fixture, self.clock)
        for url in ['http://github.com/example/repo', 'https://127.0.0.1/x', 'https://github.com@evil.example/repo']:
            with self.assertRaisesRegex(ValueError, 'INVALID_GITHUB_URL'):
                fetch_public(url)
        self.assertEqual(self.fixture.calls, [])

    def test_discovery_saves_real_page_and_registers_candidate_without_claiming_exhaustion(self):
        self.config.write_text(json.dumps({'resources': [], 'queries': [{'query': 'ontology fork:false', 'category': 'ontology'}]}))
        self.fixture.search_items = [{'full_name': 'new/ontology-agent', 'private': False, 'fork': False}]
        receipt = self.collector.refresh()
        discovery = receipt['discovery']
        self.assertEqual(discovery['registered'], ['new/ontology-agent'])
        self.assertEqual(discovery['queries'][0]['totalCount'], 145)
        self.assertTrue(discovery['queries'][0]['incompleteResults'])
        self.assertEqual(discovery['queries'][0]['page'], 1)
        new = [r for r in self.collector.state()['resources'] if r['fullName'].startswith('new/')][0]
        self.assertEqual(new['registration'], 'search_candidate')
        self.assertTrue(new['readmeDocumentId'])

    def test_failed_search_does_not_advance_cursor(self):
        self.config.write_text(json.dumps({'resources': [], 'queries': [{'query': 'ontology', 'category': 'ontology'},
                            {'query': 'data governance', 'category': 'governance'}]}))
        self.fixture.search_status = 403
        receipt = self.collector.refresh()
        self.assertEqual(receipt['discovery']['cursor'], 0)
        self.assertEqual(len(receipt['discovery']['queries']), 1)
        self.assertEqual(receipt['discovery']['status'], 'PARTIAL')

    def test_discovery_is_balanced_across_three_categories(self):
        self.config.write_text(json.dumps({'resources': [], 'queries': [
            {'query': category, 'category': category} for category in ['ontology', 'governance', 'fde']]}))
        fixture = self.fixture
        def varied_search(url, **kwargs):
            if '/search/repositories?' in url:
                from urllib.parse import parse_qs, urlsplit
                category = parse_qs(urlsplit(url).query)['q'][0]
                fixture.search_items = [{'full_name': category + '/candidate-' + str(i), 'private': False, 'fork': False} for i in range(10)]
            return fixture(url, **kwargs)
        self.collector.fetcher = varied_search
        receipt = self.collector.refresh()
        self.assertEqual(len(receipt['discovery']['queries']), 3)
        self.assertEqual(len(receipt['discovery']['registered']), 6)
        for category in ['ontology', 'governance', 'fde']:
            self.assertEqual(sum(name.startswith(category + '/') for name in receipt['discovery']['registered']), 2)

    def test_weekly_eligibility_is_monday_even_after_late_completion(self):
        self.clock.value = datetime(2026, 9, 28, 18, 55, tzinfo=timezone.utc)
        self.collector.refresh()
        resource = self.collector.state()['resources'][0]
        self.assertEqual(resource['nextDueAt'], '2026-10-05T00:00:00+00:00')
        self.clock.value = datetime(2026, 10, 5, 13, 0, tzinfo=timezone.utc)
        self.assertEqual(self.collector.refresh()['status'], 'COMPLETED')

    def test_recruiting_search_results_are_preserved_as_rejections_not_resources(self):
        self.config.write_text(json.dumps({'resources': [], 'queries': [{'query': 'FDE', 'category': 'fde'}]}))
        self.fixture.search_items = [
            {'full_name': 'akarshkudrimoti/f500-swe-radar', 'private': False, 'fork': False,
             'description': 'Live Summer 2027 software-engineering internship radar across the Fortune 500'},
            {'full_name': 'ApplyGuy/2027-New-Grad-Jobs', 'private': False, 'fork': False,
             'description': 'Verified 2027 new grad and entry-level software engineering jobs, updated automatically from employer career sites.'},
            {'full_name': 'example/fde-toolkit', 'private': False, 'fork': False,
             'description': 'FDE delivery toolkit with scheduled jobs and background task management.'},
        ]
        receipt = self.collector.refresh()
        query = receipt['discovery']['queries'][0]
        self.assertEqual([r['fullName'] for r in query['rejected']],
                         ['akarshkudrimoti/f500-swe-radar', 'ApplyGuy/2027-New-Grad-Jobs'])
        self.assertEqual(receipt['discovery']['registered'], ['example/fde-toolkit'])
        snapshot = json.loads((self.store.directory / query['snapshot']['path']).read_bytes())
        self.assertEqual(len(snapshot['items']), 3)
        self.assertIsNone(discovery_exclusion({'full_name': 'example/data-jobs', 'description': 'Governance framework for batch jobs.'}))
        self.assertIsNone(discovery_exclusion({'full_name': 'example/data-toolkit', 'description': 'Software engineering toolkit scheduling data ingestion jobs.'}))
        self.assertIsNone(discovery_exclusion({'full_name': 'example/fde-toolkit', 'description': 'Engineering toolkit; our team is hiring.'}))

    def test_review_exclusion_hides_active_resource_but_retains_history_and_skips_refresh(self):
        self.collector.refresh()
        resource = self.collector.state()['resources'][0]
        document_id = resource['readmeDocumentId']
        resource.update(reviewStatus='excluded', exclusionReason='Out of research scope')
        self.collector._save_resource(resource)
        state = self.collector.state()
        self.assertEqual(state['resources'], [])
        self.assertEqual(state['stats']['registered'], 0)
        self.assertEqual(state['stats']['readmeFetched'], 0)
        self.assertEqual(state['stats']['historicalRegistered'], 1)
        self.assertEqual(state['stats']['excluded'], 1)
        self.assertEqual(state['excluded'][0]['readmeDocumentId'], document_id)
        self.assertEqual(self.store.read(document_id)['content'], self.fixture.readme)
        calls = len(self.fixture.calls)
        self.assertEqual(self.collector.refresh(force=True)['status'], 'NOT_DUE')
        self.assertEqual(len(self.fixture.calls), calls)

    def test_process_lock_prevents_duplicate_collection(self):
        with collection_lock(self.store.directory):
            self.assertTrue(self.collector.state()['running'])
            self.assertEqual(self.collector.refresh(force=True)['status'], 'RUNNING')
        self.assertEqual(self.fixture.calls, [])


if __name__ == '__main__':
    unittest.main()

"""Guard against counting source registries or search limits as coverage."""
import json
import unittest

from source_coverage import build_coverage


class SourceCoverageTests(unittest.TestCase):
    def test_tools_are_not_sources_and_page_versions_do_not_complete_a_group(self):
        sources = [
            {
                'id': 'vendor', 'name': 'Vendor documentation',
                'source_kind': 'information_source_group',
                'urls': ['https://vendor.example/a', 'https://vendor.example/b'],
            },
            {
                'id': 'customer', 'name': 'Customer releases',
                'source_kind': 'information_source_group',
                'urls': ['https://customer.example/news'],
            },
            {
                'id': 'search_api', 'name': 'Search API documentation',
                'source_kind': 'acquisition_tool_not_information_source',
                'urls': ['https://search.example/docs'],
            },
        ]
        documents = [
            {'id': 'old', 'url': 'https://vendor.example/a', 'access': 'body_partial'},
            {'id': 'new', 'url': 'https://vendor.example/a',
             'access': 'body_fetched_not_semantically_verified'},
        ]
        events = [
            {'kind': 'fetch', 'payload': {'documentId': document['id'], 'url': document['url']}}
            for document in documents
        ]

        report = build_coverage(sources, documents, events)
        metrics = report['metrics']
        self.assertEqual(metrics['registryEntries'], 3)
        self.assertEqual(metrics['informationSourceGroups'], 2)
        self.assertEqual(metrics['acquisitionTools'], 1)
        self.assertEqual(metrics['registeredUrls'], 3)
        self.assertEqual(metrics['dshFetchedUrls'], 1)
        self.assertEqual(metrics['dshNonTruncatedUrls'], 1)
        self.assertEqual(metrics['registeredUrlsFetched'], 1)
        self.assertEqual(metrics['groupsWithAnyDshFetch'], 1)
        self.assertLess(metrics['registeredUrlsFetched'], metrics['registeredUrls'])
        self.assertEqual({group['id'] for group in report['sourceGroups']}, {'vendor', 'customer'})
        self.assertEqual(report['saturationStatus'], 'not_measured')
        self.assertIs(report['openWebExhausted'], False)

    def test_imported_text_without_a_matching_fetch_event_is_not_dsh_acquisition(self):
        sources = [{
            'id': 'research', 'name': 'Research sources',
            'source_kind': 'information_source_group',
            'urls': ['https://research.example/imported', 'https://research.example/fetched'],
        }]
        documents = [
            # Access labels alone cannot prove which collector obtained a document.
            {'id': 'imported', 'url': 'https://research.example/imported',
             'access': 'body_fetched_not_semantically_verified'},
            {'id': 'fetched', 'url': 'https://research.example/fetched',
             'access': 'body_fetched_not_semantically_verified'},
        ]
        events = [
            {'kind': 'fetch', 'payload': json.dumps({
                'documentId': 'fetched', 'url': 'https://research.example/fetched',
            })},
            # An event naming a missing document must not validate another document at its URL.
            {'kind': 'fetch', 'payload': {
                'documentId': 'missing', 'url': 'https://research.example/imported',
            }},
        ]

        metrics = build_coverage(sources, documents, events)['metrics']
        self.assertEqual(metrics['dshFetchedUrls'], 1)
        self.assertEqual(metrics['dshNonTruncatedUrls'], 1)
        self.assertEqual(metrics['registeredUrlsFetched'], 1)
        self.assertEqual(metrics['registeredUrls'], 2)

    def test_truncated_or_empty_search_results_never_establish_exhaustion(self):
        for truncated, results in [
            (True, [{'url': 'https://example.org/one'}]),
            (True, []),
            (False, []),
        ]:
            with self.subTest(truncated=truncated, result_count=len(results)):
                events = [{
                    'kind': 'search-leads',
                    'payload': {
                        'query': 'ontology FDE project evidence',
                        'result': {'sources': results, 'truncated': truncated},
                    },
                }]
                report = build_coverage([], [], events)
                self.assertEqual(report['metrics']['searchCalls'], 1)
                self.assertEqual(report['metrics']['truncatedSearchCalls'], int(truncated))
                self.assertEqual(report['metrics']['dshFetchedUrls'], 0)
                self.assertEqual(report['saturationStatus'], 'not_measured')
                self.assertIs(report['openWebExhausted'], False)


if __name__ == '__main__':
    unittest.main()

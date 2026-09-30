"""Conditional refreshes must retain the scope of previously saved text."""
from contextlib import contextmanager
import json
import sqlite3
import unittest

from catalog import catalog


class CatalogRefreshTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(':memory:')
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            CREATE TABLE records(category TEXT, payload TEXT);
            CREATE TABLE pipeline_items(id INTEGER PRIMARY KEY, result TEXT);
        """)
        self.addCleanup(self.connection.close)

    @contextmanager
    def db(self):
        yield self.connection

    def result(self, doc, access, metadata):
        value = dict(documentId=doc, access=access, metadata=metadata)
        self.connection.execute('INSERT INTO pipeline_items(result) VALUES(?)', (json.dumps(value),))

    def document(self, doc='saved'):
        return dict(id=doc, url='https://example.org/paper', title='Original title',
                    chars=4000, access='body_fetched_not_semantically_verified')

    def test_304_preserves_pdf_format_and_publication_date(self):
        self.result('saved', 'body_fetched_not_semantically_verified',
                    {'format': 'pdf', 'meta': {'article:published_time': '2026-01-01'}})
        self.result('saved', 'not_modified', {'receivedBytes': 0})
        self.result('saved', 'not_modified', {'receivedBytes': 0})
        actual, = catalog(self, [self.document()])
        self.assertEqual(actual['format'], 'pdf')
        self.assertEqual(actual['publishedAt'], '2026-01-01')

    def test_304_keeps_feed_as_listing_instead_of_article(self):
        self.result('saved', 'body_fetched_not_semantically_verified', {'format': 'rss'})
        self.result('saved', 'not_modified', {'receivedBytes': 0})
        actual, = catalog(self, [self.document()])
        self.assertEqual(actual['format'], 'rss')
        self.assertEqual(actual['quality'], 'listing')

    def test_new_document_does_not_inherit_another_versions_format(self):
        self.result('saved', 'body_fetched_not_semantically_verified', {'format': 'pdf'})
        self.result('new', 'not_modified', {})
        original, new = catalog(self, [self.document(), self.document('new')])
        self.assertEqual(original['format'], 'pdf')
        self.assertEqual(new['format'], 'unknown')


if __name__ == '__main__':
    unittest.main()

"""Regression checks for source-first case cards, separate from AI analysis."""
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import tempfile
import unittest

from agent import Store, digest


class DetailsParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.details = []

    def handle_starttag(self, tag, attrs):
        if tag == 'details':
            self.details.append(dict(attrs))


class OriginalCaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))
        self.run = self.store.start('source presentation test')
        self.source_text = 'Source words retain their original meaning.\n' + 'Additional source paragraph.\n' * 700
        self.doc = self.store.document(
            'https://example.org/original-case', 'Original 标题 & <source>',
            self.source_text, 'body_fetched_not_semantically_verified')
        self.note = dict(
            track='case', title='MODEL_TITLE_MARKER', summary='MODEL_SUMMARY_MARKER',
            analysis='MODEL_ANALYSIS_MARKER', limitations='MODEL_LIMITATIONS_MARKER',
            nextStep='MODEL_NEXT_STEP_MARKER', documentId=self.doc['id'],
            sha256=self.doc['sha256'], quote='Source words retain their original meaning.')
        compliant = dict(self.note, title=self.doc['title'], summary=self.note['quote'])
        self.note_id = self.store.submit(self.run, compliant)['id']
        self.store.finish(self.run, True, {})
        # Model the historical notes written before source-preserving submission.
        with self.store.db() as db:
            row = db.execute('SELECT payload FROM notes WHERE id=?', (self.note_id,)).fetchone()
            payload = dict(json.loads(row['payload']), title=self.note['title'], summary=self.note['summary'])
            db.execute('UPDATE notes SET title=?,payload=? WHERE id=?',
                       (self.note['title'], json.dumps(payload), self.note_id))

    def tearDown(self):
        self.temp.cleanup()

    def rendered(self):
        report = self.store.export()
        page = (Path(self.temp.name) / 'index.html').read_text(encoding='utf-8')
        markdown = (Path(self.temp.name) / '研究结果.md').read_text(encoding='utf-8')
        return report, page, markdown

    def section(self, page, id):
        match = re.search(r'<section\b[^>]*\bid=[\"\']' + re.escape(id) + r'[\"\'][^>]*>(.*?)</section>', page, re.S)
        self.assertIsNotNone(match, f'Missing section {id}')
        return match.group(1)

    def assert_no_model_case_body(self, page, markdown):
        section = self.section(page, 'case')
        lines = markdown.splitlines()
        start = next((i for i, line in enumerate(lines) if line.startswith('## 项目案例')), None)
        self.assertIsNotNone(start, 'Missing case section in Markdown export')
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith('## ')), len(lines))
        case_markdown = '\n'.join(lines[start:end])
        for field in ('title', 'summary', 'analysis', 'limitations', 'nextStep'):
            self.assertNotIn(self.note[field], section)
            self.assertNotIn(self.note[field], case_markdown)
        return section, case_markdown

    def test_case_uses_source_metadata_and_exact_excerpt(self):
        report, page, markdown = self.rendered()
        source, = report['caseSources']
        for key in ('title', 'url', 'documentId', 'sha256', 'quote', 'retrievedAt', 'access', 'available'):
            self.assertIn(key, source)
        self.assertTrue(source['available'])
        self.assertEqual(source['title'], self.doc['title'])
        self.assertEqual(source['url'], self.doc['url'])
        self.assertEqual(source['documentId'], self.doc['id'])
        self.assertEqual(source['sha256'], self.doc['sha256'])
        self.assertEqual(source['retrievedAt'], self.doc['retrievedAt'])
        self.assertEqual(source['quote'], self.note['quote'])
        section, case_markdown = self.assert_no_model_case_body(page, markdown)
        self.assertIn(html.escape(self.doc['title']), section)
        self.assertNotIn('<source>', section)
        self.assertIn(self.note['quote'], html.unescape(section))
        self.assertIn(self.doc['url'], section)
        self.assertIn(self.doc['url'], case_markdown)
        self.assertNotIn(self.source_text, html.unescape(section))
        self.assertEqual((Path(self.temp.name) / 'documents' / (self.doc['id'] + '.txt')).read_text(encoding='utf-8'), self.source_text)

    def test_ai_analysis_is_separate_and_collapsed(self):
        _, page, markdown = self.rendered()
        self.assert_no_model_case_body(page, markdown)
        analysis = self.section(page, 'case-analysis')
        self.assertIn(self.note['summary'], analysis)
        self.assertIn(self.note['analysis'], analysis)
        parser = DetailsParser()
        parser.feed(analysis)
        self.assertTrue(parser.details, 'AI notes must be in a collapsible element')
        self.assertTrue(all('open' not in attrs for attrs in parser.details))

    def test_missing_document_does_not_fall_back_to_ai_text(self):
        with self.store.db() as db:
            db.execute('DELETE FROM documents WHERE id=?', (self.doc['id'],))
        report, page, markdown = self.rendered()
        source, = report['caseSources']
        self.assertFalse(source['available'])
        section, _ = self.assert_no_model_case_body(page, markdown)
        self.assertIn(self.doc['url'], section)
        self.assertNotIn(self.note['quote'], section)

    def test_wrong_version_does_not_present_an_unmatched_excerpt(self):
        with self.store.db() as db:
            row = db.execute('SELECT payload FROM notes WHERE id=?', (self.note_id,)).fetchone()
            payload = json.loads(row['payload'])
            payload['sha256'] = digest('different version')
            db.execute('UPDATE notes SET payload=? WHERE id=?', (json.dumps(payload), self.note_id))
        report, page, markdown = self.rendered()
        source, = report['caseSources']
        self.assertFalse(source['available'])
        section, _ = self.assert_no_model_case_body(page, markdown)
        self.assertIn(self.doc['url'], section)
        self.assertNotIn(self.note['quote'], section)

    def test_partial_source_retains_acquisition_status(self):
        with self.store.db() as db:
            db.execute('UPDATE documents SET access=? WHERE id=?', ('body_partial', self.doc['id']))
        report, _, _ = self.rendered()
        source, = report['caseSources']
        self.assertTrue(source['available'])
        self.assertEqual(source['access'], 'body_partial')

    def test_new_case_cannot_rewrite_source_title_or_excerpt(self):
        run = self.store.start('reject rewritten source')
        compliant = dict(self.note, title=self.doc['title'], summary=self.note['quote'])
        for changed in ({'title': 'Model-generated title'}, {'summary': 'Model-generated summary'}):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(ValueError, 'CASE_MUST_PRESERVE_SOURCE'):
                    self.store.submit(run, dict(compliant, **changed))


if __name__ == '__main__':
    unittest.main()

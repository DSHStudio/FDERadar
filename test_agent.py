import tempfile
import unittest
from pathlib import Path
from agent import Bridge, PageText, Store, digest


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name))
        self.run=self.store.start('test')
        self.doc=self.store.document('https://example.org/paper','paper','Verified source text, with an explicit concept and relation.','body_fetched_not_semantically_verified')
        self.note=dict(track='theory',title='t',summary='s',analysis='a',limitations='l',nextStep='n',
                       documentId=self.doc['id'],sha256=self.doc['sha256'],quote='an explicit concept')

    def tearDown(self): self.temp.cleanup()

    def test_fabricated_quote_rejected(self):
        with self.assertRaisesRegex(ValueError,'CITATION_MISMATCH'):
            self.store.submit(self.run,{**self.note,'quote':'A completely fabricated customer'})

    def test_wrong_version_rejected(self):
        with self.assertRaisesRegex(ValueError,'CITATION_MISMATCH'):
            self.store.submit(self.run,{**self.note,'sha256':digest('other')})

    def test_claim_cannot_self_verify(self):
        with self.assertRaisesRegex(ValueError,'INVALID_NOTE'):
            self.store.submit(self.run,{**self.note,'independentlyVerified':True})

    def test_idempotent_note_and_document(self):
        a=self.store.submit(self.run,self.note);b=self.store.submit(self.run,self.note)
        self.assertEqual(a['id'],b['id'])
        d=self.store.document(self.doc['url'],self.doc['title'],self.doc['content'],self.doc['access'])
        self.assertEqual(d['id'],self.doc['id'])

    def test_failed_run_never_publishes(self):
        self.store.submit(self.run,self.note)
        self.store.finish(self.run,False,{'error':'cancelled'})
        self.assertEqual(self.store.library('notes')['items'],[])
        with self.assertRaisesRegex(ValueError,'RUN_CLOSED'): self.store.submit(self.run,self.note)

    def test_completed_run_only_pending_review(self):
        self.store.submit(self.run,self.note)
        self.store.finish(self.run,True,{})
        self.assertEqual(self.store.library('notes')['items'][0]['status'],'pending_review')

    def test_fetch_failure_not_reported_as_no_update(self):
        bridge=Bridge(self.store,self.run,{'maxModelRequests':2})
        bridge.dispatch('/fetch-result',{'requestedUrl':'https://example.org/blocked','result':
            dict(url='https://example.org/blocked',statusCode=403,body={'kind':'text','content':'denied'})})
        result=self.store.finish(self.run,True,{})
        self.assertEqual(result['status'],'COMPLETED_WITH_SOURCE_WARNINGS')
        self.assertEqual(result['acquisitionWarnings'],1)

    def test_unknown_tool_catalog_rejected(self):
        bridge=Bridge(self.store,self.run,{'maxModelRequests':2})
        with self.assertRaisesRegex(ValueError,'UNEXPECTED_TOOL_CATALOG'):
            bridge.dispatch('/model-request',{'toolNames':['Shell']})

    def test_empty_or_http_error_not_evidence(self):
        for code,text in [(403,'denied'),(200,'loading')]:
            result=self.store.fetched({'result':dict(url='https://example.org/other',statusCode=code,body={'kind':'text','content':text})})
            self.assertNotIn('id',result)

    def test_parser_removes_scripts_and_hidden_text(self):
        parser=PageText();parser.feed('<h1>Visible</h1><script>fake()</script><div hidden>Secret</div><p>Real text</p>')
        self.assertEqual(parser.text(),'Visible\nReal text')

    def test_new_source_version_does_not_replace_old(self):
        other=self.store.document(self.doc['url'],'changed','New version of source','body_fetched_not_semantically_verified')
        self.assertNotEqual(other['id'],self.doc['id'])
        self.assertEqual(self.store.read(self.doc['id'])['sha256'],self.doc['sha256'])


if __name__=='__main__': unittest.main()

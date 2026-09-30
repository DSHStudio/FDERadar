import json
import tempfile
import unittest
from pathlib import Path
from agent import Store
from workbench import Workbench
from catalog import catalog


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name));self.app=Workbench(self.store,{})
    def tearDown(self): self.temp.cleanup()

    def test_search_matches_saved_body_without_wildcard_expansion(self):
        doc=self.store.document('https://example.org/a','原标题','This source mentions 国能 and a 20% change.','body_fetched_not_semantically_verified')
        other=self.store.document('https://example.org/b','另一个标题','No matching text.','body_fetched_not_semantically_verified')
        self.assertEqual(self.app.search('国能')['ids'],[doc['id']])
        self.assertEqual(self.app.search('%')['ids'],[doc['id']])
        self.assertEqual(self.app.document(doc['id'])['title'],'原标题')

    def test_specific_reading_scope_is_not_overwritten_by_generic_parser_label(self):
        doc=self.store.document('https://arxiv.org/abs/2404.06571','Source abstract','Source abstract text.','body_fetched_not_semantically_verified')
        with self.store.db() as db:
            db.execute('INSERT INTO pipeline_jobs(id,status,reason,createdAt) VALUES(?,?,?,?)',('j','COMPLETED','test','2026'))
            db.execute('INSERT INTO pipeline_items(jobId,url,status,result) VALUES(?,?,?,?)',('j',doc['url'],'SUCCEEDED',json.dumps({'documentId':doc['id'],'metadata':{'format':'html','bodyScope':'extracted_visible_text'}})))
        value={**doc,'chars':20};catalog(self.store,[value])
        self.assertEqual(value['quality'],'metadata_only');self.assertIn('摘要',value['contentScope'])

    def test_transcript_is_not_mistaken_for_video_landing_page(self):
        doc=self.store.document('https://www.youtube.com/watch?v=source','Original video title','[00:00] Original caption','transcript_auto')
        value={**doc,'chars':25};catalog(self.store,[value])
        self.assertEqual(value['format'],'transcript');self.assertEqual(value['quality'],'evidence_text')
        self.assertIn('不是DSH自动视频转写',value['contentScope'])

    def test_long_document_keyword_read_is_real_text_with_offset(self):
        text='a'*18000+'FDE exact source paragraph'+'b'*20000
        doc=self.store.document('https://example.org/report','Report',text,'body_fetched_not_semantically_verified')
        read=self.store.read(doc['id'],query='FDE')
        self.assertEqual(read['matchOffset'],18000)
        self.assertEqual(read['content'],text[read['offset']:read['offset']+14000])

    def test_metadata_only_cannot_be_submitted_as_case(self):
        doc=self.store.document('https://example.org/video','Original','This is metadata, no source body.','metadata_only')
        run=self.store.start('test')
        with self.assertRaisesRegex(ValueError,'SOURCE_BODY_NOT_AVAILABLE'):
            self.store.submit(run,dict(track='case',title='Original',summary='This is metadata',quote='This is metadata',
                documentId=doc['id'],sha256=doc['sha256'],analysis='a',limitations='l',nextStep='n'))


if __name__=='__main__':unittest.main()

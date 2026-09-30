"""Evidence integrity, freshness and local progress persistence; no network or LLM."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent import Store
from research import ResearchService
from workbench import Workbench


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.store = Store(self.path / 'data')
        self.config_dir = self.path / 'config'
        self.config_dir.mkdir()
        self.doc = self.store.document('https://example.org/source', 'Original source title',
            'A source says project exists. This is not an independent verification.', 'body_fetched_not_semantically_verified')
        self.ref = dict(documentId=self.doc['id'],sha256=self.doc['sha256'],quote='project exists')
        self.cases = {'cases':[{'id':'case-a','title':'Original source title','claims':[
            {'key':'project','status':'disclosed','value':'项目披露','evidence':[self.ref]},
            {'key':'price','status':'unknown','value':'未披露','evidence':[]}]}]}
        self.curriculum = {'learning':[{'id':'learn-a','sourceRefs':[self.ref]}],
            'repoGuides':[{'fullName':'test/repo','artifacts':[{'documentId':self.doc['id'],'sha256':self.doc['sha256']}]}]}
        self.write_configs()
        self.service = ResearchService(self.store,self.config_dir)

    def write_configs(self):
        for name,value in [('research-cases.json',self.cases),('research-learning.json',self.curriculum)]:
            (self.config_dir/name).write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')

    def test_matching_reference_preserves_original_and_unknown(self):
        state=self.service.state()
        self.assertEqual(state['audit']['invalidReferences'],0)
        self.assertEqual(state['audit']['unresolvedClaims'],1)
        self.assertFalse(state['cases'][0]['independentlyVerified'])
        self.assertEqual(state['cases'][0]['claims'][0]['evidence'][0]['title'],'Original source title')
        with self.store.db() as db:
            saved=db.execute('SELECT content,sha256 FROM documents WHERE id=?',(self.doc['id'],)).fetchone()
        self.assertEqual(hashlib.sha256(saved['content'].encode()).hexdigest(),saved['sha256'])

    def test_wrong_quote_or_hash_cannot_remain_disclosed(self):
        for changed in ({'quote':'invented quote'},{'sha256':'0'*64},{'documentId':'missing'}):
            with self.subTest(changed=changed):
                self.cases['cases'][0]['claims'][0]['evidence']=[{**self.ref,**changed}]
                self.write_configs()
                state=self.service.state()
                self.assertEqual(state['cases'][0]['claims'][0]['status'],'unknown')
                self.assertGreater(state['audit']['invalidReferences'],0)

    def test_database_corruption_is_detected_not_merely_stored_hash_match(self):
        with self.store.db() as db: db.execute('UPDATE documents SET content=? WHERE id=?',('tampered project exists',self.doc['id']))
        state=self.service.state()
        self.assertEqual(state['cases'][0]['claims'][0]['status'],'unknown')
        self.assertIn('自身哈希',state['audit']['invalidDetails'][0]['reason'])

    def test_updated_url_marks_old_reference_stale_without_replacing_quote(self):
        newer=self.store.document('https://example.org/source/','Updated title','project exists with changed scope','body_fetched_not_semantically_verified')
        state=self.service.state()
        ref=state['cases'][0]['claims'][0]['evidence'][0]
        self.assertTrue(ref['valid'])
        self.assertTrue(ref['stale'])
        self.assertEqual(ref['documentId'],self.doc['id'])
        self.assertEqual(ref['latestDocumentId'],newer['id'])
        self.assertEqual(len(state['changes']),1)

    def test_same_content_hash_does_not_create_change_event(self):
        self.store.document('https://other.example/source','Mirrored title',self.doc['content'],'body_fetched_not_semantically_verified')
        self.assertEqual(self.service.state()['changes'],[])

    def test_learning_progress_persists_and_records_history(self):
        self.service.progress(dict(id='learn-a',status='in_progress',notes='原文定位与练习'))
        self.service.progress(dict(id='learn-a',status='completed',notes='自行复核，非企业验收'))
        value=ResearchService(self.store,self.config_dir).state()['learning'][0]['progress']
        self.assertEqual(value['status'],'completed')
        with self.store.db() as db: self.assertEqual(db.execute('SELECT count(*) FROM research_progress_events').fetchone()[0],2)

    def test_progress_rejects_unknown_ids_status_and_oversize_input(self):
        for data in [dict(id='missing',status='completed'),dict(id='learn-a',status='verified'),dict(id='learn-a',status='completed',notes='x'*6001)]:
            with self.subTest(data=str(data)[:100]),self.assertRaises(ValueError):self.service.progress(data)

    def test_get_state_is_read_only_and_network_free(self):
        with self.store.db() as db: before=db.execute('SELECT total_changes()').fetchone()[0]
        with patch('socket.create_connection',side_effect=AssertionError('no network')):
            self.service.state()
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM research_progress_events').fetchone()[0],0)

    def test_invalid_config_is_reported_without_inventing_case(self):
        (self.config_dir/'research-cases.json').write_text('{',encoding='utf-8')
        state=self.service.state()
        self.assertEqual(state['cases'],[])
        self.assertTrue(state['audit']['configErrors'])

    def test_artifact_read_uses_closed_allowlist(self):
        app=Workbench(self.store,{})
        id='labrun-'+'a'*32
        path=self.store.directory/'lab'/id
        path.mkdir(parents=True)
        (path/'试点准备包.md').write_text('# 合成数据',encoding='utf-8')
        self.assertEqual(app.lab_artifact(id,'pilotPack')['text'],'# 合成数据')
        for bad_id,name in [('../config','receipt'),(id,'../../config.json'),('labrun-no','pilotPack')]:
            with self.subTest(id=bad_id,name=name),self.assertRaises(ValueError):app.lab_artifact(bad_id,name)
        (path/'inputs').mkdir()
        (path/'inputs/ontology_dsh-Q1.json').write_text('{"synthetic":true}',encoding='utf-8')
        self.assertEqual(app.lab_artifact(id,'input','ontology_dsh-Q1')['text'],'{"synthetic":true}')
        for item in ['../../config-reference','ontology_dsh-Q99','retrieval_dsh-Q1/../../config-reference']:
            with self.subTest(item=item),self.assertRaises(ValueError):app.lab_artifact(id,'input',item)

    def test_agent_research_index_requires_original_citations(self):
        with patch('research.ResearchService',return_value=self.service):
            index=self.store.library('research')
            self.assertEqual(index['items'],[])
            selected=self.store.library('research','learn-a')
            self.assertEqual(selected['items'][0]['sourceRefs'][0]['documentId'],self.doc['id'])
            self.assertNotIn('progress',selected['items'][0])
            self.assertIn('不是独立证据',selected['meaning'])


if __name__=='__main__':unittest.main()

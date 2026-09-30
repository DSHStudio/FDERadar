"""Run a bounded continuation: new sources and specifically repairable acquisition gaps."""
import json
from pathlib import Path
from agent import Store
from pipeline import Pipeline

ROOT=Path(__file__).resolve().parent

if __name__=='__main__':
    store=Store(ROOT/'var');pipeline=Pipeline(store);pipeline.seed()
    selected=[]
    for source in pipeline.sources():
        if not source['enabled']: continue
        if (not source['lastAttempt'] or source['access']=='body_partial' or
                'CERTIFICATE_VERIFY_FAILED' in (source.get('error') or '') or
                ('investors.palantir.com/news' in source['url'] or 'youtube.com/watch' in source['url']) and source['access']=='body_fetched_not_semantically_verified'):
            selected.append(source['url'])
    job=pipeline.enqueue(urls=selected,force=True,limit=250,reason='新增材料与PDF/证书/正文质量修复')
    print(json.dumps({'jobId':job['id'],'planned':job['total']},ensure_ascii=False),flush=True)
    result=pipeline.run_job(job['id'],max_workers=6)
    store.export()
    print(json.dumps({'jobId':job['id'],'status':result['status'],'counts':result['counts'],'coverage':pipeline.coverage()},ensure_ascii=False),flush=True)

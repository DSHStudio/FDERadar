"""Retry transient gaps with one worker, respecting academic-site crawl delays."""
import json
from functools import partial
from pathlib import Path
from agent import Store
from acquisition import acquire
from pipeline import Pipeline

ROOT=Path(__file__).resolve().parent

if __name__=='__main__':
    store=Store(ROOT/'var');p=Pipeline(store,partial(acquire,timeout=90,max_bytes=16*1024*1024))
    p.seed()
    p.update_source({'url':'https://rss.arxiv.org/rss/cs.AI','discoveryLimit':0,'cadenceHours':24})
    selected=[s['url'] for s in p.sources() if s['enabled'] and (not s['lastAttempt'] or
        s['access'] in {'robots_deferred','network_error','response_too_large'} or
        s['url'] in {'https://wap.eastmoney.com/a/202609033864252617.html','https://www.deepexi.com/company'})]
    job=p.enqueue(urls=selected,force=True,limit=100,reason='遵循站点间隔的暂时失败重试及官方文字稿补采')
    print(json.dumps({'jobId':job['id'],'planned':job['total']},ensure_ascii=False),flush=True)
    result=p.run_job(job['id'],max_workers=1)
    store.export()
    print(json.dumps({'jobId':job['id'],'status':result['status'],'counts':result['counts']},ensure_ascii=False),flush=True)

"""One unattended, bounded acquisition-and-analysis cycle invoked by the existing heartbeat."""
import argparse
import json
from agent import Store,execute,utc,ROOT
from acquisition import acquire
from functools import partial
from pipeline import Pipeline
from expand_collection import expand
from catalog import catalog


def cycle(store,config,scheduled=False,analysis_limit=3):
    receipt={'startedAt':utc(),'trigger':'scheduled' if scheduled else 'manual','jobs':[],'analysis':None,'analyses':[]}
    # This daily entry point checks the independent seven-day GitHub clock.
    # A source failure must not suppress the established research cycle.
    from github_resources import GitHubResources
    try:
        receipt['githubResources']=GitHubResources(store).refresh(force=False)
    except Exception as exc:
        receipt['githubResources']={'status':'FAILED','error':type(exc).__name__}
    pipeline=Pipeline(store,partial(acquire,timeout=90))
    store.import_corpus((ROOT/config['corpusPath']).resolve());pipeline.seed()
    first=pipeline.enqueue(limit=200,reason='daily_due_sources')
    job=pipeline.run_job(first['id'],max_workers=4)
    receipt['jobs'].append({k:job[k] for k in ['id','status','counts','total']})
    expand(store)
    new_urls=[s['url'] for s in pipeline.sources() if s['enabled'] and not s['lastAttempt']]
    follow=pipeline.enqueue(urls=new_urls,limit=50,reason='bounded_discovered_sources')
    job=pipeline.run_job(follow['id'],max_workers=2)
    receipt['jobs'].append({k:job[k] for k in ['id','status','counts','total']})
    with store.db() as db:
        docs=[dict(r) for r in db.execute("SELECT id,url,title,sha256,access,retrievedAt,length(content) chars FROM documents WHERE access='body_fetched_not_semantically_verified' ORDER BY retrievedAt DESC")]
        processed={r[0] for r in db.execute("SELECT json_extract(payload,'$.documentId') FROM notes WHERE status IN ('pending_review','accepted','rejected')")}
    docs=[d for d in catalog(store,docs) if d['quality']=='evidence_text' and d['id'] not in processed][:analysis_limit]
    for document in docs:
        selected={k:document[k] for k in ['id','url','title','tracks','contentScope']}
        task=('增量资料学习加工。只阅读以下真实入库文档，不进行搜索、不重新获取。每份先radar_read后产出至多1条有精确短引的笔记；内容不足不强行提交。'+
            '根据实际原文选择theory/case/scenario。案例原标题、quote、summary原样保留，FDE/本体/上线/收益分别判断，未披露写未知。目录/简介不扩写全文；论文不是企业项目；观点和供应商自报不是已验证成效。'+
            '本轮仅处理这一份，analysis控制在300中文字、limitations在150字、nextStep在100字左右；不要整篇复制长文。'+json.dumps(selected,ensure_ascii=False))
        # Each source has its own model budget and receipt; a long report cannot discard other completed notes.
        try:
            analysis=execute(store,config,task)
        except Exception as exc:
            analysis={'status':'FAILED','error':type(exc).__name__}
        receipt['analyses'].append({'documentId':document['id'],**analysis})
        receipt['analysis']=analysis
    store.export()
    from research import ResearchService
    try:
        receipt['researchAudit']=ResearchService(store).export()
    except Exception as exc:
        receipt['researchAudit']={'status':'FAILED','error':type(exc).__name__}
    # Report CLI owns argument parsing; invoked in a child to preserve the caller's args.
    import subprocess,sys
    subprocess.run([sys.executable,str(ROOT/'collection_report.py'),'--data',str(store.directory)],check=True,cwd=ROOT,
                   stdout=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    receipt.update(endedAt=utc(),coverage=pipeline.coverage())
    receipt['status']='COMPLETED_WITH_GAPS' if any(j['counts']['failed'] or j['counts']['partial'] for j in receipt['jobs']) else 'COMPLETED'
    if receipt['githubResources'].get('status') in {'FAILED','PARTIAL','RATE_LIMITED','INTERRUPTED','COMPLETED_WITH_GAPS'}:
        receipt['status']='COMPLETED_WITH_GAPS'
    if any(a['status']=='FAILED' for a in receipt['analyses']):receipt['status']='ANALYSIS_FAILED'
    if receipt['researchAudit'].get('status')=='FAILED' or receipt['researchAudit'].get('audit',{}).get('invalidReferences'):
        receipt['status']='COMPLETED_WITH_GAPS'
    (store.directory/'cycle-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    if scheduled:
        (store.directory/'schedule-state.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--scheduled',action='store_true');parser.add_argument('--analysis-limit',type=int,choices=range(0,4),default=3)
    args=parser.parse_args();cfg=json.loads((ROOT/'config.json').read_text(encoding='utf-8-sig'))
    value=cycle(Store(ROOT/'var'),cfg,args.scheduled,args.analysis_limit)
    print(json.dumps(value,ensure_ascii=False,indent=2))

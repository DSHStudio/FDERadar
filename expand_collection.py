"""Select relevant links actually observed on source pages, preserving their provenance."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from agent import Store
from pipeline import Pipeline

ROOT=Path(__file__).resolve().parent


def expand(store):
    selected={}
    with store.db() as db:
        rows=db.execute('SELECT url,result FROM pipeline_items WHERE result IS NOT NULL').fetchall()
    for row in rows:
        result=json.loads(row['result'])
        for link in result.get('links',[]):
            url=link.get('href','');title=link.get('title','').strip();parts=urlsplit(url)
            keep=False;channel='技术与原始材料'
            if row['url']=='https://www.cognite.com/en/resources/customer-stories':
                keep=parts.hostname=='www.cognite.com' and parts.path.startswith('/en/resources/customer-stories/')
                channel='非Palantir制造与经营案例'
            elif row['url']=='https://a16z.com/podcasts/a16z-show/':
                keep=parts.hostname=='a16z.com' and parts.path.startswith('/podcast/') and any(t in title.lower() for t in ['karp','palantir','how enterprise ai really','building ai agents for enterprise','big ideas 2026: the enterprise'])
                channel='播客与创始人访谈'
            elif 'arxiv.org/abs/' in row['url']:
                keep=parts.hostname=='arxiv.org' and parts.path.startswith(('/pdf/','/html/'))
                channel='研究论文全文'
            elif row['url']=='https://rss.arxiv.org/rss/cs.AI':
                keep=parts.hostname=='arxiv.org' and parts.path.startswith('/abs/') and any(t in title.lower() for t in ['ontology','knowledge graph','manufactur','industrial'])
                channel='增量订阅相关论文候选'
            elif row['url']=='https://sierra.ai/uk/rss.xml':
                keep=parts.hostname=='sierra.ai' and parts.path.startswith('/uk/blog/') and any(t in (title+' '+parts.path).lower() for t in [
                    'change agents:', 'ai-agents-in-action', 'agent engineer', 'agent strategist',
                    'agent-development-life-cycle', 'shipping-and-scaling', 'enterprise-grade-agents',
                    'context-engineering', 'mcp-gateway', 'agent-data-platform', 'siriusxm',
                    'workspaces', 'model-failover', 'agent-traces', 'agent-monitoring',
                    'load-testing', 'real-world scenarios', 'rollout guide', 'sierra-and-stellarus'])
                channel='同类公司原始案例与交付方法（不自动认定FDE项目）'
            elif row['url'] in {'https://www.aboutamazon.com/rss/feed.rss','https://aws.amazon.com/blogs/media/feed/','https://tomgruber.org/feed/'}:
                keep=any(t in title.lower() for t in ['ontology','forward deployed','forward-deployed','knowledge graph','agent','seller assistant','production scheduling'])
                channel='企业与作者订阅相关候选（需核对适用范围）'
            if keep:
                selected[url]={'url':url,'title':title or url,'channel':channel,'discoveredFrom':row['url'],
                    'stage':'candidate','dshTested':False,'discoveryLimit':0,'caution':'从已取得原始页面发现；需单独获取并核对相关性、年代与证据范围。'}
    target=ROOT/'config'/'source-discovery-linked-live.json'
    target.write_text(json.dumps({'candidates':list(selected.values())},ensure_ascii=False,indent=2),encoding='utf-8')
    pipeline=Pipeline(store);result=pipeline.seed()
    for candidate in selected.values():
        pipeline.update_source({'url':candidate['url'],'discoveredFrom':candidate['discoveredFrom'],'discoveryLimit':0})
    # Footer policy PDFs and unrelated investments do not advance this research scope.
    excluded=[]
    for source in pipeline.sources():
        if source.get('discoveredFrom') in {'https://sierra.ai/uk/rss.xml','https://rss.arxiv.org/rss/cs.AI'} or source['channel']=='研究论文全文':
            pipeline.update_source({'url':source['url'],'discoveryLimit':0})
        label=(source['title']+' '+source['url']).lower()
        if source.get('discoveredFrom') and any(x in label for x in ['human rights policy','code of conduct','market%20corrections','privacy-policy','privacy_policy']):
            pipeline.update_source({'url':source['url'],'enabled':False,'origin':'scope_excluded_unrelated_footer'})
            excluded.append(source['url'])
    return {'linkedCandidates':len(selected),'seed':result,'excluded':excluded}


if __name__=='__main__': print(json.dumps(expand(Store(ROOT/'var')),ensure_ascii=False))

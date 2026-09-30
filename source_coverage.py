"""Measure recorded acquisition coverage without claiming search exhaustiveness."""
from datetime import datetime, timezone
import html
import json
from urllib.parse import urlsplit, urlunsplit


SOURCE_AXES = [
    ('Palantir理论与工程', ['palantir_docs','palantir_news','palantir_osdk','palantir_learning','palantir_devcon_media']),
    ('其他厂商与FDE团队', ['aws','openai_stories','anthropic_stories','baseten_fde','decagon_delivery','distyl_engineering','sierra_agent_engineering']),
    ('中国企业与交付社区', ['volc_practitioner_events','tencent_fde_research']),
    ('客户／公告／采购', ['customer_news','cninfo','procurement']),
    ('独立新闻原始采访', ['original_news_interviews']),
    ('新闻稿分发（非独立报道）', ['businesswire_original']),
    ('学术作者与大学', ['ontology_foundations','stanford_ontology_research','china_university_research']),
    ('视频与大会', ['founder_video_interviews','palantir_devcon_media']),
    ('播客', ['founder_podcasts']),
    ('著作', ['research_books']),
    ('纪录片', ['ai_documentaries']),
    ('案例汇编线索', ['datawhale']),
]


def normalized_url(url):
    try:
        value=urlsplit(url)
        if value.scheme not in {'http','https'} or not value.hostname or value.username or value.password:
            return None
        return urlunsplit((value.scheme,value.netloc.lower(),value.path.rstrip('/') or '/',value.query,''))
    except (ValueError, TypeError):
        return None


def decoded(value):
    return json.loads(value) if isinstance(value,str) else value


def build_coverage(sources, documents, events):
    sources=[decoded(s.get('payload',s)) for s in sources]
    groups=[s for s in sources if s.get('source_kind')=='information_source_group']
    tools=[s for s in sources if s.get('source_kind')=='acquisition_tool_not_information_source']
    docs={d['id']:d for d in documents}
    fetched=set(); nontruncated=set(); used_versions=set(); searches=[]; leads=set()
    for event in events:
        data=decoded(event['payload'])
        if event['kind']=='fetch':
            doc=docs.get(data.get('documentId'))
            if not doc: continue
            url=normalized_url(doc['url'])
            if not url: continue
            fetched.add(url); used_versions.add(doc['id'])
            if doc['access']=='body_fetched_not_semantically_verified': nontruncated.add(url)
        elif event['kind']=='search-leads':
            result=data.get('result',{})
            urls={u for s in result.get('sources',[]) if (u:=normalized_url(s.get('url')))}
            leads.update(urls)
            searches.append({'query':data['query'],'scope':data.get('scope','未记录检索范围'),
                'runId':event.get('runId'),'returnedUsableUrls':len(urls),
                'truncated':bool(result.get('truncated'))})
    group_rows=[]; registered=set()
    for source in groups:
        urls={u for value in source.get('urls',[]) if (u:=normalized_url(value))}
        registered.update(urls)
        group_rows.append({'id':source['id'],'name':source['name'],'registeredUrls':sorted(urls),
            'dshFetchedUrls':sorted(urls & fetched),'nonTruncatedFetchedUrls':sorted(urls & nontruncated),
            'status':'registered_urls_fetched_not_whole_source' if urls and urls<=nontruncated else ('partly_fetched' if urls & fetched else 'not_fetched_by_dsh')})
    by_id={s['id']:s for s in group_rows}
    matrix=[]
    for label, ids in SOURCE_AXES:
        rows=[by_id[id] for id in ids if id in by_id]
        matrix.append({'label':label,'registeredGroups':len(rows),
            'groupsWithAnyDshFetch':sum(bool(r['dshFetchedUrls']) for r in rows)})
    assigned={id for _, ids in SOURCE_AXES for id in ids}
    unassigned=[s for s in group_rows if s['id'] not in assigned]
    if unassigned:
        matrix.append({'label':'新登记／尚未归类','registeredGroups':len(unassigned),
            'groupsWithAnyDshFetch':sum(bool(s['dshFetchedUrls']) for s in unassigned)})
    metrics={'registryEntries':len(sources),'informationSourceGroups':len(groups),
        'acquisitionTools':len(tools),'unclassifiedEntries':len(sources)-len(groups)-len(tools),
        'registeredUrls':len(registered),'registeredHostnames':len({urlsplit(u).hostname for u in registered}),
        'dshFetchedUrls':len(fetched),'dshNonTruncatedUrls':len(nontruncated),
        'dshFetchedVersions':len(used_versions),'registeredUrlsFetched':len(registered & fetched),
        'groupsWithAnyDshFetch':sum(bool(s['dshFetchedUrls']) for s in group_rows),
        'searchCalls':len(searches),'truncatedSearchCalls':sum(s['truncated'] for s in searches),
        'distinctReturnedLeadUrls':len(leads),'returnedLeadUrlsFetched':len(leads & fetched)}
    return {'generatedAt':datetime.now(timezone.utc).isoformat(),'metrics':metrics,
        'assessment':'实际覆盖尚未证明充分','openWebExhausted':False,'saturationStatus':'not_measured',
        'method':'只统计DSH fetch事件关联的文档；登记入口和历史Codex查阅不计为DSH已获取。URL仅规范尾斜线和片段。',
        'sourceGroups':group_rows,'scopeMatrix':matrix,'searches':searches,
        'fetchedUrls':sorted(fetched),'unregisteredFetchedUrls':sorted(fetched-registered),
        'missingRegisteredUrls':sorted(registered-fetched),
        'limits':['访问过某个登记URL不等于扫完该站或读完其全部材料。',
            '主机名、来源组和独立证据链不是同一统计单位；类别可重叠，不能相加。',
            '未截断只描述提取状态，不能证明页面内容完整、相关、真实或独立核验。',
            '搜索结果少、未发现新结果、请求失败或被截断均不能证明穷尽。',
            '未记录完整范围、分页游标、候选排除及多轮新证据收益，无法评估检索饱和。']}


def render_coverage_html(audit):
    m=audit['metrics']
    rows=''.join(f'<tr><td>{html.escape(r["label"])}</td><td>{r["registeredGroups"]}</td><td>{r["groupsWithAnyDshFetch"]}</td></tr>' for r in audit['scopeMatrix'])
    return (f'<section id="coverage"><h2>信源覆盖评估</h2><p><strong>{audit["assessment"]}；检索饱和度未测量，不能声称全网穷尽。</strong></p>'
        f'<p>登记信息源组 {m["informationSourceGroups"]} · 工具条目 {m["acquisitionTools"]} · 登记URL {m["registeredUrls"]}<br>'
        f'DSH取得不同网页 {m["dshFetchedUrls"]}（未截断版本 {m["dshNonTruncatedUrls"]}） · 直接命中登记URL {m["registeredUrlsFetched"]}/{m["registeredUrls"]}<br>'
        f'DSH搜索记录 {m["searchCalls"]} 次，其中结果截断 {m["truncatedSearchCalls"]} 次。</p>'
        '<p>这些是本Agent的真实执行统计；此前Codex人工研究另计。以下“命中”仅指登记组内至少一个URL曾取得，不表示该组已遍历。</p>'
        '<table style="width:100%;text-align:left"><thead><tr><th>渠道／研究范围</th><th>登记组</th><th>DSH命中组</th></tr></thead><tbody>'+rows+'</tbody></table>'
        '<p>类别可重叠，不能把各行相加。来源丰富度还需检查中美、客户证据、独立报道、失败反例及时间窗口。</p>'
        '<p><a href="信源覆盖统计.json">查看逐源与逐次搜索记录</a> · <a href="../信源覆盖审计.md">查看完整审计与补充队列</a></p></section>')

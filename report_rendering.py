"""Pure rendering of saved research evidence; no database, network or model calls."""
import hashlib
import html
import json

from source_coverage import render_coverage_html

TRACKS = (('theory', '理论学习'), ('case', '项目案例'), ('scenario', '应用场景'))


def case_sources_from_notes(notes, documents):
    """Keep version-matched source titles and exact excerpts separate from AI notes."""
    by_document={d['id']:d for d in documents}
    case_sources=[]
    seen=set()
    for note in notes:
        if note['track']!='case': continue
        n=json.loads(note['payload'])
        key=(n['documentId'],n['sha256'])
        if key in seen: continue
        seen.add(key)
        doc=by_document.get(n['documentId'])
        available=bool(doc and doc['sha256']==n['sha256']==hashlib.sha256(doc['content'].encode('utf-8')).hexdigest() and n['quote'] in doc['content'])
        case_sources.append({'documentId':n['documentId'],'sha256':n['sha256'],
            'title':doc['title'] if available else '原文待获取或版本待核对',
            'url':doc['url'] if available else n['sourceUrl'],
            'quote':n['quote'] if available else '',
            'retrievedAt':doc['retrievedAt'] if available else None,
            'access':doc['access'] if available else 'source_unavailable',
            'available':available})
    return case_sources


def render_markdown(report):
    notes, runs, case_sources = (report[key] for key in ("notes", "runs", "caseSources"))
    md=['# DSH本体与FDE研究雷达','',f'更新：{report["generatedAt"]}',
        '','项目案例展示来源原标题、逐字短摘录和原文入口。AI研究笔记单列；引用匹配不代表独立核验或企业可行性。','']
    for r in runs[:3]:
        md.append(f'- 运行 {r["id"]}：{r["status"]}')
    for track,label in TRACKS:
        md+=['',f'## {label}','']
        if track=='case':
            for source in case_sources:
                md += [f'### {source["title"]}','',f'来源原文：{source["url"]}',
                    f'获取时间：{source["retrievedAt"] or "未取得"}；获取范围：{source["access"]}','']
                if source['available']:
                    md += ['原文短摘录（保持原语言，未改写）：','',source['quote'],'',
                        f'已保存网页提取文本：documents/{source["documentId"]}.txt',
                        '本地文件为当时取得的文字，包含网页导航；不代表原始版式、图表或完整附件。',
                        '来源页面被截断，不能视为全文。' if source['access']=='body_partial' else '完整内容与版式请打开来源网站。','']
                else:
                    md += ['未取得匹配版本；仅提供来源入口，不使用AI概要替代。','']
            continue
        for note in notes:
            if note['track']!=track: continue
            n=json.loads(note['payload'])
            md += [f'### {n["title"]}','',n['summary'],'',f'研究分析：{n["analysis"]}','',
                   f'限制：{n["limitations"]}',f'下一步：{n["nextStep"]}',
                   f'原文：{n["sourceUrl"]}',f'定位：{n["documentId"]} 字符 {n["quoteOffset"]}；{n["sourceAccess"]}','']
    md+=['','## AI案例研究笔记（独立于原文，默认折叠）','']
    for note in notes:
        if note['track']!='case': continue
        n=json.loads(note['payload'])
        md+=['<details>',f'<summary>AI笔记 · {html.escape(n["title"])}</summary>','',
            f'AI整理／历史概要：{n["summary"]}','',f'AI分析：{n["analysis"]}','',
            f'局限：{n["limitations"]}',f'下一步：{n["nextStep"]}','','</details>','']
    return '\n'.join(md)


def render_html(report):
    notes, runs, case_sources = (report[key] for key in ("notes", "runs", "caseSources"))
    counts, coverage = report['counts'], report['coverage']
    records, sources, failures = (report[key] for key in ('records', 'sources', 'acquisitionFailures'))
    cards=''
    for track,label in TRACKS:
        cards+=f'<section id="{track}"><h2>{label}</h2>'
        if track=='case':
            cards+='<p>原始信息优先：标题取自来源网页，摘录保持原语言和原句。点击来源网站阅读完整内容；AI整理另列在下方折叠区。</p>'
            if not case_sources: cards+='<p>尚无已关联的案例原文；不会用AI概要代替。</p>'
            for source in case_sources:
                cards+=f'<article class="source-case"><small>来源材料 · 未经AI改写</small><h3>{html.escape(source["title"])}</h3>'
                cards+=f'<p><a class="source-link" rel="noreferrer" target="_blank" href="{html.escape(source["url"],quote=True)}">打开来源网站 · 阅读原文 ↗</a></p><p>{html.escape(source["url"])}</p>'
                if source['available']:
                    cards+=f'<p>获取时间：{html.escape(source["retrievedAt"])}<br>获取范围：{html.escape(source["access"])}</p>'
                    if source['access']=='body_partial': cards+='<p class="source-warning">取得内容已截断，不是全文。</p>'
                    cards+=f'<h4>原文短摘录（未改写）</h4><blockquote>{html.escape(source["quote"])}</blockquote>'
                    cards+=f'<p><a href="documents/{source["documentId"]}.txt" target="_blank">打开已保存的网页提取文本</a></p><p>本地文本保留当时取得的文字，包含导航；提取过程已去除网页标签，不含原始版式、图表及附件。原文语言不自动翻译。</p>'
                else:
                    cards+='<p class="source-warning">未取得匹配的来源版本；仅提供原站入口，不使用AI概要代替。</p>'
                cards+='</article>'
            cards+='</section>'
            continue
        group=[n for n in notes if n['track']==track]
        if not group: cards+='<p>本分类尚无本Agent正常完成后提交的笔记。历史底稿仍保留。</p>'
        for note in group:
            n=json.loads(note['payload'])
            cards+=f'<article><small>待复核 · 引用已匹配</small><h3>{html.escape(n["title"])}</h3>'
            for key,label2 in [('summary','来源声明'),('analysis','研究分析'),('limitations','局限'),('nextStep','下一步')]:
                cards+=f'<h4>{label2}</h4><p>{html.escape(n[key])}</p>'
            cards+=f'<details><summary>查看证据</summary><blockquote>{html.escape(n["quote"])}</blockquote><p>{html.escape(n["sourceAccess"])}</p><a rel="noreferrer" target="_blank" href="{html.escape(n["sourceUrl"],quote=True)}">来源网站</a> · <a href="documents/{n["documentId"]}.txt">本地提取文本</a><p>字符位置：{n["quoteOffset"]} · SHA256：{n["sha256"]}</p></details></article>'
        cards+='</section>'
    cards+='<section id="case-analysis"><h2>AI案例研究笔记</h2><p>以下内容是AI加工或推断，独立于来源原文；默认收起，保留待复核状态。</p>'
    for note in notes:
        if note['track']!='case': continue
        n=json.loads(note['payload'])
        cards+=f'<details class="ai-case-note"><summary>展开AI笔记 · {html.escape(n["title"])}</summary>'
        for key,label in [('summary','AI整理／历史概要'),('analysis','AI分析'),('limitations','局限'),('nextStep','下一步')]:
            cards+=f'<h4>{label}</h4><p>{html.escape(n[key])}</p>'
        cards+='</details>'
    cards+='</section>'
    page='''<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DSH · 本体与FDE雷达</title><style>
        body{margin:0;background:#f4f6f8;color:#142b3b;font:16px/1.7 system-ui}header,main{max-width:1040px;margin:auto;padding:30px}header{background:#132b3d;color:#fff;max-width:none}header>div{max-width:1040px;margin:auto}nav a{color:#bce8d4;margin-right:28px}h1{font-size:30px}article{background:white;border:1px solid #dae2e8;border-radius:12px;padding:24px;margin:18px 0}small{color:#846121}h4{margin-bottom:4px}p{white-space:pre-wrap;overflow-wrap:anywhere}blockquote{border-left:3px solid #77aa95;padding-left:16px}details{background:#f5f8fa;padding:14px}footer{padding:30px;color:#536673}a{color:#006957}</style><header><div><small style="color:#bce8d4">DEEPSEEK HARNESS · RESEARCH AGENT</small><h1>本体与FDE研究雷达</h1><p>理论 → 案例 → 场景验证</p><nav><a href="#theory">理论学习</a><a href="#case">项目案例</a><a href="#scenario">应用场景</a></nav></div></header><main>'''
    page+='<article><h2>打开完整资料库</h2><p>此页是离线研究笔记快照。全部已采集资料、原文全文检索和实时采集状态在本地工作台；当前采集范围与逐条结果见验收报告。</p><p><a href="http://127.0.0.1:8765/">打开实时资料库与采集任务 ↗</a> · <a href="采集验收报告.md">采集验收报告</a> · <a href="资料目录.json">全部资料目录</a></p></article>'
    page+=f'<p>底稿记录 {counts["records"]} · 信源登记 {counts["sources"]} · 保存页面版本 {counts["documents"]} · AI笔记（待复核或已审核）{len(notes)}</p>'
    page+='<p>最近运行：'+html.escape(' / '.join(r['status'] for r in runs[:3]))+'</p><p><a href="#coverage">查看信源覆盖与检索缺口 ↓</a></p>'+cards
    page+=render_coverage_html(coverage)
    page+='<section id="library"><h2>历史研究底稿与信源</h2><p>导入资料保持原有证据等级；登记入口不等于本Agent已接通。</p>'
    for group,label in [(records,'研究底稿'),(sources,'信源登记')]:
        page+=f'<details><summary>{label} · {len(group)}</summary>'
        for row in group:
            record=json.loads(row['payload'])
            title=record.get('title') or record.get('name') or record.get('project_name') or row['id']
            page+=f'<details><summary>{html.escape(str(row["id"])+" · "+str(title))}</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">{html.escape(json.dumps(record,ensure_ascii=False,indent=2))}</pre></details>'
        page+='</details>'
    page+='</section><section><h2>获取缺口</h2>'
    if not failures: page+='<p>没有已登记的来源获取失败；这不代表已覆盖所有来源。</p>'
    for row in failures:
        page+=f'<p>{html.escape(row["createdAt"])}<br>{html.escape(row["payload"])}</p>'
    page+='</section>'
    page+='<footer>由DSH执行推理与工具调用。此页为本地研究结果，不代表独立核验项目库；没有企业实测的场景保持待验证。</footer></main></html>'
    return page

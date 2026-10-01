"""Source-reading scopes and lineage. No source title or text is rewritten."""
import json
from urllib.parse import urlsplit

def urls(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {'url', 'sourceurl'} and isinstance(item, str):
                yield item.rstrip('/')
            else:
                yield from urls(item)
    elif isinstance(value, list):
        for item in value:
            yield from urls(item)

def assigned_tracks(url, parsed, historical_tracks):
    p = parsed
    tracks = historical_tracks
    assigned = set(tracks.get(url.rstrip('/'), set()))
    if '/docs/' in p.path or '/abs/' in p.path or '/pdf/' in p.path or ('github.com' == p.hostname):
        assigned.add('theory')
    if '/customer' in p.path or '/case-stud' in p.path:
        assigned.add('case')
    if p.hostname == 'sierra.ai' and any((t in p.path for t in ['ai-agents-in-action', 'siriusxm', 'sierra-and-stellarus'])):
        assigned.add('case')
    if p.hostname == 'sierra.ai' and '/blog/' in p.path and (not assigned):
        assigned.add('theory')
    if '/podcast/' in p.path or 'Transcript' in p.path:
        assigned.add('theory')
    return assigned

def source_scope(document, p, fmt, assigned):
    scope = '网页提取文本；尚未逐项核验内容完整性'
    quality = 'evidence_text'
    if fmt == 'pdf':
        scope = 'PDF分页提取文本；图表版式请看原件'
    elif fmt in {'vtt', 'srt'}:
        scope = '字幕文字及时间戳；未逐句对音核验'
    elif fmt in {'rss', 'atom', 'json_feed'}:
        scope = '订阅条目与简介；不等于链接文章正文'
    if '/abs/' in p.path and p.hostname == 'arxiv.org':
        scope = '论文摘要与书目信息；不是论文全文'
        quality = 'metadata_only'
    if p.hostname == 'tomgruber.org' and p.path.rstrip('/') == '/writing/ontolingua-kaj-1993':
        scope = '作者的论文说明、摘要及书目；不是所链接论文全文'
        quality = 'metadata_only'
    if p.hostname == 'raw.githubusercontent.com' and p.path.endswith(('.py', '.ttl', '.json', '.yml', '.yaml')):
        scope = '公开仓库单个原始文件；供阅读审查，未安装执行，不代表整个仓库'
        assigned.add('theory')
    if 'bookscenter' in p.path or p.hostname == 'www.penguinrandomhouse.com':
        scope = '出版社书目／简介／公开片段；不是全书'
        quality = 'metadata_only'
    if p.hostname in {'newetds.lib.tsinghua.edu.cn'}:
        scope = '学位论文摘要与书目；不是论文全文'
        quality = 'metadata_only'
    if p.hostname in {'www.youtube.com', 'player.vimeo.com'}:
        scope = '视频页面元数据；尚未取得视频字幕或音轨'
        quality = 'metadata_only'
    if p.hostname == 'investors.palantir.com' and document['chars'] < 1000:
        scope = '导航空壳；公告正文未取得'
        quality = 'shell'
    if p.hostname == 'wap.eastmoney.com' and document['chars'] < 800:
        scope = 'App阅读全文提示及推荐信息；文章正文未取得'
        quality = 'metadata_only'
    if p.hostname == 'www.deepexi.com' and p.path == '/company' and (document['chars'] < 1200):
        scope = '导航和发展时间线；企业介绍正文未取得'
        quality = 'partial'
    if p.hostname == 'www.deepexi.com' and p.path == '/' and (document['chars'] < 1200):
        scope = '产品与新闻入口索引；不是具体客户项目正文'
        quality = 'listing'
    if p.hostname == 'a16z.com' and p.path.startswith('/podcast/'):
        scope = '发布者节目介绍；未取得完整对话转写'
        quality = 'metadata_only'
    if p.hostname == 'www.americanoptimist.com' or p.path == '/podcasts/a16z-show/':
        scope = '节目目录及各集简介；不是完整对话'
        quality = 'listing'
    if p.hostname == 'www.kirkland.com' and '/video/' in p.path:
        scope = '发布者视频介绍及引语；没有视频字幕'
        quality = 'metadata_only'
    if p.hostname == 'www.pbs.org' and '/in-the-age-of-ai/' in p.path:
        scope = '发布者页面及逐字转写（约字符5628后）；未对照音轨核验'
    if p.hostname == 'www.weforum.org' and '/podcasts/' in p.path:
        scope = '主办方访谈文字稿；发布者注明经语音识别、编辑及压缩，不等同未编辑音轨'
        assigned.add('theory')
    if p.hostname == 'www.tup.tsinghua.edu.cn' and '/upload/books/yz/' in p.path:
        scope = '出版社公开样章PDF；不是全书'
    if p.hostname == 'www.cninfo.com.cn' and p.path == '/':
        scope = '公告入口及部分未渲染模板；不是公告正文'
        quality = 'listing'
    if p.path.rstrip('/') in {'/en/resources/customer-stories', '/customers', '/products/c3-generative-ai/customers'}:
        scope = '客户案例目录；每个案例需另取正文'
        quality = 'listing'
    return (scope, quality)

def access_scope(document, metadata, fmt, scope, quality, assigned):
    if fmt in {'rss', 'atom', 'json_feed'}:
        quality = 'listing'
    if document['access'] == 'body_partial':
        scope += '；提取不完整'
        quality = 'partial'
    special_scopes = {'suspected_navigation_only': '疑似导航空壳；未取得文章正文', 'company_timeline_shell': '公司导航与时间线；介绍正文未取得', 'app_only_article_navigation': 'App阅读全文提示及推荐；文章正文未取得', 'video_metadata_only': '视频页面元数据；没有字幕或音轨'}
    if metadata.get('bodyScope') in special_scopes:
        scope = special_scopes[metadata['bodyScope']]
    if document['access'] in {'metadata_only', 'insufficient_body'}:
        quality = 'metadata_only' if document['access'] == 'metadata_only' else 'shell'
    if document['access'] in {'transcript_auto', 'transcript_manual'}:
        fmt = 'transcript'
        quality = 'evidence_text'
        assigned.add('theory')
        scope = '既有浏览器导出的自动字幕及时间戳；未逐句对音核验，不是DSH自动视频转写' if document['access'] == 'transcript_auto' else '导入字幕文字；需查看转写来源及对音核验状态'
    if document['access'] == 'github_readme':
        fmt = 'readme'
        quality = 'evidence_text'
        assigned.add('theory')
        scope = 'GitHub 仓库 README 原文；不含完整代码、附件或链接文档，未安装运行或核验项目效果'
    return (fmt, scope, quality)

def catalog(store, documents):
    with store.db() as db:
        records = [dict(r) for r in db.execute('SELECT * FROM records')]
        results = [json.loads(r['result']) for r in db.execute('SELECT result FROM pipeline_items WHERE result IS NOT NULL ORDER BY id')]
    by_id = {}
    for result in results:
        document_id = result.get('documentId')
        # A 304 reuses saved text but has no extraction metadata of its own.
        if document_id and (document_id not in by_id or result.get('access') != 'not_modified'):
            by_id[document_id] = result
    tracks = {}
    for row in records:
        track = 'case' if row['category'].startswith('首批') else 'scenario' if row['category'].startswith('场景') else 'theory'
        for url in urls(json.loads(row['payload'])):
            tracks.setdefault(url, set()).add(track)
    for document in documents:
        result = by_id.get(document['id'], {})
        metadata = result.get('metadata', {})
        url = document['url']
        p = urlsplit(url)
        fmt = metadata.get('format', 'unknown')
        assigned = assigned_tracks(url, p, tracks)
        scope, quality = source_scope(document, p, fmt, assigned)
        fmt, scope, quality = access_scope(document, metadata, fmt, scope, quality, assigned)
        document.update(tracks=sorted(assigned), format=fmt, contentScope=scope, quality=quality, publishedAt=(metadata.get('meta') or {}).get('article:published_time'), acquisitionJobSource=result.get('requestedUrl'), semanticVerification='not_verified')
    return documents

def measured_coverage(pipeline, documents, batch=None):
    from collections import Counter
    result = pipeline.coverage() if batch is None else batch
    latest = {}
    for d in sorted(documents, key=lambda x: x['retrievedAt']):
        latest[d['url'].rstrip('/')] = d
    usable = [d for d in latest.values() if d['quality'] == 'evidence_text']
    result.update(qualityCounts=dict(Counter((d['quality'] for d in latest.values()))), usableTextUrls=len(usable), usableTextDomains=len({urlsplit(d['url']).hostname for d in usable}), distinctTextHashes=len({d['sha256'] for d in usable}), savedUrls=len(latest), savedDocumentVersions=len(documents), allSavedDomains=len({urlsplit(d['url']).hostname for d in latest.values()}), formats=dict(Counter((d['format'] for d in latest.values()))), scope='登记清单与有界关联链接；不是2026市场全部项目，正文可读不等于项目独立核验', yearBackfillComplete=False, independentlyVerifiedProjects=0)
    return result

"""Build an auditable acquisition delivery from a single read-only SQLite snapshot.

This module never fetches, changes a database row, rewrites source text, or
upgrades a project verification claim. Run again after each collection batch.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit

from collection_report_rendering import render_collection_markdown
from catalog import catalog, measured_coverage
from pipeline import Pipeline


ROOT = Path(__file__).resolve().parent
QUALITY_NAMES = {
    'evidence_text': '正文候选／可提取文本（未逐项语义核验）',
    'metadata_only': '摘要／书目／节目或页面元数据',
    'listing': '目录／订阅条目／简介',
    'partial': '部分提取／内容不完整',
    'shell': '导航空壳／正文未取得',
}
CHINA_VENDOR_DOMAINS = {
    'deepexi.com', 'iflytek.com', 'bonc.com.cn', '4paradigm.com',
    'haizhi.com', 'tencent.com', 'volcengine.com', 'baidu.com',
    'antgroup.com', 'alibaba.com', 'aliyun.com', 'alibabacloud.com',
    'transwarp.cn', 'zhipuai.cn', 'nebula-graph.com.cn',
}
OTHER_VENDOR_DOMAINS = {
    'cognite.com', 'stardog.com', 'c3.ai', 'scale.com', 'baseten.co',
    'decagon.ai', 'sierra.ai', 'distyl.ai', 'openai.com', 'anthropic.com',
    'amazon.com', 'aws.amazon.com', 'databricks.com', 'snowflake.com',
    'neo4j.com', 'tigergraph.com', 'ontotext.com', 'relational.ai',
}
CHINA_VENDOR_NAMES = ('科大讯飞', '滴普科技', '东方国信', '第四范式', '海致科技',
                      '腾讯', '火山引擎', '蚂蚁集团', '阿里云', '百度', '星环科技', '智谱')


class ReadOnlySnapshot:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        path = self.directory / 'radar.sqlite3'
        self.connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute('BEGIN')

    @contextmanager
    def db(self):
        # All catalog and coverage queries share one consistent read snapshot.
        yield self.connection

    def close(self):
        self.connection.close()


class ReadOnlyCoverage:
    def __init__(self, store):
        self.store = store

    def coverage(self):
        # Reuse the existing calculation without running Pipeline's migrations.
        return Pipeline.coverage(self)


def _host_is(host, domains):
    return any(host == domain or host.endswith('.' + domain) for domain in domains)


def _language_signal(text, metadata):
    meta = metadata.get('meta') or {}
    declared = meta.get('og:locale') or meta.get('language') or meta.get('content-language')
    if isinstance(declared, str) and declared.strip():
        return {'label': '发布者声明：' + declared.strip(), 'basis': 'page_metadata'}
    sample = text[:20000]
    han = len(re.findall(r'[\u3400-\u4dbf\u4e00-\u9fff]', sample))
    latin = len(re.findall(r'[A-Za-z]', sample))
    kana = len(re.findall(r'[\u3040-\u30ff]', sample))
    if kana >= 20:
        label = '日文候选（含假名；未核验）'
    elif han >= 40 and han >= latin / 2:
        label = '中文候选（汉字较多；未核验）'
    elif han >= 20:
        label = '中英等混合文字候选（未核验）'
    elif latin >= 80:
        label = '拉丁文字为主（具体语言未核验）'
    else:
        label = '语种未判定'
    return {'label': label, 'basis': 'character_counts_first_20000_chars',
            'hanChars': han, 'latinChars': latin, 'kanaChars': kana}


def _vendor_signal(document, text):
    host = (urlsplit(document['url']).hostname or '').lower()
    palantir_domain = _host_is(host, {'palantir.com'})
    china_domain = _host_is(host, CHINA_VENDOR_DOMAINS)
    other_domain = _host_is(host, OTHER_VENDOR_DOMAINS)
    if palantir_domain:
        group = 'Palantir 域名资料'
    elif china_domain:
        group = '中国厂商域名资料（非 Palantir）'
    elif other_domain:
        group = '其他非 Palantir 厂商域名资料'
    else:
        group = '媒体／研究／机构／其他待分类域名'
    sample = str(document['title']) + '\n' + text[:5000]
    return {'group': group, 'basis': 'explicit_domain_allowlists',
            'palantirMentionCandidate': 'palantir' in sample.casefold(),
            'chinaVendorKeywordCandidates': [name for name in CHINA_VENDOR_NAMES if name in sample],
            'keywordBasis': 'original_title_and_first_5000_source_characters',
            'meaning': '仅为资料域名和关键词候选标签；不认定国别项目、交付关系、FDE 模式或成效。'}


def aggregate_arxiv(documents, contents):
    """Group representations by paper ID, preserving original titles and versions."""
    grouped = defaultdict(list)
    for document in documents:
        parsed = urlsplit(document['url'])
        if parsed.hostname not in {'arxiv.org', 'www.arxiv.org', 'export.arxiv.org'}:
            continue
        match = re.fullmatch(r'/(abs|pdf|html)/(\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?(?:\.pdf)?/?', parsed.path)
        if match:
            grouped[match[2]].append((document, match[1], match[3]))
    papers = []
    for paper_id, entries in sorted(grouped.items()):
        # Prefer a publisher HTML/abstract title over PDF metadata that may be
        # abbreviated. Select an existing string; never synthesize a new title.
        chosen = min(entries, key=lambda item: ({'html': 0, 'abs': 1, 'pdf': 2}[item[1]], -len(item[0]['title'])))[0]
        richest = max(entries, key=lambda item: item[0]['chars'])[0]
        text = contents.get(richest['id'], '')
        boundary = text.rfind('\nReferences\n')
        screen_text = text[:boundary] if boundary > len(text) // 8 else text
        fde_term = bool(re.search(r'\bforward[\s-]+deployed\b|\bFDE\b', screen_text, re.I))
        papers.append({
            'paperId': paper_id, 'title': chosen['title'], 'titleDocumentId': chosen['id'],
            'originalTitleVariants': list(dict.fromkeys(item[0]['title'] for item in entries)),
            'savedUrlCount': len(entries), 'urls': sorted(item[0]['url'] for item in entries),
            'representations': [{'url': document['url'], 'documentId': document['id'],
                                 'representation': representation, 'revision': revision or 'unversioned_url',
                                 'sha256': document['sha256'], 'quality': document.get('quality')}
                                for document, representation, revision in entries],
            'keywordScreen': {'fdeTermMatched': fde_term, 'documentId': richest['id'],
                              'method': 'FDE/forward-deployed literal search; text before final References heading when identifiable',
                              'meaning': '词面命中或未命中都不构成FDE项目、相关性或真实性认定。'},
            'meaning': '同一论文ID的格式与修订版聚合；不是多个独立研究或企业项目。不同修订版的结论仍需分别核对。',
        })
    return {'method': 'arxiv_paper_id_from_official_host_url',
            'savedUrlCount': sum(paper['savedUrlCount'] for paper in papers),
            'distinctPaperIds': len(papers),
            'papersWithFdeTermMatch': sum(paper['keywordScreen']['fdeTermMatched'] for paper in papers),
            'papersWithoutFdeTermMatch': sum(not paper['keywordScreen']['fdeTermMatched'] for paper in papers),
            'papers': papers,
            'scope': '仅对已保存资料URL聚合同一arXiv ID；不推定跨站转载独立性，不推定论文真实性或项目实施。'}


def relevance_review(arxiv, evidence_text_urls):
    """Retain this turn's scoped review, without manufacturing a truth rating."""
    observations = [
        {'id': 'manufacturing_research', 'paperIds': ['2012.09049', '2109.03655', '2206.10318', '2404.06571'],
         'observation': '制造知识图谱综述、数字工厂及制造服务检索研究可用于方法学习；研究或实验不直接构成具名企业FDE交付。'},
        {'id': 'ontology_agent_research', 'paperIds': ['2609.15779', '2602.03439', '2608.13662'],
         'observation': 'EvoOntology、ontology-to-tools及Ontology-Grounded Project Memory属于本体与Agent技术候选；论文实验不能替代客户部署和验收证据。'},
        {'id': 'adjacent_research', 'paperIds': ['2609.30484', '2609.30763', '2602.09163', '2609.30805'],
         'observation': '上下文评测、临床本体、果蝇本体整理、工控安全是方法或跨领域参考候选；需另行说明与企业痛点的关联，不能仅凭ontology关键词或引用关系认定FDE核心项目。'},
        {'id': 'historical_airbus', 'noteIds': ['note-d5b9d016eb204191b1610428d5d4a16f'],
         'observation': 'Airbus Skywise来源为2017年经典案例；2026年的抓取时间不能把它计为2026年新增项目。'},
        {'id': 'mccarthy_announcement', 'noteIds': ['note-22f1ab013e3c4fd995982c8da92e359a'],
         'observation': 'McCarthy材料为合作公告。已保存笔记明确部署范围、时间表及ROI未知；公告不能自动升级为生产部署或效果验证。'},
        {'id': 'company_level_fde', 'noteIds': ['note-a2d0c503dc2449fdad7894c294956108'],
         'observation': '东方国信材料为公司级FDE能力披露，笔记明确客户、项目日期、效果与验收口径未知；不是由这些材料已经确认的具名落地项目。'},
        {'id': 'iflytek_project_evidence', 'noteIds': ['note-15590b71ee3b4e408f9f55f066efb61b', 'note-5aaaa885911a4b398f927acf58fb4b27'],
         'observation': '中粮等年报项目段落不能套用公司级FDE表态；新浪招采报道仍缺采购或客户原件及指标口径，供应商披露和媒体转载不能相互自动升级为独立核验。'},
    ]
    criteria = [
        '资料按规范URL、DOI或arXiv ID聚合；一个论文的摘要、PDF、HTML和修订版不是多个独立项目。',
        '项目按具名客户、具体业务范围及实施地区建立独立ID；资料条数、正文URL数、论文数和笔记数不能直接换算项目数。',
        '标为公开披露FDE项目需要项目层面的FDE交付证据；招聘、公司团队介绍、通用知识图谱或Agent能力不能代替。',
        '本体建模、FDE交付、Agent实现分别记录证据和unknown，不能相互推断或替代。',
        '年度归属采用事件日期或来源原始披露日期，并记录口径；抓取日期不能替代项目发生日期。',
        '国别采用项目实施地或明确的项目范围；供应商总部、网站域名、语言不能替代实施地区。',
        '合作公告、试点、生产部署、验收和量化结果分阶段；没有相应证据就保留unknown。',
        '转载及同一联合新闻稿视为同一来源链线索；多个URL、双方引语或相同厂商材料不自动等于多个独立证据。',
        '效果结论应追溯基线、分母、时间区间和验收口径；客户、供应商与第三方的陈述分别标注，不自动判真伪。',
    ]
    return {'reviewedAt': '2026-09-28', 'method': '本轮读取保存材料及笔记边界的抽查，辅以URL和关键词启发式；不是人工专家验收或AI真假评分',
            'reviewIsHistoricalSnapshot': True, 'doesNotReviewFutureDocumentsAutomatically': True,
            'reviewedArxivPaperIds': [paper['paperId'] for paper in arxiv['papers'] if any(paper['paperId'] in observation.get('paperIds', []) for observation in observations)],
            'observations': observations, 'projectCountingCriteria': criteria,
            'countsKeptSeparate': {'evidenceTextCandidateUrls': evidence_text_urls,
                                  'deduplicatedEnterpriseProjects': None,
                                  'confirmedProjectLevelFdeProjects': None,
                                  'independentlyVerifiedProjects': 0,
                                  'meaning': 'null表示尚未建立可审核的项目级计数；0表示当前没有已完成独立核验的项目记录，不表示市场实际项目为零。'}}


def _read_rows(store):
    with store.db() as db:
        raw_documents = [dict(row) for row in db.execute('SELECT * FROM documents ORDER BY retrievedAt,id')]
        jobs = [dict(row) for row in db.execute('SELECT * FROM pipeline_jobs ORDER BY createdAt,id')]
        items = [dict(row) for row in db.execute('SELECT * FROM pipeline_items ORDER BY id')]
        sources = [dict(row) for row in db.execute('SELECT * FROM pipeline_sources ORDER BY url')]
    return raw_documents, jobs, items, sources


def _index_attempts(items):
    by_document = {}
    by_requested = defaultdict(list)
    for item in items:
        result = json.loads(item['result']) if item['result'] else {}
        item['result'] = result
        by_requested[item['url']].append(item)
        if item['documentId']:
            by_document[item['documentId']] = result
    return by_document, by_requested


def _enrich_documents(documents, content, items, by_document, data_directory):
    latest = {}
    for document in documents:
        result = by_document.get(document['id'], {})
        metadata = result.get('metadata') or {}
        document['domain'] = urlsplit(document['url']).hostname
        document['languageSignal'] = _language_signal(content[document['id']], metadata)
        document['vendorSignal'] = _vendor_signal(document, content[document['id']])
        document['localTextPath'] = str(data_directory / 'documents' / (document['id'] + '.txt'))
        document['localTextExists'] = Path(document['localTextPath']).is_file()
        document['originalBinaryArchived'] = False
        document['acquisitionMetadata'] = metadata
        document['acquisitionStatusCode'] = result.get('statusCode')
        document['relatedRegisteredUrls'] = sorted({item['url'] for item in items if item['documentId'] == document['id']})
        latest[document['url'].rstrip('/')] = document
    latest_documents = list(latest.values())
    latest_ids = {document['id'] for document in latest_documents}
    for document in documents:
        document['latestSavedVersionForUrl'] = document['id'] in latest_ids
    return latest_documents


def _summarize_jobs(jobs, items):
    for job in jobs:
        job_items = [item for item in items if item['jobId'] == job['id']]
        job['requestedUrls'] = len(job_items)
        job['attemptedUrls'] = sum(item['attempts'] > 0 for item in job_items)
        job['requestAttempts'] = sum(item['attempts'] for item in job_items)
        job['acquisitionAttempts'] = job['requestAttempts']
        job['outcomes'] = dict(Counter(item['status'] for item in job_items))


def _summarize_sources(sources, by_requested):
    for source in sources:
        source['origins'] = json.loads(source['origins'])
        source['enabled'] = bool(source['enabled'])
        source['candidate'] = bool(source['candidate'])
        history = by_requested.get(source['url'], [])
        last_finished = next((item for item in reversed(history) if item['result']), None)
        source['latestAttemptOutcome'] = last_finished['status'] if last_finished else 'not_completed'
        source['latestResultScope'] = (last_finished['result'].get('metadata') or {}).get('bodyScope') if last_finished else None
        source['latestResultFormat'] = (last_finished['result'].get('metadata') or {}).get('format') if last_finished else None


def _statistics(documents, latest_documents, jobs, items, sources, arxiv_aggregation):
    stats = {
        'jobCount': len(jobs), 'runningJobs': sum(job['status'] == 'RUNNING' for job in jobs),
        'allJobAttemptedUniqueUrls': len({item['url'] for item in items if item['attempts'] > 0}), 'allJobRequestAttempts': sum(item['attempts'] for item in items),
        'allJobAcquisitionAttempts': sum(item['attempts'] for item in items),
        'registeredUrls': len(sources), 'unattemptedRegisteredUrls': sum(not source['lastAttempt'] for source in sources),
        'enabledUrls': sum(source['enabled'] for source in sources),
        'unattemptedEnabledUrls': sum(source['enabled'] and not source['lastAttempt'] for source in sources),
        'pausedUrls': sum(not source['enabled'] for source in sources),
        'latestAccessStatusCounts': dict(Counter(source['access'] for source in sources)),
        'sourceCadenceHours': dict(Counter(str(source['cadenceHours']) for source in sources if source['enabled'])),
        'latestDocumentQualityCounts': dict(Counter(document['quality'] for document in latest_documents)),
        'latestDocumentFormatCounts': dict(Counter(document['format'] for document in latest_documents)),
        'latestDocumentLanguageSignals': dict(Counter(document['languageSignal']['label'] for document in latest_documents)),
        'latestDocumentVendorDomainGroups': dict(Counter(document['vendorSignal']['group'] for document in latest_documents)),
        'chinaVendorKeywordCandidateUrls': sum(bool(document['vendorSignal']['chinaVendorKeywordCandidates']) for document in latest_documents),
        'palantirMentionCandidateUrls': sum(document['vendorSignal']['palantirMentionCandidate'] for document in latest_documents),
        'savedDocumentVersions': len(documents), 'latestSavedUniqueUrls': len(latest_documents),
        'latestSavedDistinctDomains': len({document['domain'] for document in latest_documents}),
        'latestSavedDistinctHashes': len({document['sha256'] for document in latest_documents}),
        'allSavedDistinctHashes': len({document['sha256'] for document in documents}),
        'pdfSourceTextUrls': sum(document['format'] == 'pdf' for document in latest_documents),
        'pdfPartialTextUrls': sum(document['format'] == 'pdf' and document['quality'] == 'partial' for document in latest_documents),
        'captionFileTextUrls': sum(document['format'] in {'vtt', 'srt'} for document in latest_documents),
        'importedTranscriptTextUrls': sum(document['format'] == 'transcript' for document in latest_documents),
        'publisherTranscriptPageCandidates': sum(document['domain'] == 'www.pbs.org' and '/in-the-age-of-ai/' in document['url'] for document in latest_documents),
        'latestRegisteredUrlsNeedingAttention': sum(bool(source['attempts']) for source in sources),
        'originalBinaryArchiveCount': 0, 'independentlyVerifiedProjectCount': 0,
        'arxivSavedUrlCount': arxiv_aggregation['savedUrlCount'],
        'arxivDistinctPaperIds': arxiv_aggregation['distinctPaperIds'],
        'deduplicatedEnterpriseProjectCount': None,
        'confirmedProjectLevelFdeProjectCount': None,
    }
    return stats


def _report_metadata(config_path, config, data_directory, generated):
    report = {
        'schema': 'fde-radar.collection-delivery/v1', 'generatedAt': generated,
        'config': {'path': str(config_path), 'provider': config.get('provider'), 'model': config.get('model'),
                   'sdkVersion': config.get('sdkVersion'), 'corpusPath': config.get('corpusPath')},
        'databasePath': str(data_directory / 'radar.sqlite3'), 'snapshotReadOnly': True,
        'scope': '本地数据库截至快照时的全部持久化采集作业及保存资料，包括经典资料和当前年度线索；不是市场项目全量。',
        'limitations': [
            '正文候选是规则标签，相关性、完整性、陈述真实性和FDE归类尚未逐项语义核验。',
            '原始标题和提取文本没有AI改写；HTML提取不保留完整网页布局、图表及附件。',
            'PDF和字幕计数指从对应来源取得的文本；当前未在本地归档原始PDF、音视频二进制。',
            '字幕时间戳或发布者转写未逐句对音核验；节目简介和视频页面元数据不等于字幕。',
            '厂商、国别、语言分布是明确规则得到的资料候选标签；不是项目或独立证据链数量。',
            '最新保存资料与最新访问状态分别统计；历史取得过文本不代表此次抓取成功。',
            '采集尝试是管线任务调用次数；一次调用可涉及robots检查与重定向，不等同底层HTTP请求数量。',
            '同一内容hash不保证同一事实，不同hash也不保证来源相互独立；来源是否独立仍需核验。',
            '项目事件或原始披露日期不能用抓取日期替代；实施地不能用厂商总部、网站域名或语言推定。',
            '开放网络未穷尽，当前年度历史回填未完成；不得以抓取失败代替没有新增信息。',
        ],
    }
    return report


def _snapshot_report(store, config_path, config, generated):
    data_directory = store.directory
    raw_documents, jobs, items, sources = _read_rows(store)
    content = {row['id']: row['content'] for row in raw_documents}
    document_meta = [{key: value for key, value in row.items() if key != 'content'} | {'chars': len(row['content'])}
                     for row in raw_documents]
    documents = catalog(store, document_meta)
    coverage = measured_coverage(ReadOnlyCoverage(store), documents)
    by_document, by_requested = _index_attempts(items)
    latest_documents = _enrich_documents(documents, content, items, by_document, data_directory)
    _summarize_jobs(jobs, items)
    _summarize_sources(sources, by_requested)
    hash_groups = defaultdict(list)
    for document in latest_documents:
        hash_groups[document['sha256']].append(document['url'])
    arxiv_aggregation = aggregate_arxiv(latest_documents, content)
    relevance = relevance_review(arxiv_aggregation, sum(document['quality'] == 'evidence_text' for document in latest_documents))
    stats = _statistics(documents, latest_documents, jobs, items, sources, arxiv_aggregation)
    report = _report_metadata(config_path, config, data_directory, generated)
    report.update({
        'statistics': stats, 'measuredCoverage': coverage, 'jobs': jobs,
        'legacyAliases': {'allJobRequestAttempts': 'allJobAcquisitionAttempts', 'jobs.requestAttempts': 'jobs.acquisitionAttempts'},
        'latestSources': sources, 'documents': documents,
        'duplicateContentAcrossUrls': [{'sha256': sha, 'urls': urls} for sha, urls in hash_groups.items() if len(urls) > 1],
        'sourceAggregation': {'arxiv': arxiv_aggregation}, 'relevanceReview': relevance,
        'rules': {'qualityLabels': QUALITY_NAMES, 'chinaVendorDomains': sorted(CHINA_VENDOR_DOMAINS),
                  'otherVendorDomains': sorted(OTHER_VENDOR_DOMAINS), 'chinaVendorKeywords': list(CHINA_VENDOR_NAMES),
                  'language': '发布者语言元数据优先；缺失时仅按前20000字符文字比例标注候选，不推断权威语种。'},
    })
    return report


def build_report(config_path=ROOT / 'config.json', data_directory=None):
    config_path = Path(config_path).resolve()
    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    data_directory = Path(data_directory).resolve() if data_directory else ROOT / 'var'
    generated = datetime.now(timezone.utc).isoformat()
    store = ReadOnlySnapshot(data_directory)
    try:
        report = _snapshot_report(store, config_path, config, generated)
    finally:
        store.close()
    markdown_path = data_directory / '采集验收报告.md'
    json_path = data_directory / '资料目录.json'
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    markdown_path.write_text(render_collection_markdown(report, json_path), encoding='utf-8')
    return {'reportPath': str(markdown_path), 'catalogPath': str(json_path), 'generatedAt': generated, 'statistics': report['statistics']}


def main():
    parser = argparse.ArgumentParser(description='Export a read-only acquisition acceptance report.')
    parser.add_argument('--config', type=Path, default=ROOT / 'config.json')
    parser.add_argument('--data', type=Path, default=ROOT / 'var')
    args = parser.parse_args()
    print(json.dumps(build_report(args.config, args.data), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

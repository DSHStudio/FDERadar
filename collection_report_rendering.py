"""Pure collection report rendering; no database or network access."""
import html
from pathlib import Path
from urllib.parse import quote


def _url(value):
    return quote(str(value), safe=':/?&=#%+,;@!$*\'~-._')


def _md(value):
    text = html.escape(str(value) if value is not None else '—', quote=False)
    return text.replace('\\', '\\\\').replace('|', '&#124;').replace('[', '\\[').replace(']', '\\]').replace('\r', '').replace('\n', '<br>')


def _link(label, target):
    return '[' + _md(label) + '](<' + _url(target) + '>)'


def _count_table(values, first='类别'):
    lines = ['| ' + first + ' | 数量 |', '|---|---:|']
    lines.extend('| ' + _md(key) + ' | ' + str(value) + ' |' for key, value in sorted(values.items(), key=lambda item: (-item[1], str(item[0]))))
    if not values:
        lines.append('| 无记录 | 0 |')
    return lines


def _relevance_section(arxiv, review):
    count = review['countsKeptSeparate']['evidenceTextCandidateUrls']
    lines = ['', '## 内容相关性与项目认定', '',
             f'**{count} 个正文候选URL是资料数量。企业项目去重计数及项目层面的FDE认定数量尚未建立，不能由资料量换算。** '
             '当前已完成独立核验的项目记录为0；这不表示市场实际项目为零。', '',
             f'同一arXiv ID聚合后，{arxiv["savedUrlCount"]} 个已保存URL对应 **{arxiv["distinctPaperIds"]} 个论文ID**。'
             '摘要、PDF、HTML属于资料的不同表现形式；修订版仍需分别核对，不能把这些URL计为多个独立研究或企业项目。', '',
             '| arXiv ID | 来源原始标题（择一展示） | 已保存URL数 | 对应URL及修订版 |', '|---|---|---:|---|']
    if not arxiv['papers']:
        lines.append('| 尚无可聚合记录 | — | 0 | — |')
    for paper in arxiv['papers']:
        links = '；'.join(_link(item['representation'] + ' · ' + item['revision'], item['url']) for item in paper['representations'])
        lines.append('| ' + ' | '.join([_md(paper['paperId']), _md(paper['title']), str(paper['savedUrlCount']), links]) + ' |')
    lines.extend(['', f'对每个论文ID的一份较长提取文本作词面筛查，{arxiv["papersWithoutFdeTermMatch"]}/{arxiv["distinctPaperIds"]} '
                  '未匹配到FDE或forward-deployed；能识别末尾References标题时排除其后部分。'
                  '这只是启发式筛查，命中不证明采用FDE，未命中也不证明没有采用FDE。', '',
                  f'以下保留 {review["reviewedAt"]} 本轮对已保存材料及笔记边界的抽查观察，'
                  '不是人工专家验收或AI真假评分，也不自动覆盖以后新增的资料：', ''])
    lines.extend('- ' + observation['observation'] for observation in review['observations'])
    lines.extend(['', '项目认定与计数使用以下口径：', ''])
    lines.extend('- ' + criterion for criterion in review['projectCountingCriteria'])
    return lines


def _overview(report, json_path):
    generated, stats, jobs = report['generatedAt'], report['statistics'], report['jobs']
    quality_names = report['rules']['qualityLabels']
    lines = [
        '# FDE 雷达采集验收报告', '', f'生成时间：{generated}。数据来自同一只读 SQLite 快照。', '',
        f'共登记 **{stats["registeredUrls"]} 个URL**；全部 {stats["jobCount"]} 个采集作业实际尝试了 '
        f'**{stats["allJobAttemptedUniqueUrls"]} 个去重URL**、{stats["allJobAcquisitionAttempts"]} 次采集尝试。'
        f'启用 {stats["enabledUrls"]} 个，其中 {stats["unattemptedEnabledUrls"]} 个未尝试；暂停 {stats["pausedUrls"]} 个。全部登记中未尝试 {stats["unattemptedRegisteredUrls"]} 个，{stats["runningJobs"]} 个作业运行中。', '',
        f'已保存 {stats["savedDocumentVersions"]} 个文本版本；按每URL最后保存版本计为 '
        f'{stats["latestSavedUniqueUrls"]} 个URL、{stats["latestSavedDistinctDomains"]} 个域名、'
        f'{stats["latestSavedDistinctHashes"]} 个不同内容hash。以上是资料数量，**不是已确认FDE项目数量**。', '',
        '## 获取范围与真实性边界', '',
    ]
    lines.extend('- ' + item for item in report['limitations'])
    lines.extend(['', '完整机器可读目录：' + _link('资料目录.json', json_path.as_posix()) + '。', '',
                  '## 已保存资料的内容范围', '', '以下按每URL最后保存版本计数，包含此前DSH和本地采集保存的资料；失败未保存的URL不在本表内。', ''])
    lines.extend(_count_table({quality_names.get(key, key): value for key, value in stats['latestDocumentQualityCounts'].items()}))
    lines.extend(['', f'PDF来源提取文本：{stats["pdfSourceTextUrls"]} 个URL，其中部分提取 {stats["pdfPartialTextUrls"]} 个；'
                  f'VTT/SRT字幕文件提取文本：{stats["captionFileTextUrls"]} 个URL；既有字幕导入：{stats["importedTranscriptTextUrls"]} 个URL（不计为Agent自动音视频转写）；'
                  f'发布者网页转写候选：{stats["publisherTranscriptPageCandidates"]} 个URL。'
                  '原始PDF和音视频二进制尚未本地归档，原件请通过来源URL访问。', '',
                  '## 最新URL访问状态', '', '这是登记URL的最新访问结果；与历史保存资料分开，抓取失败不表示没有更新。', ''])
    lines.extend(_count_table(stats['latestAccessStatusCounts'], '最新访问状态'))
    lines.extend(['', '## 作业执行记录', '', '| 作业 | 状态 | 登记URL | 已尝试URL | 采集尝试次数 | 实际结果 |', '|---|---|---:|---:|---:|---|'])
    for job in jobs:
        outcomes = '；'.join(key + '=' + str(value) for key, value in sorted(job['outcomes'].items()))
        lines.append('| ' + ' | '.join([_md(job['id']), _md(job['status']), str(job['requestedUrls']), str(job['attemptedUrls']), str(job['requestAttempts']), _md(outcomes)]) + ' |')
    return lines


def _distribution(report, lines):
    stats = report['statistics']
    arxiv_aggregation, relevance = report['sourceAggregation']['arxiv'], report['relevanceReview']
    lines.extend(['', '## 资料分布（规则候选标签）', '', '分布单位是最后保存版本的资料URL；国别或厂商域名不证明具体项目的交付地区，也不自动说明采用了本体或FDE。', '', '### 格式', ''])
    lines.extend(_count_table(stats['latestDocumentFormatCounts']))
    lines.extend(['', '### 语言或文字信号', ''])
    lines.extend(_count_table(stats['latestDocumentLanguageSignals']))
    lines.extend(['', '### 厂商域名类别', ''])
    lines.extend(_count_table(stats['latestDocumentVendorDomainGroups']))
    lines.extend(['', f'另外，原始标题及前5000字符出现中国厂商关键词的资料候选：{stats["chinaVendorKeywordCandidateUrls"]} 个URL；'
                  f'出现Palantir文字的候选：{stats["palantirMentionCandidateUrls"]} 个URL。关键词组可重叠，不作为项目计数。'])
    lines.extend(_relevance_section(arxiv_aggregation, relevance))


def _document_directory(documents, quality_names, lines):
    lines.extend(['', '## 原始资料逐条目录', '',
                  '保留每个已保存文本版本的原始标题；版本、URL、hash和提取时间可在JSON中核对。'
                  '本地链接仅指已存在的提取文本，不能代替PDF版式、网页原件或音视频。', '',
                  '| 原始标题 | 原始URL | 本地提取文本 | 格式／访问状态 | 内容范围 | 版本 |', '|---|---|---|---|---|---|'])
    for document in sorted(documents, key=lambda row: (not row['latestSavedVersionForUrl'], row['domain'] or '', row['url'], row['retrievedAt'])):
        text_link = _link('提取文本', Path(document['localTextPath']).as_posix()) if document['localTextExists'] else '尚未导出；内容仍在SQLite'
        version = ('最后保存版本' if document['latestSavedVersionForUrl'] else '历史版本') + '；' + document['sha256'][:12]
        scope = quality_names.get(document['quality'], document['quality']) + '；' + document['contentScope']
        lines.append('| ' + ' | '.join([_md(document['title']), _link(document['url'], document['url']), text_link,
                     _md(document['format'] + ' / ' + document['access']), _md(scope), _md(version)]) + ' |')


def _remaining_gaps(report, lines):
    sources = report['latestSources']
    lines.extend(['', '## 最新失败、受限与部分获取清单', '',
                  '以下包括403、robots策略、404、超时、空壳、元数据及不完整提取。来源标题为登记时的候选标签，不冒充已读到的原始文章标题。', '',
                  '| 登记标题／线索 | URL | 最新状态 | 说明 | 下次计划尝试（UTC） |', '|---|---|---|---|---|'])
    attention = [source for source in sources if source['attempts']]
    if not attention:
        lines.append('| 无已完成失败记录 | — | — | 这不保证全部来源已尝试 | — |')
    for source in attention:
        reason = source['error'] or source['latestResultScope'] or '未取得可确认的完整正文；查看对应作业结果'
        lines.append('| ' + ' | '.join([_md(source['title']), _link(source['url'], source['url']), _md(source['access']), _md(reason), _md(source['nextDue'])]) + ' |')
    lines.extend(['', '## 重复内容与未完成范围', ''])
    if report['duplicateContentAcrossUrls']:
        for item in report['duplicateContentAcrossUrls']:
            lines.append('- 相同hash `' + item['sha256'][:16] + '`：' + '；'.join(_link(url, url) for url in item['urls']) + '。需判断是URL别名、转载还是导航壳。')
    else:
        lines.append('当前最后保存版本中未发现跨URL相同hash；这不证明各来源在事实层面相互独立。')
    lines.extend(['', '仍未完成：逐项语义相关性审核、来源独立性核验、完整年度项目回填、受限来源授权获取与现场效果验证。'
                  '开放网络穷尽状态为否；不以采集数量宣称市场项目已覆盖完毕。', '',
                  '复跑：`python collection_report.py --config config.json --data var`。报告只读取已有采集结果，不触发网络、AI分析或数据库写入。', ''])


def render_collection_markdown(report, json_path):
    lines = _overview(report, json_path)
    _distribution(report, lines)
    _document_directory(report['documents'], report['rules']['qualityLabels'], lines)
    _remaining_gaps(report, lines)
    return '\n'.join(lines)

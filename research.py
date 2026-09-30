"""Evidence-bound study dossiers; never rewrites or upgrades source documents."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from agent import ROOT, utc


def canonical(url):
    p = urlsplit(url or '')
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip('/'), p.query, ''))


class ReferenceValidator:
    """Validate source versions and literal quotations, not their factual truth."""
    def __init__(self, docs, scopes):
        self.by_id = {d['id']: d for d in docs}
        self.latest = {canonical(d['url']): d for d in docs}
        self.scopes = scopes
        self.invalid, self.stale = [], []
        self.count = 0
        self.verified_hashes = {}

    def validate(self, ref, owner, artifact=False):
        self.count += 1
        r = dict(ref)
        d = self.by_id.get(r.get('documentId'))
        valid, reason = True, ''
        if not d:
            valid, reason = False, '引用的原始文档尚未取得或不存在'
        elif r.get('sha256') != d['sha256']:
            valid, reason = False, '引用哈希与保存版本不一致'
        else:
            if d['id'] not in self.verified_hashes:
                self.verified_hashes[d['id']] = hashlib.sha256(d['content'].encode('utf-8')).hexdigest() == d['sha256']
            if not self.verified_hashes[d['id']]:
                valid, reason = False, '保存内容与自身哈希不一致'
            elif not artifact and (not isinstance(r.get('quote'), str) or not r['quote'] or len(r['quote']) > 180 or r['quote'] not in d['content']):
                valid, reason = False, '短引文不逐字匹配保存内容'
        r.update(valid=valid, reason=reason, semanticVerification='not_independently_verified')
        if d:
            current = self.latest[canonical(d['url'])]
            r.update(title=d['title'], url=d['url'], retrievedAt=d['retrievedAt'],
                     scope=r.get('scope') or self.scopes.get(d['id'], '保存的来源文本；范围待核对'),
                     stale=current['sha256'] != d['sha256'], latestDocumentId=current['id'],
                     offset=d['content'].find(r.get('quote', '')) if valid else None)
            if r['stale']:
                self.stale.append({'owner': owner, 'documentId': d['id'], 'latestDocumentId': current['id']})
        if not valid:
            self.invalid.append({'owner': owner, 'documentId': r.get('documentId'), 'reason': reason})
        return r


def document_scopes(store, docs, tables):
    from catalog import catalog
    # Scope metadata must accompany even a perfectly matching quote.
    if 'pipeline_items' in tables:
        scoped = catalog(store, [{k: d[k] for k in ('id','url','title','sha256','access','retrievedAt')} | {'chars': len(d['content'])} for d in docs])
        scopes = {d['id']: d['contentScope'] for d in scoped}
    else:
        scopes = {}
    return scopes


def validate_research(result, progress, reference):
    unresolved = 0
    for case in result['cases']:
        for claim in case.get('claims', []):
            owner = case['id'] + ':' + claim['key']
            claim['evidence'] = [reference(r, owner) for r in claim.get('evidence', [])]
            claim['declaredStatus'] = claim.get('status', 'unknown')
            if claim.get('status') not in {'disclosed', 'unknown', 'conflicting'}:
                claim['status'] = 'unknown'
            if claim.get('status') == 'disclosed' and (not claim['evidence'] or not all(r['valid'] for r in claim['evidence'])):
                claim['status'] = 'unknown'
                claim['validationWarning'] = '证据缺失或版本校验失败，不能按已披露展示。'
            if claim['status'] != 'disclosed':
                unresolved += 1
        case['independentlyVerified'] = False
    for unit in result['learning']:
        unit['sourceRefs'] = [reference(r, unit['id']) for r in unit.get('sourceRefs', [])]
        unit['progress'] = progress.get(unit['id'], {'status': 'not_started', 'notes': ''})
    for scenario in result['scenarios']:
        scenario['evidence'] = [reference(r, scenario['id']) for r in scenario.get('evidence', [])]
        scenario['status'] = 'research_only'
    for guide in result['repoGuides']:
        guide['artifacts'] = [reference(r, guide['fullName'], artifact=True) for r in guide.get('artifacts', [])]
    return unresolved


def acquisition_gaps(cases, sources, latest):
    source_by_url = {canonical(s['url']): s for s in sources}
    gaps = []
    for case in cases:
        for index, item in enumerate(case.get('nextAcquisition', [])):
            u = canonical(item.get('url'))
            source, doc = source_by_url.get(u), latest.get(u)
            # A saved historical version never masks a failed current visit.
            gap = dict(id=case['id'] + ':' + str(index), owner=case['id'], **item,
                status=source['access'] if source and source.get('access') else 'saved_text' if doc else 'not_attempted',
                documentId=doc['id'] if doc else None, error=source.get('error') if source else None,
                nextDue=source.get('nextDue') if source else None,
                meaning='取得文本仍需逐项复核，不自动填充案件主张')
            gaps.append(gap)
            item.update({k:v for k,v in gap.items() if k not in {'id','owner'}})
    known_gap_urls = {canonical(g.get('url')) for g in gaps}
    for source in sources:
        if 'source-discovery-deepening-' not in source.get('origins', '') or canonical(source['url']) in known_gap_urls:
            continue
        if source.get('access') not in {'body_fetched_not_semantically_verified', 'not_modified'}:
            gaps.append(dict(id=source['id'],owner='学习/开源深入资料',url=source['url'],purpose=source['title'],
                status=source.get('access') or 'not_attempted',error=source.get('error'),nextDue=source.get('nextDue'),
                documentId=(latest.get(canonical(source['url'])) or {}).get('id')))
    return gaps


def version_changes(docs):
    grouped = defaultdict(list)
    for d in docs:
        grouped[canonical(d['url'])].append(d)
    changes = []
    for group in grouped.values():
        for old, new in zip(group, group[1:]):
            if old['sha256'] != new['sha256']:
                changes.append(dict(url=new['url'], title=new['title'], oldDocumentId=old['id'], newDocumentId=new['id'],
                    oldHash=old['sha256'], newHash=new['sha256'], retrievedAt=new['retrievedAt'],
                    oldChars=len(old['content']), newChars=len(new['content']),
                    meaning='原文版本变化，尚未核对语义；可能来自导航、提取修复或正文变化'))
    return sorted(changes, key=lambda x: x['retrievedAt'], reverse=True)


class ResearchService:
    def __init__(self, store, config_dir=None):
        self.store = store
        self.config_dir = Path(config_dir or ROOT / 'config')
        with store.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS research_progress(
              id TEXT PRIMARY KEY, status TEXT NOT NULL, notes TEXT NOT NULL, updatedAt TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS research_progress_events(
              seq INTEGER PRIMARY KEY, id TEXT NOT NULL, status TEXT NOT NULL,
              notes TEXT NOT NULL, updatedAt TEXT NOT NULL);
            ''')

    def _config(self):
        result = {'cases': [], 'learning': [], 'scenarios': [], 'repoGuides': []}
        errors = []
        for name in ('research-cases.json', 'research-learning.json'):
            path = self.config_dir / name
            if not path.exists():
                errors.append({'file': name, 'error': '配置尚未建立'})
                continue
            try:
                value = json.loads(path.read_text(encoding='utf-8-sig'))
                for key in result:
                    if key in value:
                        if not isinstance(value[key], list):
                            raise ValueError('invalid collection')
                        result[key].extend(value[key])
            except (OSError, ValueError, TypeError):
                errors.append({'file': name, 'error': '配置无法读取，未使用其研究内容'})
        return result, errors

    def progress(self, data):
        collection, _ = self._config()
        ids = {x['id'] for x in collection['learning']}
        id, status, notes = data.get('id'), data.get('status'), data.get('notes', '')
        if not isinstance(id, str) or id not in ids:
            raise ValueError('UNKNOWN_LEARNING_UNIT')
        if status not in {'not_started', 'in_progress', 'completed'}:
            raise ValueError('INVALID_LEARNING_STATUS')
        if not isinstance(notes, str) or len(notes) > 6000:
            raise ValueError('INVALID_LEARNING_NOTES')
        value = dict(id=id, status=status, notes=notes, updatedAt=utc())
        with self.store.db() as db:
            db.execute('INSERT INTO research_progress VALUES(:id,:status,:notes,:updatedAt) '
                       'ON CONFLICT(id) DO UPDATE SET status=excluded.status,notes=excluded.notes,updatedAt=excluded.updatedAt', value)
            db.execute('INSERT INTO research_progress_events(id,status,notes,updatedAt) VALUES(:id,:status,:notes,:updatedAt)', value)
        return {**value, 'meaning': '个人学习自记，不是系统考核或项目验收'}

    def state(self):
        result, errors = self._config()
        with self.store.db() as db:
            docs = [dict(r) for r in db.execute('SELECT * FROM documents ORDER BY retrievedAt,id')]
            progress = {r['id']: dict(r) for r in db.execute('SELECT * FROM research_progress')}
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            sources = [dict(r) for r in db.execute('SELECT * FROM pipeline_sources')] if 'pipeline_sources' in tables else []
        validator = ReferenceValidator(docs, document_scopes(self.store, docs, tables))
        unresolved = validate_research(result, progress, validator.validate)
        gaps = acquisition_gaps(result['cases'], sources, validator.latest)
        result.update(generatedAt=utc(), changes=version_changes(docs),
            audit={'unresolvedClaims': unresolved, 'invalidReferences': len(validator.invalid), 'invalidDetails': validator.invalid,
                   'staleReferences': len(validator.stale), 'staleDetails': validator.stale, 'referenceCount': validator.count,
                   'notIndependentlyVerified': len(result['cases']), 'independentlyVerifiedProjects': 0,
                   'acquisitionGaps': gaps, 'configErrors': errors},
            practiceProgress=progress,
            boundary='研究路径、归类与中文字段是编辑组织的研究索引；原始标题、文本和版本独立保留。逐字匹配不证明事实属实。')
        return result

    def export(self):
        result = self.state()
        directory = self.store.directory / 'research'
        directory.mkdir(exist_ok=True)
        path = directory / ('audit-' + result['generatedAt'].replace(':', '-').replace('+', '_') + '.json')
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        (directory / 'latest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return {'path': str(path), 'audit': result['audit']}

"""Bounded, credential-free GitHub evidence collection; repository code is never run."""
from __future__ import annotations

import argparse
from file_lock import exclusive_file_lock

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import quote, urlencode, urlsplit
import uuid

from acquisition import AcquisitionError, _follow, _headers
from agent import ROOT, Store

WEEK_SECONDS = 7 * 24 * 3600
MAX_API_PER_RUN = 45
MAX_SEARCHES = 3
MAX_DISCOVERED = 6
MAX_RESOURCES = 120
MAX_RUN_SECONDS = 480
NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9_.-]{1,100}$')
ALLOWED_HOSTS = {'api.github.com', 'raw.githubusercontent.com', 'github.com', 'www.github.com'}


def _now():
    return datetime.now(timezone.utc)


def _iso(value):
    return value.astimezone(timezone.utc).isoformat()


def _next_week(value):
    """Eligibility date, not an appointment: the existing NY 09:00 heartbeat runs it."""
    value = value.astimezone(timezone.utc)
    days = (7 - value.weekday()) % 7 or 7
    return (value + timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)


def _date(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc) if value else None
    except (ValueError, TypeError, AttributeError):
        return None


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _valid_name(value):
    if not isinstance(value, str) or not NAME.fullmatch(value) or any(p in {'.', '..'} for p in value.split('/')):
        raise ValueError('INVALID_GITHUB_REPOSITORY')
    return value


def discovery_exclusion(item):
    """Reject observed recruiting listings, not ordinary engineering 'jobs' terminology."""
    name = str(item.get('full_name') or '').rsplit('/', 1)[-1].lower()
    description = item.get('description') if isinstance(item.get('description'), str) else ''
    name_patterns = [
        r'(?:^|[-_])new[-_]?grad(?:[-_]|$).*jobs?',
        r'(?:^|[-_])jobs?[-_]?(?:boards?|listings?|feeds?|trackers?|radars?)(?:[-_]|$)',
        r'(?:^|[-_])(?:swe|internship|recruitment)[-_](?:radar|jobs|tracker)(?:[-_]|$)',
    ]
    description_patterns = [
        r'\b(?:jobs?|careers?|recruitment|internships?)\s+(?:boards?|listings?|feeds?|aggregators?|trackers?|radars?)\b',
        r'\b(?:new[- ]grad|entry[- ]level)\b.{0,50}\bjobs?\b',
        r'\b(?:software[- ]engineering|software[- ]engineer)\s+(?:internships?|jobs?)\b',
        r'\b(?:curated|verified|updated|live)\b.{0,80}\b(?:internships?|job openings)\b.{0,40}\b(?:radar|list|board|feed)\b',
        r'(?:招聘|职位|岗位).{0,12}(?:清单|列表|聚合|信息汇总)|(?:清单|列表|聚合).{0,12}(?:招聘|职位)',
    ]
    if any(re.search(pattern, name) for pattern in name_patterns) or any(re.search(pattern, description, re.I) for pattern in description_patterns):
        return '仓库名称或原始描述显示为招聘／职位清单，不属于本体、数据治理或 FDE 交付工具与项目。'
    return None


def _safe_url(url):
    part = urlsplit(url)
    if part.scheme != 'https' or part.hostname not in ALLOWED_HOSTS or part.username or part.password or part.port not in {None, 443}:
        raise ValueError('INVALID_GITHUB_URL')
    if re.search(r'[\x00-\x20\x7f\\]', url):
        raise ValueError('INVALID_GITHUB_URL')
    return url


def fetch_public(url, *, headers=None, max_bytes=2 * 1024 * 1024, timeout=20):
    """Reuse DNS pinning, TLS verification, public-address and robots checks."""
    _safe_url(url)
    request_headers = _headers()
    request_headers.update(headers or {})
    status, received, body, final, chain = _follow(url, request_headers, max_bytes, time.monotonic() + timeout, robots=True)
    _safe_url(final)
    return {'status': status, 'headers': received, 'body': body, 'url': final, 'redirectChain': chain}


class GitHubBusy(Exception):
    pass


@contextmanager
def collection_lock(directory):
    with exclusive_file_lock(Path(directory) / 'github.lock', GitHubBusy):
        yield


class GitHubResources:
    def __init__(self, store, config_path=None, fetcher=None, now=None):
        self.store = store
        self.config_path = Path(config_path or ROOT / 'config' / 'github-resources.json')
        self.fetcher = fetcher or fetch_public
        self.now = now or _now
        self.directory = store.directory / 'github'
        self.directory.mkdir(parents=True, exist_ok=True)
        with store.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS github_resources(fullName TEXT PRIMARY KEY COLLATE NOCASE, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS github_runs(id TEXT PRIMARY KEY, status TEXT, startedAt TEXT, endedAt TEXT, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS github_state(key TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS github_snapshots(id TEXT PRIMARY KEY, fullName TEXT, kind TEXT, sha256 TEXT,
                  path TEXT, fetchedAt TEXT, status INTEGER, url TEXT);
            ''')
        self.config = self._load_config()
        self._seed()

    def _load_config(self):
        if not self.config_path.exists():
            return {'resources': [], 'searches': []}
        value = json.loads(self.config_path.read_text(encoding='utf-8-sig'))
        if isinstance(value, list):
            value = {'resources': value, 'searches': []}
        if not isinstance(value, dict) or not isinstance(value.get('resources', []), list):
            raise ValueError('INVALID_GITHUB_CONFIG')
        for item in value.get('resources', []):
            _valid_name(item.get('fullName'))
            if item.get('category') not in {'ontology', 'governance', 'fde'}:
                raise ValueError('INVALID_GITHUB_CATEGORY')
        return value

    def _seed(self):
        with self.store.db() as db:
            current = {r['fullName'].lower(): r['payload'] for r in db.execute('SELECT fullName,payload FROM github_resources')}
            for item in self.config.get('resources', []):
                name = _valid_name(item['fullName'])
                original = current.get(name.lower())
                old = json.loads(original) if original else self._new_resource(name, item)
                for key in ['category', 'kind', 'tags', 'selectionReason', 'discoveredVia', 'readmePath']:
                    if key in item:
                        old[key] = item[key]
                old['selectionReasonType'] = 'editorial'
                old['registration'] = 'curated_seed'
                serialized = _json(old)
                if serialized != original:
                    db.execute('INSERT INTO github_resources VALUES(?,?) ON CONFLICT(fullName) DO UPDATE SET payload=excluded.payload',
                               (name, serialized))
                    current[name.lower()] = serialized

    def _new_resource(self, name, item):
        return {'id': 'gh-' + _hash(name.lower().encode())[:20], 'fullName': name,
                'url': 'https://github.com/' + name, 'description': None,
                'category': item.get('category', 'fde'), 'kind': item.get('kind', 'tool'),
                'tags': item.get('tags', []), 'selectionReason': item.get('selectionReason', ''),
                'selectionReasonType': 'editorial', 'registration': item.get('registration', 'search_candidate'),
                'license': None, 'licenseStatus': 'unknown', 'stars': None, 'forks': None,
                'language': None, 'archived': None, 'fork': None, 'pushedAt': None,
                'defaultBranch': None, 'readmeDocumentId': None, 'readmeSha256': None,
                'readmeChars': 0, 'readmeUrl': None, 'lastAttempt': None,
                'lastSuccess': None, 'lastStatus': 'NOT_ATTEMPTED', 'error': None,
                'metadataStatus': 'NOT_ATTEMPTED', 'readmeStatus': 'NOT_ATTEMPTED',
                'metadataAt': None, 'readmeAt': None, 'nextDueAt': None,
                'scope': 'GitHub 仓库元数据及 README；未审计源代码，也不等于真实企业项目或 FDE 参与证据。'}

    def _resource(self, name):
        with self.store.db() as db:
            row = db.execute('SELECT payload FROM github_resources WHERE fullName=?', (name,)).fetchone()
        return json.loads(row[0]) if row else None

    def _save_resource(self, value):
        with self.store.db() as db:
            db.execute('INSERT INTO github_resources VALUES(?,?) ON CONFLICT(fullName) DO UPDATE SET payload=excluded.payload',
                       (value['fullName'], _json(value)))

    def _get(self, key, default=None):
        with self.store.db() as db:
            row = db.execute('SELECT payload FROM github_state WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def _put(self, key, value):
        with self.store.db() as db:
            db.execute('INSERT INTO github_state VALUES(?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload', (key, _json(value)))

    def _all_resources(self):
        with self.store.db() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT payload FROM github_resources ORDER BY fullName')]

    def state(self):
        historical = self._all_resources()
        excluded = [r for r in historical if r.get('reviewStatus') == 'excluded']
        resources = [r for r in historical if r.get('reviewStatus') != 'excluded']
        with self.store.db() as db:
            latest = db.execute('SELECT payload FROM github_runs ORDER BY startedAt DESC,rowid DESC LIMIT 1').fetchone()
            snapshot_count = db.execute('SELECT COUNT(*) FROM github_snapshots').fetchone()[0]
        last = json.loads(latest[0]) if latest else None
        running = False
        try:
            with collection_lock(self.store.directory):
                pass
        except GitHubBusy:
            running = True
        due = [r['nextDueAt'] for r in resources if r.get('nextDueAt')]
        gaps = [{'fullName': r['fullName'], 'metadataStatus': r['metadataStatus'],
                 'readmeStatus': r['readmeStatus'], 'error': r.get('error'), 'nextDueAt': r.get('nextDueAt')}
                for r in resources if r['lastStatus'] not in {'SUCCEEDED', 'UNCHANGED'}]
        return {'resources': resources, 'excluded': excluded,
                'stats': {'registered': len(resources), 'historicalRegistered': len(historical), 'excluded': len(excluded),
                          'metadataFetched': sum(bool(r.get('metadataAt')) for r in resources),
                          'readmeFetched': sum(bool(r.get('readmeDocumentId')) for r in resources),
                          'licenseIdentified': sum(r['licenseStatus'] == 'identified' for r in resources),
                          'licenseUnknown': sum(r['licenseStatus'] == 'unknown' for r in resources),
                          'failed': sum(r['lastStatus'] == 'FAILED' for r in resources),
                          'partial': sum(r['lastStatus'] == 'PARTIAL' for r in resources),
                          'snapshots': snapshot_count,
                          'categories': {c: sum(r['category'] == c for r in resources) for c in ['ontology', 'governance', 'fde']}},
                'lastRun': last, 'nextDueAt': min(due) if due else None, 'running': running,
                'gaps': gaps, 'rateLimits': {b: self._get('rate:' + b, {}) for b in ['core', 'search']},
                'refreshCadenceDays': 7, 'coverage': '精选种子与每周有界 GitHub 检索；没有穷尽 GitHub。公开可见不自动等于开源许可。',
                'discovery': self._get('discovery', {})}

    def _snapshot(self, name, kind, url, response):
        body = response.get('body', b'')
        if isinstance(body, str):
            body = body.encode('utf-8')
        sha = _hash(body)
        suffix = '.json' if kind in {'metadata', 'search'} else '.md'
        rel = Path('github') / 'snapshots' / (sha + suffix)
        path = self.store.directory / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(body)
        now = _iso(self.now())
        identifier = 'ghsnapshot-' + uuid.uuid4().hex
        with self.store.db() as db:
            db.execute('INSERT INTO github_snapshots VALUES(?,?,?,?,?,?,?,?)',
                       (identifier, name, kind, sha, str(rel), now, response.get('status'), url))
        return {'id': identifier, 'sha256': sha, 'path': str(rel), 'retrievedAt': now}

    def _rate_allowed(self, bucket):
        info = self._get('rate:' + bucket, {})
        retry = _date(info.get('retryAt'))
        if retry and retry > self.now():
            return False
        return True

    def _request(self, url, *, bucket=None, validators=None):
        _safe_url(url)
        if time.monotonic() >= self.deadline:
            raise AcquisitionError('run_deadline', '本轮采集达到时间上限；未完成资源将重试。')
        headers = {'Accept': 'application/vnd.github+json' if bucket else 'text/plain'}
        if bucket:
            if not self._rate_allowed(bucket):
                raise AcquisitionError('rate_limited', 'GitHub 限流退避尚未到期。')
            if self.api_calls >= MAX_API_PER_RUN:
                raise AcquisitionError('api_budget', '本轮 GitHub API 请求预算已用完。')
            self.api_calls += 1
            headers['X-GitHub-Api-Version'] = '2022-11-28'
        for name, value in (validators or {}).items():
            if value and isinstance(value, str) and len(value) < 2048 and not re.search(r'[\r\n\x00]', value):
                headers[name] = value
        result = self.fetcher(url, headers=headers, max_bytes=2 * 1024 * 1024,
                              timeout=max(1, min(20, self.deadline - time.monotonic())))
        result['headers'] = {k.lower(): v for k, v in result.get('headers', {}).items()}
        body = result.get('body', b'')
        if isinstance(body, str):
            body = body.encode('utf-8')
        if len(body) > 2 * 1024 * 1024:
            raise AcquisitionError('response_too_large', 'GitHub 响应超过 2 MiB 上限。')
        result['body'] = body
        _safe_url(result.get('url', url))
        received = result['headers']
        if bucket:
            info = {'observedAt': _iso(self.now()), 'remaining': received.get('x-ratelimit-remaining'),
                    'reset': received.get('x-ratelimit-reset'), 'limit': received.get('x-ratelimit-limit')}
            retry = None
            if result['status'] in {403, 429} or received.get('x-ratelimit-remaining') == '0':
                retry = self.now() + timedelta(hours=1)
                try:
                    retry = datetime.fromtimestamp(int(received['x-ratelimit-reset']) + 5, timezone.utc)
                except (KeyError, ValueError, OverflowError):
                    pass
                after = received.get('retry-after')
                if after:
                    try:
                        retry = max(retry, self.now() + timedelta(seconds=int(after)))
                    except ValueError:
                        try:
                            retry = max(retry, parsedate_to_datetime(after).astimezone(timezone.utc))
                        except (ValueError, TypeError):
                            pass
                retry = max(retry, self.now() + timedelta(minutes=1))
            info['retryAt'] = _iso(retry) if retry else None
            self._put('rate:' + bucket, info)
        return result

    def _metadata(self, resource):
        url = 'https://api.github.com/repos/' + resource['fullName']
        response = self._request(url, bucket='core', validators={'If-None-Match': resource.get('metadataEtag'),
                                                               'If-Modified-Since': resource.get('metadataLastModified')})
        status = response['status']
        resource['metadataHttpStatus'] = status
        if status == 304 and resource.get('metadataAt'):
            resource['metadataStatus'] = 'UNCHANGED'
            resource['metadataCheckedAt'] = _iso(self.now())
            return
        if status != 200:
            raise AcquisitionError('metadata_http_' + str(status), '仓库元数据请求 HTTP ' + str(status))
        try:
            value = json.loads(response['body'])
            canonical = _valid_name(value['full_name'])
            if value.get('private') is not False:
                raise ValueError('not public')
            if not isinstance(value.get('default_branch'), str):
                raise ValueError('missing branch')
        except (ValueError, TypeError, KeyError) as exc:
            raise AcquisitionError('invalid_metadata', '响应不是有效的公开仓库元数据。') from exc
        snapshot = self._snapshot(resource['fullName'], 'metadata', url, response)
        previous_hash = (resource.get('metadataSnapshot') or {}).get('sha256')
        tracked = {'description': 'description', 'stars': 'stargazers_count', 'forks': 'forks_count',
                   'language': 'language', 'archived': 'archived', 'fork': 'fork', 'pushedAt': 'pushed_at',
                   'defaultBranch': 'default_branch'}
        changes = {key: {'before': resource.get(key), 'after': value.get(raw_key)}
                   for key, raw_key in tracked.items() if resource.get('metadataAt') and resource.get(key) != value.get(raw_key)}
        license_info = value.get('license') or {}
        spdx = license_info.get('spdx_id')
        license_known = isinstance(spdx, str) and spdx not in {'', 'NOASSERTION', 'NONE'}
        resource.update(canonicalFullName=canonical, url='https://github.com/' + canonical,
                        description=value.get('description'), stars=value.get('stargazers_count'),
                        forks=value.get('forks_count'), language=value.get('language'),
                        archived=value.get('archived'), fork=value.get('fork'), pushedAt=value.get('pushed_at'),
                        defaultBranch=value.get('default_branch'), topics=value.get('topics', []),
                        license=spdx if license_known else None, licenseName=license_info.get('name'),
                        licenseStatus='identified' if license_known else 'unknown',
                        licenseMeaning='GitHub 元数据识别；具体使用仍以仓库许可文件及适用条件为准。',
                        metadataStatus='SUCCEEDED', metadataAt=_iso(self.now()), metadataCheckedAt=_iso(self.now()),
                        metadataEtag=response['headers'].get('etag'), metadataLastModified=response['headers'].get('last-modified'),
                        metadataChanged=bool(previous_hash and previous_hash != snapshot['sha256']), metadataChanges=changes,
                        metadataSnapshot=snapshot)

    def _readme(self, resource):
        name = resource.get('canonicalFullName') or resource['fullName']
        branches = [resource['defaultBranch']] if resource.get('defaultBranch') else ['main', 'master']
        paths = list(dict.fromkeys([p for p in [resource.get('readmePath'), 'README.md', 'README.rst', 'README'] if p]))
        candidates = []
        if resource.get('readmeUrl'):
            candidates.append(resource['readmeUrl'])
        for branch in branches:
            for path in paths:
                if not isinstance(path, str) or '..' in path.split('/') or path.startswith('/') or '\\' in path:
                    continue
                candidates.append('https://raw.githubusercontent.com/' + name + '/' + quote(branch, safe='') + '/' + quote(path, safe='/'))
        attempts = []
        for url in list(dict.fromkeys(candidates))[:6]:
            validators = {'If-None-Match': resource.get('readmeEtag'), 'If-Modified-Since': resource.get('readmeLastModified')} if url == resource.get('readmeUrl') else None
            response = self._request(url, validators=validators)
            attempts.append({'url': url, 'status': response['status']})
            if response['status'] == 304 and resource.get('readmeDocumentId'):
                resource.update(readmeStatus='UNCHANGED', readmeCheckedAt=_iso(self.now()), readmeAttempts=attempts)
                return
            if response['status'] == 404:
                continue
            if response['status'] != 200:
                resource['readmeAttempts'] = attempts
                raise AcquisitionError('readme_http_' + str(response['status']), 'README 请求 HTTP ' + str(response['status']))
            try:
                content = response['body'].decode('utf-8-sig')
            except UnicodeDecodeError as exc:
                raise AcquisitionError('readme_encoding', 'README 不是可可靠解码的 UTF-8 文本。') from exc
            if len(content.strip()) < 80 or '\x00' in content or re.match(r'\s*(<!doctype html|<html)', content, re.I):
                resource['readmeAttempts'] = attempts
                raise AcquisitionError('readme_insufficient', '未取得可读 README 正文；短占位或 HTML 响应不计采集成功。')
            snapshot = self._snapshot(resource['fullName'], 'readme', url, response)
            previous_hash = resource.get('readmeSha256')
            document = self.store.document(url, name + ' — README', content, 'github_readme')
            resource.update(readmeDocumentId=document['id'], readmeSha256=document['sha256'], readmeChars=len(content),
                            readmeUrl=url, readmeStatus='SUCCEEDED', readmeAt=_iso(self.now()),
                            readmeCheckedAt=_iso(self.now()), readmeEtag=response['headers'].get('etag'),
                            readmeLastModified=response['headers'].get('last-modified'),
                            readmeChanged=bool(previous_hash and previous_hash != document['sha256']),
                            readmeSnapshot=snapshot, readmeAttempts=attempts,
                            readmeScope='仓库默认分支 README 原始文本；不是整个仓库，也未取得所有代码、文档或关联论文。')
            return
        resource['readmeAttempts'] = attempts
        raise AcquisitionError('readme_not_found', '常见 README 路径未找到；没有声称已穷尽仓库文件。')

    def _collect(self, resource):
        resource['lastAttempt'] = _iso(self.now())
        errors = []
        for stage, action in [('metadata', self._metadata), ('readme', self._readme)]:
            try:
                action(resource)
            except AcquisitionError as exc:
                resource[stage + 'Status'] = exc.code.upper()
                errors.append(exc.code + ': ' + str(exc))
            except Exception as exc:
                resource[stage + 'Status'] = 'FAILED'
                errors.append(stage + ': ' + type(exc).__name__)
        okay = [resource[s + 'Status'] in {'SUCCEEDED', 'UNCHANGED'} for s in ['metadata', 'readme']]
        resource['lastStatus'] = ('UNCHANGED' if all(resource[s + 'Status'] == 'UNCHANGED' for s in ['metadata', 'readme']) else 'SUCCEEDED') if all(okay) else ('PARTIAL' if any(okay) else 'FAILED')
        resource['error'] = '; '.join(errors) if errors else None
        if all(okay):
            resource['lastSuccess'] = _iso(self.now())
            resource['consecutiveFailures'] = 0
            next_due = _next_week(self.now())
        else:
            resource['consecutiveFailures'] = min(resource.get('consecutiveFailures', 0) + 1, 10)
            next_due = self.now() + timedelta(hours=min(24 * (2 ** (resource['consecutiveFailures'] - 1)), 7 * 24))
        retry = _date(self._get('rate:core', {}).get('retryAt'))
        if not okay[0] and retry:
            next_due = max(next_due, retry)
        resource['nextDueAt'] = _iso(next_due)
        self._save_resource(resource)
        return {'fullName': resource['fullName'], 'status': resource['lastStatus'], 'metadataStatus': resource['metadataStatus'],
                'readmeStatus': resource['readmeStatus'], 'documentId': resource.get('readmeDocumentId'), 'error': resource['error']}

    def _discover(self):
        previous = self._get('discovery', {})
        next_due = _date(previous.get('nextDueAt'))
        if next_due and next_due > self.now():
            return {'status': 'NOT_DUE', 'nextDueAt': previous['nextDueAt'], 'queries': [], 'registered': []}
        searches = self.config.get('searches', self.config.get('queries', []))
        receipt = {'startedAt': _iso(self.now()), 'queries': [], 'registered': [], 'scope': '每轮最多3条检索、每条第1页10个结果；未遍历全部分页，未穷尽 GitHub。'}
        offset = previous.get('cursor', 0) % max(1, len(searches))
        cursor = offset
        for index in range(min(MAX_SEARCHES, len(searches))):
            entry = searches[(offset + index) % len(searches)]
            query = entry['query'] if isinstance(entry, dict) else entry
            category = entry.get('category', 'fde') if isinstance(entry, dict) else 'fde'
            if not isinstance(query, str) or len(query) > 400 or category not in {'ontology', 'governance', 'fde'}:
                continue
            url = 'https://api.github.com/search/repositories?' + urlencode({'q': query, 'sort': 'updated', 'order': 'desc', 'per_page': 10, 'page': 1})
            query_receipt = {'query': query, 'url': url, 'page': 1, 'perPage': 10, 'category': category, 'rejected': []}
            try:
                response = self._request(url, bucket='search')
                query_receipt['httpStatus'] = response['status']
                if response['status'] != 200:
                    raise AcquisitionError('search_http_' + str(response['status']), 'GitHub 检索未取得结果。')
                value = json.loads(response['body'])
                if not isinstance(value.get('items'), list):
                    raise ValueError('invalid result')
                query_receipt.update(status='SUCCEEDED', totalCount=value.get('total_count'),
                                     incompleteResults=value.get('incomplete_results'), obtained=len(value['items']),
                                     snapshot=self._snapshot('', 'search', url, response))
                added_this_query = 0
                for item in value['items']:
                    if added_this_query >= 2 or len(receipt['registered']) >= MAX_DISCOVERED or len([r for r in self._all_resources() if r.get('reviewStatus') != 'excluded']) >= MAX_RESOURCES:
                        break
                    name = _valid_name(item.get('full_name'))
                    exclusion = discovery_exclusion(item)
                    if exclusion:
                        query_receipt['rejected'].append({'fullName': name, 'reason': exclusion})
                        continue
                    if not self._resource(name) and item.get('private') is False and not item.get('fork'):
                        new = self._new_resource(name, {'category': category, 'kind': 'tool',
                             'selectionReason': 'GitHub 检索命中候选；相关性、工程质量和实际 FDE 参与尚待复核。'})
                        new['discoveredVia'] = {'query': query, 'url': url, 'retrievedAt': _iso(self.now())}
                        self._save_resource(new)
                        receipt['registered'].append(name)
                        added_this_query += 1
                cursor = (offset + index + 1) % max(1, len(searches))
            except AcquisitionError as exc:
                query_receipt.update(status=exc.code.upper(), error=str(exc))
            except (ValueError, TypeError, KeyError) as exc:
                query_receipt.update(status='INVALID_RESPONSE', error=type(exc).__name__)
            receipt['queries'].append(query_receipt)
            if query_receipt['status'] != 'SUCCEEDED':
                # Retry this same query later; failure must not advance the cursor.
                break
        succeeded = all(q['status'] == 'SUCCEEDED' for q in receipt['queries'])
        receipt.update(status='SUCCEEDED' if succeeded else 'PARTIAL', cursor=cursor if succeeded else offset, endedAt=_iso(self.now()),
                       nextDueAt=_iso(_next_week(self.now()) if succeeded else self.now() + timedelta(days=1)))
        self._put('discovery', receipt)
        return receipt

    def refresh(self, force=False):
        try:
            with collection_lock(self.store.directory):
                return self._refresh_locked(force)
        except GitHubBusy:
            return {'status': 'RUNNING', 'message': 'GitHub 采集已在进行中。'}

    def _refresh_locked(self, force):
        self.deadline = time.monotonic() + MAX_RUN_SECONDS
        self.api_calls = 0
        self.config = self._load_config()
        self._seed()
        # Upgrade earlier completion+7d timestamps to the next weekly eligibility day.
        # Daily NY 09:00 triggers then run on Monday instead of drifting to Tuesday.
        for resource in [r for r in self._all_resources() if r.get('reviewStatus') != 'excluded']:
            last_success = _date(resource.get('lastSuccess'))
            if resource['lastStatus'] in {'SUCCEEDED', 'UNCHANGED'} and last_success:
                eligible = _iso(_next_week(last_success))
                if resource.get('nextDueAt') != eligible:
                    resource['nextDueAt'] = eligible
                    self._save_resource(resource)
        due = [r for r in self._all_resources() if r.get('reviewStatus') != 'excluded'
               and (force or not _date(r.get('nextDueAt')) or _date(r['nextDueAt']) <= self.now())]
        discovery_due = not _date(self._get('discovery', {}).get('nextDueAt')) or _date(self._get('discovery', {})['nextDueAt']) <= self.now()
        if not due and not discovery_due:
            dates = [r['nextDueAt'] for r in self._all_resources() if r.get('nextDueAt') and r.get('reviewStatus') != 'excluded']
            return {'status': 'NOT_DUE', 'nextDueAt': min(dates) if dates else None, 'items': []}
        with self.store.db() as db:
            for row in db.execute("SELECT id,payload FROM github_runs WHERE status='RUNNING'").fetchall():
                orphan = json.loads(row['payload'])
                orphan.update(status='INTERRUPTED', endedAt=_iso(self.now()), error='此前采集进程已中断；保留已提交资料，未完成资源待重试。')
                db.execute('UPDATE github_runs SET status=?,endedAt=?,payload=? WHERE id=?', ('INTERRUPTED', orphan['endedAt'], _json(orphan), row['id']))
        receipt = {'id': 'ghrun-' + uuid.uuid4().hex, 'status': 'RUNNING', 'startedAt': _iso(self.now()),
                   'endedAt': None, 'trigger': 'manual' if force else 'due_check', 'items': [], 'apiRequests': 0,
                   'scope': '只获取公开仓库元数据和 README，不克隆、不安装、不运行仓库代码。'}
        self._save_run(receipt)
        # Existing registrations are collected first; discovery cannot starve curated sources.
        for resource in due:
            if time.monotonic() >= self.deadline:
                receipt['deferred'] = len(due) - len(receipt['items'])
                break
            receipt['items'].append(self._collect(resource))
            receipt['apiRequests'] = self.api_calls
            self._save_run(receipt)
        receipt['discovery'] = self._discover() if time.monotonic() < self.deadline else {'status': 'DEFERRED'}
        for name in receipt['discovery'].get('registered', []):
            if time.monotonic() >= self.deadline:
                break
            receipt['items'].append(self._collect(self._resource(name)))
            self._save_run(receipt)
        has_gaps = any(r['status'] not in {'SUCCEEDED', 'UNCHANGED'} for r in receipt['items'])
        has_gaps |= receipt['discovery']['status'] not in {'SUCCEEDED', 'NOT_DUE'} or bool(receipt.get('deferred'))
        receipt.update(status='COMPLETED_WITH_GAPS' if has_gaps else 'COMPLETED', endedAt=_iso(self.now()), apiRequests=self.api_calls,
                       counts={s: sum(r['status'] == s for r in receipt['items']) for s in ['SUCCEEDED', 'UNCHANGED', 'PARTIAL', 'FAILED']})
        self._save_run(receipt)
        (self.directory / (receipt['id'] + '.json')).write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        (self.directory / 'latest-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        return receipt

    def _save_run(self, value):
        with self.store.db() as db:
            db.execute('INSERT INTO github_runs VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,endedAt=excluded.endedAt,payload=excluded.payload',
                       (value['id'], value['status'], value['startedAt'], value.get('endedAt'), _json(value)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', default=str(ROOT / 'var'))
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--state', action='store_true')
    args = parser.parse_args()
    collector = GitHubResources(Store(args.data))
    print(json.dumps(collector.state() if args.state else collector.refresh(force=args.force), ensure_ascii=False, indent=2))

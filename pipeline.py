"""Persistent, bounded acquisition queue; source text never passes through an LLM.

The queue is independent of DSH reasoning runs.  Its events deliberately use
``pipeline_fetch`` so a successful HTTP request is not counted as a DSH search,
an independently verified case, or proof that a whole website was searched.
"""
from __future__ import annotations

from file_lock import exclusive_file_lock

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
import uuid


ROOT = Path(__file__).resolve().parent
FULL_ACCESS = {'body_fetched_not_semantically_verified', 'body_fetched', 'text_fetched'}
ACTIVE_JOBS = ('QUEUED', 'RUNNING')
REVIEW_STATES = {'pending_review', 'accepted', 'rejected'}


def utc():
    return datetime.now(timezone.utc).isoformat()


def encoded(value):
    return json.dumps(value, ensure_ascii=False)


def _label(value, default=''):
    """Retain historical scalar/list labels without inventing classifications."""
    if value is None:
        return default
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return ' / '.join(_label(item) for item in value if item is not None) or default
    if isinstance(value, dict):
        for key in ('title', 'name', 'label', 'type', 'value'):
            if value.get(key):
                return _label(value[key], default)
        return encoded(value)
    return str(value)


def normalize_url(value):
    if not isinstance(value, str) or len(value) > 8192:
        raise ValueError('INVALID_SOURCE_URL')
    try:
        parts = urlsplit(value.strip())
        host = (parts.hostname or '').lower()
        port = parts.port
    except ValueError as exc:
        raise ValueError('INVALID_SOURCE_URL') from exc
    if parts.scheme.lower() not in {'http', 'https'} or not host or parts.username or parts.password:
        raise ValueError('INVALID_SOURCE_URL')
    if host in {'localhost', 'localhost.localdomain'} or host.endswith(('.localhost', '.local', '.internal')):
        raise ValueError('PRIVATE_SOURCE_URL')
    try:
        if not ipaddress.ip_address(host).is_global:
            raise ValueError('PRIVATE_SOURCE_URL')
    except ValueError as exc:
        if str(exc) == 'PRIVATE_SOURCE_URL':
            raise
    netloc = '[' + host + ']' if ':' in host else host
    if port is not None and not ((parts.scheme.lower() == 'https' and port == 443) or (parts.scheme.lower() == 'http' and port == 80)):
        netloc += ':' + str(port)
    return urlunsplit((parts.scheme.lower(), netloc, parts.path or '/', parts.query, ''))


def _record_urls(value, key=''):
    """Read explicit URL fields, never turn prose or a search snippet into a URL."""
    found = []
    if isinstance(value, dict):
        for name, item in value.items():
            found.extend(_record_urls(item, name))
    elif isinstance(value, list):
        for item in value:
            found.extend(_record_urls(item, key))
    elif isinstance(value, str) and ('url' in key.lower() or key.lower() in {'link', 'links', 'href', 'source'}):
        if value.startswith(('https://', 'http://')):
            try:
                found.append(normalize_url(value))
            except ValueError:
                pass
    return list(dict.fromkeys(found))


@contextmanager
def _worker_lock(directory):
    with exclusive_file_lock(Path(directory) / 'pipeline.lock', lambda: RuntimeError('PIPELINE_BUSY')):
        yield


class Pipeline:
    def __init__(self, store, acquire_callable=None):
        self.store = store
        self.acquire_callable = acquire_callable
        with store.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS pipeline_sources(
              url TEXT PRIMARY KEY, id TEXT NOT NULL, title TEXT NOT NULL,
              sourceId TEXT, channel TEXT, origins TEXT NOT NULL DEFAULT '[]',
              candidate INTEGER NOT NULL DEFAULT 1, enabled INTEGER NOT NULL DEFAULT 1,
              cadenceHours REAL NOT NULL DEFAULT 24, discoveryLimit INTEGER NOT NULL DEFAULT 10,
              discoveredFrom TEXT, createdAt TEXT NOT NULL,
              lastAttempt TEXT, lastSuccess TEXT, nextDue TEXT,
              etag TEXT, lastModified TEXT, lastHash TEXT, lastDocumentId TEXT,
              access TEXT NOT NULL DEFAULT 'not_attempted', httpStatus INTEGER,
              error TEXT, attempts INTEGER NOT NULL DEFAULT 0,
              totalAttempts INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS pipeline_jobs(
              id TEXT PRIMARY KEY, status TEXT NOT NULL, reason TEXT NOT NULL,
              createdAt TEXT NOT NULL, startedAt TEXT, endedAt TEXT,
              cancelRequested INTEGER NOT NULL DEFAULT 0, error TEXT
            );
            CREATE TABLE IF NOT EXISTS pipeline_items(
              id INTEGER PRIMARY KEY, jobId TEXT NOT NULL, url TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'QUEUED', startedAt TEXT, endedAt TEXT,
              attempts INTEGER NOT NULL DEFAULT 0, documentId TEXT, result TEXT,
              UNIQUE(jobId,url)
            );
            CREATE INDEX IF NOT EXISTS pipeline_due ON pipeline_sources(enabled,nextDue);
            CREATE INDEX IF NOT EXISTS pipeline_job_items ON pipeline_items(jobId,status);
            ''')

    def update_source(self, data):
        if not isinstance(data, dict):
            raise ValueError('INVALID_SOURCE')
        url = normalize_url(data.get('url'))
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT * FROM pipeline_sources WHERE url=?', (url,)).fetchone()
            cadence = data.get('cadenceHours', prior['cadenceHours'] if prior else 24)
            discovery = data.get('discoveryLimit', prior['discoveryLimit'] if prior else 10)
            if isinstance(cadence, bool) or not isinstance(cadence, (int, float)) or not 1 / 60 <= cadence <= 8760:
                raise ValueError('INVALID_CADENCE_HOURS')
            if isinstance(discovery, bool) or not isinstance(discovery, int) or not 0 <= discovery <= 50:
                raise ValueError('INVALID_DISCOVERY_LIMIT')
            for flag in ('candidate', 'enabled'):
                if flag in data and not isinstance(data[flag], bool):
                    raise ValueError('INVALID_' + flag.upper())
            for field in ('title', 'sourceId', 'channel', 'discoveredFrom'):
                if field in data and data[field] is not None and (not isinstance(data[field], str) or len(data[field]) > 8192):
                    raise ValueError('INVALID_SOURCE_' + field.upper())
            if 'title' in data and data['title'] is None:
                data = dict(data, title=prior['title'] if prior else url)
            origins = json.loads(prior['origins']) if prior else []
            incoming = data.get('origins', [data['origin']] if data.get('origin') else [])
            if not isinstance(incoming, list) or any(not isinstance(v, str) or len(v) > 1000 for v in incoming):
                raise ValueError('INVALID_SOURCE_ORIGINS')
            origins = list(dict.fromkeys(origins + incoming))[:100]
            if prior:
                allowed = {'title', 'sourceId', 'channel', 'candidate', 'enabled', 'discoveredFrom'}
                fields = {key: data[key] for key in allowed if key in data}
                fields.update(cadenceHours=cadence, discoveryLimit=discovery, origins=encoded(origins))
                db.execute('UPDATE pipeline_sources SET ' + ','.join(key + '=?' for key in fields) + ' WHERE url=?',
                           (*fields.values(), url))
            else:
                db.execute('''INSERT INTO pipeline_sources
                  (url,id,title,sourceId,channel,origins,candidate,enabled,cadenceHours,discoveryLimit,discoveredFrom,createdAt)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (url, 'source-' + hashlib.sha256(url.encode()).hexdigest()[:20], str(data.get('title') or url)[:2000],
                   data.get('sourceId'), data.get('channel', 'unclassified'), encoded(origins),
                   int(data.get('candidate', True)), int(data.get('enabled', True)), cadence, discovery,
                   data.get('discoveredFrom'), utc()))
            result = dict(db.execute('SELECT * FROM pipeline_sources WHERE url=?', (url,)).fetchone())
        return self._source(result)

    @staticmethod
    def _source(row):
        row = dict(row)
        row['origins'] = json.loads(row['origins'])
        row['candidate'] = bool(row['candidate'])
        row['enabled'] = bool(row['enabled'])
        row['independentlyVerified'] = False
        return row

    def seed(self, candidate_paths=None, include_records=True):
        """Register existing URLs without claiming that the new collector read them."""
        with self.store.db() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM sources')]
            records = [dict(r) for r in db.execute('SELECT * FROM records')] if include_records else []
            existing = {r['url']: r['channel'] for r in db.execute('SELECT url,channel FROM pipeline_sources')}
        added, seen, errors = 0, set(), []

        def register(url, **metadata):
            nonlocal added
            try:
                url = normalize_url(url)
                for field in ('title', 'sourceId', 'channel', 'discoveredFrom'):
                    if field in metadata and metadata[field] is not None:
                        metadata[field] = _label(metadata[field])[:2000]
                # Seeding does not reset user cadence, enablement, or classification.
                if url in existing:
                    incoming_channel = metadata.get('channel')
                    metadata = {'origins': metadata.get('origins', [])}
                    if existing[url] in {'unclassified', 'candidate', 'historical_record', None, ''} and incoming_channel:
                        metadata['channel'] = incoming_channel
                self.update_source(dict(url=url, **metadata))
                if url not in existing:
                    added += 1
                    existing[url] = metadata.get('channel')
                elif metadata.get('channel'):
                    existing[url] = metadata['channel']
                seen.add(url)
            except (ValueError, TypeError) as exc:
                errors.append({'url': str(url)[:300], 'error': str(exc)})

        for row in rows:
            record = json.loads(row['payload'])
            if record.get('source_kind') == 'acquisition_tool' or row['id'] == 'search_api':
                continue
            cadence = 168 if '周' in str(record.get('cadence', '')) else 24
            for url in record.get('urls', []):
                register(url, title=record.get('name', row['id']), sourceId=row['id'],
                         origins=['registry:' + row['id']], candidate=False, cadenceHours=cadence,
                         channel=record.get('role', 'unclassified'))
        for row in records:
            record = json.loads(row['payload'])
            for url in _record_urls(record):
                register(url, title=record.get('title') or record.get('name') or url,
                         sourceId='record:' + row['id'], origins=['record:' + row['id']],
                         candidate=True, channel=record.get('channel') or record.get('media_type') or record.get('media') or record.get('track') or 'historical_record', discoveryLimit=0)
        paths = sorted((ROOT / 'config').glob('source-discovery-*.json')) if candidate_paths is None else candidate_paths
        for path in paths:
            path = Path(path)
            try:
                data = json.loads(path.read_text(encoding='utf-8-sig'))
            except (OSError, ValueError) as exc:
                errors.append({'path': str(path), 'error': str(exc)})
                continue
            for item in data.get('candidates', []):
                register(item.get('url'), title=item.get('title'), sourceId=item.get('id'),
                         origins=['candidate_file:' + path.name], channel=item.get('channel') or item.get('role') or item.get('media_type') or item.get('media') or item.get('track') or 'candidate', candidate=True)
        return {'added': added, 'seen': len(seen), 'total': len(self.sources()), 'errors': errors,
                'meaning': 'URL 已登记；候选、历史阅读记录和实际本轮获取分别记录。'}

    def sources(self, query='', limit=2000):
        if not isinstance(limit, int) or not 1 <= limit <= 10000:
            raise ValueError('INVALID_LIMIT')
        with self.store.db() as db:
            rows = db.execute('''SELECT * FROM pipeline_sources WHERE url LIKE ? OR title LIKE ?
              OR channel LIKE ? ORDER BY COALESCE(lastAttempt,''),createdAt,url LIMIT ?''',
              ('%' + query + '%', '%' + query + '%', '%' + query + '%', limit)).fetchall()
        return [self._source(row) for row in rows]

    def enqueue(self, urls=None, force=False, limit=20, reason='manual'):
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise ValueError('INVALID_LIMIT')
        if urls is not None:
            if not isinstance(urls, (list, tuple)):
                raise ValueError('URLS_MUST_BE_LIST')
            urls = list(dict.fromkeys(normalize_url(url) for url in urls))
            with self.store.db() as db:
                existing = {row['url'] for row in db.execute('SELECT url FROM pipeline_sources')}
            for url in urls:
                if url not in existing:
                    self.update_source({'url': url, 'origin': 'explicit_request', 'candidate': True})
        now, job_id = utc(), 'job-' + uuid.uuid4().hex
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            pending = {row['url'] for row in db.execute('''SELECT i.url FROM pipeline_items i
              JOIN pipeline_jobs j ON i.jobId=j.id WHERE j.status IN ('QUEUED','RUNNING')
              AND i.status IN ('QUEUED','RUNNING')''')}
            rows = db.execute('''SELECT url,enabled,nextDue FROM pipeline_sources
              ORDER BY COALESCE(lastAttempt,''),createdAt,url''').fetchall()
            wanted = set(urls) if urls is not None else None
            selected = [r['url'] for r in rows if r['enabled'] and r['url'] not in pending
                        and (wanted is None or r['url'] in wanted)
                        and (force or not r['nextDue'] or r['nextDue'] <= now)][:limit]
            status = 'QUEUED' if selected else 'COMPLETED_EMPTY'
            db.execute('INSERT INTO pipeline_jobs(id,status,reason,createdAt,endedAt) VALUES(?,?,?,?,?)',
                       (job_id, status, str(reason)[:2000], now, now if not selected else None))
            db.executemany('INSERT INTO pipeline_items(jobId,url) VALUES(?,?)', [(job_id, url) for url in selected])
        self.store.event(job_id, 'pipeline_enqueued', {'urls': selected, 'force': bool(force), 'reason': reason})
        return self.get_job(job_id)

    def get_job(self, job_id, include_items=True):
        with self.store.db() as db:
            row = db.execute('SELECT * FROM pipeline_jobs WHERE id=?', (job_id,)).fetchone()
            if not row:
                raise ValueError('JOB_NOT_FOUND')
            value = dict(row)
            items = [dict(item) for item in db.execute('SELECT * FROM pipeline_items WHERE jobId=? ORDER BY id', (job_id,))]
        value['cancelRequested'] = bool(value['cancelRequested'])
        value['total'] = len(items)
        value['counts'] = {state.lower(): sum(item['status'] == state for item in items)
                           for state in ('QUEUED', 'RUNNING', 'SUCCEEDED', 'UNCHANGED', 'PARTIAL', 'FAILED', 'CANCELLED')}
        if include_items:
            for item in items:
                item['result'] = json.loads(item['result']) if item['result'] else None
            value['items'] = items
        return value

    def jobs(self, limit=30):
        if not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError('INVALID_LIMIT')
        with self.store.db() as db:
            ids = [row['id'] for row in db.execute('SELECT id FROM pipeline_jobs ORDER BY createdAt DESC LIMIT ?', (limit,))]
        return [self.get_job(job_id, include_items=False) for job_id in ids]

    def cancel_job(self, job_id):
        with self.store.db() as db:
            row = db.execute('SELECT status FROM pipeline_jobs WHERE id=?', (job_id,)).fetchone()
            if not row:
                raise ValueError('JOB_NOT_FOUND')
            if row['status'] in {'QUEUED', 'RUNNING', 'INTERRUPTED'}:
                db.execute('UPDATE pipeline_jobs SET cancelRequested=1 WHERE id=?', (job_id,))
                if row['status'] != 'RUNNING':
                    db.execute("UPDATE pipeline_items SET status='CANCELLED',endedAt=? WHERE jobId=? AND status='QUEUED'", (utc(), job_id))
                    db.execute("UPDATE pipeline_jobs SET status='CANCELLED',endedAt=? WHERE id=?", (utc(), job_id))
        return self.get_job(job_id)

    def _cancelled(self, job_id, cancel):
        if cancel is not None:
            external = cancel.is_set() if hasattr(cancel, 'is_set') else cancel() if callable(cancel) else bool(cancel)
            if external:
                self.cancel_job(job_id)
                return True
        with self.store.db() as db:
            return bool(db.execute('SELECT cancelRequested FROM pipeline_jobs WHERE id=?', (job_id,)).fetchone()[0])

    def run_job(self, job_id, cancel=None, max_workers=4):
        """Run bounded requests; cancelling stops new requests, not an in-flight socket."""
        if not isinstance(max_workers, int) or not 1 <= max_workers <= 8:
            raise ValueError('INVALID_WORKER_COUNT')
        with _worker_lock(self.store.directory):
            with self.store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                target = db.execute('SELECT * FROM pipeline_jobs WHERE id=?', (job_id,)).fetchone()
                if not target:
                    raise ValueError('JOB_NOT_FOUND')
                if target['status'] not in {'QUEUED', 'RUNNING', 'INTERRUPTED'}:
                    return self.get_job(job_id)
                # Holding the process lock proves these RUNNING rows have no live pool.
                db.execute("UPDATE pipeline_jobs SET status='INTERRUPTED',error='Worker exited before completion' WHERE status='RUNNING'")
                db.execute("UPDATE pipeline_items SET status='QUEUED',startedAt=NULL WHERE status='RUNNING'")
                db.execute("UPDATE pipeline_jobs SET status='RUNNING',startedAt=COALESCE(startedAt,?),endedAt=NULL,error=NULL WHERE id=?", (utc(), job_id))
                queue = [dict(row) for row in db.execute("SELECT * FROM pipeline_items WHERE jobId=? AND status='QUEUED' ORDER BY id", (job_id,))]
            try:
                with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='radar-acquire') as pool:
                    pending = {}
                    remaining = iter(queue)
                    exhausted = False
                    while pending or not exhausted:
                        stopping = self._cancelled(job_id, cancel)
                        while not stopping and not exhausted and len(pending) < max_workers:
                            item = next(remaining, None)
                            if item is None:
                                exhausted = True
                                break
                            pending[pool.submit(self._run_item, job_id, item)] = item
                        if stopping:
                            exhausted = True
                        if pending:
                            done, _ = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
                            for future in done:
                                future.result()
                                del pending[future]
                cancelled = self._cancelled(job_id, cancel)
                with self.store.db() as db:
                    if cancelled:
                        db.execute("UPDATE pipeline_items SET status='CANCELLED',endedAt=? WHERE jobId=? AND status='QUEUED'", (utc(), job_id))
                    counts = dict(db.execute('SELECT status,COUNT(*) FROM pipeline_items WHERE jobId=? GROUP BY status', (job_id,)).fetchall())
                    status = 'CANCELLED' if cancelled else 'COMPLETED_WITH_WARNINGS' if counts.get('FAILED', 0) or counts.get('PARTIAL', 0) else 'SUCCEEDED'
                    db.execute('UPDATE pipeline_jobs SET status=?,endedAt=? WHERE id=?', (status, utc(), job_id))
            except BaseException as exc:
                with self.store.db() as db:
                    db.execute("UPDATE pipeline_jobs SET status='INTERRUPTED',endedAt=?,error=? WHERE id=?", (utc(), str(exc)[:1000], job_id))
                    db.execute("UPDATE pipeline_items SET status='QUEUED',startedAt=NULL WHERE jobId=? AND status='RUNNING'", (job_id,))
                raise
        return self.get_job(job_id)

    def _run_item(self, job_id, item):
        attempted = utc()
        with self.store.db() as db:
            source = dict(db.execute('SELECT * FROM pipeline_sources WHERE url=?', (item['url'],)).fetchone())
            db.execute("UPDATE pipeline_items SET status='RUNNING',startedAt=?,attempts=attempts+1 WHERE id=?", (attempted, item['id']))
            db.execute('UPDATE pipeline_sources SET lastAttempt=?,totalAttempts=totalAttempts+1 WHERE url=?', (attempted, item['url']))
        try:
            acquire = self.acquire_callable
            if acquire is None:
                from acquisition import acquire
            result = acquire(item['url'], etag=source.get('etag'), last_modified=source.get('lastModified'))
            if not isinstance(result, dict):
                raise ValueError('INVALID_ACQUISITION_RESULT')
            result = dict(result)
        except Exception as exc:
            result = {'url': item['url'], 'access': 'adapter_error', 'error': str(exc)[:1000]}
        access, content = result.get('access', 'unknown_error'), result.get('content', '')
        doc = None
        outcome = 'FAILED'
        if access in FULL_ACCESS or access == 'body_partial':
            if not isinstance(content, str) or not content.strip():
                result.update(access='extraction_failed', error='Adapter returned no extracted source text')
                access = result['access']
            else:
                try:
                    final_url = normalize_url(result.get('finalUrl') or result.get('url') or item['url'])
                    sha = hashlib.sha256(content.encode('utf-8')).hexdigest()
                    with self.store.db() as db:
                        old = db.execute('SELECT id FROM documents WHERE url=? AND sha256=? ORDER BY retrievedAt LIMIT 1', (final_url, sha)).fetchone()
                    doc = self.store.read(old['id']) if old else self.store.document(final_url, result.get('title') or final_url, content, access)
                    outcome = 'PARTIAL' if access == 'body_partial' else 'UNCHANGED' if sha == source.get('lastHash') else 'SUCCEEDED'
                except (ValueError, TypeError) as exc:
                    result.update(access='extraction_failed', error=str(exc)[:1000])
                    access = result['access']
        elif access == 'not_modified':
            if source.get('lastDocumentId') and source.get('lastHash'):
                try:
                    cached = self.store.read(source['lastDocumentId'])
                    if cached.get('sha256') != source['lastHash']:
                        raise ValueError('CACHED_VERSION_MISMATCH')
                    doc, outcome = cached, 'UNCHANGED'
                except ValueError:
                    result.update(access='cache_missing', error='304 without a readable cached document version')
                    access = result['access']
            else:
                result.update(access='cache_missing', error='304 without a previously fetched full document')
                access = result['access']
        completed = utc()
        success = outcome in {'SUCCEEDED', 'UNCHANGED'}
        attempts = 0 if success else source['attempts'] + 1
        delay = source['cadenceHours'] if success else min(24, 0.25 * 2 ** min(attempts - 1, 8))
        next_due = (datetime.now(timezone.utc) + timedelta(hours=delay)).isoformat()
        safe_result = {key: value for key, value in result.items() if key != 'content'}
        safe_result.update(outcome=outcome, requestedUrl=item['url'],
                           documentId=doc['id'] if doc else None,
                           sha256=doc['sha256'] if doc else None,
                           extractedChars=len(content) if isinstance(content, str) else 0,
                           independentlyVerified=False)
        # Validators from a 200 response replace earlier validators. Keeping an
        # old ETag when a new body omits it can later bind 304 to the wrong version.
        etag = (result.get('etag') or source['etag']) if access == 'not_modified' else result.get('etag')
        last_modified = (result.get('lastModified') or source['lastModified']) if access == 'not_modified' else result.get('lastModified')
        with self.store.db() as db:
            db.execute('''UPDATE pipeline_sources SET access=?,httpStatus=?,error=?,attempts=?,nextDue=?,
              lastSuccess=?,etag=?,lastModified=?,lastHash=?,lastDocumentId=? WHERE url=?''',
              (access, result.get('statusCode'), result.get('error'), attempts, next_due,
               completed if success else source['lastSuccess'],
               etag if success else source['etag'],
               last_modified if success else source['lastModified'],
               doc['sha256'] if success else source['lastHash'],
               doc['id'] if success else source['lastDocumentId'], item['url']))
            db.execute('''UPDATE pipeline_items SET status=?,endedAt=?,documentId=?,result=? WHERE id=?''',
                       (outcome, completed, doc['id'] if doc else None, encoded(safe_result), item['id']))
        self.store.event(job_id, 'pipeline_fetch', safe_result)
        if not success:
            self.store.event(job_id, 'pipeline_acquisition_failure', safe_result)
        if success and source['discoveryLimit']:
            self._discover(job_id, source, result)
        return safe_result

    def _discover(self, job_id, source, result):
        links = result.get('links') or []
        fmt = (result.get('metadata') or {}).get('format', '').lower()
        picked = []
        for link in links:
            if not isinstance(link, dict):
                continue
            kind = str(link.get('kind', '')).lower()
            if kind not in {'feed', 'feed_entry', 'entry', 'article', 'transcript', 'caption', 'pdf'} and not (
                fmt in {'rss', 'atom', 'feed', 'jsonfeed', 'json_feed'} and kind in {'', 'related'}
            ):
                continue
            try:
                url = normalize_url(urljoin(result.get('finalUrl') or source['url'], link.get('href') or link.get('url') or ''))
            except ValueError:
                continue
            if url == source['url'] or url in picked:
                continue
            picked.append(url)
            with self.store.db() as db:
                exists = db.execute('SELECT 1 FROM pipeline_sources WHERE url=?', (url,)).fetchone()
            metadata = {'url': url, 'origin': 'discovered:' + source['url']}
            if not exists:
                metadata.update(title=link.get('title') or url, sourceId=source['sourceId'],
                                channel='discovered_' + (kind or fmt), candidate=True,
                                discoveryLimit=0, discoveredFrom=source['url'], cadenceHours=source['cadenceHours'])
            self.update_source(metadata)
            if len(picked) >= source['discoveryLimit']:
                break
        if picked:
            self.store.event(job_id, 'pipeline_discovered', {'parentUrl': source['url'], 'urls': picked,
                             'boundedBy': source['discoveryLimit'], 'status': 'candidate_not_fetched',
                             'notice': '下轮有限队列采集；发现链接不代表已取得内容或已确认为 FDE 项目。'})

    def review(self, note_id, status):
        if status not in REVIEW_STATES:
            raise ValueError('INVALID_REVIEW_STATUS')
        with self.store.db() as db:
            row = db.execute('SELECT * FROM notes WHERE id=?', (note_id,)).fetchone()
            if not row:
                raise ValueError('NOTE_NOT_FOUND')
            if row['status'] not in REVIEW_STATES:
                raise ValueError('NOTE_NOT_REVIEWABLE')
            payload = json.loads(row['payload'])
            # Acceptance means the user accepted a note. It never certifies a case.
            if status == 'accepted':
                doc = db.execute('SELECT * FROM documents WHERE id=?', (payload.get('documentId'),)).fetchone()
                if not doc or payload.get('sha256') != doc['sha256'] or not payload.get('quote') or payload['quote'] not in doc['content']:
                    raise ValueError('CITATION_MISMATCH')
            previous = row['status']
            db.execute('UPDATE notes SET status=? WHERE id=?', (status, note_id))
        self.store.event(row['runId'], 'note_review', {'noteId': note_id, 'previousStatus': previous,
                         'status': status, 'verification': 'citation_matches_only', 'independentlyVerified': False})
        return {'id': note_id, 'status': status, 'verification': 'citation_matches_only',
                'independentlyVerified': False, 'meaning': '复核状态仅表示笔记取舍；不自动证明项目成效或场景可行性。'}

    def coverage(self):
        with self.store.db() as db:
            rows = [dict(row) for row in db.execute('SELECT * FROM pipeline_sources')]
            fetched = db.execute("SELECT COUNT(DISTINCT documentId) FROM pipeline_items WHERE documentId IS NOT NULL").fetchone()[0]
            statuses = dict(db.execute('SELECT status,COUNT(*) FROM pipeline_items GROUP BY status').fetchall())
        channels = {}
        for row in rows:
            group = channels.setdefault(row['channel'] or 'unclassified', {'registered': 0, 'attempted': 0, 'withExtractedText': 0, 'withFullText': 0, 'needsAttention': 0})
            group['registered'] += 1
            group['attempted'] += bool(row['lastAttempt'])
            group['withFullText'] += bool(row['lastSuccess'])
            group['withExtractedText'] += bool(row['lastSuccess'])
            group['needsAttention'] += bool(row['attempts'])
        now = utc()
        return {'generatedAt': now, 'collector': 'local_acquisition_pipeline', 'registeredUrls': len(rows),
                'enabledUrls': sum(bool(row['enabled']) for row in rows),
                'candidateUrls': sum(bool(row['candidate']) for row in rows),
                'attemptedUrls': sum(bool(row['lastAttempt']) for row in rows),
                'urlsWithExtractedText': sum(bool(row['lastSuccess']) for row in rows),
                'urlsWithFullText': sum(bool(row['lastSuccess']) for row in rows),
                'urlsNeedingAttention': sum(bool(row['attempts']) for row in rows),
                'dueUrls': sum(bool(row['enabled']) and (not row['nextDue'] or row['nextDue'] <= now) for row in rows),
                'documentVersions': fetched, 'attemptOutcomes': statuses, 'channels': channels,
                'openWebExhausted': False, 'saturationStatus': 'not_measured',
                'legacyAliases': {'urlsWithFullText': 'urlsWithExtractedText', 'channels.withFullText': 'channels.withExtractedText'},
                'meaning': '这是登记 URL 的采集覆盖。取得可提取文本可能仅为列表、目录或元数据，不保证文章全文、语义相关或案例真实；成功不等于独立核验、整站遍历或开放网络穷尽。旧字段 urlsWithFullText 仅为兼容别名。'}

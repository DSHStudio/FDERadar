"""Bounded public-source acquisition. Extracted text is evidence, never a model summary.

Every network hop resolves and rejects non-public addresses, then connects to one of
the checked IPs. TLS still verifies the original hostname. No cookies, credentials,
proxy, browser session, login bypass, or audio transcription is used.
"""
from __future__ import annotations

import hashlib
import http.client
import io
import ipaddress
import json
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.robotparser
import xml.etree.ElementTree as ET
import zlib
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

USER_AGENT = 'FDEResearchRadar/1.0 (+public-source-research; respects-robots)'
ROBOT_AGENT = 'FDEResearchRadar'
MAX_CHARS = 900_000
MAX_PDF_PAGES = 400
_ROBOTS = {}
_ROBOTS_LOCK = threading.Lock()
_ROBOTS_NEXT = {}


class AcquisitionError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _public_url(url):
    if not isinstance(url, str) or len(url) > 8192 or re.search(r'[\x00-\x20\x7f\\]', url):
        raise AcquisitionError('invalid_url', 'URL contains whitespace, control characters, or backslashes.')
    try:
        part = urlsplit(url)
        host = part.hostname
        port = part.port
        if part.scheme not in {'http', 'https'} or not host or part.username is not None or part.password is not None:
            raise ValueError('Only credential-free HTTP(S) URLs are supported.')
        if '%' in host or host.rstrip('.').lower() in {'localhost', 'localhost.localdomain'} or host.lower().endswith(('.localhost', '.local')):
            raise ValueError('Local hostnames and scoped addresses are not allowed.')
        host = host.encode('idna').decode('ascii').lower()
        port = port or (443 if part.scheme == 'https' else 80)
        if port not in {80, 443}:
            raise ValueError('Only public web ports 80 and 443 are supported.')
    except (ValueError, UnicodeError) as exc:
        raise AcquisitionError('invalid_url', str(exc)) from exc
    authority = '[' + host + ']' if ':' in host else host
    if port != (443 if part.scheme == 'https' else 80):
        authority += ':' + str(port)
    canonical = urlunsplit((part.scheme, authority, quote(part.path or '/', safe="/%:@!$&'()*+,;=-._~"),
                           quote(part.query, safe="%/:?@!$&'()*+,;=-._~"), ''))
    return canonical, part.scheme, host, port


def _addresses(host, port):
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise AcquisitionError('network_error', 'DNS lookup failed: ' + str(exc)) from exc
    values = []
    for family, socktype, proto, _, address in answers:
        try:
            ip = ipaddress.ip_address(address[0])
        except ValueError as exc:
            raise AcquisitionError('invalid_url', 'DNS returned a non-IP address.') from exc
        checked = ip.ipv4_mapped if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped else ip
        if not checked.is_global or checked.is_multicast or checked.is_unspecified:
            raise AcquisitionError('invalid_url', 'Destination resolves to a non-public address.')
        if family not in {socket.AF_INET, socket.AF_INET6}:
            raise AcquisitionError('invalid_url', 'Unsupported network address family.')
        value = (family, socktype, proto, address)
        if value not in values:
            values.append(value)
    if not values:
        raise AcquisitionError('network_error', 'DNS returned no public addresses.')
    return values


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AcquisitionError('network_error', 'Acquisition time limit exceeded.')
    return remaining


def _tls_context():
    context = ssl.create_default_context()
    try:
        import certifi
        context.load_verify_locations(cafile=certifi.where())
    except ImportError:
        pass
    return context


class _PinnedConnection(http.client.HTTPConnection):
    def __init__(self, host, port, addresses, deadline, secure):
        super().__init__(host, port, timeout=_remaining(deadline))
        self.addresses, self.deadline, self.secure = addresses, deadline, secure

    def connect(self):
        last = None
        for family, socktype, proto, address in self.addresses:
            raw = socket.socket(family, socktype, proto)
            try:
                raw.settimeout(_remaining(self.deadline))
                raw.connect(address)
                self.sock = _tls_context().wrap_socket(raw, server_hostname=self.host) if self.secure else raw
                return
            except (OSError, AcquisitionError) as exc:
                raw.close()
                last = exc
        raise AcquisitionError('network_error', 'Connection failed: ' + str(last))


def _read_body(response, connection, max_bytes, deadline):
    declared = response.getheader('Content-Length')
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise AcquisitionError('response_too_large', 'Declared response exceeds the configured byte limit.')
    chunks, size = [], 0
    while True:
        if connection.sock:
            connection.sock.settimeout(_remaining(deadline))
        else:
            _remaining(deadline)
        chunk = response.read(min(65536, max_bytes + 1 - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
        if size > max_bytes:
            raise AcquisitionError('response_too_large', 'Response exceeds the configured byte limit.')
    body = b''.join(chunks)
    encoding = response.getheader('Content-Encoding', '').strip().lower()
    if encoding in {'gzip', 'deflate'}:
        inflater = zlib.decompressobj(16 + zlib.MAX_WBITS if encoding == 'gzip' else zlib.MAX_WBITS)
        try:
            body = inflater.decompress(body, max_bytes + 1)
            if len(body) > max_bytes or inflater.unconsumed_tail:
                raise AcquisitionError('response_too_large', 'Decoded response exceeds the configured byte limit.')
            if not inflater.eof:
                raise AcquisitionError('extraction_failed', 'Compressed response is incomplete.')
        except zlib.error as exc:
            raise AcquisitionError('extraction_failed', 'Cannot decode compressed response.') from exc
    elif encoding and encoding != 'identity':
        raise AcquisitionError('extraction_failed', 'Unsupported content encoding: ' + encoding)
    return body


def _request_once(url, headers, max_bytes, deadline):
    canonical, scheme, host, port = _public_url(url)
    addresses = _addresses(host, port)
    connection = _PinnedConnection(host, port, addresses, deadline, scheme == 'https')
    part = urlsplit(canonical)
    path = part.path + ('?' + part.query if part.query else '')
    try:
        connection.request('GET', path, headers=headers)
        response = connection.getresponse()
        result_headers = {k.lower(): v for k, v in response.getheaders()}
        # Do not download audio/video, redirects, or error bodies just to classify them.
        kind = result_headers.get('content-type', '').split(';')[0].strip().lower()
        skip = response.status == 304 or response.status >= 300 or kind.startswith(('audio/', 'video/'))
        body = b'' if skip else _read_body(response, connection, max_bytes, deadline)
        return response.status, result_headers, body, canonical
    except AcquisitionError:
        raise
    except (OSError, http.client.HTTPException) as exc:
        raise AcquisitionError('network_error', str(exc)) from exc
    finally:
        connection.close()


def _follow(url, headers, max_bytes, deadline, *, robots=False):
    visited = []
    current = url
    for _ in range(6):
        canonical, _, _, _ = _public_url(current)
        if canonical in visited:
            raise AcquisitionError('http_error', 'Redirect loop detected.')
        visited.append(canonical)
        if robots:
            _check_robots(canonical, deadline)
        status, response_headers, body, final = _request_once(canonical, headers, max_bytes, deadline)
        if status not in {301, 302, 303, 307, 308}:
            return status, response_headers, body, final, visited
        location = response_headers.get('location')
        if not location:
            raise AcquisitionError('http_error', 'Redirect response has no Location.')
        current = urljoin(final, location)
        # Conditional validators belong to the original resource, not another origin.
        if urlsplit(current).netloc != urlsplit(final).netloc:
            headers = {k: v for k, v in headers.items() if not k.lower().startswith('if-')}
    raise AcquisitionError('http_error', 'Redirect limit exceeded.')


def _headers():
    return {'User-Agent': USER_AGENT, 'Accept': 'text/html,application/pdf,application/rss+xml,application/atom+xml,application/json,text/*;q=0.9,*/*;q=0.2',
            'Accept-Encoding': 'identity', 'Connection': 'close'}


def _check_robots(url, deadline):
    part = urlsplit(url)
    origin = part.scheme + '://' + part.netloc
    now = time.monotonic()
    with _ROBOTS_LOCK:
        cached = _ROBOTS.get(origin)
    if not cached or cached['expires'] <= now:
        try:
            status, _, body, _, _ = _follow(origin + '/robots.txt', _headers(), 512 * 1024, deadline)
            if status in {404, 410}:
                cached = {'parser': None, 'error': None, 'expires': now + 3600}
            elif status in {401, 403}:
                cached = {'parser': None, 'error': 'robots_disallowed', 'expires': now + 600}
            elif 200 <= status < 300:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(body.decode('utf-8', errors='replace').splitlines())
                cached = {'parser': parser, 'error': None, 'expires': now + 3600}
            else:
                cached = {'parser': None, 'error': 'robots_unavailable', 'expires': now + 120}
        except AcquisitionError as exc:
            cached = {'parser': None, 'error': 'robots_unavailable', 'expires': now + 120,
                      'detail': str(exc)}
        with _ROBOTS_LOCK:
            _ROBOTS[origin] = cached
    if cached['error']:
        raise AcquisitionError(cached['error'], 'robots.txt could not authorize acquisition: ' + cached.get('detail', cached['error']))
    parser = cached['parser']
    if parser and not parser.can_fetch(ROBOT_AGENT, url):
        raise AcquisitionError('robots_disallowed', 'robots.txt disallows this URL for the research radar.')
    if parser:
        delay = float(parser.crawl_delay(ROBOT_AGENT) or 0)
        rate = parser.request_rate(ROBOT_AGENT)
        if rate and rate.requests:
            delay = max(delay, rate.seconds / rate.requests)
        if delay:
            with _ROBOTS_LOCK:
                allowed_at = max(time.monotonic(), _ROBOTS_NEXT.get(origin, 0))
                wait = allowed_at - time.monotonic()
                if wait >= _remaining(deadline):
                    raise AcquisitionError('robots_deferred', 'robots.txt crawl delay exceeds this acquisition window; retry later.')
                _ROBOTS_NEXT[origin] = allowed_at + delay
            if wait > 0:
                time.sleep(wait)


def _decode(body, content_type):
    charset = re.search(r'charset\s*=\s*["\']?([^\s;"\']+)', content_type, re.I)
    if not charset:
        head = body[:4096].decode('ascii', errors='ignore')
        charset = re.search(r'charset\s*=\s*["\']?([^\s;"\'>/]+)', head, re.I)
    encoding = charset.group(1) if charset else 'utf-8-sig'
    try:
        return body.decode(encoding)
    except (LookupError, UnicodeError):
        return body.decode('utf-8-sig', errors='replace')


def _link(href, base, title='', kind='related'):
    try:
        normalized, _, _, _ = _public_url(urljoin(base, href))
        if kind == 'related':
            path = urlsplit(normalized).path.lower()
            if path.endswith('.pdf'):
                kind = 'pdf'
            elif path.endswith(('.vtt', '.srt')):
                kind = 'transcript'
        return {'href': normalized, 'title': str(title)[:1000], 'kind': kind}
    except (AcquisitionError, ValueError, TypeError):
        return None


class _HTML(HTMLParser):
    VOID = {'br', 'hr', 'img', 'input', 'meta', 'link', 'source', 'wbr', 'area', 'base', 'embed'}
    BLOCKS = {'p', 'div', 'section', 'article', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'br', 'blockquote'}

    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.parts, self.title, self.links = base, [], [], []
        self.skip, self.in_title, self.anchor = [], False, None
        self.meta, self.jsonld, self.ld_text = {}, [], None
        self.prose_stack, self.prose_chars = [], 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.ld_text is not None:
            return
        if self.skip:
            if tag not in self.VOID:
                self.skip.append(tag)
            return
        if tag == 'script' and attrs.get('type', '').lower() == 'application/ld+json':
            self.ld_text = []
            return
        if tag == 'iframe' and attrs.get('src'):
            item = _link(attrs['src'], self.base, attrs.get('title', ''), 'media')
            if item:
                self.links.append(item)
        if tag in {'script', 'style', 'noscript', 'template', 'iframe', 'svg'} or 'hidden' in attrs or attrs.get('aria-hidden') == 'true':
            if tag not in self.VOID:
                self.skip.append(tag)
            return
        if tag == 'title':
            self.in_title = True
        if tag in self.BLOCKS:
            self.parts.append('\n')
        if tag not in self.VOID:
            self.prose_stack.append(tag)
        if tag == 'meta':
            key = attrs.get('property') or attrs.get('name')
            if key and attrs.get('content'):
                self.meta[key.lower()] = attrs['content'][:5000]
        if tag == 'a' and attrs.get('href'):
            item = _link(attrs['href'], self.base)
            if item:
                self.links.append(item)
                self.anchor = item
        if tag == 'link' and attrs.get('href'):
            kind = 'feed' if attrs.get('type') in {'application/rss+xml', 'application/atom+xml', 'application/feed+json'} else 'related'
            item = _link(attrs['href'], self.base, attrs.get('title', ''), kind)
            if item:
                self.links.append(item)
        if tag in {'track', 'source', 'audio', 'video'} and attrs.get('src'):
            item = _link(attrs['src'], self.base, attrs.get('label', ''), 'transcript' if tag == 'track' else 'media')
            if item:
                self.links.append(item)

    def handle_endtag(self, tag):
        if self.ld_text is not None:
            if tag == 'script':
                try:
                    self.jsonld.append(json.loads(''.join(self.ld_text)))
                except (ValueError, RecursionError):
                    pass
                self.ld_text = None
            return
        if self.skip:
            if tag in self.skip:
                self.skip = self.skip[:len(self.skip) - 1 - self.skip[::-1].index(tag)]
            return
        if tag == 'title':
            self.in_title = False
        if tag == 'a':
            self.anchor = None
        if tag in self.BLOCKS:
            self.parts.append('\n')
        if tag in self.prose_stack:
            self.prose_stack = self.prose_stack[:len(self.prose_stack) - 1 - self.prose_stack[::-1].index(tag)]

    def handle_data(self, data):
        if self.ld_text is not None:
            self.ld_text.append(data)
        elif not self.skip:
            self.parts.append(data)
            if any(tag in self.prose_stack for tag in ('p', 'article')) and not any(tag in self.prose_stack for tag in ('nav', 'header', 'footer')):
                self.prose_chars += len(data.strip())
            if self.in_title:
                self.title.append(data)
            if self.anchor:
                self.anchor['title'] = (self.anchor['title'] + data)[:1000]

    def text(self):
        return '\n'.join(line.strip() for line in ''.join(self.parts).splitlines() if line.strip())


def _unique_links(links):
    seen, result = set(), []
    for item in links:
        if item and (item['href'], item['kind']) not in seen:
            result.append(item)
            seen.add((item['href'], item['kind']))
        if len(result) >= 1000:
            break
    return result


def _markup_text(text, base):
    parser = _HTML(base)
    parser.feed(text)
    return parser.text()


def _feed(text, url):
    if re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', text, re.I):
        raise AcquisitionError('extraction_failed', 'XML document types and entity declarations are not accepted.')
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise AcquisitionError('extraction_failed', 'Invalid XML feed: ' + str(exc)) from exc
    local = lambda node: node.tag.rsplit('}', 1)[-1].lower()
    is_feed = local(root) in {'rss', 'feed', 'rdf'}
    if not is_feed:
        return None
    channel = next((node for node in root if local(node) == 'channel'), root)
    title = next((''.join(node.itertext()).strip() for node in channel if local(node) == 'title'), url)
    entries, links = [], []
    item_nodes = [node for node in root.iter() if local(node) in {'item', 'entry'}]
    for node in item_nodes[:500]:
        entry = {'title': '', 'url': '', 'publishedAt': None, 'description': '', 'transcripts': [], 'media': []}
        for child in node:
            tag = local(child)
            value = ''.join(child.itertext()).strip()
            if tag == 'title':
                entry['title'] = value
            elif tag == 'link':
                href = child.attrib.get('href') or value
                rel = child.attrib.get('rel', 'alternate')
                kind = 'media' if rel == 'enclosure' else 'entry'
                candidate = _link(href, url, entry['title'], kind)
                if candidate:
                    links.append(candidate)
                    if kind == 'entry' and not entry['url']:
                        entry['url'] = candidate['href']
                    elif kind == 'media':
                        entry['media'].append(candidate['href'])
            elif tag in {'pubdate', 'published', 'updated', 'date'} and not entry['publishedAt']:
                entry['publishedAt'] = value
            elif tag in {'description', 'summary', 'content', 'encoded'}:
                candidate = _markup_text(value, url) if '<' in value else value
                if len(candidate) > len(entry['description']):
                    entry['description'] = candidate
            elif tag in {'transcript', 'enclosure'}:
                href = child.attrib.get('url') or child.attrib.get('href')
                if href:
                    kind = 'transcript' if tag == 'transcript' else 'media'
                    candidate = _link(href, url, entry['title'], kind)
                    if candidate:
                        links.append(candidate)
                        entry['transcripts' if kind == 'transcript' else 'media'].append(candidate['href'])
        # Some RSS feeds put links before titles; bind the final original title now.
        for candidate in links:
            if candidate['href'] == entry['url']:
                candidate['title'] = entry['title']
        entries.append(entry)
    content = '\n\n'.join('\n'.join(v for v in [entry['title'], entry['publishedAt'], entry['url'], entry['description']] if v) for entry in entries)
    return title, content, _unique_links(links), {'format': 'atom' if local(root) == 'feed' else 'rss',
              'entries': entries, 'entryCount': len(item_nodes), 'entriesReturned': len(entries),
              'truncated': len(item_nodes) > len(entries), 'notice': 'Feed metadata and publisher excerpts; entry bodies and audio have not been fetched.'}


def _pdf(body, url):
    try:
        import pdfplumber
    except ImportError as exc:
        raise AcquisitionError('dependency_missing', 'PDF extraction requires pdfplumber.') from exc
    parts, pages, length = [], [], 0
    try:
        with pdfplumber.open(io.BytesIO(body)) as document:
            count = len(document.pages)
            title = str((document.metadata or {}).get('Title') or '').strip()
            truncated = count > MAX_PDF_PAGES
            for number, page in enumerate(document.pages[:MAX_PDF_PAGES], 1):
                extracted = page.extract_text() or ''
                if not title and extracted.strip():
                    title = next(line.strip() for line in extracted.splitlines() if line.strip())
                block = f'\n[PDF page {number}]\n' + extracted
                available = MAX_CHARS - length
                if len(block) > available:
                    block = block[:available]
                    truncated = True
                pages.append({'number': number, 'start': length, 'end': length + len(block), 'textChars': len(extracted)})
                parts.append(block)
                length += len(block)
                if length >= MAX_CHARS:
                    truncated = truncated or number < count
                    break
            chars = sum(page['textChars'] for page in pages)
            return (title or url)[:2000], ''.join(parts), [], {'format': 'pdf', 'pageCount': count, 'pages': pages,
                'pagesExtracted': len(pages), 'truncated': truncated, 'needsOCR': chars == 0,
                'titleOrigin': 'pdf_metadata' if (document.metadata or {}).get('Title') else 'first_nonempty_page_line',
                'notice': 'Page text extracted without OCR. Layout, charts and reading order require the original PDF.'}
    except Exception as exc:
        raise AcquisitionError('extraction_failed', 'PDF text extraction failed: ' + type(exc).__name__) from exc


def _pdf_bounded(body, url, extraction_timeout=120):
    """A separate process gives PDF parsing a real CPU/wall-time stopping point.

    Threads cannot safely interrupt pdfminer. The helper receives only the already
    fetched bytes and performs no network requests or file writes.
    """
    try:
        completed = subprocess.run(
            [sys.executable, __file__, '--extract-pdf', url, str(MAX_PDF_PAGES), str(MAX_CHARS)],
            input=body, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=extraction_timeout, check=False,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if completed.returncode:
            raise AcquisitionError('extraction_failed', 'PDF extraction process exited unexpectedly.')
        response = json.loads(completed.stdout.decode('utf-8'))
        if response.get('error'):
            raise AcquisitionError(response.get('code', 'extraction_failed'), response['error'])
        result = response['result']
        result[3]['extractionTimeoutSeconds'] = extraction_timeout
        return result
    except subprocess.TimeoutExpired as exc:
        raise AcquisitionError('extraction_timeout', f'PDF extraction exceeded {extraction_timeout} seconds; its worker was stopped.') from exc
    except (OSError, ValueError, KeyError) as exc:
        raise AcquisitionError('extraction_failed', 'PDF worker returned no valid result: ' + type(exc).__name__) from exc


def _json(text, url):
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise AcquisitionError('extraction_failed', 'Invalid JSON response.') from exc
    title = str(data.get('title') or data.get('name') or url) if isinstance(data, dict) else url
    links = []
    if isinstance(data, dict) and isinstance(data.get('items'), list):
        for item in data['items'][:500]:
            if not isinstance(item, dict):
                continue
            for key in ('url', 'external_url'):
                if item.get(key):
                    links.append(_link(item[key], url, item.get('title', ''), 'entry'))
            for attachment in item.get('attachments', [])[:20]:
                if isinstance(attachment, dict) and attachment.get('url'):
                    kind = 'transcript' if attachment.get('mime_type', '').startswith('text/') else 'media'
                    links.append(_link(attachment['url'], url, attachment.get('title', ''), kind))
    return title, text, _unique_links(links), {'format': 'json_feed' if isinstance(data, dict) and str(data.get('version', '')).startswith('https://jsonfeed.org/') else 'json',
          'notice': 'Original decoded JSON; no generated fields have been added to the source content.'}


def _extract(body, content_type, url, extraction_timeout=120):
    kind = content_type.split(';')[0].strip().lower()
    if kind == 'application/pdf' or body.startswith(b'%PDF-'):
        return _pdf_bounded(body, url, extraction_timeout)
    if kind.startswith(('audio/', 'video/')):
        raise AcquisitionError('unsupported_media', 'Audio/video needs a publisher transcript or authorized transcription; no transcript was generated.')
    text = _decode(body, content_type)
    stripped = text.lstrip()
    if kind in {'application/json', 'application/feed+json', 'application/ld+json'} or kind.endswith('+json'):
        return _json(text, url)
    if kind in {'application/rss+xml', 'application/atom+xml', 'application/xml', 'text/xml', 'application/rdf+xml'} or re.match(r'<(?:\?xml\b|rss\b|feed\b)', stripped, re.I):
        parsed = _feed(text, url)
        if parsed:
            return parsed
        return url, text, [], {'format': 'xml', 'notice': 'Original decoded XML.'}
    if kind == 'text/vtt' or stripped.startswith('WEBVTT') or re.search(r'\d{2}:\d{2}:\d{2}[,.]\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}[,.]\d{3}', text[:5000]):
        cue_pattern = re.compile(r'(?m)^((?:\d{2}:)?\d{2}:\d{2}[,.]\d{3})\s+-->\s+((?:\d{2}:)?\d{2}:\d{2}[,.]\d{3})[^\n]*')
        cues = [{'startTime': m.group(1), 'endTime': m.group(2), 'offset': m.start()} for m in cue_pattern.finditer(text)]
        return urlsplit(url).path.rsplit('/', 1)[-1] or url, text, [], {'format': 'vtt' if stripped.startswith('WEBVTT') else 'srt',
            'cues': cues[:10000], 'cueCount': len(cues), 'notice': 'Publisher caption text preserved with timestamps; not checked against the audio.'}
    if kind in {'text/html', 'application/xhtml+xml'} or re.match(r'<(?:!doctype\s+html|html|head|body)\b', stripped, re.I):
        parser = _HTML(url)
        parser.feed(text)
        content = parser.text()
        title = ''.join(parser.title).strip() or parser.meta.get('og:title') or url
        metadata = {'format': 'html', 'meta': parser.meta, 'structuredMetadata': parser.jsonld[:20],
                    'notice': 'Visible HTML text extracted; scripts, page layout and media are excluded. No AI rewriting.'}
        metadata.update(bodyScope='extracted_visible_text', proseChars=parser.prose_chars)
        structured = json.dumps(parser.jsonld, ensure_ascii=False)
        if re.search(r'"isAccessibleForFree"\s*:\s*(?:false|"[Ff]alse")', structured):
            metadata['publisherRestriction'] = 'Publisher marks the article as subscription-only; only publicly returned text is captured.'
            metadata['truncated'] = True
        hostname = (urlsplit(url).hostname or '').lower()
        if hostname in {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'}:
            metadata.update(bodyScope='video_page_metadata', metadataOnly=True,
                            bodyLimitation='Video page metadata only; no publisher transcript or audio was acquired.')
        elif hostname == 'wap.eastmoney.com' and re.search(r'(?:前往|打开)东方财富APP.*?(?:阅读全文|查看原文)', content) and len(content) < 2000:
            metadata.update(bodyScope='app_only_article_navigation', metadataOnly=True,
                            bodyLimitation='The publisher returned an app-only article prompt and recommendations; the requested article was not acquired.')
        elif len(content) < 150:
            metadata['bodyScope'] = 'insufficient_visible_text'
            metadata['bodyLimitation'] = 'Page contains little readable text; it may need JavaScript, authentication, or manual review.'
        elif len(content) < 2000 and parser.prose_chars < 100 and max(map(len, content.splitlines()), default=0) < 160:
            metadata.update(bodyScope='suspected_navigation_only', bodyScopeHeuristic=True,
                            bodyLimitation='Only short navigation-like lines were found; article body has not been established.')
        elif hostname in {'www.deepexi.com', 'deepexi.com'} and urlsplit(url).path.rstrip('/') == '/company' and len(content) < 1600:
            # Observed company template exposes dates/headings, while its introduction
            # is loaded separately. Scope this check to that route, not DeepWorks.
            lines = [line.strip() for line in content.splitlines() if line.strip()]
            timeline = sum(bool(re.fullmatch(r'(?:20\d{2}|\d{1,2}月)', line)) for line in lines)
            if timeline >= 15 and max(map(len, lines), default=0) < 120:
                metadata.update(bodyScope='company_timeline_shell', bodyScopeHeuristic=True,
                                bodyLimitation='The company page contains navigation, empty introduction headings and timeline dates; the introduction text was not acquired.')
        return title, content, _unique_links(parser.links), metadata
    if kind.startswith('text/') or not kind:
        return urlsplit(url).path.rsplit('/', 1)[-1] or url, text, [], {'format': 'text'}
    raise AcquisitionError('unsupported_format', 'Unsupported response type: ' + (kind or 'unknown'))


def acquire(url, *, etag=None, last_modified=None, max_bytes=8 * 1024 * 1024,
            timeout=30, respect_robots=True, extraction_timeout=120):
    """Acquire one public resource, without summarizing or following discovered links.

    Validators support incremental updates. ``respect_robots=False`` is an explicit
    testing/authorized-source option; it never disables URL/address/TLS checks.
    Errors are returned as data so unattended batches can continue honestly.
    ``timeout`` bounds network I/O; ``extraction_timeout`` separately bounds PDF
    processing in a child process. With defaults the combined budget is 150 seconds.
    """
    result = {'url': url, 'finalUrl': url, 'title': '', 'content': '', 'access': 'network_error',
              'statusCode': None, 'etag': None, 'lastModified': None, 'contentType': None,
              'links': [], 'metadata': {'robotsChecked': bool(respect_robots)}}
    try:
        if not isinstance(max_bytes, int) or not 1024 <= max_bytes <= 16 * 1024 * 1024:
            raise AcquisitionError('invalid_configuration', 'max_bytes must be between 1024 and 16777216.')
        if not isinstance(timeout, (int, float)) or not 0 < timeout <= 180:
            raise AcquisitionError('invalid_configuration', 'timeout must be between 0 and 180 seconds.')
        if not isinstance(extraction_timeout, (int, float)) or not 0 < extraction_timeout <= 120:
            raise AcquisitionError('invalid_configuration', 'extraction_timeout must be between 0 and 120 seconds.')
        canonical, _, host, port = _public_url(url)
        # Reject unsafe URLs before robots handling, retaining the real reason.
        _addresses(host, port)
        headers = _headers()
        for name, value in [('If-None-Match', etag), ('If-Modified-Since', last_modified)]:
            if value:
                if not isinstance(value, str) or len(value) > 2048 or re.search(r'[\r\n\x00]', value):
                    raise AcquisitionError('invalid_configuration', 'Invalid conditional request validator.')
                headers[name] = value
        deadline = time.monotonic() + timeout
        status, received, body, final, chain = _follow(canonical, headers, max_bytes, deadline, robots=respect_robots)
        result.update(finalUrl=final, statusCode=status, etag=received.get('etag'), lastModified=received.get('last-modified'),
                      contentType=received.get('content-type', ''))
        result['metadata'].update(redirectChain=chain, receivedBytes=len(body), maxBytes=max_bytes,
                                  retryAfter=received.get('retry-after'))
        if status == 304:
            result['access'] = 'not_modified'
            return result
        if status in {401, 403, 407, 451}:
            raise AcquisitionError('access_restricted', 'Publisher returned an access restriction (HTTP ' + str(status) + ').')
        if not 200 <= status < 300:
            raise AcquisitionError('http_error', 'Publisher returned HTTP ' + str(status) + '.')
        title, content, links, metadata = _extract(body, result['contentType'], final, extraction_timeout)
        result['metadata'].update(metadata)
        if len(content) > MAX_CHARS:
            content = content[:MAX_CHARS]
            result['metadata']['truncated'] = True
        result.update(title=title[:2000], content=content, links=links)
        result['metadata']['contentSha256'] = hashlib.sha256(content.encode('utf-8')).hexdigest()
        if result['metadata'].get('needsOCR'):
            result['access'] = 'ocr_required'
        elif result['metadata'].get('metadataOnly'):
            result['access'] = 'metadata_only'
        elif result['metadata'].get('bodyLimitation'):
            result['access'] = 'insufficient_body'
        else:
            result['access'] = 'body_partial' if result['metadata'].get('truncated') else 'body_fetched_not_semantically_verified'
        return result
    except AcquisitionError as exc:
        result.update(access=exc.code, error=str(exc))
    except Exception as exc:
        result.update(access='extraction_failed', error='Acquisition failed: ' + type(exc).__name__)
    return result


if __name__ == '__main__':
    if len(sys.argv) != 5 or sys.argv[1] != '--extract-pdf':
        raise SystemExit('This module is imported by the radar; no standalone fetch command is provided.')
    MAX_PDF_PAGES, MAX_CHARS = int(sys.argv[3]), int(sys.argv[4])
    try:
        output = {'result': _pdf(sys.stdin.buffer.read(16 * 1024 * 1024 + 1), sys.argv[2])}
    except AcquisitionError as exc:
        output = {'error': str(exc), 'code': exc.code}
    sys.stdout.buffer.write(json.dumps(output, ensure_ascii=False).encode('utf-8'))

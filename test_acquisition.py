import contextlib
import gzip
import socket
import subprocess
import time
import unittest
from unittest.mock import MagicMock, patch

import acquisition as a


PUBLIC_DNS = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        a._ROBOTS.clear()
        a._ROBOTS_NEXT.clear()

    def request(self, body=b'', content_type='text/plain', status=200, headers=None, **kwargs):
        received = {'content-type': content_type}
        received.update(headers or {})
        def response(url, request_headers, max_bytes, deadline):
            return status, received, body, url
        with patch.object(a.socket, 'getaddrinfo', return_value=PUBLIC_DNS), patch.object(a, '_request_once', side_effect=response):
            return a.acquire('https://example.com/resource', respect_robots=False, **kwargs)

    def test_rejects_private_and_mixed_dns(self):
        for ip in ['127.0.0.1', '192.168.1.8', '10.0.0.1', '169.254.169.254', '100.64.0.1', '224.0.0.1', '::1', '::ffff:127.0.0.1']:
            answer = PUBLIC_DNS + [(socket.AF_INET6 if ':' in ip else socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443))]
            with self.subTest(ip=ip), patch.object(a.socket, 'getaddrinfo', return_value=answer):
                result = a.acquire('https://example.com/data')
                self.assertEqual(result['access'], 'invalid_url')

    def test_rejects_url_credentials_local_hosts_and_non_web_schemes(self):
        values = ['file:///etc/passwd', 'https://name:password@example.com/', 'http://localhost/', 'http://app.local/',
                  'https://example.com:22/a', 'https://example.com/\r\nx', 'https://example.com\\@127.0.0.1/', 'http://[fe80::1%25eth0]/']
        with patch.object(a.socket, 'getaddrinfo') as dns:
            for url in values:
                with self.subTest(url=url):
                    self.assertEqual(a.acquire(url)['access'], 'invalid_url')
            dns.assert_not_called()

    def test_connection_pins_checked_ip_and_retains_tls_hostname(self):
        raw, context = MagicMock(), MagicMock()
        with patch.object(a.socket, 'socket', return_value=raw), patch.object(a.ssl, 'create_default_context', return_value=context):
            checked = [(family, socktype, proto, address) for family, socktype, proto, _, address in PUBLIC_DNS]
            connection = a._PinnedConnection('publisher.example', 443, checked, time.monotonic() + 10, True)
            connection.connect()
            raw.connect.assert_called_once_with(('93.184.216.34', 443))
            context.wrap_socket.assert_called_once_with(raw, server_hostname='publisher.example')

    def test_redirects_revalidate_every_hop_and_strip_cross_origin_validators(self):
        calls = []
        def request(url, headers, limit, deadline):
            calls.append((url, headers.copy()))
            if len(calls) == 1:
                return 302, {'location': 'https://second.example/item'}, b'', url
            return 200, {'content-type': 'text/plain'}, b'original body', url
        with patch.object(a, '_request_once', side_effect=request), patch.object(a, '_check_robots') as robots:
            result = a._follow('https://first.example/', {'If-None-Match': 'first-tag', 'User-Agent': a.USER_AGENT}, 1024, time.monotonic() + 5, robots=True)
        self.assertEqual(result[3], 'https://second.example/item')
        self.assertNotIn('If-None-Match', calls[1][1])
        self.assertEqual(robots.call_count, 2)
        self.assertEqual(robots.call_args_list[1].args[0], 'https://second.example/item')

    def test_unsafe_redirect_refused_before_connection(self):
        with patch.object(a, '_request_once', return_value=(302, {'location': 'http://localhost/private'}, b'', 'https://example.com/')) as request:
            with self.assertRaises(a.AcquisitionError) as caught:
                a._follow('https://example.com/', {}, 1024, time.monotonic() + 5)
        self.assertEqual(caught.exception.code, 'invalid_url')
        self.assertEqual(request.call_count, 1)

    def test_robots_disallow_and_unavailable_are_distinct(self):
        with patch.object(a, '_follow', return_value=(200, {}, b'User-agent: *\nDisallow: /private\n', '', [])) as fetch:
            with self.assertRaises(a.AcquisitionError) as caught:
                a._check_robots('https://example.com/private', time.monotonic() + 5)
            self.assertEqual(caught.exception.code, 'robots_disallowed')
            a._check_robots('https://example.com/public', time.monotonic() + 5)
            self.assertEqual(fetch.call_count, 1)
        a._ROBOTS.clear()
        with patch.object(a, '_follow', return_value=(503, {}, b'', '', [])):
            with self.assertRaises(a.AcquisitionError) as caught:
                a._check_robots('https://example.com/public', time.monotonic() + 5)
            self.assertEqual(caught.exception.code, 'robots_unavailable')

    def test_robots_404_allows_but_respects_long_crawl_delay(self):
        with patch.object(a, '_follow', return_value=(404, {}, b'', '', [])):
            a._check_robots('https://example.com/public', time.monotonic() + 5)
        a._ROBOTS.clear()
        with patch.object(a, '_follow', return_value=(200, {}, b'User-agent: *\nCrawl-delay: 120\n', '', [])):
            a._check_robots('https://example.com/public', time.monotonic() + 5)
            with self.assertRaises(a.AcquisitionError) as caught:
                a._check_robots('https://example.com/second', time.monotonic() + 5)
            self.assertEqual(caught.exception.code, 'robots_deferred')

    def test_conditional_304_keeps_validator_and_no_body(self):
        result = self.request(status=304, headers={'etag': '"v1"', 'last-modified': 'Mon, 28 Sep 2026 00:00:00 GMT'}, etag='"v1"')
        self.assertEqual(result['access'], 'not_modified')
        self.assertEqual(result['etag'], '"v1"')
        self.assertEqual(result['content'], '')
        self.assertEqual(result['statusCode'], 304)

    def test_restriction_and_audio_do_not_fabricate_transcripts(self):
        self.assertEqual(self.request(status=403)['access'], 'access_restricted')
        audio = self.request(content_type='audio/mpeg')
        self.assertEqual(audio['access'], 'unsupported_media')
        self.assertEqual(audio['content'], '')

    def test_html_preserves_visible_original_and_finds_channels(self):
        source = '<html><head><title>Original &amp; title</title><link rel="alternate" type="application/rss+xml" href="/feed.xml"></head><body><script>secret</script><div hidden>hidden words</div><article><h1>Original story</h1><p>' + ('Original statement. ' * 12) + '</p><a href="/paper.pdf">Original PDF</a><track src="/captions.vtt"><iframe src="https://www.youtube.com/embed/abc" title="Interview"></iframe></article></body></html>'
        result = self.request(source.encode(), 'text/html')
        self.assertEqual(result['title'], 'Original & title')
        self.assertNotIn('secret', result['content'])
        self.assertNotIn('hidden words', result['content'])
        self.assertIn('Original statement.', result['content'])
        self.assertEqual({v['kind'] for v in result['links']}, {'feed', 'pdf', 'transcript', 'media'})
        self.assertEqual(result['access'], 'body_fetched_not_semantically_verified')

    def test_dynamic_shell_and_paywall_are_not_full_articles(self):
        shell = self.request(b'<html><title>App</title><script>loadEverything()</script><div id="root"></div></html>', 'text/html')
        self.assertEqual(shell['access'], 'insufficient_body')
        source = '<html><script type="application/ld+json">{"isAccessibleForFree":false}</script><p>' + ('Publisher preview. ' * 20) + '</p></html>'
        preview = self.request(source.encode(), 'text/html')
        self.assertEqual(preview['access'], 'body_partial')
        self.assertIn('publisherRestriction', preview['metadata'])

    def test_navigation_shell_and_youtube_metadata_are_not_article_bodies(self):
        navigation = '<html><title>Investor relations</title><body><nav>' + ''.join('<div>News Events Financials Governance Resources</div>' for _ in range(12)) + '</nav></body></html>'
        result = self.request(navigation.encode(), 'text/html')
        self.assertEqual(result['access'], 'insufficient_body')
        self.assertEqual(result['metadata']['bodyScope'], 'suspected_navigation_only')
        _, _, _, metadata = a._extract(b'<html><title>Original video title</title><p>About Press Copyright</p></html>', 'text/html', 'https://www.youtube.com/watch?v=abc')
        self.assertTrue(metadata['metadataOnly'])
        self.assertEqual(metadata['bodyScope'], 'video_page_metadata')

    def test_app_article_and_empty_company_timeline_are_not_bodies(self):
        app_page = '<html><title>东方财富资讯</title><p>前往东方财富APP阅读全文</p><div>热门推荐</div>' + '<p>其他推荐新闻标题</p>' * 15 + '</html>'
        _, _, _, metadata = a._extract(app_page.encode(), 'text/html', 'https://wap.eastmoney.com/a/202609033864252617.html')
        self.assertTrue(metadata['metadataOnly'])
        self.assertEqual(metadata['bodyScope'], 'app_only_article_navigation')
        timeline = '<html><title>公司 - 滴普科技</title><p>企业介绍</p><p>发展历程</p>' + ''.join(f'<p>{month}月</p>' for month in list(range(1, 13)) * 3) + '<p>资质认证 客户信赖 联系我们</p></html>'
        _, _, _, metadata = a._extract(timeline.encode(), 'text/html', 'https://www.deepexi.com/company')
        self.assertIn('bodyLimitation', metadata)
        # The real product landing page is a different route and has meaningful prose.
        product = '<html><title>DeepWorks</title><p>' + 'DeepWorks提供企业智能体平台，说明数据本体和现场交付模式。' * 50 + '</p></html>'
        _, content, _, metadata = a._extract(product.encode(), 'text/html', 'https://deepworks.deepexi.com/')
        self.assertGreater(len(content), 1000)
        self.assertNotIn('bodyLimitation', metadata)

    def test_rss_original_entries_and_podcast_transcript_links(self):
        feed = b'''<rss xmlns:podcast="https://podcastindex.org/namespace/1.0"><channel><title>Original feed</title><item><link>https://publisher.example/episode</link><title>Original episode &amp; FDE</title><pubDate>Mon, 28 Sep 2026</pubDate><description><![CDATA[<p>Publisher's words.</p>]]></description><enclosure url="https://publisher.example/audio.mp3"/><podcast:transcript url="https://publisher.example/transcript.vtt" type="text/vtt"/></item></channel></rss>'''
        result = self.request(feed, 'application/rss+xml')
        self.assertEqual(result['title'], 'Original feed')
        entry = result['metadata']['entries'][0]
        self.assertEqual(entry['title'], 'Original episode & FDE')
        self.assertEqual(entry['description'], "Publisher's words.")
        self.assertEqual(entry['transcripts'], ['https://publisher.example/transcript.vtt'])
        self.assertEqual({v['kind'] for v in result['links']}, {'entry', 'media', 'transcript'})

    def test_atom_xml_and_external_entities(self):
        feed = b'<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom title</title><entry><title>Paper</title><link href="/paper"/><published>2026-09-01</published><summary>Original abstract</summary></entry></feed>'
        result = self.request(feed, 'application/atom+xml')
        self.assertEqual(result['metadata']['format'], 'atom')
        self.assertEqual(result['metadata']['entries'][0]['url'], 'https://example.com/paper')
        malicious = b'<!DOCTYPE rss [<!ENTITY secret SYSTEM "file:///etc/passwd">]><rss>&secret;</rss>'
        self.assertEqual(self.request(malicious, 'application/xml')['access'], 'extraction_failed')

    def test_json_and_captions_preserve_original_bytes_decoded(self):
        source = '{ "title": "Original", "value": 7 }\n'
        result = self.request(source.encode(), 'application/json')
        self.assertEqual(result['content'], source)
        self.assertEqual(result['metadata']['format'], 'json')
        vtt = 'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nOriginal caption.\n'
        result = self.request(vtt.encode(), 'text/vtt')
        self.assertEqual(result['content'], vtt)
        self.assertEqual(result['metadata']['cues'][0]['startTime'], '00:00:01.000')
        srt = '1\n00:00:01,000 --> 00:00:03,000\nOriginal SRT.\n'
        result = self.request(srt.encode(), 'application/x-subrip')
        self.assertEqual(result['content'], srt)
        self.assertEqual(result['metadata']['format'], 'srt')

    def test_truncation_is_explicit(self):
        with patch.object(a, 'MAX_CHARS', 20):
            result = self.request(b'original ' * 20, 'text/plain')
        self.assertEqual(result['access'], 'body_partial')
        self.assertEqual(len(result['content']), 20)
        self.assertTrue(result['metadata']['truncated'])

    def test_pdf_page_locators_and_ocr_flag(self):
        first, second = MagicMock(), MagicMock()
        first.extract_text.return_value, second.extract_text.return_value = 'Original page one.', 'Original page two.'
        document = MagicMock()
        document.pages, document.metadata = [first, second], {'Title': 'Original PDF'}
        in_process = lambda body, url, timeout: a._pdf(body, url)
        with patch('pdfplumber.open', return_value=contextlib.nullcontext(document)), patch.object(a, '_pdf_bounded', side_effect=in_process):
            result = self.request(b'%PDF-1.4 mock', 'application/pdf')
        self.assertEqual(result['title'], 'Original PDF')
        self.assertEqual(result['metadata']['pageCount'], 2)
        page = result['metadata']['pages'][1]
        self.assertEqual(result['content'][page['start']:page['end']], '\n[PDF page 2]\nOriginal page two.')
        document.metadata = {}
        with patch('pdfplumber.open', return_value=contextlib.nullcontext(document)), patch.object(a, '_pdf_bounded', side_effect=in_process):
            result = self.request(b'%PDF-1.4 mock', 'application/pdf')
        self.assertEqual(result['title'], 'Original page one.')
        self.assertEqual(result['metadata']['titleOrigin'], 'first_nonempty_page_line')
        first.extract_text.return_value = second.extract_text.return_value = None
        with patch('pdfplumber.open', return_value=contextlib.nullcontext(document)), patch.object(a, '_pdf_bounded', side_effect=in_process):
            result = self.request(b'%PDF-1.4 mock', 'application/pdf')
        self.assertEqual(result['access'], 'ocr_required')

    def test_pdf_worker_wall_time_limit_is_reported(self):
        with patch.object(a.subprocess, 'run', side_effect=subprocess.TimeoutExpired(['pdf-helper'], 0.1)) as worker:
            with self.assertRaises(a.AcquisitionError) as caught:
                a._pdf_bounded(b'%PDF-1.4', 'https://example.com/paper.pdf', 0.1)
        self.assertEqual(caught.exception.code, 'extraction_timeout')
        self.assertEqual(worker.call_args.kwargs['timeout'], 0.1)
        self.assertEqual(worker.call_args.kwargs['input'], b'%PDF-1.4')

    def test_declared_and_streamed_byte_limits(self):
        connection = MagicMock()
        response = MagicMock()
        response.getheader.side_effect = lambda key, default=None: '2048' if key == 'Content-Length' else default
        with self.assertRaises(a.AcquisitionError) as caught:
            a._read_body(response, connection, 1024, time.monotonic() + 5)
        self.assertEqual(caught.exception.code, 'response_too_large')
        response.getheader.side_effect = lambda key, default=None: default
        response.read.side_effect = [b'x' * 1025]
        with self.assertRaises(a.AcquisitionError) as caught:
            a._read_body(response, connection, 1024, time.monotonic() + 5)
        self.assertEqual(caught.exception.code, 'response_too_large')

    def test_compression_bomb_is_bounded(self):
        compressed = gzip.compress(b'x' * 100000)
        response, connection = MagicMock(), MagicMock()
        response.getheader.side_effect = lambda key, default=None: 'gzip' if key == 'Content-Encoding' else default
        response.read.side_effect = [compressed, b'']
        with self.assertRaises(a.AcquisitionError) as caught:
            a._read_body(response, connection, 1024, time.monotonic() + 5)
        self.assertEqual(caught.exception.code, 'response_too_large')

    def test_malformed_headers_and_config_are_returned_as_failures(self):
        with patch.object(a.socket, 'getaddrinfo', return_value=PUBLIC_DNS):
            result = a.acquire('https://example.com/', etag='foo\r\nCookie: bar', respect_robots=False)
        self.assertEqual(result['access'], 'invalid_configuration')
        self.assertEqual(a.acquire('https://example.com/', max_bytes=100)['access'], 'invalid_configuration')
        self.assertEqual(a.acquire('https://example.com/', timeout=0)['access'], 'invalid_configuration')


if __name__ == '__main__':
    unittest.main()

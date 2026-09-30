"""Real DSH plugin invocation, real local corpus, synthetic local model; no paid calls."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import threading
from urllib.parse import urlencode
from urllib.request import urlopen
import uuid

from dsh_plugin import ROOT, TOOL_NAMES, install


def _verification_fixture(endpoint):
    with urlopen(endpoint + 'api/plugin/info', timeout=10) as response:
        info = json.load(response)
    assert info.get('features', {}).get('cacheOnlyReading') and info.get('features', {}).get('readingPagination'), 'BACKEND_RESTART_REQUIRED'
    with urlopen(endpoint + 'api/plugin/library?' + urlencode({'kind': 'documents', 'query': 'Skywise', 'limit': 1}), timeout=10) as response:
        document = json.load(response)['items'][0]
    calls = [
        ('fde_radar_status', {}),
        ('fde_radar_library', {'kind': 'documents', 'query': 'Skywise', 'limit': 2}),
        ('fde_radar_read', {'id': document['id'], 'sha256': document['sha256'], 'query': 'Skywise'}),
        ('fde_radar_library', {'kind': 'github', 'limit': 1}),
        ('fde_radar_reading', {'documentId': document['id'], 'mode': 'translate'}),
        ('fde_radar_tasks', {}),
        ('fde_radar_workbench', {'section': 'case'}),
    ]
    return document, calls


def _model_server(calls, requests):
    class Model(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            length = int(self.headers.get('Content-Length', '0'))
            body = json.loads(self.rfile.read(length))
            requests.append(body)
            index = len(requests) - 1
            if index < len(calls):
                name, args = calls[index]
                delta = {'tool_calls': [{'index': 0, 'id': 'plugin-check-' + str(index), 'type': 'function',
                         'function': {'name': name, 'arguments': json.dumps(args)}}]}
                finish = 'tool_calls'
            else:
                delta, finish = {'content': 'FDE_PLUGIN_VERIFIED'}, 'stop'
            chunks = [{'choices': [{'delta': {'role': 'assistant', 'content': None}}]},
                      {'choices': [{'delta': delta}]},
                      {'choices': [{'delta': {}, 'finish_reason': finish}], 'usage': {'prompt_tokens': 1, 'completion_tokens': 1}}]
            text = ''.join('data: ' + json.dumps(chunk) + '\n\n' for chunk in chunks) + 'data: [DONE]\n\n'
            raw = text.encode('utf-8')
            self.send_response(200); self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Model)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _runtime_variants(endpoint):
    import yaml
    installed = install()
    variants = [('sdk-runtime-overlay', installed, None)]
    cli = ROOT.parents[2] / 'DSH' / 'runtime' / 'node_modules' / '@deepseek-ai' / 'dsh' / 'lib' / 'bin.js'
    cli_home = ROOT / 'var' / 'dsh-plugin-cli-home'
    profile = cli_home / 'profiles' / 'sdk-minimal'
    if cli.is_file() and (profile / 'package.json').is_file():
        manifest = json.loads((profile / 'package.json').read_text(encoding='utf-8'))
        if 'dsh-plugin-fde-radar' in manifest.get('dsh', {}).get('profile', {}).get('bundles', []):
            rows = yaml.safe_load(Path(installed['patch']).read_text(encoding='utf-8'))[:-1]
            rows.append({'id': 'fde-radar', 'config': {'endpoint': endpoint, 'readOnly': False}})
            cli_patch = profile / 'fde-verify.patch.yml'
            cli_patch.write_text(yaml.safe_dump(rows, allow_unicode=True, sort_keys=False), encoding='utf-8')
            variants.append(('official-cli-installed-bundle', {'home': str(cli_home), 'patch': str(cli_patch)},
                             (shutil.which('node'), str(cli), '--profile', 'sdk-minimal', '--patch', str(cli_patch))))
    return variants


def _verify_variant(variant, server, calls, requests, document, endpoint):
    from deepseek_harness import DeepSeekHarness
    label, instance, launch_args = variant
    requests.clear()
    with DeepSeekHarness(dsh_home=instance['home'], cwd=str(ROOT), runtime_cwd=str(ROOT),
         profile='sdk-minimal', patches=(instance['patch'],), provider='deepseek-official', model='deepseek-v4-flash',
         reasoning_effort='low', max_tokens=1024, initialize_timeout_seconds=60, request_timeout_seconds=90,
         shutdown_timeout_seconds=5, api_key='synthetic-plugin-verification-only',
         base_url=f'http://127.0.0.1:{server.server_port}', env={'DSH_HOME': instance['home']},
         _launch_args=launch_args) as harness:
        response = harness.run('验证插件实际工具调用；仅查询本地已保存资料，不启动采集、研究或生成。',
                               session_id='plugin-verify-' + uuid.uuid4().hex)
    assert response.finish_reason == 'completed', response.finish_reason
    assert response.final_response == 'FDE_PLUGIN_VERIFIED', response.final_response
    assert len(requests) == len(calls) + 1, len(requests)
    registered = sorted(tool['function']['name'] for tool in requests[0].get('tools', []))
    assert set(TOOL_NAMES).issubset(registered), registered
    tool_messages = [m for m in requests[-1].get('messages', []) if m.get('role') == 'tool']
    assert len(tool_messages) == len(calls), tool_messages
    outputs = []
    for message in tool_messages:
        content = message['content']
        if isinstance(content, list):
            content = ''.join(block.get('text', '') for block in content)
        outputs.append(json.loads(content))
    assert outputs[0]['product'] == 'fde-radar', outputs[0]
    assert any(r['id'] == document['id'] for r in outputs[1]['items']), outputs[1]
    assert outputs[2]['sha256'] == document['sha256'] and 'Skywise' in outputs[2]['content'], outputs[2]
    assert outputs[3]['kind'] == 'github' and outputs[3]['items'], outputs[3]
    assert outputs[4]['status'] in {'not_generated', 'SUCCEEDED', 'FAILED', 'RUNNING', 'QUEUED', 'INTERRUPTED', 'CANCELLED'}, outputs[4]
    assert 'items' in outputs[5], outputs[5]
    assert outputs[6]['url'] == endpoint + '#case', outputs[6]
    return {'mode': label, 'status': 'passed', 'registeredPluginTools': TOOL_NAMES,
        'actualReadOnlyCalls': [name for name, _ in calls], 'modelFixtureRequests': len(requests),
        'documentId': document['id'], 'sha256': document['sha256'], 'sourceTitle': document['title'],
        'sourceUrl': document['url'], 'finishReason': response.finish_reason}


def verify():
    from datetime import datetime, timezone
    endpoint = 'http://127.0.0.1:8765/'
    document, calls = _verification_fixture(endpoint)
    requests = []
    server = _model_server(calls, requests)
    try:
        results = [_verify_variant(variant, server, calls, requests, document, endpoint)
                   for variant in _runtime_variants(endpoint)]
        report = {'status': 'passed', 'runtimeVersion': '0.1.5-rc.1',
                  'pluginVersion': json.loads((ROOT / 'dsh-plugin' / 'package.json').read_text(encoding='utf-8'))['version'],
                  'verifiedAt': datetime.now(timezone.utc).isoformat(), 'variants': results,
                  'actualSavedCorpusRead': True, 'externalModelCalled': False, 'collectionStarted': False,
                  'meaning': '真实DSH加载与工具执行；模型输出由本机测试服务提供。验证的是集成，不是模型研究质量。'}
        (ROOT / 'var' / 'dsh-plugin-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        return report
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    print(json.dumps(verify(), ensure_ascii=False, indent=2))

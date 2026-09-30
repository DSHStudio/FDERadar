import assert from 'node:assert/strict';
import test from 'node:test';
import { RadarClient, endpointUrl } from './client.mjs';
import { radarTools } from './tools.mjs';
const json = (value, status = 200, headers = {}) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json', ...headers } });
const identity = { product: 'fde-radar', apiVersion: 1 };
test('only exact local endpoint accepted', () => {
  for (const value of ['https://example.org/', 'http://localhost:8765/', 'http://127.0.0.1/path', 'http://x:y@127.0.0.1/', 'http://127.0.0.1/?key=a']) assert.throws(() => endpointUrl(value));
  assert.equal(endpointUrl('http://127.0.0.1:8765/').port, '8765');
});
test('requires known protocol before querying data', async () => {
  const client = new RadarClient({}, { fetchImpl: async () => json({ product: 'different' }) });
  await assert.rejects(client.get('/api/plugin/library'), { code: 'INCOMPATIBLE_RADAR_SERVICE' });
});
test('read-only prevents writes before any HTTP request', async () => {
  let calls = 0; const client = new RadarClient({}, { fetchImpl: async () => { calls++; return json(identity); } });
  await assert.rejects(client.post('/api/analyze', { task: 'a' }), { code: 'RADAR_READ_ONLY' }); assert.equal(calls, 0);
});
test('URL query encodes data and keeps source text intact', async () => {
  const calls = []; const raw = '<script>not executable</script> 原文';
  const client = new RadarClient({}, { fetchImpl: async (url, opts) => { calls.push([String(url), opts]); return json(calls.length === 1 ? identity : { content: raw, sha256: 'a' }); } });
  const result = await client.get('/api/plugin/read', { id: 'a&b#c' });
  assert.equal(result.content, raw); assert.equal(new URL(calls[1][0]).searchParams.get('id'), 'a&b#c');
  assert.equal(calls[1][1].redirect, 'error');
});
test('only explicit forbidden refreshes session and retries once', async () => {
  let sessions = 0, writes = 0;
  const client = new RadarClient({ readOnly: false }, { fetchImpl: async (url, options) => {
    if (url.pathname.endsWith('/info')) return json(identity);
    if (url.pathname.endsWith('/session')) return json({ token: 'private-token-' + ++sessions + '-abcdef' });
    writes++; if (writes === 1) return json({ error: 'FORBIDDEN' }, 403);
    assert.equal(options.headers['X-Radar-Token'], 'private-token-2-abcdef'); return json({ id: 'job-1' });
  } });
  assert.equal((await client.post('/api/collect', {})).id, 'job-1'); assert.equal(sessions, 2); assert.equal(writes, 2);
});
test('ambiguous write transport failure does not retry', async () => {
  let writes = 0;
  const client = new RadarClient({ readOnly: false }, { fetchImpl: async url => {
    if (url.pathname.endsWith('/info')) return json(identity);
    if (url.pathname.endsWith('/session')) return json({ token: 'secret-token-at-least-16' });
    writes++; throw Error('private server details');
  } });
  await assert.rejects(client.post('/api/analyze', {}), error => error.code === 'RADAR_UNAVAILABLE' && !error.message.includes('private server'));
  assert.equal(writes, 1);
});
test('HTTP errors do not echo untrusted server messages', async () => {
  const client = new RadarClient({}, { fetchImpl: async () => json({ error: 'secret path and arbitrary HTML' }, 500) });
  await assert.rejects(client.verify(), { code: 'RADAR_HTTP_500' });
});
test('response bytes are bounded with or without length header', async () => {
  for (const headers of [{}, { 'content-length': '3000' }]) {
    const client = new RadarClient({ maxResponseBytes: 1024 }, { fetchImpl: async () => json({ text: 'x'.repeat(3000) }, 200, headers) });
    await assert.rejects(client.verify(), { code: 'RESPONSE_TOO_LARGE' });
  }
});
test('plugin disposal signal reaches transport', async () => {
  const controller = new AbortController(); controller.abort();
  const client = new RadarClient({}, { signal: controller.signal, fetchImpl: async (_url, options) => { options.signal.throwIfAborted(); } });
  await assert.rejects(client.verify(), { code: 'RADAR_REQUEST_ABORTED' });
});
test('tools are namespaced and bounded before writes', async () => {
  let writes = 0; const tools = radarTools({ post: async () => { writes++; }, base: new URL('http://127.0.0.1:8765/') });
  assert.equal(new Set(tools.map(t => t.name)).size, 8);
  const update = tools.find(t => t.name === 'fde_radar_update');
  for (const args of [{ kind: 'sources', urls: [] }, { kind: 'sources', urls: ['file:///a'] }, { kind: 'sources', urls: Array(21).fill('https://example.org') }, { kind: 'github', urls: ['https://example.org'] }]) await assert.rejects(update.execute(args));
  assert.equal(writes, 0);
});
test('update acceptance and actual task status stay distinct', async () => {
  const tools = radarTools({ post: async () => ({ id: 'j', status: 'QUEUED', items: [1, 2] }) });
  const result = await tools.find(t => t.name === 'fde_radar_update').execute({ kind: 'sources' });
  assert.equal(result.status, 'QUEUED'); assert.equal(result.planned, 2); assert.equal(result.items, undefined);
});
test('translation is cache-only by default and retains partial status', async () => {
  const client = { get: async (path, query) => {
    assert.equal(path, '/api/plugin/reading'); assert.equal(query.offset, 14000);
    return { content: '第二页😀', offset: 14000, nextOffset: 28000, hasMore: true,
      chunks: [{ index: 0 }], status: 'FAILED', completedChunks: 1, totalChunks: 2, partial: true };
  }, post: async () => { throw Error('should not write'); } };
  const result = await radarTools(client).find(t => t.name === 'fde_radar_reading').execute({ documentId: 'd', mode: 'translate', offset: 14000 });
  assert.equal(result.content, '第二页😀'); assert.equal(result.nextOffset, 28000); assert.equal(result.hasMore, true); assert.equal(result.status, 'FAILED'); assert.equal(result.partial, true);
  assert.deepEqual(result.chunks, [{ index: 0 }]);
});

test('reading generation uses bounded receipt route and explicit boolean', async () => {
  let writes = 0;
  const client = { post: async (path, data) => {
    assert.equal(path, '/api/plugin/reading'); assert.deepEqual(data, { documentId: 'd', mode: 'explain' });
    writes++; return { id: 'reading-1', status: 'QUEUED' };
  } };
  const tool = radarTools(client).find(t => t.name === 'fde_radar_reading');
  await assert.rejects(tool.execute({ documentId: 'd', mode: 'explain', generate: 'false' }), { code: 'INVALID_GENERATE' });
  assert.equal(writes, 0);
  assert.equal((await tool.execute({ documentId: 'd', mode: 'explain', generate: true })).status, 'QUEUED');
  assert.equal(writes, 1);
});
test('workbench returns allowed local section and does not open a browser', async () => {
  const client = { verify: async () => identity, base: new URL('http://127.0.0.1:8765/') };
  const tool = radarTools(client).find(t => t.name === 'fde_radar_workbench');
  assert.equal((await tool.execute({ section: 'case' })).url, 'http://127.0.0.1:8765/#case');
  await assert.rejects(tool.execute({ section: '//example.com' }));
});

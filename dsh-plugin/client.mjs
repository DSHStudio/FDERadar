export class RadarError extends Error {
  constructor(code, message = code) { super(message); this.name = 'RadarError'; this.code = code; }
}

export function endpointUrl(value) {
  let url;
  try { url = new URL(value); } catch { throw new RadarError('INVALID_RADAR_ENDPOINT'); }
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || url.pathname !== '/' || url.username || url.password || url.search || url.hash)
    throw new RadarError('INVALID_RADAR_ENDPOINT', 'FDE 雷达地址必须为 http://127.0.0.1:端口/，不能包含凭据、路径或参数。');
  return url;
}

async function boundedJson(response, max) {
  if (Number(response.headers.get('content-length')) > max) throw new RadarError('RESPONSE_TOO_LARGE');
  if (!response.body) throw new RadarError('EMPTY_RESPONSE');
  const reader = response.body.getReader(); const chunks = []; let length = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read(); if (done) break;
      length += value.byteLength;
      if (length > max) { await reader.cancel(); throw new RadarError('RESPONSE_TOO_LARGE'); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(length); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); }
  catch { throw new RadarError('INVALID_RADAR_RESPONSE'); }
}

export class RadarClient {
  #token = ''; #verified = false;
  constructor(config = {}, { fetchImpl = fetch, signal } = {}) {
    this.base = endpointUrl(config.endpoint || 'http://127.0.0.1:8765/');
    this.readOnly = config.readOnly ?? true;
    this.timeoutMs = config.timeoutMs ?? 30000;
    this.maxResponseBytes = config.maxResponseBytes ?? 4000000;
    if (typeof this.readOnly !== 'boolean' || !Number.isInteger(this.timeoutMs) || this.timeoutMs < 100 || this.timeoutMs > 120000 ||
        !Number.isInteger(this.maxResponseBytes) || this.maxResponseBytes < 1024 || this.maxResponseBytes > 16000000)
      throw new RadarError('INVALID_RADAR_CONFIG');
    this.fetch = fetchImpl; this.signal = signal;
  }
  async request(path, body, signal) {
    const combined = AbortSignal.any([AbortSignal.timeout(this.timeoutMs), this.signal, signal].filter(Boolean));
    let response;
    try {
      response = await this.fetch(new URL(path, this.base), {
        method: body === undefined ? 'GET' : 'POST', redirect: 'error', signal: combined,
        headers: { Accept: 'application/json', ...(body === undefined ? {} : { 'Content-Type': 'application/json', 'X-Radar-Token': this.#token }) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
    } catch {
      throw new RadarError(combined.aborted ? 'RADAR_REQUEST_ABORTED' : 'RADAR_UNAVAILABLE',
        combined.aborted ? 'FDE 雷达请求已取消或超时；提交是否被接受需查询任务，不能自动重复提交。' : '无法连接本机 FDE 雷达，请先启动本地工作台。');
    }
    const value = await boundedJson(response, this.maxResponseBytes);
    if (!response.ok) throw new RadarError(typeof value?.error === 'string' && /^[A-Z0-9_]+$/.test(value.error) ? value.error : 'RADAR_HTTP_' + response.status);
    return value;
  }
  async verify(signal) {
    const info = await this.request('/api/plugin/info', undefined, signal);
    if (info?.product !== 'fde-radar' || info.apiVersion !== 1) throw new RadarError('INCOMPATIBLE_RADAR_SERVICE');
    this.#verified = true; return info;
  }
  async get(path, query = {}, signal) {
    if (!this.#verified) await this.verify(signal);
    const params = new URLSearchParams(Object.entries(query).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)]));
    return this.request(path + (params.size ? '?' + params : ''), undefined, signal);
  }
  async post(path, body, signal) {
    if (this.readOnly) throw new RadarError('RADAR_READ_ONLY', '当前插件配置为只读；在插件配置中设置 readOnly: false 后才能发起任务。');
    if (!this.#verified) await this.verify(signal);
    const session = async () => {
      const value = await this.request('/api/session', undefined, signal);
      if (typeof value?.token !== 'string' || value.token.length < 16) throw new RadarError('INVALID_RADAR_SESSION');
      this.#token = value.token;
    };
    if (!this.#token) await session();
    try { return await this.request(path, body, signal); }
    catch (error) {
      // Only an explicit rejection means the first write did not happen.
      if (error.code !== 'FORBIDDEN') throw error;
      await session(); return this.request(path, body, signal);
    }
  }
}

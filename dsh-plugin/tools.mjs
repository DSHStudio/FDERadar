import { RadarError } from './client.mjs';
const text = { type: 'string', required: true };
const page = { offset: { type: 'integer', description: '从0开始的分页位置' } };
function required(value, max = 500) { if (typeof value !== 'string' || !value.trim() || value.length > max) throw new RadarError('INVALID_ARGUMENT'); return value; }
function offset(value) { if (value !== undefined && (!Number.isInteger(value) || value < 0 || value > 100000000)) throw new RadarError('INVALID_OFFSET'); return value || 0; }
function briefTask(value) {
  const { content, items, chunks, ...rest } = value;
  return { ...rest, ...(items ? { planned: items.length } : {}), notice: '任务已受理不等于完成。用 fde_radar_tasks 查询；生成结果仍须对照原文。' };
}

export function radarTools(client) {
  return [
    { name: 'fde_radar_status', title: '查看雷达状态', description: '查看本机FDE雷达连接、实际库存数量及能力边界。登记和保存版本数不是独立证据数。', parameters: {},
      execute: async (_a, s) => ({ ...(await client.verify(s)), pluginReadOnly: client.readOnly }) },
    { name: 'fde_radar_library', title: '检索雷达资料', description: '分页检索已保存的本体/FDE原文、信源、研究索引、待复核笔记、GitHub仓库或实际覆盖。documents的query按标题、URL和正文做字面检索；原文未经改写。',
      parameters: { kind: { type: 'string', enum: ['documents', 'sources', 'records', 'notes', 'research', 'github', 'coverage'], required: true }, query: { type: 'string' }, ...page, limit: { type: 'integer', description: '1至50，默认20' } },
      execute: (a, s) => client.get('/api/plugin/library', { ...a, offset: offset(a.offset) }, s) },
    { name: 'fde_radar_read', title: '读取保存原文', description: '按documentId和字符位置读取真实保存原文，每页最多14000字符。传sha256可锁定版本，query可定位原词。hasMore为true必须续读才能称读完。历史记录和AI笔记不等于原文。',
      parameters: { id: text, sha256: { type: 'string' }, query: { type: 'string' }, ...page },
      execute: (a, s) => client.get('/api/plugin/read', { ...a, id: required(a.id), offset: offset(a.offset) }, s) },
    { name: 'fde_radar_update', title: '更新原始资料', description: '按用户任务启动公开信源采集或GitHub更新；异步返回任务ID。sources不传urls时只采到期信源；GitHub手动更新不改变每周计划。不会执行下载源码。只读配置下不可用。',
      parameters: { kind: { type: 'string', enum: ['sources', 'github'], required: true }, urls: { type: 'array', items: { type: 'string' } } },
      execute: async (a, s) => {
        if (a.kind === 'github') { if (a.urls?.length) throw new RadarError('GITHUB_DOES_NOT_ACCEPT_URLS'); return briefTask(await client.post('/api/github/refresh', {}, s)); }
        if (a.kind !== 'sources' || (a.urls !== undefined && (!Array.isArray(a.urls) || !a.urls.length || a.urls.length > 20))) throw new RadarError('INVALID_UPDATE');
        for (const value of a.urls || []) { let url; try { url = new URL(required(value, 4096)); } catch { throw new RadarError('INVALID_SOURCE_URL'); } if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw new RadarError('INVALID_SOURCE_URL'); }
        return briefTask(await client.post('/api/collect', a.urls ? { urls: a.urls } : {}, s));
      } },
    { name: 'fde_radar_research', title: '发起证据研究', description: '按用户明确任务启动雷达专用DSH研究，实际阅读/获取原文并暂存带引用的笔记。使用本地受管模型凭据，可能消耗模型额度。异步排队不代表研究完成；只有正常完成的批次保留待复核笔记。不得把所有AI项目算FDE或编造客户/报价/ROI。',
      parameters: { task: text }, execute: async (a, s) => briefTask(await client.post('/api/analyze', { task: required(a.task, 6000) }, s)) },
    { name: 'fde_radar_reading', title: '中文阅读与通俗解读', description: '读取指定原文版本的AI中文译文或通俗解读。默认仅读缓存；用户要求生成时设置generate=true，可能消耗模型额度。原文与生成内容分开；部分完成必须明确报告未处理范围。',
      parameters: { documentId: text, mode: { type: 'string', enum: ['translate', 'explain'], required: true }, generate: { type: 'boolean' }, ...page },
      execute: async (a, s) => {
        const id = required(a.documentId); if (!['translate', 'explain'].includes(a.mode)) throw new RadarError('INVALID_READING_MODE');
        const start = offset(a.offset);
        if (a.generate !== undefined && typeof a.generate !== 'boolean') throw new RadarError('INVALID_GENERATE');
        if (a.generate) return briefTask(await client.post('/api/plugin/reading', { documentId: id, mode: a.mode }, s));
        return client.get('/api/plugin/reading', { documentId: id, mode: a.mode, offset: start }, s);
      } },
    { name: 'fde_radar_tasks', title: '查询雷达任务', description: '查看任务实际状态。传id查询单项；不传列近期采集、DSH研究和阅读任务。未知/排队/失败都不是已完成。', parameters: { id: { type: 'string' } },
      execute: (a, s) => client.get('/api/plugin/tasks', a, s) },
    { name: 'fde_radar_workbench', title: '进入研究工作台', description: '返回当前本机雷达的可点击工作台地址。包括情报、理论、案例、场景、开源、实作、信源、任务。保留现有完整UI，不会自动打开浏览器。',
      parameters: { section: { type: 'string', enum: ['intelligence', 'theory', 'case', 'scenario', 'opensource', 'practice', 'sources', 'tasks'] } },
      execute: async (a, s) => {
        const sections = ['intelligence', 'theory', 'case', 'scenario', 'opensource', 'practice', 'sources', 'tasks'];
        if (a.section && !sections.includes(a.section)) throw new RadarError('INVALID_SECTION');
        await client.verify(s); return { url: client.base.href + '#' + (a.section || 'intelligence'), title: 'FDE 雷达', localOnly: true };
      } },
  ];
}

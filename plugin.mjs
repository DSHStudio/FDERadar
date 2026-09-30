import { defineTool } from '@deepseek-ai/dsh-tools';
export const name = 'fde-radar-tools';
export const inject = ['tools', 'llm', 'web'];
const names = ['radar_library', 'radar_read', 'radar_search', 'radar_fetch', 'radar_submit'];
export function apply(ctx) {
  const base = new URL(process.env.RADAR_ENDPOINT);
  if (base.protocol !== 'http:' || base.hostname !== '127.0.0.1' || base.pathname !== '/') throw new Error('INVALID_RADAR_ENDPOINT');
  const token = process.env.RADAR_TOKEN;
  let calls = 0;
  async function post(path, body, signal) {
    const r = await fetch(new URL(path, base), {
      method: 'POST', redirect: 'error',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
      body: JSON.stringify(body),
      signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(path === '/acquire' ? 240000 : 30000)]) : AbortSignal.timeout(path === '/acquire' ? 240000 : 30000),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || 'RADAR_SERVICE_ERROR');
    return data;
  }
  ctx.tools.guard(exec => {
    if (!names.includes(exec.name)) return 'TOOL_NOT_ALLOWED';
    if (++calls > Number(process.env.RADAR_TOOL_LIMIT || 24)) return 'TOOL_BUDGET_EXCEEDED';
  });
  function register(name, description, parameters, handler) {
    ctx.tools.register(defineTool({name, description, parameters,
      output: { schema: {type:'object', additionalProperties:false, properties:{payload:{type:'string',required:true}}},
        render: (_args, value) => [{type:'text',text:value.payload}] },
      presentCall: () => ({card:'generic',title:description}),
      async execute(args, exec) { return {payload:JSON.stringify(await handler(args, exec))}; }
    }));
  }
  const str = {type:'string',required:true};
  register('radar_library','查看已有研究记录、信源或本轮原文', {
    kind:{type:'string',enum:['records','sources','documents','notes','coverage','research'],required:true}, query:{type:'string'},
  }, (args,e)=>post('/library',args,e.signal));
  register('radar_read','按ID分页读取原文；query定位长PDF内真实关键词', {id:str,offset:{type:'integer'},query:{type:'string'}}, (a,e)=>post('/read',a,e.signal));
  register('radar_search','用DSH原生搜索发现公开资料（仅线索）；scope记录本轮时间/地区/主题范围', {query:str,scope:{type:'string'}}, async(a,e)=>{
    await post('/budget',{kind:'search'},e.signal);
    try {
      const result=await ctx.web.search({query:a.query,maxResults:6},AbortSignal.any([e.signal,AbortSignal.timeout(60000)]));
      return await post('/search-result',{query:a.query,scope:a.scope||'未记录检索范围',result},e.signal);
    } catch(error) {
      await post('/failure',{operation:'search',target:a.query,code:error.code||'SEARCH_FAILED'});
      return {status:'failed',code:error.code||'SEARCH_FAILED',message:'搜索未取得有效结果，不能当作无更新。'};
    }
  });
  register('radar_fetch','取得公开HTML/PDF/订阅/字幕原文；不生成音视频转写', {url:str}, async(a,e)=>{
    await post('/budget',{kind:'fetch'},e.signal);
    try {
      return await post('/acquire',{url:a.url},e.signal);
    } catch(error) {
      await post('/failure',{operation:'fetch',target:a.url,code:error.code||'FETCH_FAILED'});
      return {status:'failed',code:error.code||'FETCH_FAILED',message:'原文尚未取得；访问受限、动态页面或音视频需公开原始文字稿或已有授权。'};
    }
  });
  register('radar_submit','保存带真实原文引用的待复核研究笔记', {
    track:{type:'string',enum:['theory','case','scenario'],required:true},
    title:str,summary:str,analysis:str,limitations:str,nextStep:str,
    documentId:str,sha256:str,quote:str,
  }, (a,e)=>post('/submit',a,e.signal));
  ctx.on('llm/stream',async function*(_options,next){
    await post('/model-request',{toolNames:ctx.tools.schemas().map(s=>s.name).sort()});
    yield* next();
  });
}

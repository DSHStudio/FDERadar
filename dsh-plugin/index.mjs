import { defineTool } from '@deepseek-ai/dsh-tools';
import Schema from '@deepseek-ai/schemastery';
import { RadarClient } from './client.mjs';
import { radarTools } from './tools.mjs';

export const name = 'fde-radar';
export const inject = ['tools'];
export const Config = Schema.object({
  endpoint: Schema.string().default('http://127.0.0.1:8765/').description('本机 FDE 雷达服务地址'),
  readOnly: Schema.boolean().default(true).description('关闭后可发起采集、DSH研究和中文阅读生成'),
  timeoutMs: Schema.number().default(30000),
  maxResponseBytes: Schema.number().default(4000000),
});

export function apply(ctx, config) {
  const controller = new AbortController();
  const client = new RadarClient(config, { signal: controller.signal });
  ctx.on('dispose', () => controller.abort());
  for (const tool of radarTools(client)) {
    ctx.tools.register(defineTool({
      name: tool.name, description: tool.description, parameters: tool.parameters,
      output: {
        schema: { type: 'object', additionalProperties: false, properties: { payload: { type: 'string', required: true } } },
        render: (_args, value) => [{ type: 'text', text: value.payload }],
      },
      presentCall: () => ({ card: 'generic', title: tool.title }),
      async execute(args, exec) { return { payload: JSON.stringify(await tool.execute(args, exec.signal)) }; },
    }));
  }
}

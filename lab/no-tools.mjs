export const name = 'fde-lab-no-tools';
export const inject = ['tools', 'llm'];
export function apply(ctx) {
  ctx.tools.guard(() => 'LAB_TOOLS_DISABLED');
  ctx.on('llm/stream', async function* (_options, next) {
    if (ctx.tools.schemas().length !== 0) throw new Error('LAB_TOOL_CATALOG_NOT_EMPTY');
    yield* next();
  });
}

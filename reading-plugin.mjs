export const name = 'fde-reading-no-tools';
export const inject = ['tools', 'llm'];
export function apply(ctx) {
  ctx.tools.guard(() => 'READING_TOOLS_DISABLED');
  ctx.on('llm/stream', async function* (_options, next) {
    if (ctx.tools.schemas().length !== 0) throw new Error('READING_TOOL_CATALOG_NOT_EMPTY');
    yield* next();
  });
}

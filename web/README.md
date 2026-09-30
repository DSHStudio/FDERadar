# 前端代码约定

工作台继续使用原生 JavaScript，无构建步骤。`assets.json` 是允许对浏览器提供的脚本清单，`index.html` 按同一顺序使用 `defer` 加载。HTTP 集成测试会检查两者一致、所有文件可读取及未公开测试/配置文件。新增脚本时同步这两个文件。

这些是按职责拆分的经典脚本，共享词法作用域，不是 ES modules。`state.js` 明确持有 `app`、`reader`、`researchUI` 等状态；其他文件不在顶层启动请求。`app.js` 最后加载，负责绑定全局事件及首次刷新。

| 文件 | 责任 |
|---|---|
| `dom.js` | DOM、安全链接、日期、状态标签等显示基础函数 |
| `data.js` | 已加载数据的选择和筛选 |
| `api.js` | HTTP、操作提示、状态刷新 |
| `forms.js` | 表单草稿与统一提交流程；成功才清理草稿 |
| `research.js` | 证据引用、来源卡片、研究详情的共享呈现 |
| `documents.js`、`reader.js` | 原文列表、分页、原文定位、AI 阅读及取消 |
| `cases.js`、`learning.js`、`scenarios.js` | 案例、学习和场景页 |
| `github.js`、`practice.js` | 开源资源、实作结果及评分依据 |
| `sources.js`、`tasks.js` | 信源管理、任务与审核 |

原文使用 `textContent` 呈现；引用定位继续核对文档 ID、哈希及逐字引文。AI 派生内容不写回原文。阅读器的代次检查、计时器清理和焦点恢复留在 `reader.js`；学习记录在提交期间有新输入时保留新草稿，不套用普通表单的成功清理策略。

测试命令：`node --test web/test_reader.js web/test_research.js`。两个测试共用 `test_support/load_ui.cjs`，按实际清单加载脚本，跳过最后的自动刷新。两个 DOM 夹具刻意保留：阅读器夹具覆盖节点销毁、焦点及异步响应，研究夹具适合快速验证研究字段与评分边界，不能互相替换。

本轮统一格式使用 Prettier 3.6.2（`parser: babel`、`printWidth: 100`、`quoteProps: preserve`）。工具仅存于 `var/refactor-tools`，不属于部署依赖。当前不要求运行它才能启动工作台。

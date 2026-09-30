# FDE 雷达 · DSH 插件

`dsh-plugin-fde-radar` 0.1.1 为 DeepSeek Harness 的 Cordis 工具插件和可安装 bundle。已针对本机 DSH SDK/runtime `0.1.5-rc.1` 验证。插件连接运行中的本地 FDE 雷达服务，使用同一原文库、采集队列、GitHub周更新、DSH研究和Web工作台。

## 在 DSH 安装

已安装完整 DSH CLI 的机器，在插件压缩包所在目录执行：

```powershell
dsh plugin --profile fde-radar add ./dsh-plugin-fde-radar-0.1.1.tgz
dsh --profile fde-radar --dump-config
```

包自带 `dsh.bundle` 和 `cordis.patch.yml`，安装会挂载 `fde-radar` 插件行。然后按现有 DSH 使用方式启动这个 profile。默认连接 `http://127.0.0.1:8765/`，默认只读；在该 profile 的 `cordis.patch.yml` 配置：

```yaml
- id: fde-radar
  config:
    endpoint: http://127.0.0.1:8765/
    readOnly: false
    timeoutMs: 30000
    maxResponseBytes: 4000000
```

`readOnly: false` 允许用户通过 DSH 发起采集、GitHub更新、研究及翻译/解释任务；研究与翻译会使用雷达已有的受管模型凭据和额度。插件不读取、复制或返回模型密钥，不覆盖宿主的其他工具或系统提示。删除插件：`dsh plugin --profile fde-radar remove dsh-plugin-fde-radar`，本地研究数据仍保留。

本工程可直接运行 `./Run-DshPlugin.ps1 -Action install`：先建立项目专用 SDK profile，若找到本机已有的完整 DSH CLI，再通过其 `plugin add` 离线安装 bundle。两种安装分别位于工程的 `var/dsh-plugin-home` 和 `var/dsh-plugin-cli-home`，不会修改用户其他 DSH profile。`./Run-DshPlugin.ps1 -Action run -Task '…'` 使用 SDK profile 的同一插件模块完成对话。`-Action verify` 用真实DSH、真实本地原文库和本机模型测试服务验证集成，不调用付费模型。

本机完整 CLI `0.1.5-rc.1` 在 Windows 下通过 shell 转发 pnpm 参数，含空格路径需要再次保留引号；项目安装脚本已处理，用户优先用上述脚本。跨机器安装时可把插件包放在不含空格的目录再运行官方命令。

## 可以说什么

- “查看雷达状态，再找本体与 Agent 结合的原文；给出标题、出处和获取范围。”
- “找到 Airbus Skywise 案例的原文，核对合作范围和金额，未知保持未知。”
- “查看 GitHub 数据治理工具的 README，区分维护者自述与已验证结果。”
- “采集这些公开网址，告诉我任务 ID，结束后按实际状态报告。”
- “研究近期中国具名 FDE 案例，读原文后提交待复核笔记。”
- “将这份已采集的英文资料生成中文译文。”
- “打开项目案例工作台。”

## 工具

| 工具 | 作用 |
|---|---|
| `fde_radar_status` | 连接、库存、能力边界 |
| `fde_radar_library` | 原文、信源、研究、笔记、GitHub、覆盖的分页检索 |
| `fde_radar_read` | 按版本分页读原文并定位关键词 |
| `fde_radar_update` | 启动到期信源采集或手动GitHub更新 |
| `fde_radar_research` | 启动雷达已有的DSH证据研究流程 |
| `fde_radar_reading` | 读取或生成中文译文、通俗解读 |
| `fde_radar_tasks` | 查询实际任务状态 |
| `fde_radar_workbench` | 返回八模块工作台地址 |

## 部署与数据

需要运行本工程的 Python 后端（插件API v1）及原有依赖；先运行 `./Start-Radar.ps1`。连接失败会明确返回错误。插件包是宿主适配层，不包含 Python 后端、数据库、历史证据或凭据，不是无依赖的单文件应用。换机器时需要另行部署雷达后端和合法取得的数据，不能仅靠这个小插件包复制整个研究库。

0.1.1 需要同时更新本工程后端，并在空闲时用 `./Start-Radar.ps1 -Restart` 加载。状态接口的 `features.readingPagination` 与 `features.cacheOnlyReading` 标识新能力：中文阅读在服务端按字符分页，缓存查询不会启动排队的生成任务；明确生成时仅返回小型任务回执。任务列表按状态与时间排序，已知阅读任务 ID 不受最近 100 项限制。

插件仅接受固定本机回环地址，不转发到远端主机，不跟随重定向。原文仍在原库，版本哈希、标题、原语言、分页和获取范围保留。翻译和研究调用雷达的独立DSH任务，以便保留既有终态校验和引用检查；外层宿主对话是任务入口，不自动替代待复核笔记的审核。

每日采集与GitHub每周到期逻辑沿用原来配置；安装插件不会创建第二个日程或变为全天候云服务。停用插件不会停止已被后台接受的采集/研究任务；请在工作台查看实际状态。连接超时不自动重试写入，避免重复启动；只有服务器明确拒绝过期会话时才刷新会话并重试一次。

官方格式参考：[DSH插件打包与安装](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/develop/basic/publish.md)、[插件配置](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/develop/basic/config.md)。DSH仍在快速迭代；其他版本需重新验证。

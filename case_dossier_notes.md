# 首批案例档案审读说明

审读日期：2026-09-28。研究索引位于 `config/research-cases.json`，引用完整性审计位于 `var/case-study-audit.json`。本轮只读 SQLite 中已保存的正文，没有修改数据库、原文或 UI。

## 已完成的材料

5 份具名档案，每份包含项目、客户、供应方、问题、范围、交付、FDE、本体、Agent、运行、效果、金额和验收 13 个字段。共 65 项判断：44 项为来源披露，21 项未知。8 份本地文档版本支撑 59 处短引文。

`disclosed` 只表示引述来源作出了该项表述，不表示独立核验。`unknown` 表示当前材料不足；它不等于该能力不存在。原始标题保持不变，中文字段是研究索引，不是原文译文或替代稿。场景迁移部分是研究建议，不当作来源已经完成的工作。

| 档案 | 来源性质与可以学习的内容 | 关键边界 |
| --- | --- | --- |
| Airbus Skywise | Palantir 合作方及平台提供方 Airbus 的启动与后续披露；可观察航空数据整合、定制应用和维护场景推进 | 2017、2018、2024 是不同时间点；这些材料没有直接证明正式 FDE 岗位、本体模式或大模型 Agent |
| McCarthy Pulse | 客户官网披露本体建模和嵌入式工程师组织 | 可标为 FDE 相邻组织证据；不能补写正式岗位说明、自主 Agent、精确合同价或量化效益 |
| 地方病知识图谱采购 | 政府采购结果公告明确采购人、供应商、成交价和服务期限 | 成交不等于已签合同、上线、验收；知识图谱项目名不足以证明本体实施或 FDE 模式 |
| Cognite–MaMaTa | 供应商披露知识图谱、设备关系及工业数据应用 | 生成式 AI 属文中的后续计划；客户侧验收、正式 FDE 组织和自主 Agent 未取得 |
| 科大讯飞–国家能源招采 | 新浪转载每经文章，明确出现 FDE、本体和 Agent 表述 | 转载不算独立证据；报道效果、累计采购业务量和 2026 年新中标范围须分开 |

这 5 份档案不是“5 个经独立核验的 FDE 项目”。现有材料中，1 份明确使用 FDE 模式表述，1 份具备嵌入式工程师相邻证据，其余 3 份仍保留 FDE 未证实。5 份都没有取得签署的验收结论。

## 原文定位

每条证据保留 `documentId`、保存版本 `sha256` 和逐字短引文；完整原文仍从原文阅读器打开。以下为主源入口，不把链接存在当作内容取得或事实认证。

| 档案 | 本地主要文档 | 原始来源 |
| --- | --- | --- |
| Airbus | `doc-3094609758e64997af1b72318353803f` | [2017 年平台启动稿](https://www.airbus.com/en/newsroom/press-releases/2017-06-airbus-launches-skywise-aviations-open-data-platform) |
| McCarthy | `doc-9baf7b329c78490191ab88a20fa6e2fb` | [McCarthy 官方合作公告](https://www.mccarthy.com/insights/mccarthy-and-palantir-announce-strategic-partnership-to-bring-ai-to-the-construction-field) |
| 地方病知识图谱 | `doc-2c1f4cf702e142cd8c609245c5fe0145` | [政府采购成交公告](https://www.ccgp.gov.cn/cggg/dfgg/cjgg/202604/t20260402_26351019.htm) |
| MaMaTa | `doc-0f43fbe1c30740e692a7bf1d4edc8504` | [Cognite 具名案例](https://www.cognite.com/en/resources/customer-stories/mamata-unleashes-industrial-knowledge-with-cognite-data-fusion) |
| 国家能源招采 | `doc-8c722aff3663401f9c35310576d2c77f` | [新浪转载报道](https://finance.sina.com.cn/roll/2026-08-10/doc-inimuvrv5046493.shtml) |

Airbus 已补采并审读三份后续文档：

- [2017 年具名早期采用者材料](https://www.airbus.com/en/newsroom/news/2017-06-skywise-airline-early-adopter-highlights)：`doc-c3dd74626bb54bd193545187fa8cea3c`。补充 easyJet 共同处理运营问题、定制应用及部署的来源披露。
- [2018 年 easyJet 协议](https://www.airbus.com/en/newsroom/press-releases/2018-03-easyjet-signs-skywise-predictive-maintenance-agreement-with-airbus)：`doc-003d954f231f487fbb61ad85c893dfae`。五年和接近 300 架飞机是协议期限与覆盖范围，不是价格或逐机完成情况。
- [2024 年维护运营文章](https://www.aircraft.airbus.com/en/newsroom/news/2024-10-keeping-the-fleet-flying)：`doc-ded06620a6fa4a7a9f7a8c676962974b`。把其 SFP+ 效果表述归于后续产品及对应月份；仍缺反事实计算方法、运行原始记录和独立核对。

四份 Airbus 材料均来自同一企业渠道，不因文档增加就变成多条独立证据链。它们也不能证明项目从 2017 年到当前持续、不间断运行。

## 金额、项目数量和效果口径

- 地方病项目的人民币 59.8 万元，即 598,000.00 元，是 2026-04-02 结果公告的成交金额。公告里的评审价格不替代最终成交价；成交金额也不等于预算、付款、结算或报价分项。
- McCarthy 公告只给出多年及数百万 dollar 量级措辞，没有精确金额和币种代码。档案不自动将其写成已核对的美元合同价。
- 国家能源报道的业务采购项目量不是 FDE 项目数量，客户采购业务体量不是软件项目合同金额。报道准确率缺测试集、样本规模、测量时间与错误成本，保留为报道主张。
- Airbus 集团营收、航空售后市场规模和行业潜在节约均不可填入本项目价格。MaMaTa 没有取得合同或实施费用。

## 补采状态及具体缺口

地方病公告的报价 PDF 和采购文件 ZIP 已发现准确链接。报价 PDF 本轮正常采集在 robots 检查阶段遇到 SSL EOF，没有取得正文；这不是附件内容已被证实，也不能解释为采购方主动禁止全文获取。ZIP 尚未取得可审读采购需求。保留原链接用于正常公开访问恢复后的采集，不绕过访问边界。

MaMaTa 缺可靠客户侧实施和验收材料。已有 Cognite 活动入口可追索客户演示，但仍是供应商渠道，不计为独立核验。没有用搜索中的不明学生报告补齐数据。

国家能源案已发现每经原刊、其他转载及采购结果入口，列入下一步采集。当前档案仍以已经保存的新浪版本为证据；取得原刊后应核对稿源和重复关系，不把同文复制计为交叉证实。上市公司半年报在其他金融业务段落出现的 FDE 驻场表述，不能迁移用作国家能源项目的组织证据。

后续优先材料分别是：采购需求与验收条款、正式合同与价格口径、客户运行记录、可检查的本体模式、实际工程师职责和迭代记录、Agent 工具权限及评测。未发现准确公开链接的材料只记为缺口，不编造 URL。

## 审计结论

已验证 5 个标题与主要保存文档一致，65 个字段齐全，所有披露项均有本地引用。59 处引文逐字命中，引用 SHA 与保存文档一致，且重新计算 UTF-8 正文 SHA 一致；单条引文不超过 180 字符，各来源英文引文总量不超过 25 词。审计保留引用位置及引文哈希，不重复复制长文。

这些检查只证明索引与保存文本之间的引用完整性。它们不证明网站陈述真实、不认证采购履约、不证明效果可复现，也不替代人工审读上下文。引用采用短定位片段，判断应连同完整段落阅读，不能只靠片段猜测事实。

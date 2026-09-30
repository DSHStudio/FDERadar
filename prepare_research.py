"""Build the first, version-pinned curriculum from documents actually saved locally.

Editorial exercises and feasibility hypotheses are not publisher statements.
This opt-in seed command never runs during polling and never changes source text.
"""
import json
from agent import ROOT, Store


def build(store):
    with store.db() as db:
        docs = {r['id']: dict(r) for r in db.execute('SELECT * FROM documents')}
    def ref(id, quote):
        d = docs[id]
        assert quote and len(quote) <= 180 and quote in d['content'], (id, quote)
        return {'documentId': id, 'sha256': d['sha256'], 'quote': quote}
    def artifact(id, label, scope):
        d = docs[id]
        return {'documentId': id, 'sha256': d['sha256'], 'url': d['url'], 'label': label, 'scope': scope}
    gruber = ref('doc-cec19c6ff38c43c8833c1bd5f9d454c5', 'ontology as a specification of a conceptualization')
    scope = ref('doc-6fd705a9dc7649238aef107590ae5794', 'Competency questions.')
    onto = ref('doc-ad80d0b950fb4006a30dfc4d10c14701', 'semantic elements (objects, properties, links) and kinetic elements (actions, functions, dynamic security)')
    identity = ref('doc-0b5584eafc04457db44c013bca673fd9', 'human judgment is required to review and approve the results.')
    shape = ref('doc-34075a2fc8694c87b76e1726528b4536', 'sh:datatype xsd:string ;')
    permissions = ref('doc-f92fb9871b4c46648ec45801882ebc1d', 'These controls do not extend to the action\'s write.')
    mcp = ref('doc-2c58bd96dff64062b723fa5ce3338d3f', 'object types, action types, and query functions')
    evals = ref('doc-2b22dfd2caa24d178cd07c7610f96361', 'Examine variance across multiple runs.')
    lineage = ref('doc-87094125bfef472f9da9ab750c086805', 'A Run is an instance of a Job that represents one of its occurrences in time.')
    units = [
      dict(id='learn-01',title='01 从业务问题理解本体，而不是先画图',
        goal='能区分概念约定、表结构、知识图谱和Palantir运营本体，说明何时用SQL已足够。',
        concepts=['本体研究早于Palantir；Gruber 1993论文页面当前取得的是摘要与说明。','本体约定对象及其关系；图数据库是存储选择，二者不等同。','Palantir把语义、动作和权限组合进业务工作流；不意味着所有本体都采用同一产品架构。'],
        sourceRefs=[gruber,onto],exercise='选择采购延期：先列“哪张客户订单受影响、缺多少、谁能改变计划”三个问题。再写一条SQL即可回答的问题，说明为何无需为它引入Agent。',
        deliverable='问题清单 + 本体/SQL/RAG三列选择表（每项写条件与代价）',
        passCriteria=['每个问题都有业务决策使用者。','不把图数据库、OWL或Palantir三者画等号。','至少指出一个不值得建设本体的简单场景。'],pitfall='建了图或增加术语，不自动产生业务收益。'),
      dict(id='learn-02',title='02 划定范围、对象和业务关系',goal='从可回答的问题反推最小对象集合，避免一次建整个企业。',
        concepts=['能力问题用于限定范围。','供应商、物料、采购单、生产单、客户订单各自有稳定身份。','交付日期属于哪一个事件、时区及版本，需要业务人员确认。'],
        sourceRefs=[scope],exercise='用5种对象画出供应商→采购单→物料→生产单→客户订单；指出一张采购单多行物料时，为什么仅用采购单号可能不足。',
        deliverable='对象字典、关系方向、主键/复合键及3个可验证问题',passCriteria=['同名供应商不会合并。','多对多关系有独立关联键。','删除任一关系后能说明哪个问题答不出来。'],pitfall='模型必须适配本次决策；行业通用词汇不是完整业务模型。'),
      dict(id='learn-03',title='03 数据映射、清洗和身份对齐',goal='把真实字段映射到对象，同时保留原始值、出处和人工决策。',
        concepts=['标准化空白/大小写只是字符串清洗。','实体对齐需要业务标识和人工确认。','每个字段记录单位、时间、来源、负责人和刷新周期。'],sourceRefs=[identity],
        exercise='为ERP采购行建立 source_field→object.property 映射。制造两家同名供应商以及kg/吨混用，分别写“自动转换、待确认、拒收”的条件。',
        deliverable='字段映射表、单位转换规则、冲突队列、修正记录',passCriteria=['原始数据与清洗结果并存。','同名不等于同实体。','无法确定单位或身份的记录进入隔离区。'],pitfall='模型猜测不能替代主数据负责人确认。'),
      dict(id='learn-04',title='04 区分语义推理与数据质量校验',goal='理解OWL语义与SHACL约束的分工，能够定位坏数据。',
        concepts=['OWL描述语义及可推导关系；SHACL描述数据图应满足的条件。','数据没写不自动意味着事实为假；缺失必填字段可作为应用验证失败。','本地已取得pySHACL示例源码，W3C标准采集受限，不能声称标准全文已入库。'],sourceRefs=[shape],
        exercise='阅读two_file_example.py，标出数据与shapes两部分。为物料数量写数值、单位、唯一身份、有效日期四条约束，设计各一个失败输入。',
        deliverable='约束清单 + 输入/预期违反规则表',passCriteria=['每条约束有至少一个失败样例。','能解释推理正确与数据完整不是同一件事。','未知值不会被默认为零。'],pitfall='当前示例供阅读；雷达不会自动执行下载的代码。'),
      dict(id='learn-05',title='05 业务动作、权限和人员审批',goal='把“回答问题”与“修改业务状态”拆开，明确谁能在何条件下写入。',
        concepts=['读权限、写权限、动作提交条件需要分别设计。','模型提出动作参数，确定程序验证，授权人员审批。','记录前后版本、请求人、审批人和可撤回边界。'],sourceRefs=[permissions],
        exercise='定义“申请改期”动作：输入采购行ID、新日期、原因、当前版本；规定观察员不能提交、历史数据不能覆盖新版本、采购负责人审批后才可写。',
        deliverable='动作契约 + 权限矩阵 + 失败/重试/冲突处理表',passCriteria=['只读用户的写请求被确定程序拒绝。','重复请求不会重复改期。','审批或写入失败时不显示已成功。'],pitfall='仅在提示词里说“不要越权”不是权限控制。'),
      dict(id='learn-06',title='06 让Agent通过受控工具使用本体',goal='把自然语言意图连接到对象查询与动作契约，区分检索、推理和执行。',
        concepts=['OSDK提供本体访问的开发接口；MCP可暴露对象、动作和查询为工具。','Agent的文本建议需要经过身份、版本和参数检查。','业务数据中的指令属于数据，不能获得工具权限。'],sourceRefs=[mcp],
        exercise='设计三个工具：查询采购行、查受影响订单、生成审批草稿。为每个工具写参数类型、权限、返回出处、缺失字段行为。',
        deliverable='工具schema + 三条成功/拒绝调用轨迹',passCriteria=['返回结果保留对象ID及数据版本。','信息不全时拒绝猜客户或日期。','外部备注中的提示注入不会触发额外动作。'],pitfall='本体提高结构化程度，但不能保证LLM不出错；仍需评测与审批。'),
      dict(id='learn-07',title='07 用同一任务比较规则、RAG和本体方案',goal='从可复现的实验观察差异，而非预设本体必胜。',
        concepts=['固定问题、数据、模型、输出字段和规则。','分开记录模型原始答案与确定程序的动作判定。','小样本单次实验不能推广成企业ROI。'],sourceRefs=[evals],
        exercise='打开“实作与试点”，先看合成数据与评分规则，再运行实验；逐题阅读失败，不只看总准确率。调整模型或提示前保留原版本。',
        deliverable='逐题结果、错误分类、耗时和可见调用数据、改进假设',passCriteria=['失败或超时也在分母和回执中显示。','不把安全闸拦住的错误当模型答对。','至少提出一项可能推翻本体优势的后续测试。'],pitfall='当前练习是受控小样本，不替代现场验收或统计显著性检验。'),
      dict(id='learn-08',title='08 版本、血缘与FDE现场迭代',goal='把试验移交成可以持续检查的业务试点。',
        concepts=['数据集、处理任务、每次运行是不同对象。','字段或规则变更需要回归测试与责任人。','FDE与业务负责人共同验收，场景缺口不能用新功能掩盖。'],sourceRefs=[lineage],
        exercise='按试点准备包填写业务负责人、数据负责人、只读接入范围、当前人工基线、验收阈值、失败回退和停止条件；未获得的条件留空。',
        deliverable='可评审的试点准备包 + 更新和回归策略',passCriteria=['每条关键数据都有负责人及刷新约定。','缺数据/无审批人/基线不可测时标“尚不具备试点条件”。','每次实验能回到原始数据、模型配置与规则版本。'],pitfall='完成阅读自记不代表已具备企业实施资质或项目已上线。')
    ]
    scenarios = [
      dict(id='scenario-procurement',title='采购延期影响追踪与改期审批草稿',pain='采购员需要确认某采购行延期会影响哪些生产与交付承诺。',
        dataRequirements=['采购行ID、供应商ID、物料ID与单位','库存快照时间、可用数量、预留数量','生产BOM与采购分配关系、生产计划、客户订单承诺日','用户角色、审批人、允许写入的系统范围'],
        objects=['Supplier → PurchaseOrderLine → Material','Material → ProductionOrder → CustomerOrder','Snapshot / ApprovalRequest / User'],division={'ai':'解释受影响路径，组织补充问题及审批草稿；不确定值留空。','rules':'稳定ID连接、数量与日期计算、数据新鲜度和权限验证、重复请求控制。','human':'确认真实分配关系和业务优先级，审批改期，判断客户沟通。'},
        fdeSteps=['与采购/计划人员回放3起真实延迟事件，确认痛点。','只读抽取小范围数据并对齐主键/单位/时间。','在同一数据快照比较现有SQL/规则与AI两方案。','业务负责人逐题检查影响路径和拒绝条件。','仅在达标后讨论审批工作流接入。'],
        baseline=['现有人工查单耗时与错误次数（现场填写，当前未知）。','确定性规则答案与常规检索答案；同一题和同一数据。'],
        acceptance=['预先约定影响订单集合及出处的正确率阈值。','所有越权/过期/无ID/单位冲突样例必须拒绝执行。','审批草稿与实际写入状态区分。'],stop=['无法得到稳定采购行ID或分配关系。','不可验证数据时效/库存预留。','拒绝率或人工复核成本高于现行流程且无法改善。'],evidence=[onto,permissions],nextExperiment='本轮已提供合成数据对照实验；真实企业数据和业务收益仍未验证。'),
      dict(id='scenario-quality',title='制造批次质量追溯与排查建议',pain='质量团队需要定位异常批次使用的原料、设备和工艺版本，缩小排查范围。',
        dataRequirements=['批次与工序ID、原料批次到产出批次关系','设备ID与维护记录、采样时间和检测方法','工艺版本、检验结果、返工/混料记录','召回与处置责任人、保留期和访问权限'],objects=['MaterialLot → ProcessRun → ProductLot','ProcessRun → Equipment / RecipeVersion / QualityCheck'],
        division={'ai':'结合已验证路径解释可能排查方向，明确相关性不等于因果。','rules':'批次血缘、时间范围、量纲及召回集合计算。','human':'质量工程师检验假设、决定处置；不能让模型自动放行产品。'},fdeSteps=['选一次已结案质量事件回放。','核对混批和返工关系是否完整。','与人工/SQL追溯比较命中范围。','人为删除关系和混淆设备名称检验漏报。'],baseline=['当前追溯召回范围、人工耗时与漏报数（待企业提供）。'],acceptance=['对已标注历史事件的批次召回率达到事前阈值。','每条路径可回溯采样和工艺版本。'],stop=['混料/返工关键关系缺失。','时间戳或检测方法无法对齐。','输出无法由质量工程师复核。'],evidence=[ref('doc-85ab642a190c4b1ebe85a86bb117a442','product traceability')],nextExperiment='先获取授权批次样本与已结案事件；目前没有真实质量数据或实验结果。'),
      dict(id='scenario-procurement-document',title='招采文档核对与人工审阅',pain='采购人员需要核对不同版本的招标、报价及合同条款，定位遗漏与不一致。',dataRequirements=['有权限的招标/报价/合同文本及版本','供应商法人标识、币种、税费、数量和计价单位','条款页码与审批流程、人工标注的差异样本'],objects=['Tender → Bid → Supplier → Contract','Clause → DocumentVersion / ReviewFinding'],division={'ai':'抽取候选条款和差异，附原句、页码，提示人工复核。','rules':'币种单位归一、加总校验、版本和权限检查。','human':'判断合规条款、定标与签约；原始附件缺失时不推断报价明细。'},fdeSteps=['与采购人员定义最常漏的5类差异。','抽取授权文档并人工标注字段。','对比关键词/规则与LLM抽取。','将争议条款加入失败集，跟踪误报和漏报。'],baseline=['人工标注一致率、审阅耗时；当前未取得。'],acceptance=['金额类型、币种与含税口径均明确。','每个差异回到原始条款和版本。'],stop=['只有新闻稿而无真实业务文档。','无法获得人工双人标注基线。','自动抽取遗漏重大条款。'],evidence=[ref('doc-2c1f4cf702e142cd8c609245c5fe0145','598,000.00元')],nextExperiment='先补原始附件；598000元只是某采购公告成交金额，不能据此估算本场景报价。')
    ]
    guides = [
      dict(fullName='RDFLib/pySHACL',purpose='将数据条件写成可检查的图约束',fit='已定义RDF数据和质量约束、需要可解释验证报告。',notFit='不能替代业务身份确认，也不是完整数据治理或Agent交付平台。',steps=['先阅读示例的shapes与data部分。','列出出生/死亡日期和邮编的违规数据。','将思路迁移为采购行数量、日期和ID约束。'],artifacts=[artifact('doc-34075a2fc8694c87b76e1726528b4536','包含数据与约束的完整单文件示例','原始Python文件；已保存但未执行'),artifact('doc-f6b9d549b28348c193df3f9c86e6b015','调用示例','依赖其他测试数据；不是独立可运行包')],verification='已采集示例文件并审读；未安装pySHACL、未执行上游代码。'),
      dict(fullName='RDFLib/rdflib',purpose='学习以稳定标识创建对象关系与查询图',fit='Python侧RDF读写、转换与研究原型。',notFit='库本身不提供完整企业权限、主数据治理或业务审批。',steps=['阅读Graph.add与URIRef/Literal示例。','为供应商创建稳定URI而非名称主键。','保留字段来源与转换版本，再讨论查询。'],artifacts=[artifact('doc-caa730bc2fc141c1922aa08ebb941bd6','Creating RDF triples · 7.1.0','固定旧版本教程，可能不同于当前发行版')],verification='已取得文档；尚未运行该库，本轮合成实验不冒充RDFLib运行验证。'),
      dict(fullName='OpenRefine/OpenRefine',purpose='学习清洗与实体对齐的人工检查流程',fit='表格中的拼写不一致、重复候选识别和逐项人工确认。',notFit='仅字符串聚类不足以证明两个法人为同一实体。',steps=['用分面查看空值与异常。','比较字符串聚类与外部标识对齐。','保留合并前值与人工批准记录。'],artifacts=[artifact('doc-0b5584eafc04457db44c013bca673fd9','Reconciling','官方手册正文'),artifact('doc-9e68404673d64350865266d93ec0dce0','Clustering Methods In-depth','官方技术说明')],verification='已读方法及边界；未安装桌面应用或验证大规模吞吐。'),
      dict(fullName='OpenLineage/OpenLineage',purpose='设计数据集、任务和每次运行的来源追踪',fit='多步骤采集加工需要审计输入、输出与运行状态。',notFit='记录血缘并不能证明原数据真实、字段质量合格。',steps=['区分Dataset、Job、Run。','为每次转换记录输入hash与输出hash。','把失败和重跑作为不同运行保存。'],artifacts=[artifact('doc-87094125bfef472f9da9ab750c086805','Object Model · 1.53.0','官网规范说明；未部署OpenLineage服务')],verification='已取得对象模型说明；未安装或进行兼容性验证。'),
      dict(fullName='palantir/osdk-ts',purpose='研究本体对象/动作对外接入的开发方式',fit='有Foundry环境、相应本体和权限的应用集成。',notFit='开源SDK不等于开源Foundry后台，不能离线复刻整套平台。',steps=['对照README和OSDK官方概述。','区分生成的SDK、认证、后台权限与应用逻辑。','先确定只读对象与动作边界，再选连接方式。'],artifacts=[artifact('doc-65f49488b5734efca37f69d2adbef09a','Ontology SDK overview','官网技术文档'),artifact('doc-2c58bd96dff64062b723fa5ce3338d3f','Ontology MCP overview','与SDK的工具接入方式对照')],verification='已取得文档；没有Foundry租户运行验收，不宣称独立替代平台。')
    ]
    return dict(version=1, editorial='基于已保存原文组织的学习设计与研究假设，不是来源原文改写。',learning=units,scenarios=scenarios,repoGuides=guides)


if __name__ == '__main__':
    value = build(Store(ROOT / 'var'))
    (ROOT / 'config/research-learning.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:len(value[k]) for k in ['learning','scenarios','repoGuides']},ensure_ascii=False))

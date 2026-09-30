"""Use DSH to read and analyze a small, explicit set of already acquired sources."""
import json
from pathlib import Path
from agent import Store, execute

ROOT=Path(__file__).resolve().parent
GROUPS=[
    ('理论与实现', 'theory', ['ontology-mcp/overview','github.com/OpenSPG/KAG','ontology101.pdf'],
     '逐份说明可学习的概念、如何构建对象/关系/动作与权限、与Agent结合的技术边界。只写文中有依据的内容，说明不是已复现的实现或客户成效。'),
    ('跨厂商案例', 'case', ['how-nfl-next-gen-stats-built','mamata-unleashes-industrial-knowledge','mccarthy-and-palantir-announce'],
     '逐份给出客户、供应商、业务痛点、原文明确的技术和工程方法。区分FDE参与、本体、Agent和上线证据，未知不猜。Cognite案例不自动归为FDE。'),
    ('中国原始披露', 'case', ['1225485550.PDF','1225547373.PDF','doc-inimuvrv5046493'],
     '长PDF用radar_read(query)分别定位国能/中粮/FDE，在原句上下文阅读。公司级FDE披露不能自动转成具名项目。新浪文章系每日经济新闻转载，指标保持自报，不能当作独立审计。'),
    ('制造与经营试验', 'scenario', ['rapidly-turning-shop-floor-needs','drill-down-smarter-how-cognite'],
     '逐份结合公开材料提出一个可落地性待验证的制造/经营试验。analysis写痛点、对象关系、企业数据接口、规则/AI/人员分工、FDE现场步骤、基线与验收、停止条件。所有方案是研究建议，不编造已完成的企业实验或ROI。')
]


def run():
    s=Store(ROOT/'var');config=json.loads((ROOT/'config.json').read_text(encoding='utf-8-sig'))
    for label,track,needles,instruction in GROUPS:
        with s.db() as db:
            docs=[]
            for needle in needles:
                d=db.execute("SELECT id,url,title,sha256 FROM documents WHERE url LIKE ? AND access='body_fetched_not_semantically_verified' ORDER BY retrievedAt DESC LIMIT 1",('%'+needle+'%',)).fetchone()
                if d:
                    # A previously completed note for this source+track makes reruns incremental.
                    prior=db.execute("SELECT 1 FROM notes WHERE track=? AND status IN ('pending_review','accepted') AND json_extract(payload,'$.documentId')=?",(track,d['id'])).fetchone()
                    if not prior: docs.append(dict(d))
        if not docs:
            print(json.dumps({'group':label,'status':'NO_UNPROCESSED_DOCUMENTS'},ensure_ascii=False),flush=True);continue
        for doc in docs:
            task=('采集后学习加工：'+label+'。只处理下面这1份已经实际获取的文档，不搜索、不重新抓取。用radar_read读取相关原文；长PDF先query定位FDE、国能或中粮，不必遍历财务报表。提交1条track='+track+'笔记后正常结束。'+instruction+
                  ' analysis最多300中文字，limitations最多150中文字，nextStep最多100中文字，不扩写长篇。案例title必须原样等于document.title，summary必须原样等于quote，quote保持原句且不超过100字符。只阅读所引用段落及上下文，明确未通读整份PDF，不称全文已读。如果内容不支持就不提交。文档：'+json.dumps(doc,ensure_ascii=False))
            receipt=execute(s,config,task)
            print(json.dumps({'group':label,'document':doc['id'],**receipt},ensure_ascii=False),flush=True)


if __name__=='__main__': run()

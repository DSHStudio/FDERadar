// Run with node web/test_research.js. No network, browser package or model calls.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const elements = new Map();
class Element {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.listeners = {};
    this.attributes = {};
    this.dataset = {};
    this.style = {};
    this._text = "";
    this.classList = { toggle() {} };
  }
  set id(value) {
    this._id = value;
    elements.set(value, this);
  }
  get id() {
    return this._id;
  }
  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }
  get textContent() {
    return (
      this._text +
      this.children
        .map((child) => (typeof child === "string" ? child : child.textContent))
        .join(" ")
    );
  }
  set innerHTML(_) {
    throw new Error("Source HTML must never be executed");
  }
  get childElementCount() {
    return this.children.length;
  }
  append(...children) {
    this.children.push(...children);
  }
  add(child) {
    this.append(child);
  }
  prepend(...children) {
    this.children.unshift(...children);
  }
  replaceChildren(...children) {
    this._text = "";
    this.children = children;
  }
  setAttribute(key, value) {
    this.attributes[key] = String(value);
  }
  removeAttribute(key) {
    delete this.attributes[key];
  }
  addEventListener(key, callback) {
    this.listeners[key] = callback;
  }
  querySelectorAll() {
    return [];
  }
  contains() {
    return false;
  }
  closest() {
    return null;
  }
  focus() {
    sandbox.document.activeElement = this;
  }
  blur() {}
  showModal() {
    this.open = true;
  }
  close() {
    this.open = false;
  }
}
for (const [, id] of fs
  .readFileSync(path.join(__dirname, "index.html"), "utf8")
  .matchAll(/id="([^"]+)"/g)) {
  const node = new Element("div");
  node.id = id;
}
const sandbox = {
  assert,
  console,
  URL,
  location: { hash: "#case" },
  setTimeout() {
    return 1;
  },
  clearTimeout() {},
  Option: function (label, value) {
    const node = new Element("option");
    node.textContent = label;
    node.value = value;
    return node;
  },
  window: { addEventListener() {} },
  document: {
    activeElement: null,
    hidden: false,
    getElementById: (id) => elements.get(id),
    createElement: (tag) => new Element(tag),
    querySelectorAll: () => [],
    addEventListener() {},
  },
  fetch() {
    throw new Error("Unexpected network request");
  },
};
vm.createContext(sandbox);
require("./test_support/load_ui.cjs").loadUi(sandbox, __dirname);
const test = `
(async () => {
  let checks = 0; const check = (value, message) => { assert.ok(value, message); checks++; }; const originalRefresh=refresh, originalApi=api;
  const walk = node => [node, ...node.children.flatMap(child => typeof child === 'string' ? [] : walk(child))];
  const visibleText = node => typeof node==='string'?node:node._text+(node.tagName==='details'&&!node.open?node.children.filter(child=>child.tagName==='summary'):node.children).map(visibleText).join(' ');
  const control = (node, name) => walk(node).find(child => child.tagName === 'button' && child.textContent === name);
  const reference = {documentId:'doc-1',sha256:'hash-1',quote:'Original source statement <script>alert(1)</script>',valid:true,title:'Original title',url:'https://example.com/original',retrievedAt:'2026-09-28T12:00:00Z'};
  const example = {id:'case-1',title:'Original project title',classification:'研究分类',editorialNote:'中文整理必须折叠',claims:[{key:'scope',label:'合作范围',value:'编辑中文索引',status:'disclosed',evidence:[reference]},{key:'price',label:'金额与报价',value:'未知',status:'unknown',evidence:[]}],gaps:['未取得分项报价'],nextAcquisition:[{url:'https://example.com/contract',purpose:'取得合同范围'}],transfer:{usable:['方法'],conditions:['数据条件'],notProven:['企业ROI']}};
  const lesson = {id:'learn-1',title:'学习本体',goal:'理解对象与关系',concepts:['对象','关系'],sourceRefs:[reference],exercise:'建立对象表',deliverable:'对象关系清单',passCriteria:['逐项说明依据'],pitfall:'不要把模型输出当事实',progress:{status:'not_started',notes:''}};
  app.data = {documents:[],notes:[],records:[],sources:[],jobs:[],runs:[],githubResources:{resources:[]},research:{cases:[example],learning:[lesson],scenarios:[{id:'scenario-1',title:'订单试验',pain:'等待确认',dataRequirements:['真实订单数据'],objects:['订单→客户'],division:{ai:'解释',rules:'验证条件',human:'批准'},fdeSteps:['核对流程'],baseline:['当前耗时'],acceptance:['人工核对'],stop:['来源缺失停止'],evidence:[reference],status:'research_only',nextExperiment:'先验证十条'}],repoGuides:[],audit:{unresolvedClaims:1,invalidReferences:0,staleReferences:0,notIndependentlyVerified:1,acquisitionGaps:[{url:'https://example.com/contract',purpose:'取得合同范围',status:'not_attempted'}]},changes:[{url:'https://example.com/original',title:'Original title',oldDocumentId:'doc-1',newDocumentId:'doc-2',oldHash:'hash-1',newHash:'hash-2',meaning:'原文版本变化，尚未核对语义'}]}};
  let opened, openedReference; openDocument = (...args) => { opened=args; }; openEvidence = ref => { openedReference=ref; opened=[ref.documentId]; };
  render();
  check($('page-title').textContent==='项目案例', 'case navigation');
  check($('content').textContent.includes(reference.quote), 'exact original quote kept');
  check(!$('content').children.some(node=>node.tagName==='script'), 'source markup is text');
  const caseCard = caseResearchCard(example);
  check(!caseCard.textContent.includes('编辑中文索引')&&caseCard.textContent.includes(reference.quote), 'default project facts contain original evidence without editorial values');
  control(caseCard,'定位原文').listeners.click(); check(openedReference===reference&&openedReference.sha256==='hash-1', 'case reader receives exact quote and version for original location');
  check(caseCard.textContent.includes('尚无该项的充分原句依据'), 'unknown claim has no invented evidence');
  control(caseCard,'原始资料').listeners.click(); const sourcesPane=$('content'); control(sourcesPane,'Original title').listeners.click();
  check(openedReference===reference&&sourcesPane.textContent.includes('example.com')&&sourcesPane.textContent.includes('采集于 2026-09-28')&&!sourcesPane.textContent.includes('原始材料 1'),'source entry has original title and honest collected date, opens matching reference');
  control(sourcesPane,'研究解读').listeners.click(); check($('content').textContent.includes('编辑中文索引')&&$('content').textContent.includes('研究整理 · 以下为中文解读，非来源原文'),'interpretations live in explicitly labeled research pane');
  researchUI.casePane='facts';
  researchUI.caseFilter='price'; render(); check($('content').textContent.includes('没有符合此证据条件'), 'unknown price excluded from disclosed amount filter');
  researchUI.caseFilter='missing'; render(); check($('content').textContent.includes('Original project title'), 'missing evidence filter');
  researchUI.caseFilter='conflicting'; render(); check($('content').textContent.includes('没有符合此证据条件'), 'conflict filter does not invent conflicts');
  researchUI.caseFilter='';
  const invalid = researchEvidence({...reference,valid:false,reason:'Hash mismatch'}); check(invalid.textContent.includes('登记引文 · 尚未匹配')&&invalid.textContent.includes('Hash mismatch'), 'invalid quote distinguished');
  const stale = researchEvidence({...reference,stale:true,latestDocumentId:'doc-2'}); control(stale,'比较最新原文').listeners.click(); check(opened[0]==='doc-2','stale reference opens new version');
  location.hash='#theory'; render(); check($('content').textContent.includes('完成产出')&&$('content').textContent.includes('自查条件'), 'learning deliverable and pass criteria');
  let calls=[]; api=async(path,body)=>{calls.push({path,body});return body;};
  const card=learningCard(lesson); const form=walk(card).find(node=>node.tagName==='form');
  const select=walk(card).find(node=>node.tagName==='select');const textarea=walk(card).find(node=>node.tagName==='textarea');
  select.value='in_progress';textarea.value='My observed result';textarea.listeners.input();
  check(researchUI.drafts.get('learn-1').notes==='My observed result', 'draft retained between renders');
  await form.listeners.submit({preventDefault(){}});
  check(calls.at(-1).path==='/api/research/progress'&&calls.at(-1).body.id==='learn-1'&&calls.at(-1).body.notes==='My observed result','learning progress saved via real endpoint contract');
  check(lesson.progress.status==='in_progress'&&form.textContent.includes('已保存'),'save success reflected as self-record');
  api=async()=>{throw Error('HTTP 503');};textarea.value='Unsaved result';textarea.listeners.input();await form.listeners.submit({preventDefault(){}});
  check(form.textContent.includes('保存失败')&&researchUI.drafts.get('learn-1').notes==='Unsaved result','failed save retains draft, no false completion');
  location.hash='#scenario';render();check($('content').textContent.includes('来源缺失停止')&&$('content').textContent.includes('确定性规则')&&$('content').textContent.includes('未经企业实测'),'scenario conditions and evidence boundary');
  const guide=repoGuidePanel({purpose:'使用路径',fit:['适用条件'],notFit:['不适用条件'],steps:['实际上手步骤'],artifacts:[reference],verification:'尚未运行'});
  check(guide.tagName==='details'&&guide.textContent.includes('尚未运行')&&guide.textContent.includes(reference.quote),'repo guide keeps validation and real artifact');
  location.hash='#intelligence';render();control($('content'),'阅读旧版本').listeners.click();check(opened[0]==='doc-1','old document version route');control($('content'),'阅读新版本').listeners.click();check(opened[0]==='doc-2','new document version route');
  check($('content').textContent.includes('不能直接视为理论'),'version difference not semantic change');
  location.hash='#sources';render();check($('content').textContent.includes('研究结论的证据缺口'),'audit integrated in source route');
  let acquisition; action=(path,body)=>{acquisition={path,body};};control($('content'),'获取此资料').listeners.click();check(acquisition.path==='/api/collect'&&acquisition.body.urls[0]==='https://example.com/contract','gap acquisition actionable');
  researchUI.lab={scope:'synthetic local test',running:false,dataset:{type:'synthetic'},latest:null,runs:[]}; location.hash='#practice';render();
  check($('page-title').textContent==='实作与试点'&&$('collect-button').hidden,'practice navigation and scoped action');
  check($('content').textContent.includes('尚无实际试验记录'),'no run means no fabricated result');
  researchUI.lab.running=true;render();check($('run-lab').disabled&&anyTaskRunning(),'running lab disables duplicate and polls state');
  researchUI.lab.running=false;api=async(path,body)=>{calls.push({path,body});return path==='/api/lab'?{running:false,scope:'test',dataset:{},runs:[],latest:{id:'run-1',status:'SUCCEEDED'}}:{id:'run-1',status:'QUEUED'};};refresh=async()=>{};await runResearchLab();
  check(calls.some(call=>call.path==='/api/lab/run')&&calls.at(-1).path==='/api/lab','lab run POST followed by actual state GET');
  check(researchUI.lab.latest.id==='run-1','only returned result shown');
  const detailed = {id:'labrun-test',status:'COMPLETED_WITH_FAILURES',synthetic:true,startedAt:'2026-09-28T12:00:00Z',completed:2,total:3,metrics:{ontology_dsh:{attempted:2,completed:1,correct:0,accuracy:0,safetyPassed:1,constraintBlocked:1,elapsedSeconds:2.5}},results:[{questionId:'Q1',challenge:'invalid data',arm:'ontology_dsh',status:'SUCCEEDED',execution:'actual_dsh',rawOutput:'<img onerror=alert(1)>',answer:{decision:'impact'},grading:{correct:false,fieldChecks:{decision:false},safetyBoundaryPassed:true,expected:{decision:'abstain'}},constraintCheck:{accepted:false,violations:['FRESHNESS_CONSTRAINT']}}]};
  const runCard = labRunCard(detailed);check(runCard.textContent.includes('0.0%（0 / 2）')&&runCard.textContent.includes('2.5 秒'),'actual metrics and failure denominator');
  check(runCard.textContent.includes('拦截不会改写模型答案')&&runCard.textContent.includes('自动判分：不正确'),'constraint rejection not recounted as correct model answer');
  check(runCard.textContent.includes('<img onerror=alert(1)>'),'raw lab output stays text');
  check(runCard.textContent.includes('已执行 2 / 3 题次（包含执行失败；不是通过题数）'),'progress attempts distinct from pass count');
  check(!control(labRunCard({id:'queued',status:'QUEUED',artifacts:{pilotPack:'not-created'}}),'阅读试点准备包'),'queued artifact path not proof generated file');
  api=async(path)=>{calls.push({path});return {text:'Actual saved pilot document <script>not executed</script>',name:'pilotPack',mimeType:'text/markdown'};};await openLabArtifact('labrun-test','pilotPack');
  check(calls.at(-1).path==='/api/lab/artifact?runId=labrun-test&name=pilotPack'&&$('lab-artifact-content').textContent.includes('Actual saved pilot document'),'artifact whitelist API displays actual content');
  api=async()=>{throw Error('FILE_NOT_FOUND');};await openLabArtifact('labrun-test','receipt');check($('lab-artifact-content').textContent.includes('不以生成文字替代缺失文件'),'missing artifact error not substituted');
  check(researchEvidence({valid:true,documentId:'doc-1'}).textContent.includes('版本已匹配')&&!researchEvidence({valid:true,documentId:'doc-1'}).textContent.includes('原句 /'),'artifact references do not falsely claim quote validation');
  location.hash='#practice';app.token='session';app.busy=false;researchUI.lab={running:false,runs:[],latest:null,dataset:{questions:8},arms:['sql_rules','retrieval_dsh','ontology_dsh']};
  api=async(path)=>path==='/api/state'?app.data:{running:false,runs:[],latest:detailed,dataset:{questions:8},arms:['sql_rules','retrieval_dsh','ontology_dsh']};
  await originalRefresh(false);check($('content').textContent.includes('0.0%（0 / 2）'),'lab polling redraws changed trial results when library state is unchanged');
  researchUI.lab.boundaryMeaning='共享权限预过滤，不计模型能力';researchUI.lab.costMeaning='未取得计费账单';render();
  check($('content').textContent.includes('共享权限预过滤，不计模型能力')&&$('content').textContent.includes('未取得计费账单'),'actual boundary and cost meanings displayed');
  check($('content').textContent.includes('不评估解释忠实性')&&$('content').textContent.includes('历史 v1：请求权限 / 无写入字段'),'legacy scoring explicitly limited');
  const currentRun = labRunCard({...detailed,scoringVersion:'v2'});check(walk(currentRun).some(node=>node.tagName==='th'&&node.textContent==='输出权限 / 动作字段检查'),'current table names precise output checks');
  api=async(path)=>{calls.push({path});return {text:'ACTUAL FILE CONTENT',name:'data',mimeType:'application/json'};};
  await control(runCard,'查看合成数据快照').listeners.click();check(calls.at(-1).path==='/api/lab/artifact?runId=labrun-test&name=data'&&$('lab-artifact-title').textContent==='合成数据快照','run data button reads snapshot endpoint');
  await control(runCard,'查看题目与标准答案').listeners.click();check(calls.at(-1).path==='/api/lab/artifact?runId=labrun-test&name=questions','questions button reads gold fixture endpoint');
  await control(runCard,'读取此题实际输入').listeners.click();check(calls.at(-1).path==='/api/lab/artifact?runId=labrun-test&name=input&item=ontology_dsh-Q1'&&$('lab-artifact-content').textContent==='ACTUAL FILE CONTENT','per-question input button carries run and arm/question');
  check($('lab-artifact-meta').textContent.includes('不是企业生产数据'),'artifact scope remains synthetic');
  await openLabArtifact('run &?/test','input','ontology_dsh-Q1 &name=receipt');check(calls.at(-1).path==='/api/lab/artifact?runId=run%20%26%3F%2Ftest&name=input&item=ontology_dsh-Q1%20%26name%3Dreceipt','artifact query values encoded without parameter injection');
  check(!control(labResultCard({arm:'../private',questionId:'Q1',status:'FAILED'},'run'),'读取此题实际输入'),'invalid arm does not create an input file control');
  api=originalApi;const response=(status,data)=>({status,ok:status>=200&&status<300,json:async()=>data});let requests=[];
  fetch=async(path,options)=>{requests.push({path,...options});return requests.length===1?response(403,{error:'FORBIDDEN'}):path==='/api/session'?response(200,{token:'renewed-session'}):response(200,{status:'saved'});};app.token='stale-session';
  const savedProgress=await api('/api/research/progress',{id:'learn-1',status:'in_progress',notes:'preserved notes'});
  check(savedProgress.status==='saved'&&requests.map(request=>request.path).join(',')==='/api/research/progress,/api/session,/api/research/progress','exact forbidden POST refreshes same-origin session then retries once');
  check(requests[0].headers['X-Radar-Token']==='stale-session'&&requests[2].headers['X-Radar-Token']==='renewed-session'&&requests[0].body===requests[2].body,'retry preserves original operation with refreshed token');
  requests=[];fetch=async(path,options)=>{requests.push({path,...options});return path==='/api/session'?response(200,{token:'still-rejected'}):response(403,{error:'FORBIDDEN'});};
  await assert.rejects(()=>api('/api/research/progress',{id:'learn-1'}),/FORBIDDEN/);check(requests.length===3&&requests.filter(request=>request.method==='POST').length===2,'second forbidden failure ends without retry loop');
  requests=[];fetch=async(path,options)=>{requests.push({path,...options});throw Error('NETWORK_UNCERTAIN');};await assert.rejects(()=>api('/api/lab/run',{}),/NETWORK_UNCERTAIN/);check(requests.length===1,'uncertain network failure never repeats a mutation');
  requests=[];fetch=async(path,options)=>{requests.push({path,...options});return response(503,{error:'SERVICE_UNAVAILABLE'});};await assert.rejects(()=>api('/api/lab/run',{}),/SERVICE_UNAVAILABLE/);check(requests.length===1,'general HTTP failure never repeats operation');
  requests=[];fetch=async(path,options)=>{requests.push({path,...options});return response(403,{error:'ORIGIN_NOT_ALLOWED'});};await assert.rejects(()=>api('/api/research/progress',{}),/ORIGIN_NOT_ALLOWED/);check(requests.length===1,'other forbidden reason is not session recovery trigger');
  requests=[];fetch=async(path,options)=>{requests.push({path,...options});return response(403,{error:'FORBIDDEN'});};await assert.rejects(()=>api('/api/state'),/FORBIDDEN/);check(requests.length===1,'GET forbidden never enters POST recovery');
  requests=[];fetch=async(path,options)=>{requests.push({path,...options});return path==='/api/session'?response(200,{}):response(403,{error:'FORBIDDEN'});};await assert.rejects(()=>api('/api/lab/run',{}),/会话未能恢复/);check(requests.length===2,'invalid recovered session does not retry operation');
  const retained=learningCard(lesson);const retainedForm=walk(retained).find(node=>node.tagName==='form');const retainedNotes=walk(retained).find(node=>node.tagName==='textarea');retainedNotes.value='preserve after auth failure';retainedNotes.listeners.input();requests=[];fetch=async(path,options)=>{requests.push({path,...options});return path==='/api/session'?response(200,{token:'rejected'}):response(403,{error:'FORBIDDEN'});};await retainedForm.listeners.submit({preventDefault(){}});check(retainedForm.textContent.includes('保存失败')&&researchUI.drafts.get('learn-1').notes==='preserve after auth failure'&&requests.length===3,'failed auth recovery keeps learning input and stops');
  const sourceView=researchEvidence(reference);check(visibleText(sourceView).includes(reference.quote)&&!visibleText(sourceView).includes('hash-1')&&sourceView.textContent.includes('hash-1'),'reference quote remains visible while version metadata folds');
  researchUI.casePane='facts';const focusedCase=caseResearchCard(example);check(visibleText(focusedCase).includes(reference.quote)&&visibleText(focusedCase).includes('金额与报价')&&visibleText(focusedCase).includes('待补证')&&!visibleText(focusedCase).includes('编辑中文索引'),'case prioritizes original source and material price gap');
  check(walk(focusedCase).filter(node=>node.className==='case-fact').length===2&&!walk(focusedCase).some(node=>node.tagName==='details'),'case facts are a single level without nested fold controls');
  const conciseLesson=learningCard({...lesson,id:'fresh-lesson',progress:{status:'not_started',notes:''}});check(visibleText(conciseLesson).includes('理解对象与关系')&&visibleText(conciseLesson).includes('对象关系清单')&&!visibleText(conciseLesson).includes('SHA-256')&&!visibleText(conciseLesson).includes('保存学习记录'),'learning prioritizes goal and output with records collapsed');
  const scenarioPanel=el('div');renderScenarioResearch(scenarioPanel);check(visibleText(scenarioPanel).includes('真实订单数据')&&visibleText(scenarioPanel).includes('来源缺失停止')&&visibleText(scenarioPanel).includes('人工核对')&&!visibleText(scenarioPanel).includes('当前耗时'),'scenario exposes prerequisites, acceptance and stop condition while implementation steps fold');
  const focusedRun=labRunCard(detailed);check(visibleText(focusedRun).includes('0.0%（0 / 2）')&&!visibleText(focusedRun).includes('labrun-test')&&!visibleText(focusedRun).includes('SHA-256')&&!visibleText(focusedRun).includes('历史 v1')&&focusedRun.textContent.includes('labrun-test'),'trial shows outcomes while retaining technical traceability in closed details');
  const auditPanel=el('div');renderResearchAudit(auditPanel);check(auditPanel.children[0].tagName==='details'&&!auditPanel.children[0].open&&visibleText(auditPanel).includes('研究证据复核'),'source audit collapsed by default');
  researchUI.casePane='analysis';const networkGapCase=caseResearchCard({...example,gaps:['robots blocked','SSL EOF; source remains unavailable']});check(!visibleText(networkGapCase).includes('robots')&&!visibleText(networkGapCase).includes('SSL EOF')&&networkGapCase.textContent.includes('SSL EOF'),'long acquisition diagnostics remain available without dominating case');
  const gapPanels=walk(networkGapCase).filter(node=>node.tagName==='details'&&node.children[0]?.textContent.includes('待补证'));check(gapPanels.length===1&&!gapPanels[0].open&&gapPanels[0].textContent.includes('获取此资料')&&gapPanels[0].textContent.includes('2 项缺口'),'one closed panel combines gaps and actual acquisition controls');researchUI.casePane='facts';
  const casesOnly=el('div');renderCaseResearch(casesOnly);const learningOnly=el('div');renderLearning(learningOnly);check(!casesOnly.textContent.includes('案例原始资料库')&&!learningOnly.textContent.includes('理论原始资料库')&&!scenarioPanel.textContent.includes('其他场景研究笔记'),'research modules do not duplicate next section headings');
  const secondCase={...example,id:'case-2',title:'Second project source title',claims:[{key:'price',label:'金额与报价',value:'中文金额索引',status:'disclosed',evidence:[{...reference,quote:'USD 20 million'}]}],gaps:[]};
  app.data.research.cases=[example,secondCase];location.hash='#case';app.query='';researchUI.caseId=null;researchUI.caseDetail=false;researchUI.caseFilter='';researchUI.casePane='facts';render();
  let workspace=walk($('content')).find(node=>node.className?.includes('case-workspace'));
  check(researchUI.caseId==='case-1'&&!workspace.className.includes('mobile-detail')&&walk(workspace).some(node=>node.className==='research-index')&&walk(workspace).some(node=>node.className==='research-detail'),'initial workspace keeps both desktop panes while narrow view starts at list');
  check(walk(workspace).filter(node=>node.className?.includes('research-index-item')).length===2&&walk(workspace).filter(node=>node.className==='card research-case').length===1,'case list renders all choices and one current detail');
  $('case-choice-case-2').listeners.click();workspace=walk($('content')).find(node=>node.className?.includes('case-workspace'));
  check(researchUI.caseId==='case-2'&&researchUI.caseDetail&&workspace.className.includes('mobile-detail')&&$('case-choice-case-2').attributes['aria-pressed']==='true'&&document.activeElement.id==='case-detail-title','choosing a case enters narrow detail, marks selection and focuses heading');
  control($('content'),'原始资料').listeners.click();check(researchUI.casePane==='sources'&&document.activeElement.id==='case-tab-sources','case tabs switch content and retain focus');
  control($('content'),'返回案例列表').listeners.click();check(researchUI.caseId==='case-2'&&!researchUI.caseDetail&&document.activeElement.id==='case-choice-case-2','back returns to selected case without dropping selection');
  $('case-choice-case-1').listeners.click();check(researchUI.casePane==='facts','new case starts with original project facts');
  const priceFilter=$('case-evidence-filter');priceFilter.value='price';priceFilter.listeners.change();
  check(researchUI.caseFilter==='price'&&researchUI.caseId==='case-2'&&!researchUI.caseDetail&&$('case-evidence-filter').value==='price','filter removing selected case chooses valid result but keeps narrow list open');
  $('case-choice-case-2').listeners.click();control($('content'),'返回案例列表').listeners.click();check(researchUI.caseFilter==='price'&&researchUI.caseId==='case-2','detail back preserves active evidence filter');
  app.query='no matching title';render();check(!researchUI.caseDetail&&$('content').textContent.includes('没有符合此证据条件'),'zero matching cases returns to usable list state');app.query='';researchUI.caseFilter='';
  const keywordCard=caseResearchCard({...example,claims:[{key:'provider',label:'供应方',status:'disclosed',evidence:[{...reference,quote:'Skywise'}]}]});
  check(!walk(keywordCard).some(node=>node.tagName==='blockquote')&&keywordCard.textContent.includes('定位词：Skywise')&&keywordCard.textContent.includes('需结合上下文')&&keywordCard.textContent.includes('来源披露'),'single-word matches retain source status and location but are not presented as informative excerpts');
  control(keywordCard,'定位原文').listeners.click();check(openedReference.quote==='Skywise','short quote still opens exact original context');
  const mixedExcerpt=caseResearchCard({...example,claims:[{key:'scope',label:'合作范围',status:'disclosed',evidence:[{...reference,quote:'Skywise'},reference]}]});check(mixedExcerpt.textContent.includes(reference.quote)&&!mixedExcerpt.textContent.includes('定位词：Skywise'),'meaningful original excerpt replaces a redundant keyword from the same claim');
  const uncertainDate=sourceMaterial({...reference,publishedAt:'2021-10-27T00:00:00Z'});check(uncertainDate.textContent.includes('来源标注 2021-10-27（待核对）')&&!uncertainDate.textContent.includes('10/26')&&!uncertainDate.textContent.includes('发布 '),'extracted publication date remains provisional and preserves raw date without timezone shift');
  const statusCard=caseResearchCard({...example,claims:[{key:'price',label:'金额',status:'unknown',evidence:[]},{key:'scope',label:'范围',status:'conflicting',evidence:[reference]},{key:'delivery',label:'交付',status:'disclosed',evidence:[{...reference,valid:false}]}]});
  const factRows=walk(statusCard).filter(node=>node.className==='case-fact');
  check(!walk(factRows[0]).some(node=>node.className?.includes('warn'))&&walk(factRows[1]).some(node=>node.className?.includes('warn'))&&walk(factRows[2]).some(node=>node.className?.includes('warn')),'unknown is neutral while conflicting and invalid evidence are warning states');
  const factIds=walk(caseResearchCard(example)).filter(node=>node.tagName==='button'&&node.textContent==='定位原文').map(node=>node.id);check(factIds.length>0&&factIds.every(Boolean)&&new Set(factIds).size===factIds.length,'original location controls have stable unique focus targets');
  app.data.research.learning=Array.from({length:8},(_,index)=>({...lesson,id:'unit-'+(index+1),title:'学习单元 '+(index+1),progress:{status:'not_started',notes:''}}));location.hash='#theory';researchUI.lessonId=null;researchUI.lessonDetail=false;render();
  let learningWorkspace=walk($('content')).find(node=>node.className?.includes('learning-workspace'));
  check(walk(learningWorkspace).filter(node=>node.className?.includes('research-index-item')).length===8&&walk(learningWorkspace).filter(node=>node.tagName==='form').length===1&&!learningWorkspace.className.includes('mobile-detail'),'eight-unit directory has only one current form and starts at narrow list');
  $('lesson-choice-unit-1').listeners.click();let draftNotes=$('learning-notes-unit-1'),draftStatus=$('learning-progress-unit-1');draftNotes.value='Unit one unfinished working notes';draftStatus.value='in_progress';draftNotes.listeners.input();
  $('lesson-choice-unit-2').listeners.click();check(researchUI.lessonId==='unit-2'&&$('learning-notes-unit-2').value==='','switching lessons does not leak notes into a different unit');
  $('lesson-choice-unit-1').listeners.click();check($('learning-notes-unit-1').value==='Unit one unfinished working notes'&&$('learning-progress-unit-1').value==='in_progress','returning to a unit restores unsaved notes and selected status');
  control($('content'),'返回学习目录').listeners.click();check(!researchUI.lessonDetail&&researchUI.lessonId==='unit-1'&&document.activeElement.id==='lesson-choice-unit-1','learning back retains selected unit and focus');
  $('lesson-choice-unit-1').listeners.click();app.query='学习单元 8';render();check(researchUI.lessonId==='unit-8'&&!researchUI.lessonDetail,'learning search excluding selection returns to matching directory without forcing narrow detail');app.query='';render();
  $('lesson-choice-unit-1').listeners.click();let releaseSave;api=async()=>new Promise(resolve=>{releaseSave=resolve;});
  let activeForm=walk($('content')).find(node=>node.tagName==='form');draftNotes=$('learning-notes-unit-1');const pendingSave=activeForm.listeners.submit({preventDefault(){}});draftNotes.value='A newer edit while save is pending';draftNotes.listeners.input();releaseSave({status:'saved'});await pendingSave;
  check(researchUI.drafts.get('unit-1').notes==='A newer edit while save is pending'&&activeForm.textContent.includes('新修改尚未保存')&&app.data.research.learning[0].progress.notes==='Unit one unfinished working notes','save completion records submitted values without erasing newer edits');
  api=async()=>({status:'saved'});await activeForm.listeners.submit({preventDefault(){}});check(!researchUI.drafts.has('unit-1')&&app.data.research.learning[0].progress.notes==='A newer edit while save is pending','saving newer draft commits exactly its values');
  draftNotes.value='Saved after switching units';draftNotes.listeners.input();api=async()=>new Promise(resolve=>{releaseSave=resolve;});const switchedSave=activeForm.listeners.submit({preventDefault(){}});$('lesson-choice-unit-2').listeners.click();releaseSave({status:'saved'});await switchedSave;
  check(app.data.research.learning[0].progress.notes==='Saved after switching units'&&researchUI.lessonId==='unit-2','asynchronous progress response updates its own unit after user switches');
  researchUI.lab={running:false,latest:detailed,runs:[detailed],dataset:{questions:8,synthetic:true},arms:['sql_rules','retrieval_dsh','ontology_dsh']};const practiceOrder=el('div');renderPractice(practiceOrder);
  const resultIndex=practiceOrder.children.findIndex(node=>node.className==='card lab-run'),methodIndex=practiceOrder.children.findIndex(node=>node.tagName==='details'&&node.children[0]?.textContent==='试验方法与限制'),dataIndex=practiceOrder.children.findIndex(node=>node.tagName==='details'&&node.children[0]?.textContent.includes('练习题与数据'));
  check(resultIndex>=0&&resultIndex<methodIndex&&resultIndex<dataIndex&&control(practiceOrder,'运行试验'),'existing trial outcome is before method/data while the actual run control remains available');
  console.log('PASS: '+checks+' research UI checks');
})()`;
vm.runInContext(test, sandbox).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

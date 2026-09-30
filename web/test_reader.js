// Independent reader/navigation regression checks. Run: node web/test_reader.js
// No network, browser automation, model execution, or layout claims.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const elements = new Map();
const timers = new Map();
let timerSequence = 0;
const doc = { activeElement: null, hidden: false };
function descendants(node) {
  return [
    node,
    ...node.children.flatMap((child) => (typeof child === "string" ? [] : descendants(child))),
  ];
}
function forget(node) {
  if (typeof node === "string") return;
  node.children.forEach(forget);
  if (node.id && elements.get(node.id) === node) elements.delete(node.id);
  node.parentElement = null;
}
class Element {
  constructor(tag) {
    this.tagName = tag.toLowerCase();
    this.children = [];
    this.listeners = {};
    this.attributes = {};
    this.dataset = {};
    this.style = {};
    this._text = "";
    this.className = "";
    this.value = "";
    this.parentElement = null;
    this.classList = {
      toggle: (name, enabled) => {
        const names = new Set(this.className.split(/\s+/).filter(Boolean));
        if (enabled === undefined ? !names.has(name) : enabled) names.add(name);
        else names.delete(name);
        this.className = [...names].join(" ");
      },
    };
  }
  set id(value) {
    this._id = value;
    elements.set(value, this);
  }
  get id() {
    return this._id;
  }
  set textContent(value) {
    this.children.forEach(forget);
    this.children = [];
    this._text = String(value);
  }
  get textContent() {
    return (
      this._text +
      this.children.map((child) => (typeof child === "string" ? child : child.textContent)).join("")
    );
  }
  set innerHTML(_) {
    throw new Error("Untrusted source must not be parsed as HTML");
  }
  get childElementCount() {
    return this.children.filter((child) => typeof child !== "string").length;
  }
  append(...children) {
    children.forEach((child) => {
      this.children.push(child);
      if (typeof child !== "string") child.parentElement = this;
    });
  }
  prepend(...children) {
    children.reverse().forEach((child) => {
      this.children.unshift(child);
      if (typeof child !== "string") child.parentElement = this;
    });
  }
  add(child) {
    this.append(child);
    if (this.tagName === "select" && this.children.length === 1) this.value = child.value;
  }
  replaceChildren(...children) {
    this.children.forEach(forget);
    this.children = [];
    this._text = "";
    this.append(...children);
  }
  setAttribute(key, value) {
    this.attributes[key] = String(value);
  }
  getAttribute(key) {
    return this.attributes[key];
  }
  removeAttribute(key) {
    delete this.attributes[key];
  }
  addEventListener(type, callback) {
    (this.listeners[type] ||= []).push(callback);
  }
  async emit(type, event = {}) {
    event.target ||= this;
    event.preventDefault ||= () => {};
    for (const listener of this.listeners[type] || []) await listener(event);
    if (["input", "change"].includes(type) && this.parentElement)
      await this.parentElement.emit(type, event);
  }
  matches(selector) {
    return selector.startsWith(".")
      ? this.className.split(/\s+/).includes(selector.slice(1))
      : this.tagName === selector.toLowerCase();
  }
  closest(selector) {
    for (let node = this; node; node = node.parentElement) if (node.matches(selector)) return node;
    return null;
  }
  contains(target) {
    return descendants(this).includes(target);
  }
  querySelectorAll(selector) {
    return descendants(this)
      .slice(1)
      .filter((node) => node.matches(selector));
  }
  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }
  focus() {
    doc.activeElement = this;
  }
  blur() {
    if (doc.activeElement === this) doc.activeElement = null;
  }
  setSelectionRange(start, end) {
    this.selectionStart = start;
    this.selectionEnd = end;
  }
  showModal() {
    this.open = true;
    this.focus();
  }
  close() {
    this.open = false;
    for (const callback of this.listeners.close || []) callback({ target: this });
  }
  scrollIntoView(options) {
    this.scrolledIntoView = options;
  }
  reset() {
    descendants(this).forEach((node) => {
      if (["input", "textarea"].includes(node.tagName)) node.value = "";
    });
  }
}
for (const [, id] of fs
  .readFileSync(path.join(__dirname, "index.html"), "utf8")
  .matchAll(/id="([^"]+)"/g)) {
  const node = new Element(id.endsWith("dialog") ? "dialog" : "div");
  node.id = id;
}
Object.assign(doc, {
  getElementById: (id) => elements.get(id) || null,
  createElement: (tag) => new Element(tag),
  querySelectorAll: () => [],
  addEventListener() {},
});
const windowObject = {
  scrollY: 0,
  addEventListener() {},
  scrollTo(value) {
    this.scrollY = value.top;
  },
};
const sandbox = {
  assert,
  console,
  URL,
  document: doc,
  window: windowObject,
  location: { hash: "#intelligence" },
  setTimeout(callback, delay) {
    const id = ++timerSequence;
    timers.set(id, { callback, delay });
    return id;
  },
  clearTimeout(id) {
    timers.delete(id);
  },
  Option: function (label, value) {
    const node = new Element("option");
    node.textContent = label;
    node.value = value;
    return node;
  },
  fetch() {
    throw new Error("Unexpected network request");
  },
};
vm.createContext(sandbox);
require("./test_support/load_ui.cjs").loadUi(sandbox, __dirname);

const suite = String.raw`
(async () => {
  const checks = []; const failures = [];
  async function test(name, run) { try { await run(); checks.push(name); } catch(error) { failures.push({name, message:error.message}); } }
  const walk = node => [node,...node.children.flatMap(child => typeof child==='string'?[]:walk(child))];
  const field = (node,label) => walk(node).find(child=>child.attributes['aria-label']===label);
  const control = (node,label) => walk(node).find(child=>child.tagName==='button'&&child.textContent===label);
  const data = {documents:[],notes:[],records:[],sources:[],jobs:[],runs:[],githubResources:{resources:[]},research:{cases:[],learning:[],scenarios:[],repoGuides:[],audit:{},changes:[]}};
  app.data=data;
  const quote='边界 🧪 <script>alert(1)</script> exact';
  const source={id:'doc-a',sha256:'hash-a',title:'原始文档 A',url:'https://example.com/a',content:'开始\n'+quote+'\n中间\n'+quote+'\n结束',quality:'evidence_text',access:'body_fetched_not_semantically_verified'};
  const ref={documentId:source.id,sha256:source.sha256,quote,valid:true};
  const openSaved=async(reference=ref,doc=source)=>{api=async()=>doc;await openEvidence(reference);};

  await test('exact duplicate excerpts remain plain text and keep the complete original',async()=>{
    await openSaved();
    assert.equal($('document-content').textContent,source.content);
    assert.equal($('evidence-highlight').textContent,quote);
    assert.equal(walk($('document-content')).filter(node=>node.tagName==='script').length,0);
    assert.match($('evidence-locator').textContent,/1 \/ 2/);
    await control($('evidence-locator'),'下一处').emit('click');
    assert.match($('evidence-locator').textContent,/2 \/ 2/);
    assert.equal($('document-content').textContent,source.content);
  });
  await test('hash mismatch, invalid citation and absent quote never produce a highlight',async()=>{
    for(const reference of [{...ref,sha256:'old-hash'},{...ref,valid:false},{...ref,quote:'not in this version'}]) {
      await openSaved(reference);
      assert.equal($('document-content').textContent,source.content);
      assert.equal(walk($('document-content')).filter(node=>node.tagName==='mark').length,0);
      assert.match($('evidence-locator').textContent,/未定位|尚未匹配/);
    }
  });
  await test('quote matching has a bounded occurrence count without truncating source',async()=>{
    const long={...source,content:'x'.repeat(500)};
    await openSaved({...ref,quote:'x'},long);
    assert.equal($('document-content').textContent,long.content);
    assert.match($('evidence-locator').textContent,/200/);
  });
  await test('older document response cannot overwrite a later selected evidence version',async()=>{
    let finishA,finishB;
    api=path=>new Promise(resolve=>{if(path.includes('doc-a'))finishA=resolve;else finishB=resolve;});
    const pendingA=openEvidence(ref);
    const b={...source,id:'doc-b',sha256:'hash-b',title:'文档 B',content:'B exact quote'};
    const pendingB=openEvidence({documentId:'doc-b',sha256:'hash-b',quote:'exact',valid:true});
    finishB(b);await pendingB;finishA(source);await pendingA;
    assert.equal(reader.document.id,'doc-b');
    assert.equal($('document-content').textContent,b.content);
    assert.equal($('evidence-highlight').textContent,'exact');
  });
  await test('closing a pending reader prevents late response from reopening or binding it',async()=>{
    let finish;api=()=>new Promise(resolve=>{finish=resolve;});
    const pending=openEvidence(ref);closeDocument();$('document-dialog').close();finish(source);await pending;
    assert.equal(reader.document,null);assert.equal(app.selectedDocument,null);assert.equal($('document-dialog').open,false);
  });
  await test('a stale reading task cannot replace the original tab and partial status remains explicit',async()=>{
    await openSaved();let finish;api=()=>new Promise(resolve=>{finish=resolve;});
    const pending=setReadingMode('translate');await setReadingMode('original');
    finish({id:'reading-old',documentId:source.id,sha256:source.sha256,mode:'translate',status:'RUNNING',content:'old translation'});await pending;
    assert.equal(reader.mode,'original');assert.equal($('document-content').textContent,source.content);
    reader.mode='translate';reader.task={id:'reading-partial',documentId:source.id,sha256:source.sha256,mode:'translate',status:'FAILED',content:'已完成一段',completedChunks:1,totalChunks:3,processedChars:100,totalChars:500,error:'network failure'};renderReading();
    assert.equal($('reading-status').hidden,false);assert.match($('reading-status').textContent,/400 字符.*未处理/);
    assert.match($('document-content').textContent,/已完成一段/);
  });
  await test('business form drafts survive losing focus and rebuilding on another view',async()=>{
    closeDocument();$('document-dialog').close();document.activeElement=null;
    const forms=[['source',sourceForm,'信源 URL','https://example.com/evidence'],['collect',collectForm,'待获取的 URL，每行一个','https://example.com/one\nhttps://example.com/two'],['analyze',analyzeForm,'研究任务','未提交的研究计划与范围']];
    for(const [key,create,label,value] of forms) {
      const first=create();field(first,label).value=value;await field(first,label).emit('input');
      assert.equal(app.formDrafts.get(key)[0],value);
      location.hash='#intelligence';render();location.hash='#sources';render();
      const rebuilt=create();assert.equal(field(rebuilt,label).value,value);
    }
  });
  await test('view navigation restores filters, page and scroll independently',async()=>{
    document.activeElement=null;const realRender=render;render=()=>{app.view=location.hash.slice(1);};
    try {
      app.view='intelligence';location.hash='#intelligence';app.query='ontology';app.host='example.com';app.track='theory';app.page=2;app.matchedIds=new Set(['doc-a']);app.searchQuery='ontology';window.scrollY=640;
      location.hash='#opensource';navigateView();assert.equal(app.query,'');githubFilters.category='governance';app.query='quality';app.page=3;window.scrollY=210;
      location.hash='#intelligence';navigateView();assert.equal(app.query,'ontology');assert.equal(app.host,'example.com');assert.equal(app.track,'theory');assert.equal(app.page,2);assert.equal(window.scrollY,640);assert.ok(app.matchedIds.has('doc-a'));
      location.hash='#opensource';navigateView();assert.equal(githubFilters.category,'governance');assert.equal(app.query,'quality');assert.equal(app.page,3);assert.equal(window.scrollY,210);
    } finally {render=realRender;}
  });
  await test('explicit navigation is allowed while an old-view form retains keyboard focus',async()=>{
    app.query='';app.host='';app.track='';app.page=1;app.view='tasks';location.hash='#tasks';document.activeElement=null;render();
    const textarea=field($('content'),'研究任务');assert.ok(textarea);textarea.value='在页面返回之前留下的草稿';await textarea.emit('input');textarea.focus();
    location.hash='#sources';navigateView();
    assert.ok(field($('content'),'信源 URL'),'explicit navigation must replace old task content with sources');
    assert.equal(app.formDrafts.get('analyze')[0],'在页面返回之前留下的草稿');
  });
  await test('closing a reader restores the rebuilt list trigger after background rendering',async()=>{
    document.activeElement=null;app.data={...data,documents:[source]};app.query='';app.host='';app.track='';app.page=1;location.hash='#intelligence';render();
    const before=$('read-'+source.id);assert.ok(before,'document read trigger has stable identity');before.focus();api=async()=>source;
    await before.emit('click');assert.equal(reader.returnFocusId,before.id);
    render();const rebuilt=$('read-'+source.id);assert.notEqual(rebuilt,before);
    $('document-dialog').close();assert.equal(document.activeElement,rebuilt);
  });
  await test('failed business form submission keeps its draft while confirmed success clears it',async()=>{
    const card=analyzeForm();const form=walk(card).find(node=>node.tagName==='form');const input=field(card,'研究任务');
    input.value='需要保留的未成功提交研究任务';await input.emit('input');
    api=async()=>{throw Error('NETWORK_FAILURE');};await form.emit('submit');
    assert.equal(app.formDrafts.get('analyze')[0],input.value);
    const savedRefresh=refresh;refresh=async()=>{};api=async()=>({id:'accepted-task'});
    try {await form.emit('submit');assert.equal(app.formDrafts.has('analyze'),false);} finally {refresh=savedRefresh;}
  });
  console.log(JSON.stringify({passed:checks.length,checks,failures},null,2));
  assert.equal(failures.length,0,failures.map(row=>row.name+': '+row.message).join('\n'));
})()
`;
vm.runInContext(suite, sandbox).catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});

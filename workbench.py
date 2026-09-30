"""Local, same-origin workbench. DSH continues to own the reasoning loop."""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import json
import secrets
import subprocess
import sys
import threading
import uuid

ROOT = Path(__file__).resolve().parent
WEB_SCRIPTS = tuple(json.loads((ROOT / 'web' / 'assets.json').read_text(encoding='utf-8')))
WEB_ASSETS = {'index.html': 'text/html', 'style.css': 'text/css',
              **dict.fromkeys(WEB_SCRIPTS, 'application/javascript')}
if any('/' in name or '\\' in name or not name.endswith('.js') for name in WEB_SCRIPTS):
    raise ValueError('INVALID_WEB_ASSET_MANIFEST')


class Workbench:
    def __init__(self, store, config):
        from pipeline import Pipeline
        from reading import ReadingService
        from github_resources import GitHubResources
        from research import ResearchService
        from lab import LabService
        self.store, self.config = store, config
        self.pipeline = Pipeline(store)
        self.reading = ReadingService(store, config)
        self.github = GitHubResources(store)
        self.research = ResearchService(store)
        self.lab = LabService(store, config)
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.active = {}

    def state(self):
        from agent import utc
        with self.store.db() as db:
            records = [dict(r) for r in db.execute('SELECT * FROM records ORDER BY id')]
            notes = [dict(r) for r in db.execute("SELECT * FROM notes WHERE status IN ('pending_review','accepted','rejected') ORDER BY createdAt DESC")]
            documents = [dict(r) for r in db.execute('SELECT id,url,title,sha256,access,retrievedAt,length(content) chars FROM documents ORDER BY retrievedAt DESC')]
            runs = [dict(r) for r in db.execute('SELECT * FROM runs ORDER BY startedAt DESC LIMIT 30')]
        for row in records + notes:
            row['payload'] = json.loads(row['payload'])
        for row in runs:
            row['result'] = json.loads(row['result']) if row['result'] else None
        from catalog import catalog, measured_coverage
        documents=catalog(self.store,documents)
        with self.lock:
            tasks = [dict(v) for v in self.active.values()]
        return dict(generatedAt=utc(), records=records, notes=notes, documents=documents,
            sources=self.pipeline.sources(), jobs=self.pipeline.jobs(), runs=runs, readings=self.reading.list_tasks(), githubResources=self.github.state(), research=self.research.state(),
            coverage=measured_coverage(self.pipeline,documents), legacyCoverage=self.store.library('coverage'), tasks=tasks,
            capabilities={'html':True,'pdf':True,'rss':True,'captions':'公开字幕文件；音视频不自动转写',
                'schedule':'Codex每日09:00 America/New_York；设备和应用须运行',
                'independentlyVerifiedProjects':0,'fullWebExhausted':False})

    def document(self, id):
        with self.store.db() as db:
            row=db.execute('SELECT * FROM documents WHERE id=?',(id,)).fetchone()
            if not row: raise ValueError('DOCUMENT_NOT_FOUND')
            document=dict(row)
        from catalog import catalog
        document['chars']=len(document['content'])
        return catalog(self.store,[document])[0]

    def reading_result(self, document_id, mode):
        return self.reading.get(document_id, mode)

    def lab_artifact(self, run_id, name, item=None):
        import re
        if not isinstance(run_id, str) or not re.fullmatch(r'labrun-[0-9a-f]{32}', run_id):
            raise ValueError('INVALID_LAB_RUN')
        allowed = {'pilotPack': ('试点准备包.md', 'text/markdown'), 'receipt': ('receipt.json', 'application/json'),
                   'data': ('data.json', 'application/json'), 'questions': ('questions-and-gold.json', 'application/json')}
        if name=='input':
            if not isinstance(item,str) or not re.fullmatch(r'(sql_rules|retrieval_dsh|ontology_dsh)-Q[1-8]',item):
                raise ValueError('INVALID_LAB_INPUT')
            allowed['input']=('inputs/'+item+'.json','application/json')
        if name not in allowed:
            raise ValueError('UNKNOWN_LAB_ARTIFACT')
        filename, mime = allowed[name]
        directory = (self.store.directory / 'lab').resolve()
        path = (directory / run_id / filename).resolve()
        if not path.is_relative_to(directory) or not path.is_file():
            raise ValueError('LAB_ARTIFACT_NOT_FOUND')
        if path.stat().st_size > 5 * 1024 * 1024:
            raise ValueError('LAB_ARTIFACT_TOO_LARGE')
        return {'name': filename, 'mimeType': mime, 'text': path.read_text(encoding='utf-8')}

    def search(self, query):
        if len(query)>500: raise ValueError('QUERY_TOO_LONG')
        # Escaping keeps literal %/_ searches from becoming wildcard scans.
        pattern='%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        with self.store.db() as db:
            ids=[r['id'] for r in db.execute("SELECT id FROM documents WHERE content LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\'",(pattern,pattern))]
        return {'ids':ids,'query':query}

    def collect(self, data):
        urls=data.get('urls')
        if urls is not None and (not isinstance(urls,list) or len(urls)>500 or any(not isinstance(u,str) for u in urls)):
            raise ValueError('INVALID_URLS')
        job=self.pipeline.enqueue(urls=urls,force=bool(data.get('force',False)),limit=200,reason='workbench')
        def work():
            import time
            while True:
                try:
                    self.pipeline.run_job(job['id'])
                    break
                except RuntimeError as exc:
                    if str(exc)!='PIPELINE_BUSY': raise
                    if self.pipeline.get_job(job['id'])['cancelRequested']: break
                    time.sleep(2)
            self.store.export()
        threading.Thread(target=work,daemon=True).start()
        return job

    def analyze(self,data):
        task=data.get('task','')
        if not isinstance(task,str) or not task.strip() or len(task)>6000: raise ValueError('INVALID_TASK')
        from agent import utc
        with self.lock:
            if any(x['status']=='RUNNING' for x in self.active.values()): raise ValueError('ANALYSIS_ALREADY_RUNNING')
            id='analysis-'+uuid.uuid4().hex
            self.active[id]={'id':id,'status':'RUNNING','task':task,'createdAt':utc()}
        directory=self.store.directory/'jobs';directory.mkdir(exist_ok=True)
        logfile=directory/(id+'.log')
        def work():
            code=1
            try:
                configfile=directory/(id+'.config.json')
                # Config only contains a credential reference, never the secret.
                configfile.write_text(json.dumps(self.config,ensure_ascii=False),encoding='utf-8')
                with logfile.open('w',encoding='utf-8') as out:
                    process=subprocess.Popen([sys.executable,str(ROOT/'agent.py'),'--config',str(configfile),'--data',str(self.store.directory),'run','--task',task],
                        cwd=ROOT,stdout=out,stderr=out,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    with self.lock: self.active[id]['pid']=process.pid
                    code=process.wait()
            finally:
                with self.lock:
                    self.active[id].update(status='SUCCEEDED' if code==0 else 'FAILED',completedAt=utc())
        threading.Thread(target=work,daemon=True).start()
        return self.active[id]

    def refresh_github(self):
        from agent import utc
        if self.github.state().get('running'):
            raise ValueError('GITHUB_REFRESH_ALREADY_RUNNING')
        with self.lock:
            if any(x.get('kind')=='github' and x['status']=='RUNNING' for x in self.active.values()):
                raise ValueError('GITHUB_REFRESH_ALREADY_RUNNING')
            id='github-refresh-'+uuid.uuid4().hex
            self.active[id]={'id':id,'kind':'github','status':'RUNNING','createdAt':utc()}
        def work():
            try:
                result=self.github.refresh(force=True)
                with self.lock:
                    outcome=result.get('status','COMPLETED')
                    self.active[id].update(status='ALREADY_RUNNING' if outcome=='RUNNING' else outcome,result=result,completedAt=utc())
            except Exception as exc:
                with self.lock:
                    self.active[id].update(status='FAILED',error=type(exc).__name__,completedAt=utc())
        threading.Thread(target=work,daemon=True).start()
        with self.lock:
            return dict(self.active[id])

    def post(self,path,data):
        if path=='/api/plugin/reading':
            from plugin_api import PluginAPI
            return PluginAPI(self).start_reading(data)
        if path=='/api/research/progress': return self.research.progress(data)
        if path=='/api/lab/run': return self.lab.start()
        if path=='/api/github/refresh': return self.refresh_github()
        if path=='/api/reading': return self.reading.start(data.get('documentId'),data.get('mode'))
        if path=='/api/reading/cancel': return self.reading.cancel(data.get('id'))
        if path=='/api/collect': return self.collect(data)
        if path=='/api/analyze': return self.analyze(data)
        if path=='/api/source': return self.pipeline.update_source(data)
        if path=='/api/review':
            result=self.pipeline.review(data['id'],data['status']); self.store.export(); return result
        if path=='/api/cancel': return self.pipeline.cancel_job(data['id'])
        raise ValueError('UNKNOWN_OPERATION')


def serve(store,config,port=8765):
    app=Workbench(store,config)
    app.pipeline.seed()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def valid_origin(self):
            allowed={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
            if self.headers.get('Host') not in allowed: return False
            origin=self.headers.get('Origin')
            if origin and origin not in {'http://'+h for h in allowed}: return False
            return True
        def respond(self,value,status=200,content_type='application/json; charset=utf-8'):
            raw=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers(); self.wfile.write(raw)
        def do_GET(self):
            if not self.valid_origin(): self.respond({'error':'INVALID_ORIGIN'},403); return
            path=urlsplit(self.path).path
            try:
                if path=='/api/session': self.respond({'token':app.token})
                elif path.startswith('/api/plugin/'):
                    from plugin_api import PluginAPI
                    self.respond(PluginAPI(app).dispatch(path,{k:v[0] for k,v in parse_qs(urlsplit(self.path).query).items()}))
                elif path=='/api/state': self.respond(app.state())
                elif path=='/api/github': self.respond(app.github.state())
                elif path=='/api/research': self.respond(app.research.state())
                elif path=='/api/lab': self.respond(app.lab.state())
                elif path=='/api/lab/artifact':
                    query=parse_qs(urlsplit(self.path).query)
                    self.respond(app.lab_artifact(query.get('runId',[''])[0],query.get('name',[''])[0],query.get('item',[None])[0]))
                elif path=='/api/document': self.respond(app.document(parse_qs(urlsplit(self.path).query).get('id',[''])[0]))
                elif path=='/api/search': self.respond(app.search(parse_qs(urlsplit(self.path).query).get('q',[''])[0]))
                elif path=='/api/reading':
                    query=parse_qs(urlsplit(self.path).query)
                    self.respond(app.reading_result(query.get('documentId',[''])[0],query.get('mode',[''])[0]))
                elif path == '/' or path[1:] in WEB_ASSETS:
                    name='index.html' if path=='/' else path[1:]
                    kind=WEB_ASSETS[name]
                    self.respond((ROOT/'web'/name).read_bytes(),content_type=kind+'; charset=utf-8')
                else: self.respond({'error':'NOT_FOUND'},404)
            except ValueError as exc: self.respond({'error':str(exc)},400)
        def do_POST(self):
            if not self.valid_origin() or not secrets.compare_digest(self.headers.get('X-Radar-Token',''),app.token):
                self.respond({'error':'FORBIDDEN'},403); return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=100000: raise ValueError('INVALID_BODY')
                data=json.loads(self.rfile.read(length))
                if not isinstance(data,dict): raise ValueError('INVALID_BODY')
                self.respond(app.post(urlsplit(self.path).path,data))
            except (ValueError,KeyError,TypeError) as exc: self.respond({'error':str(exc)},400)
            except Exception: self.respond({'error':'INTERNAL_ERROR'},500)
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print(f'FDE Radar: http://127.0.0.1:{server.server_port}',flush=True)
    try: server.serve_forever()
    finally: server.server_close()

"""Offline GraphRAG: authoritative ACL store, provenance graph and bounded agent."""
from __future__ import annotations
import hashlib
import json
import math
import os
import re
import sqlite3
import threading
import time
import unicodedata
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, Protocol
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from langgraph.graph import StateGraph, START, END
from opentelemetry import trace
from backend.budget import TokenBudget, messages_for
from backend.grounding import semantic_chunks, verified_span, resolve_model_evidence
from backend.telemetry import stage_latency

tracer = trace.get_tracer("knowledge-platform")
INJECTION = re.compile(r"ignore\s+(all\s+)?(previous|prior)|игнорир\w*.{0,40}инструкц|system\s*prompt|системн\w*\s+промпт|<script|drop\s+table", re.I)
PII = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\w)(?:\+7|8)[\s()-]*\d{3}[\s()-]*\d{3}[\s()-]*\d{2}[\s()-]*\d{2}(?!\w)")
ENTITY = re.compile(r"\b(?:[A-Za-zА-Яа-яЁё]{1,12}-\d{1,6}|[А-ЯA-Z]{2,8}\d{1,6})\b")
STOP = set("как какой какие где когда почему для или что это его она они через между связь связан связано связаны к с и в на по а из у от ли он".split())

def clean(text: str) -> str:
    return PII.sub("[PII]", unicodedata.normalize("NFKC", text))

def terms(text: str) -> set[str]:
    return set(re.findall(r"[\w-]+", text.casefold())) - STOP

def embedding(text: str, dimensions: int = 256) -> list[float]:
    # ponytail: hashed lexical vectors are offline fixtures, use local semantic embedder for synonyms.
    vector = [0.0] * dimensions
    for token in terms(text):
        digest = hashlib.sha256(token.encode()).digest()
        vector[int.from_bytes(digest[:4], "little") % dimensions] += 1 if digest[4] % 2 else -1
    norm = math.sqrt(sum(v*v for v in vector)) or 1
    return [v/norm for v in vector]

@dataclass(frozen=True)
class Principal:
    user: str
    tenant: str
    roles: tuple[str, ...]
    identity_path: str = ''
    token_digest: str = ''

    def refresh(self):
        if not self.identity_path:
            return self
        identities = json.loads(Path(self.identity_path).read_text(encoding='utf-8'))
        for identity in identities:
            digest = hashlib.sha256(identity['token'].encode()).hexdigest()
            if digest == self.token_digest:
                if (identity['user'], identity['tenant'], tuple(identity['roles'])) == (self.user, self.tenant, self.roles):
                    return self
                break
        raise PermissionError('Identity authorization changed')

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,tenant TEXT NOT NULL,title TEXT NOT NULL,hash TEXT NOT NULL,version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS grants(doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,role TEXT NOT NULL,PRIMARY KEY(doc_id,role));
CREATE TABLE IF NOT EXISTS chunks(id TEXT PRIMARY KEY,doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,page INTEGER NOT NULL,text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mentions(chunk_id TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,entity TEXT NOT NULL,PRIMARY KEY(chunk_id,entity));
CREATE TABLE IF NOT EXISTS edges(chunk_id TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,src TEXT NOT NULL,dst TEXT NOT NULL,relation TEXT NOT NULL,PRIMARY KEY(chunk_id,src,dst));
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,user TEXT NOT NULL,tenant TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY,session_id TEXT NOT NULL REFERENCES sessions(id),question TEXT NOT NULL,chunk_ids TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,request_id TEXT NOT NULL,user_ref TEXT NOT NULL,status TEXT NOT NULL,chunk_ids TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS security_epoch(id INTEGER PRIMARY KEY CHECK(id=1),value INTEGER NOT NULL);
INSERT OR IGNORE INTO security_epoch VALUES(1,0);
CREATE TABLE IF NOT EXISTS index_releases(version TEXT PRIMARY KEY,collection TEXT NOT NULL,corpus_hash TEXT NOT NULL,dimensions INTEGER NOT NULL,chunk_count INTEGER NOT NULL,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS service_state(name TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_chain(audit_id INTEGER PRIMARY KEY REFERENCES audit(id),prev_hash TEXT NOT NULL,event_hash TEXT NOT NULL,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS history_time(history_id INTEGER PRIMARY KEY REFERENCES history(id) ON DELETE CASCADE,created_at REAL NOT NULL);
"""

class Store:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript(SCHEMA)
            for table in ('documents', 'grants', 'chunks', 'mentions', 'edges'):
                for operation in ('INSERT', 'UPDATE', 'DELETE'):
                    db.execute(f'CREATE TRIGGER IF NOT EXISTS epoch_{table}_{operation} AFTER {operation} ON {table} BEGIN UPDATE security_epoch SET value=value+1 WHERE id=1; END')
            db.execute("PRAGMA journal_mode=WAL")

    @contextmanager
    def connect(self):
        # ponytail: one writer lock per process; PostgreSQL for multiple backend replicas.
        with self.lock:
            db=sqlite3.connect(self.path, timeout=10)
            db.row_factory=sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            try:
                with db: yield db
            finally: db.close()

    @contextmanager
    def request_scope(self):
        """Keep WAL attached during one request, without retaining a snapshot.

        Short-lived connections otherwise repeatedly become the last SQLite
        client and checkpoint/remove WAL on close (costly on a bind mount).
        This idle connection uses autocommit and fully consumes its sole read.
        Authorization still uses fresh, separate transactions in connect(); no
        process lock or SQL transaction is held across inference/network work.
        The handle is always closed, including failed/cancelled worker calls.
        """
        keeper = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            keeper.execute('SELECT value FROM security_epoch WHERE id=1').fetchall()
            yield
        finally:
            keeper.close()

    def ingest(self, title: str, pages: list[str], tenant: str, roles: list[str]) -> str:
        if not roles or not tenant or not pages or not any(t.strip() for t in pages):
            raise ValueError("Nonempty content, tenant and ACL are required")
        if any(INJECTION.search(unicodedata.normalize('NFKC', t)) for t in pages):
            raise ValueError("Document quarantined: suspicious instructions")
        title=clean(title)
        doc_id=hashlib.sha256((tenant+"\0"+title).encode()).hexdigest()[:24]
        digest=hashlib.sha256("\n".join(pages).encode()).hexdigest()
        with self.connect() as db:
            prior=db.execute("SELECT version,hash FROM documents WHERE id=?",(doc_id,)).fetchone()
            if prior and prior['hash']==digest and {r[0] for r in db.execute('SELECT role FROM grants WHERE doc_id=?',(doc_id,))}==set(roles):
                return doc_id
            version=prior[0]+1 if prior else 1
            db.execute("DELETE FROM documents WHERE id=?",(doc_id,))
            db.execute("INSERT INTO documents VALUES(?,?,?,?,?)",(doc_id,tenant,title,digest,version))
            db.executemany("INSERT INTO grants VALUES(?,?)",[(doc_id,r) for r in sorted(set(roles))])
            for page_no,text in enumerate(pages,1):
                text=clean(text)
                for offset, part in semantic_chunks(text):
                    if not part: continue
                    cid=hashlib.sha256(f"{doc_id}:{version}:{page_no}:{offset}".encode()).hexdigest()[:24]
                    db.execute("INSERT INTO chunks VALUES(?,?,?,?)",(cid,doc_id,page_no,part))
                    entities=sorted(set(ENTITY.findall(part)))
                    db.executemany("INSERT INTO mentions VALUES(?,?)",[(cid,e) for e in entities])
                    # Co-mentions are provenance links, never asserted as a typed physical relation.
                    db.executemany("INSERT INTO edges VALUES(?,?,?,?)",[(cid,a,b,"CO_MENTION") for i,a in enumerate(entities) for b in entities[i+1:]])
        return doc_id

    def allowed(self, principal: Principal) -> list[dict]:
        with self.connect() as db:
            return self._allowed(db, principal)

    @staticmethod
    def _allowed(db, principal: Principal) -> list[dict]:
        if not principal.roles: return []
        slots=','.join('?' for _ in principal.roles)
        return [dict(row) for row in db.execute(f"""SELECT DISTINCT c.*,d.title,d.version,d.tenant FROM chunks c
            JOIN documents d ON c.doc_id=d.id JOIN grants g ON g.doc_id=d.id
            WHERE d.tenant=? AND g.role IN ({slots}) ORDER BY c.id""",(principal.tenant,*principal.roles))]

    def finalize(self, principal: Principal, query: str, sid: str, rid: str, state: dict) -> dict:
        """Release boundary: serialize one authorized snapshot before commit.

        BEGIN IMMEDIATE serializes concurrent SQL administrators with release.
        No network/model call runs under this lock. A writer committing before
        this transaction is observed; a later writer cannot revoke bytes already
        authorized for release. SSE uses this same complete immutable result.
        """
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            principal.refresh()
            owner = db.execute('SELECT user,tenant FROM sessions WHERE id=?', (sid,)).fetchone()
            if owner and tuple(owner) != (principal.user, principal.tenant):
                raise PermissionError('Session belongs to another principal')
            allowed = {c['id']: c for c in self._allowed(db, principal)}
            context = {c['id']: c for c in state.get('chunks', [])}
            def unchanged(cid):
                return cid in allowed and cid in context and all(allowed[cid][k] == context[cid][k] for k in ('version', 'text', 'tenant', 'title', 'page'))
            evidence = state.get('evidence', [])
            status = state['status']
            if any(not unchanged(e['chunk_id']) or e['quote'] not in allowed[e['chunk_id']]['text'] for e in evidence):
                evidence, status = [], 'output_blocked'
            edges = [dict(r) for r in db.execute('SELECT * FROM edges ORDER BY chunk_id,src,dst')]
            graph = [e for e in edges if unchanged(e['chunk_id']) and e in state.get('edges', [])] if evidence else []
            ids = [e['chunk_id'] for e in evidence]
            if status == 'answered':
                db.execute('INSERT OR IGNORE INTO sessions VALUES(?,?,?)', (sid, principal.user, principal.tenant))
                entry=db.execute('INSERT INTO history(session_id,question,chunk_ids) VALUES(?,?,?)', (sid, clean(query), json.dumps(ids)))
                db.execute('INSERT INTO history_time VALUES(?,?)',(entry.lastrowid,time.time()))
            self._append_audit(db,principal,rid,status,ids)
            epoch = db.execute('SELECT value FROM security_epoch WHERE id=1').fetchone()[0]
            result = {'request_id':rid,'session_id':sid,'status':status,'evidence':evidence,'graph':graph,
                      'authorization_epoch':epoch, 'usage':state.get('usage',{'mode':'extractive','input_tokens':0,'output_tokens':0}),
                      'stages':state.get('stages',[])}
            # Freeze all nested values at the release boundary, before SQL commit.
            return json.loads(json.dumps(result, ensure_ascii=False))

    def graph(self, principal: Principal, seeds: list[str], hops: int = 2,
              max_chunks: int = 32, max_entities: int = 128) -> tuple[list[dict],list[dict]]:
        with self.connect() as db:
            db.execute('BEGIN')
            allowed={c['id']:c for c in self._allowed(db,principal)}
            rows=[dict(r) for r in db.execute('SELECT * FROM edges ORDER BY chunk_id,src,dst') if r['chunk_id'] in allowed]
            mentions=[dict(r) for r in db.execute('SELECT * FROM mentions ORDER BY entity,chunk_id') if r['chunk_id'] in allowed]
        max_chunks=max(1,min(max_chunks,128));max_entities=max(1,min(max_entities,512))
        selected=set(sorted(set(seeds)&allowed.keys())[:max_chunks])
        frontier=set(sorted({r['entity'] for r in mentions if r['chunk_id'] in selected})[:max_entities])
        visited=set(frontier)
        for _ in range(max(0,min(hops,2))):
            neighbors=sorted({r['chunk_id'] for r in mentions if r['entity'] in frontier}-selected)
            selected.update(neighbors[:max_chunks-len(selected)])
            discovered={r['entity'] for r in mentions if r['chunk_id'] in selected}-visited
            frontier=set(sorted(discovered)[:max_entities-len(visited)])
            visited.update(frontier)
            if not frontier: break
        edges=[r for r in rows if r['chunk_id'] in selected and r['src'] in visited and r['dst'] in visited]
        return [allowed[cid] for cid in sorted(selected)],edges

    def remember(self, principal: Principal, sid: str, question: str, chunk_ids: list[str]) -> None:
        with self.connect() as db:
            prior=db.execute("SELECT user,tenant FROM sessions WHERE id=?",(sid,)).fetchone()
            if prior and tuple(prior)!=(principal.user,principal.tenant): raise PermissionError("Session belongs to another principal")
            db.execute("INSERT OR IGNORE INTO sessions VALUES(?,?,?)",(sid,principal.user,principal.tenant))
            db.execute("INSERT INTO history(session_id,question,chunk_ids) VALUES(?,?,?)",(sid,clean(question),json.dumps(chunk_ids)))

    def memory(self, principal: Principal, sid: str) -> list[str]:
        with self.connect() as db:
            prior=db.execute("SELECT user,tenant FROM sessions WHERE id=?",(sid,)).fetchone()
            if prior and tuple(prior)!=(principal.user,principal.tenant): raise PermissionError("Session belongs to another principal")
            rows=list(db.execute("SELECT chunk_ids FROM history WHERE session_id=? ORDER BY id DESC LIMIT 3",(sid,)))
        allowed={c['id'] for c in self.allowed(principal)}
        return sorted({cid for r in rows for cid in json.loads(r[0]) if cid in allowed})

    def public_view(self, principal: Principal, sid: str | None = None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            principal.refresh()
            allowed={c['id']:c for c in self._allowed(db,principal)}
            if sid is None:
                chunks=[{'id':c['id'],'title':c['title'],'page':c['page']} for c in allowed.values()]
                edges=[dict(r) for r in db.execute('SELECT * FROM edges ORDER BY chunk_id,src,dst') if r['chunk_id'] in allowed]
                result={'chunks':chunks,'edges':edges}
            else:
                owner=db.execute('SELECT user,tenant FROM sessions WHERE id=?',(sid,)).fetchone()
                if owner and tuple(owner)!=(principal.user,principal.tenant):
                    raise PermissionError('Session belongs to another principal')
                history=list(db.execute('SELECT chunk_ids FROM history WHERE session_id=? ORDER BY id DESC LIMIT 3',(sid,)))
                ids=sorted({cid for row in history for cid in json.loads(row[0]) if cid in allowed})
                result={'sources':[{'chunk_id':cid,'title':allowed[cid]['title'],'page':allowed[cid]['page']} for cid in ids]}
            return json.loads(json.dumps(result,ensure_ascii=False))

    def record(self, principal: Principal, rid: str, status: str, ids: list[str]):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._append_audit(db,principal,rid,status,ids)

    @staticmethod
    def _append_audit(db,principal,rid,status,ids):
        last=db.execute('SELECT event_hash FROM audit_chain ORDER BY audit_id DESC LIMIT 1').fetchone()
        if last:
            previous=last[0]
        else:
            legacy=[dict(r) for r in db.execute('SELECT * FROM audit ORDER BY id')]
            previous=hashlib.sha256(json.dumps(legacy,sort_keys=True).encode()).hexdigest()
            anchor=max((r['id'] for r in legacy),default=0)
            db.execute("INSERT OR IGNORE INTO service_state VALUES('audit_anchor_id',?)",(str(anchor),))
            db.execute("INSERT OR IGNORE INTO service_state VALUES('audit_anchor_hash',?)",(previous,))
        event=db.execute('INSERT INTO audit(request_id,user_ref,status,chunk_ids) VALUES(?,?,?,?)',
                         (rid,hashlib.sha256((principal.tenant+principal.user).encode()).hexdigest()[:16],status,json.dumps(ids)))
        row=dict(db.execute('SELECT * FROM audit WHERE id=?',(event.lastrowid,)).fetchone())
        digest=hashlib.sha256((previous+json.dumps(row,sort_keys=True)).encode()).hexdigest()
        db.execute('INSERT INTO audit_chain VALUES(?,?,?,?)',(event.lastrowid,previous,digest,time.time()))

    def verify_audit(self):
        with self.connect() as db:
            db.execute('BEGIN')
            anchor=db.execute("SELECT value FROM service_state WHERE name='audit_anchor_id'").fetchone()
            if not anchor: return db.execute('SELECT count(*) FROM audit_chain').fetchone()[0]==0
            anchor=int(anchor[0])
            legacy=[dict(r) for r in db.execute('SELECT * FROM audit WHERE id<=? ORDER BY id',(anchor,))]
            previous=hashlib.sha256(json.dumps(legacy,sort_keys=True).encode()).hexdigest()
            stored=db.execute("SELECT value FROM service_state WHERE name='audit_anchor_hash'").fetchone()
            if not stored or previous!=stored[0]: return False
            for event in db.execute('SELECT * FROM audit WHERE id>? ORDER BY id',(anchor,)):
                chain=db.execute('SELECT * FROM audit_chain WHERE audit_id=?',(event['id'],)).fetchone()
                digest=hashlib.sha256((previous+json.dumps(dict(event),sort_keys=True)).encode()).hexdigest()
                if not chain or chain['prev_hash']!=previous or chain['event_hash']!=digest: return False
                previous=digest
            return True

def local_url(url: str) -> str:
    parsed=urlparse(url)
    hosts=set(os.environ.get("INTERNAL_HOSTS","localhost,127.0.0.1,vllm,embedder").split(','))
    if parsed.scheme not in ('http','https') or parsed.hostname not in hosts or parsed.username or parsed.password:
        raise ValueError("Inference URL must be on the explicit internal allowlist")
    return url.rstrip('/')

class Generator:
    def __init__(self, url: str | None = None, model: str = 'qwen-local'):
        self.url=local_url(url) if url else None
        self.model=model
        self.budget = TokenBudget(self.count_tokens,
                                  int(os.environ.get('LLM_MAX_MODEL_LEN', '4096')),
                                  int(os.environ.get('LLM_OUTPUT_TOKENS', '700')),
                                  int(os.environ.get('LLM_SAFETY_MARGIN', '64')))

    def count_tokens(self, messages):
        request = Request(self.url+'/tokenize', data=json.dumps({'model':self.model,'messages':messages,'add_generation_prompt':True}).encode(), headers={'Content-Type':'application/json'})
        try:
            with urlopen(request, timeout=10) as response:
                data = json.load(response)
            if type(data.get('count')) is not int:
                raise OSError('Invalid local tokenizer response')
            if type(data.get('max_model_len')) is int and self.budget.max_model_len > data['max_model_len']:
                raise OSError('Backend context configuration exceeds serving context')
            return data['count']
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise OSError('Invalid local tokenizer response') from exc

    def invoke(self, query: str, chunks: list[dict]) -> tuple[list[dict],dict]:
        if re.search('давлен|температур',query,re.I):
            named=set(ENTITY.findall(query));values={}
            for c in chunks:
                for number,unit in re.findall(r'(\d+(?:[.,]\d+)?)\s*(бар|МПа|°C|градусов)\b',c['text'],re.I):
                    for entity in named.intersection(ENTITY.findall(c['text'])):
                        values.setdefault((entity,unit.casefold()),set()).add(number.replace(',','.'))
            if any(len(numbers)>1 for numbers in values.values()):
                return [{'chunk_id':c['id'],'quote':c['text']} for c in chunks], {
                    'mode':'extractive-conflict','input_tokens':0,'output_tokens':0,
                    'fallback_reason':'unreconciled_numeric_sources','human_review_required':True}
        if not self.url:
            named=set(ENTITY.findall(query))
            selected=[c for c in chunks if not named or named.intersection(ENTITY.findall(c['text']))]
            return [{'chunk_id':c['id'],'quote':c['text']} for c in selected],{'mode':'extractive','input_tokens':0,'output_tokens':0}
        packed, count = self.budget.pack(query, chunks)
        budget_usage = {'budget_input_tokens':count,'max_model_len':self.budget.max_model_len,
                        'reserved_output_tokens':self.budget.output_tokens,'safety_margin':self.budget.margin}
        if len(packed) != len(chunks):
            # Preserve complete evidence and graph context without truncating a
            # negation/condition or sending a broken bridge to a smaller prompt.
            return [{'chunk_id':c['id'],'quote':c['text']} for c in chunks], {
                'mode':'extractive-context-limited','input_tokens':0,'output_tokens':0,
                'fallback_reason':'context_budget', **budget_usage}
        payload={'model':self.model,'temperature':0,'max_tokens':self.budget.output_tokens,
                 'response_format':{'type':'json_object'},'messages':messages_for(query, packed)}
        request=Request(self.url+'/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
        try:
            with tracer.start_as_current_span('llm.generate'):
                with urlopen(request,timeout=30) as response:
                    data=json.load(response)
            usage=data['usage']
            if not isinstance(usage, dict) or type(usage.get('prompt_tokens')) is not int or usage['prompt_tokens'] > count + self.budget.margin:
                raise OSError('Serving tokenizer usage mismatch')
            if type(usage.get('completion_tokens')) is not int or usage['completion_tokens']>self.budget.output_tokens or usage['prompt_tokens']+usage['completion_tokens']+self.budget.margin>self.budget.max_model_len:
                raise OSError('Serving output token budget mismatch')
            evidence=resolve_model_evidence(json.loads(data['choices'][0]['message']['content'])['evidence'],packed)
            valid=evidence is not None
            mode='vllm' if valid else 'extractive-invalid-generation'
            result_usage={'mode':mode,'input_tokens':usage['prompt_tokens'],'output_tokens':usage['completion_tokens'], **budget_usage}
            if not valid:
                # Never repair a model's clipped assertion. Discard its output
                # and expose full canonical units through the same ACL validator.
                evidence=[{'chunk_id':c['id'],'quote':c['text']} for c in packed]
                result_usage['fallback_reason']='invalid_model_citation'
            return evidence or [],result_usage
        except (KeyError,IndexError,TypeError,json.JSONDecodeError) as e:
            raise OSError('Invalid local model response') from e

class State(TypedDict, total=False):
    query: str
    principal: Principal
    session_id: str
    request_id: str
    safe_query: str
    steps: int
    memory: list[str]
    chunks: list[dict]
    edges: list[dict]
    evidence: list[dict]
    usage: dict
    status: str
    stages: list[str]

class EvidenceGenerator(Protocol):
    def invoke(self, query: str, chunks: list[dict]) -> tuple[list[dict],dict]: ...

class Agent:
    def __init__(self, store: Store, generator: EvidenceGenerator | None = None, vector=None):
        self.store=store; self.generator=generator or Generator(); self.vector=vector
        workflow=StateGraph(State)
        for name in ('guard','plan','retrieve','expand','rerank','generate','validate'):
            method=getattr(self,name)
            def traced(state, fn=method, stage=name):
                started=time.perf_counter()
                try:
                    with tracer.start_as_current_span('agent.'+stage):
                        update=fn(state)
                        update['stages']=state.get('stages',[])+[stage]
                        return update
                finally:
                    stage_latency.labels(stage).observe(time.perf_counter()-started)
            workflow.add_node(name,traced)
        workflow.add_edge(START,'guard')
        workflow.add_conditional_edges('guard',lambda s: END if s.get('status')=='blocked' else 'plan')
        workflow.add_edge('plan','retrieve'); workflow.add_edge('retrieve','expand'); workflow.add_edge('expand','rerank')
        workflow.add_conditional_edges('rerank',lambda s:'generate' if s.get('chunks') else ('plan' if s['steps']<2 else END))
        workflow.add_edge('generate','validate'); workflow.add_edge('validate',END)
        self.workflow=workflow.compile()

    def guard(self,s):
        query=unicodedata.normalize('NFKC', s['query']).strip()
        if not query or len(query)>2000: raise ValueError('Query length must be 1..2000')
        return {'safe_query':clean(query),'steps':0,'chunks':[],'edges':[],'evidence':[], 'status':'blocked' if INJECTION.search(query) else 'searching'}

    def plan(self,s):
        return {'steps':s['steps']+1,'memory':self.store.memory(s['principal'],s['session_id'])}

    def retrieve(self,s):
        candidates=self.store.allowed(s['principal'])
        query=terms(s['safe_query']); ranked=[]
        for c in candidates:
            overlap=len(query&terms(c['text']))
            # Enforce lexical evidence before considering a vector candidate.
            if overlap: ranked.append((overlap,c))
        ranked.sort(key=lambda p:(-p[0],p[1]['id']))
        seeds=[c for _,c in ranked[:3]]
        if self.vector and candidates:
            matches=self.vector.search(s['safe_query'],s['principal'])
            allowed={c['id']:c for c in candidates}
            ids=[c['id'] for c in seeds]
            for cid in matches:
                if cid in allowed and cid not in ids: seeds.append(allowed[cid]); ids.append(cid)
        if s['steps']>1 and not seeds:
            memory=set(s.get('memory',[]))
            if re.search(r'\b(он|она|это|этот|того|него)\b',s['safe_query'],re.I): seeds=[c for c in candidates if c['id'] in memory]
        return {'chunks':seeds[:5]}

    def expand(self,s):
        chunks,edges=self.store.graph(s['principal'],[c['id'] for c in s['chunks']])
        return {'chunks':chunks,'edges':edges}

    def rerank(self,s):
        # ponytail: bounded lexical pair reranking; cross-encoder for ambiguous free-text corpora.
        query=terms(s['safe_query']); seeds={c['id'] for c in s['chunks']}
        ranked=sorted(s['chunks'],key=lambda c:(-len(query&terms(c['text'])),c['id']))
        # Explicit unsupported engineering attributes must not become an answer
        # merely because the requested asset occurs in an unrelated paragraph.
        facets=((r'масс|\bвес',r'масс|\bвес'),(r'мощност',r'мощност'),
                (r'давлен',r'давлен'),(r'бюджет',r'бюджет'),(r'температур',r'температур'))
        for requested,required in facets:
            if re.search(requested,s['safe_query'],re.I):
                ranked=[c for c in ranked if re.search(required,c['text'],re.I)]
        return {'chunks':ranked[:6],'status':'grounded' if ranked else 'no_evidence'}

    def generate(self,s):
        evidence,usage=self.generator.invoke(s['safe_query'],s['chunks'])
        if not isinstance(usage,dict) or any(type(usage.get(k)) is not int or not 0<=usage[k]<=2**63-1 for k in ('input_tokens','output_tokens')):
            raise OSError('Invalid model token usage')
        return {'evidence':evidence,'usage':usage}

    def validate(self,s):
        # Re-authorize after generation, including when grants change during inference.
        allowed={c['id']:c for c in self.store.allowed(s['principal'])}
        context={c['id']:c for c in s['chunks']}; verified=[]
        if not isinstance(s['evidence'],list) or len(s['evidence'])>6: return {'evidence':[],'status':'output_blocked'}
        for e in s['evidence']:
            if not isinstance(e,dict): return {'evidence':[],'status':'output_blocked'}
            cid=e.get('chunk_id'); quote=e.get('quote')
            if not isinstance(cid,str) or cid not in context or cid not in allowed or not isinstance(quote,str) or not quote.strip() or INJECTION.search(quote) or PII.search(quote):
                return {'evidence':[],'status':'output_blocked'}
            c=allowed[cid]
            span=verified_span(c['text'],quote)
            if span is None or INJECTION.search(span['quote']) or PII.search(span['quote']):
                return {'evidence':[],'status':'output_blocked'}
            verified.append({'chunk_id':cid,**span,'title':c['title'],'page':c['page'],'version':c['version']})
        return {'evidence':verified,'status':'answered' if verified else 'no_evidence'}

    def run(self,query: str,principal: Principal,session_id: str | None=None) -> dict:
        sid=session_id or str(uuid.uuid4()); rid=str(uuid.uuid4())
        with self.store.request_scope():
            with tracer.start_as_current_span('query') as span:
                result=self.workflow.invoke({'query':query,'principal':principal,'session_id':sid,'request_id':rid}, {'recursion_limit':20})
                span.set_attribute('request.id',rid); span.set_attribute('result.status',result['status'])
            # The pre-release event contains no source IDs, quotes or question text.
            self.store.record(principal,rid,'pending_release',[])
            started=time.perf_counter()
            try:
                with tracer.start_as_current_span('query.finalize'):
                    return self.store.finalize(principal,query,sid,rid,result)
            finally:
                stage_latency.labels('finalize').observe(time.perf_counter()-started)

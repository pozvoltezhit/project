import json
import logging
import os
import secrets
import hashlib
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPBearer
from fastapi.responses import FileResponse, Response, StreamingResponse, JSONResponse
from pydantic import BaseModel, Field, ConfigDict
from prometheus_client import Counter, Histogram, REGISTRY, generate_latest, CONTENT_TYPE_LATEST
from backend.finops import CostCollector
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from backend.core import Store, Agent, Generator, Principal
from backend.telemetry import HTTPAccounting, http_requests
from backend.telemetry import budget_failures, dependency_errors, readiness, dependency_ready
from backend.quality_export import EvaluationCollector
from backend.budget import BudgetExceeded
from backend.admission import Admission
from urllib.request import urlopen
import sqlite3
import asyncio

ROOT=Path(__file__).resolve().parents[1]
store=Store(os.environ.get('DB_PATH',str(ROOT/'data/knowledge.db')))
agent=Agent(store,Generator(os.environ.get('LLM_URL')))
logger=logging.getLogger('knowledge')
requests=Counter('knowledge_requests_total','GraphRAG requests',['status'])
latency=Histogram('knowledge_latency_seconds','Full query latency',buckets=(.005,.01,.025,.05,.1,.2,.5,1,2,5,10,30))
tokens=Counter('knowledge_tokens_total','Tokens reported by real local serving',['direction'])
REGISTRY.register(CostCollector(requests))
REGISTRY.register(EvaluationCollector())

@asynccontextmanager
async def lifespan(app):
    global agent
    managed_indexes=None
    if os.environ.get('KNOWLEDGE_OTLP_ENDPOINT'):
        provider=TracerProvider(resource=Resource.create({'service.name':'knowledge-platform'}))
        exporter=OTLPSpanExporter(endpoint=os.environ['KNOWLEDGE_OTLP_ENDPOINT'].rstrip('/')+'/v1/traces')
        provider.add_span_processor(BatchSpanProcessor(exporter)); trace.set_tracer_provider(provider)
    if os.environ.get('QDRANT_URL'):
        from backend.adapters import Indexes
        password=Path(os.environ['NEO4J_PASSWORD_FILE']).read_text().strip()
        indexes=Indexes(store,os.environ['QDRANT_URL'],os.environ['NEO4J_URL'],password)
        managed_indexes=indexes
        # Containers can start before the databases accept connections.
        for attempt in range(12):
            try:
                await asyncio.to_thread(indexes.sync)
                break
            except Exception:
                if attempt==11: raise RuntimeError('Required indices failed startup') from None
                await asyncio.sleep(min(1.5**attempt,5))
        agent=Agent(store,Generator(os.environ.get('LLM_URL')),indexes)
    yield
    if managed_indexes is not None:
        managed_indexes.qdrant.close()
        managed_indexes.neo4j.close()
    if os.environ.get('KNOWLEDGE_OTLP_ENDPOINT'): provider.shutdown()

app=FastAPI(title='Закрытая GraphRAG платформа',version='1.1.0',lifespan=lifespan)
app.add_middleware(Admission)
app.add_middleware(HTTPAccounting)
bearer_scheme=HTTPBearer(auto_error=False,scheme_name='BearerToken')

def principal(authorization: str | None=Header(default=None),_credential=Depends(bearer_scheme)) -> Principal:
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'Bearer token required')
    token=authorization[7:]
    path=Path(os.environ.get('AUTH_FILE',str(ROOT/'data/identities.json')))
    if not path.exists(): raise HTTPException(503,'Identity provisioning required')
    identities=json.loads(path.read_text(encoding='utf-8'))
    for identity in identities:
        if secrets.compare_digest(identity['token'].encode('utf-8'),token.encode('utf-8')):
            return Principal(identity['user'],identity['tenant'],tuple(identity['roles']),str(path),hashlib.sha256(token.encode()).hexdigest())
    raise HTTPException(401,'Invalid token')

class Query(BaseModel):
    model_config=ConfigDict(extra='forbid')
    question: str=Field(min_length=1,max_length=2000)
    session_id: str | None=Field(default=None,max_length=80,pattern=r'^[A-Za-z0-9-]+$')

class Evidence(BaseModel):
    chunk_id: str
    quote: str
    title: str
    page: int
    version: int
    start: int
    end: int
    selection_start: int
    selection_end: int

class Answer(BaseModel):
    request_id: str
    session_id: str
    status: str
    evidence: list[Evidence]
    graph: list[dict]
    usage: dict
    stages: list[str]
    authorization_epoch: int

class ErrorBody(BaseModel):
    detail: str
    code: str

@app.exception_handler(HTTPException)
async def http_error(request: Request, error: HTTPException):
    codes={401:'unauthorized',403:'forbidden',422:'invalid_request',429:'overloaded',503:'dependency_unavailable'}
    code='token_budget_exceeded' if error.status_code==422 and error.detail=='Question exceeds the model token budget' else codes.get(error.status_code,'request_failed')
    return JSONResponse({'detail':str(error.detail),'code':code},status_code=error.status_code,
                        headers={'WWW-Authenticate':'Bearer'} if error.status_code==401 else None)

@app.exception_handler(RequestValidationError)
async def validation_error(request: Request,error: RequestValidationError):
    return JSONResponse({'detail':'Request schema validation failed','code':'invalid_request'},status_code=422)

@app.exception_handler(Exception)
async def unexpected_error(request: Request,error: Exception):
    logger.error('Unhandled request failure: %s',type(error).__name__)
    return JSONResponse({'detail':'Internal request failure','code':'internal_error'},status_code=500)

def answer(body: Query,p: Principal):
    started=time.perf_counter()
    try:
        result=agent.run(body.question,p,body.session_id)
    except PermissionError as e: raise HTTPException(403,str(e)) from e
    except BudgetExceeded as e:
        budget_failures.inc()
        raise HTTPException(422,'Question exceeds the model token budget') from e
    except (OSError,KeyError,TypeError,json.JSONDecodeError,sqlite3.Error):
        requests.labels('failed').inc()
        dependency_errors.labels('retrieval_or_inference').inc()
        raise HTTPException(503,'Retrieval or inference unavailable or invalid response')
    except ValueError as e: raise HTTPException(422,str(e)) from e
    finally: latency.observe(time.perf_counter()-started)
    requests.labels(result['status']).inc()
    tokens.labels('input').inc(result['usage']['input_tokens']); tokens.labels('output').inc(result['usage']['output_tokens'])
    logger.info(json.dumps({'request_id':result['request_id'],'status':result['status'],'evidence_count':len(result['evidence'])}))
    return result

@app.post('/query',response_model=Answer,responses={code:{'model':ErrorBody} for code in (401,403,422,429,500,503)})
def query(body: Query,p: Principal=Depends(principal)): return answer(body,p)

@app.post('/query/stream')
def stream(body: Query,p: Principal=Depends(principal)):
    result=answer(body,p)
    # Validate the complete answer before releasing any SSE event.
    return StreamingResponse(iter(['event: result\ndata: '+json.dumps(result,ensure_ascii=False)+'\n\n']),media_type='text/event-stream')

@app.get('/graph')
def graph(p: Principal=Depends(principal)):
    try: return store.public_view(p)
    except PermissionError as e: raise HTTPException(403,str(e)) from e

@app.get('/history/{session_id}')
def history(session_id: str,p: Principal=Depends(principal)):
    try: return store.public_view(p,session_id)
    except PermissionError as e: raise HTTPException(403,str(e)) from e

@app.get('/health')
def health(): return {'status':'ok','generation':'local-vllm' if os.environ.get('LLM_URL') else 'extractive-offline'}

@app.get('/ready')
def ready():
    checks={}
    try:
        with store.connect() as db: db.execute('SELECT value FROM security_epoch').fetchone()
        checks['sql']=True
        checks['audit_integrity']=store.verify_audit()
    except sqlite3.Error:
        checks['sql']=False
    try:
        identity_path=Path(os.environ.get('AUTH_FILE',str(ROOT/'data/identities.json')))
        identities=json.loads(identity_path.read_text(encoding='utf-8'))
        checks['identity']=bool(identities) and all(set(('user','tenant','roles','token')) <= set(i) for i in identities)
    except (OSError,ValueError,TypeError):
        checks['identity']=False
    if agent.vector is not None:
        checks['qdrant']=checks['neo4j']=checks['indices']=False
        try:
            release=agent.vector.active_release()
            checks['qdrant']=bool(release) and agent.vector.qdrant.collection_exists(release['collection'])
        except Exception:
            pass
        try:
            agent.vector.neo4j.verify_connectivity()
            checks['neo4j']=True
        except Exception:
            pass
        try:
            checks['indices']=checks['qdrant'] and checks['neo4j'] and agent.vector.ready()
        except Exception:
            checks['indices']=False
    if agent.generator.url:
        try:
            with urlopen(agent.generator.url+'/health',timeout=2) as response:
                checks['vllm']=response.status==200
            with urlopen(agent.generator.url+'/v1/models',timeout=2) as response:
                models=json.load(response)['data']
            checks['model_config']=any(m['id']==agent.generator.model and m.get('max_model_len',0)>=agent.generator.budget.max_model_len for m in models)
        except (OSError,KeyError,TypeError,ValueError):
            checks['vllm']=False
    good=bool(checks) and all(checks.values())
    readiness.set(int(good))
    for dependency,value in checks.items(): dependency_ready.labels(dependency).set(int(value))
    return JSONResponse({'ready':good,'checks':checks},status_code=200 if good else 503)

@app.get('/metrics',include_in_schema=False)
def metrics(): return Response(generate_latest(),media_type=CONTENT_TYPE_LATEST)

@app.get('/',include_in_schema=False)
def frontend(): return FileResponse(ROOT/'frontend/index.html')

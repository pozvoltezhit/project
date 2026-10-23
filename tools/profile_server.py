"""Opt-in disposable-stand profiler. Records numbers only, never SQL/prompts/IDs.

Run with /app unchanged; mount this tool separately at /instrument. Inclusive
timings overlap and must not be summed. No caching or authorization changes.
"""
import contextvars
import functools
import json
import os
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, '/app')
current = contextvars.ContextVar('numeric_profile', default=None)
write_lock = threading.Lock()


def emit(record):
    with write_lock:
        with Path(os.environ['PROFILE_OUTPUT']).open('a', encoding='utf-8') as output:
            output.write(json.dumps(record)+'\n')


def sample(name, elapsed, cpu=0):
    record = current.get()
    if record is not None:
        item = record['stages'].setdefault(name, {'calls':0, 'seconds':0., 'cpu_seconds':0.})
        item['calls'] += 1
        item['seconds'] += elapsed
        item['cpu_seconds'] += cpu


def timed(fn, name):
    @functools.wraps(fn)
    def call(*args, **kwargs):
        start, cpu = time.perf_counter(), time.thread_time()
        try:
            return fn(*args, **kwargs)
        finally:
            sample(name, time.perf_counter()-start, time.thread_time()-cpu)
    return call


class MeasuredConnection:
    def __init__(self, db):
        object.__setattr__(self, 'db', db)

    def __getattr__(self, name):
        if name in ('execute', 'executemany', 'executescript', 'commit', 'rollback'):
            return timed(getattr(self.db, name), 'sql.'+name)
        return getattr(self.db, name)

    def __setattr__(self, name, value):
        setattr(self.db, name, value)

    def __enter__(self):
        self.db.__enter__()
        return self

    def __exit__(self, *args):
        return timed(self.db.__exit__, 'sql.commit_or_rollback')(*args)


def install():
    import backend.core as core
    from backend.adapters import Indexes
    from qdrant_client import QdrantClient
    QdrantClient.query_points = timed(QdrantClient.query_points,'network.qdrant')
    original_connect = sqlite3.connect
    sqlite3.connect = lambda *a, **kw: MeasuredConnection(original_connect(*a, **kw))
    for cls, names in ((core.Agent, ('guard','plan','retrieve','expand','rerank','generate','validate')),
                       (core.Store, ('allowed','graph','memory','finalize','record')),
                       (core.Generator, ('count_tokens',)), (Indexes, ('search','active_release','encode'))):
        for name in names:
            setattr(cls, name, timed(getattr(cls, name), cls.__name__+'.'+name))
    core.TokenBudget.pack = timed(core.TokenBudget.pack, 'budget.pack')
    original_connection = core.Store.connect
    @contextmanager
    def connection(self):
        start = time.perf_counter()
        with original_connection(self) as db:
            sample('sql.connection_and_process_lock_wait', time.perf_counter()-start)
            begin = time.perf_counter()
            try:
                yield db
            finally:
                sample('sql.connection_body', time.perf_counter()-begin)
    core.Store.connect = connection
    original_urlopen = core.urlopen
    def urlopen(request, *args, **kwargs):
        start = time.perf_counter()
        kind = 'tokenize' if request.full_url.endswith('/tokenize') else 'generation'
        try:
            return original_urlopen(request, *args, **kwargs)
        finally:
            sample('network.'+kind, time.perf_counter()-start)
            record = current.get()
            if record is not None:
                record[kind+'_request_bytes'] = record.get(kind+'_request_bytes', 0) + len(request.data or b'')
    core.urlopen = urlopen
    original_run = core.Agent.run
    def run(self, *args, **kwargs):
        owned_record = current.get() is None
        record = current.get() or {'stages':{}, 'timestamp':time.time(), 'retries':None}
        token = current.set(record)
        start = time.perf_counter()
        anchor = None
        try:
            if os.environ.get('PROFILE_WAL_ANCHOR') == '1':
                anchor = sqlite3.connect(self.store.path, timeout=10)
                anchor.execute('SELECT value FROM security_epoch WHERE id=1').fetchall()
                assert not anchor.in_transaction
            result = original_run(self, *args, **kwargs)
            record['usage'] = {k:v for k,v in result['usage'].items() if type(v) in (int,float)}
            record['mode'] = result['usage']['mode']
            record['status'] = result['status']
            return result
        except BaseException as exc:
            record['error_type'] = type(exc).__name__
            raise
        finally:
            if anchor is not None:
                anchor.close()
            record['agent_seconds'] = time.perf_counter()-start
            record['seconds'] = record['agent_seconds']
            current.reset(token)
            if owned_record:
                emit(record)
    core.Agent.run = run


if __name__ == '__main__':
    install()
    import uvicorn
    if os.environ.get('PROFILE_HTTP') != '1':
        uvicorn.run('backend.api:app', host='0.0.0.0', port=8000, log_level='warning')
    else:
        import backend.api as api
        import backend.admission as admission
        import fastapi.routing
        serialize = fastapi.routing.serialize_response
        async def serialization(*args, **kwargs):
            began = time.perf_counter()
            try:
                return await serialize(*args, **kwargs)
            finally:
                sample('serialization',time.perf_counter()-began)
        fastapi.routing.serialize_response = serialization
        for route in api.app.routes:
            for dependency in getattr(getattr(route,'dependant',None),'dependencies',[]):
                if dependency.call is api.principal:
                    dependency.call = timed(api.principal,'auth')
        observe = admission.wait_time.observe
        def wait_observation(value):
            sample('admission.wait',value)
            observe(value)
        admission.wait_time.observe = wait_observation
        async def application(scope, receive, send):
            if scope['type'] != 'http' or scope.get('path') not in ('/query','/query/stream'):
                return await api.app(scope,receive,send)
            record = {'stages':{},'timestamp':time.time(),'retries':None}
            token = current.set(record)
            start = time.perf_counter()
            async def measured(message):
                began = time.perf_counter()
                try:
                    await send(message)
                finally:
                    sample('asgi.send',time.perf_counter()-began)
            try:
                return await api.app(scope,receive,measured)
            finally:
                sample('HTTP.total',time.perf_counter()-start)
                record['seconds'] = time.perf_counter()-start
                current.reset(token)
                emit(record)
        # Keep FastAPI lifespan and dependency startup on the inner application.
        uvicorn.run(application,host='0.0.0.0',port=8000,log_level='warning')

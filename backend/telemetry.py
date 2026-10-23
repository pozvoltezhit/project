"""Bounded HTTP transport accounting, distinct from business outcomes."""
import time
import asyncio
from prometheus_client import Counter, Gauge, Histogram

http_requests = Counter('knowledge_http_requests_total', 'HTTP attempts including interrupted responses', ['route','method','status_class','outcome'])
http_latency = Histogram('knowledge_http_latency_seconds','HTTP time including admission and response',['route'],buckets=(.01,.05,.1,.25,.5,1,2,5,10,30,60))
stage_latency = Histogram('knowledge_stage_latency_seconds','Agent stage duration',['stage'],buckets=(.001,.005,.01,.05,.1,.5,1,2,5,10,30))
dependency_errors = Counter('knowledge_dependency_errors_total','Dependency failures',['dependency'])
readiness = Gauge('knowledge_ready','Required execution dependencies ready')
dependency_ready = Gauge('knowledge_dependency_ready','Readiness of configured dependency',['dependency'])
budget_failures = Counter('knowledge_budget_rejections_total','Question budget rejections')
ROUTES = {'/','/query','/query/stream','/graph','/history/{session_id}','/health','/ready','/metrics','/docs','/openapi.json','/redoc'}


def outcome(status: int) -> str:
    return {401:'unauthorized',403:'forbidden',422:'invalid',429:'overloaded',500:'unexpected',503:'unavailable',504:'timeout'}.get(status, 'success' if status < 400 else 'rejected')


for route in ('/query','/query/stream'):
    for status in (200,401,403,422,429,500,503,504):
        http_requests.labels(route,'POST',f'{status//100}xx',outcome(status)).inc(0)
    http_latency.labels(route)  # Initialize empty histograms, never fake observations.


class HTTPAccounting:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        started = time.perf_counter()
        status = 500
        completed = False
        failure = None
        async def measured(message):
            nonlocal status, completed, failure
            if message['type'] == 'http.response.start':
                status = message['status']
            try:
                await send(message)
            except OSError:
                failure = 'transport_error'
                raise
            if message['type'] == 'http.response.body' and not message.get('more_body', False):
                completed = True
        try:
            await self.app(scope, receive, measured)
        except asyncio.CancelledError:
            failure = 'cancelled'
            raise
        except BaseException:
            failure = failure or 'unexpected'
            raise
        finally:
            route = getattr(scope.get('route'), 'path', '/unmatched')
            if route not in ROUTES:
                route = '/unmatched'
            method = scope['method'] if scope['method'] in {'GET','POST','PUT','DELETE','PATCH','HEAD','OPTIONS'} else 'OTHER'
            result = failure or (outcome(status) if completed else 'incomplete')
            http_requests.labels(route,method,f'{status//100}xx',result).inc()
            http_latency.labels(route).observe(time.perf_counter()-started)

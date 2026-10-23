"""Small per-process admission controller; bounded active/waiting work."""
import asyncio
import os
import threading
import time
from collections import deque

from prometheus_client import Gauge, Histogram
from starlette.responses import JSONResponse

active = Gauge('knowledge_active_queries','Admitted active queries')
waiting = Gauge('knowledge_waiting_queries','Queries awaiting a worker')
wait_time = Histogram('knowledge_admission_wait_seconds','Admission delay',buckets=(.001,.01,.05,.1,.5,1,2,5))


class Admission:
    def __init__(self, app):
        self.app = app
        self.limit = int(os.environ.get('MAX_ACTIVE_QUERIES','8'))
        self.queue = int(os.environ.get('MAX_QUEUED_QUERIES','8'))
        self.per_minute = int(os.environ.get('MAX_REQUESTS_PER_MINUTE','600'))
        self.timeout = float(os.environ.get('ADMISSION_TIMEOUT_SECONDS','2'))
        if self.limit < 1 or self.queue < 0 or self.per_minute < 1 or self.timeout <= 0:
            raise ValueError('Invalid admission configuration')
        self.lock = threading.Lock()
        self.running = self.queued = 0
        self.arrivals = deque()

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('path') not in ('/query','/query/stream') or scope['method'] != 'POST':
            return await self.app(scope,receive,send)
        started = time.monotonic()
        queued = False
        admitted = False
        try:
            with self.lock:
                while self.arrivals and self.arrivals[0] <= started-60:
                    self.arrivals.popleft()
                rejected = len(self.arrivals) >= self.per_minute or (self.running >= self.limit and self.queued >= self.queue)
                if not rejected:
                    self.arrivals.append(started)
                    if self.running < self.limit:
                        self.running += 1; admitted = True
                    else:
                        self.queued += 1; queued = True; waiting.inc()
            if rejected:
                return await self.reject(scope,receive,send)
            while not admitted:
                with self.lock:
                    if self.running < self.limit:
                        self.running += 1; admitted = True
                        self.queued -= 1; queued = False; waiting.dec()
                if admitted:
                    break
                if time.monotonic()-started >= self.timeout:
                    return await self.reject(scope,receive,send)
                await asyncio.sleep(.01)
            wait_time.observe(time.monotonic()-started)
            active.inc()
            try:
                return await self.app(scope,receive,send)
            finally:
                active.dec()
        finally:
            with self.lock:
                if admitted: self.running -= 1
                if queued: self.queued -= 1; waiting.dec()

    @staticmethod
    async def reject(scope,receive,send):
        # Set a bounded route for accounting even before FastAPI routing.
        from types import SimpleNamespace
        scope['route'] = SimpleNamespace(path=scope['path'])
        response = JSONResponse({'detail':'Request admission limit reached','code':'overloaded'},status_code=429,headers={'Retry-After':'2'})
        return await response(scope,receive,send)

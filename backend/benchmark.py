"""Measured local ASGI benchmark. Does not pretend to measure GPU serving."""
import argparse
import asyncio
import json
import os
import platform
import statistics
import time
from pathlib import Path
import httpx

async def main(count,concurrency,output,url=None):
    from backend.api import app
    identities=json.loads(Path(os.environ.get('AUTH_FILE','data/identities.json')).read_text(encoding='utf-8'))
    token=next(x['token'] for x in identities if x['user']=='engineer-b')
    durations=[]; modes=set(); errors=0; gate=asyncio.Semaphore(concurrency)
    options={'base_url':url,'timeout':60} if url else {'transport':httpx.ASGITransport(app=app),'base_url':'http://local'}
    async with httpx.AsyncClient(**options) as client:
        async def one(i):
            nonlocal errors
            async with gate:
                start=time.perf_counter()
                try:
                    r=await client.post('/query',json={'question':'Как связан насос Н-17 с датчиком Д-8?'},headers={'Authorization':'Bearer '+token})
                    if r.status_code!=200 or r.json()['status']!='answered' or '987654321' in r.text: errors+=1
                    if r.status_code==200: modes.add(r.json()['usage']['mode'])
                except httpx.HTTPError: errors+=1
                durations.append((time.perf_counter()-start)*1000)
        start=time.perf_counter(); await asyncio.gather(*(one(i) for i in range(count))); elapsed=time.perf_counter()-start
    durations.sort()
    scope=('HTTP through loopback gateway to Docker backend; server profile recorded separately' if url else 'in-process ASGI, SQLite graph, hashed lexical retrieval; NO network')
    result={'scope':scope,'generation_modes':sorted(modes),'system':platform.platform(),'processor':platform.processor(),'requests':count,'concurrency':concurrency,'elapsed_seconds':round(elapsed,3),'successful_rps':round((count-errors)/elapsed,2),'errors':errors,'p50_ms':round(statistics.median(durations),2),'p95_ms':round(durations[min(count-1,int(.95*count))],2),'p99_ms':round(durations[min(count-1,int(.99*count))],2)}
    Path(output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--requests',type=int,default=200);p.add_argument('--concurrency',type=int,default=8);p.add_argument('--output',default='docs/benchmark.json');p.add_argument('--url');a=p.parse_args()
    if a.requests<1 or a.concurrency<1: p.error('requests/concurrency must be positive')
    asyncio.run(main(a.requests,a.concurrency,a.output,a.url))

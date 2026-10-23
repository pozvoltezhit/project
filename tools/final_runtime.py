"""Final evidence from a strictly isolated, already-built remediation stack."""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
COURSE=ROOT.parents[2]
DATA=COURSE/'tmp/remediation-20261020/data'
WHEELS=COURSE/'tmp/remediation-20261020/wheelhouse'
EVIDENCE=ROOT/'docs/remediation/evidence'
NAMESPACE='course-remediation-20261020'
BACKEND=NAMESPACE+'-backend-1'


def command(args,log=None,check=True):
    print('RUN',args[0],args[1:4],flush=True)
    result=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',errors='replace')
    if log:(EVIDENCE/log).write_text(result.stdout+result.stderr,encoding='utf-8')
    if args[1]!='inspect':print(result.stdout[-1600:],result.stderr[-400:],flush=True)
    if check and result.returncode:raise RuntimeError('Command failed: '+str(args[:4]))
    return result


def copy(name,target=None):
    (EVIDENCE/(target or name)).write_bytes((DATA/name).read_bytes())


def get(url,data=None,token=None):
    headers={'Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    request=urllib.request.Request(url,data=json.dumps(data).encode() if data is not None else None,headers=headers)
    try:
        with urllib.request.urlopen(request,timeout=20) as response:return response.status,json.load(response)
    except urllib.error.HTTPError as error:return error.code,json.load(error)


def main():
    os.chdir(ROOT)
    if '--rebuild' in sys.argv:
        # Preserve the failed candidate evidence instead of relabelling it green.
        attempt=1
        while (EVIDENCE/f'candidate-{attempt}').exists():attempt+=1
        archive=EVIDENCE/f'candidate-{attempt}'
        archive.mkdir(exist_ok=True)
        for name in ('eval-gpu.json','benchmark-gpu.json','verification.json','gpu-regression.json','integration-cpu.json','integration-gpu.json','eval-cpu.json','benchmark-cpu.json','build-final.json'):
            if (EVIDENCE/name).exists():(archive/name).write_bytes((EVIDENCE/name).read_bytes())
        command(['docker','build','--network','none','-f','infra/Dockerfile.offline','-t','course-knowledge-remediated:20261020','.'],'build-final.log')
        image=json.loads(command(['docker','image','inspect','course-knowledge-remediated:20261020']).stdout)[0]['Id']
        (EVIDENCE/'build-final.json').write_text(json.dumps({'status':'PASS','method':'offline prepared-runtime rebase','image_id':image,
             'dependency_versions':'Verified against full lock during build','limitation':'Prepared OS/OCR runtime required; fresh offline apt build not confirmed'},indent=2))
        override=COURSE/'tmp/remediation-20261020/compose.final.yaml'
        config=override.read_text(encoding='utf-8').splitlines()
        config=[('    image: '+image) if line.startswith('    image: ') else line for line in config]
        override.write_text('\n'.join(config)+'\n',encoding='utf-8')
        compose=['docker','compose','-p',NAMESPACE,'-f','infra/compose.yaml','-f','infra/compose.indexes.yaml']
        final=['-f',str(override)]
        command(compose+final+['up','-d','--no-build','--pull','never'],'start-cpu-final.log')
        command(['docker','exec',BACKEND,'python','-m','backend.integration_check'],'integration-cpu.log')
        copy('integration-result.json','integration-cpu.json')
        command(['docker','exec',BACKEND,'python','-m','backend.stack_check'],'stack-regression.log')
        copy('stack-regression.json')
        command(['docker','exec',BACKEND,'python','-m','backend.evaluate','--output','/app/data/eval-cpu-final.json'],'eval-cpu.log')
        copy('eval-cpu-final.json','eval-cpu.json')
        command(['docker','exec',BACKEND,'python','-m','backend.benchmark','--url','http://gateway:18080','--requests','300','--concurrency','8','--output','/app/data/benchmark-cpu-final.json'],'benchmark-cpu.log')
        copy('benchmark-cpu-final.json','benchmark-cpu.json')
        # Include GPU scrape override; the previously loaded model is reused.
        command(compose+['-f','infra/compose.gpu.yaml']+final+['up','-d','--no-build','--pull','never'],'start-gpu-final.log')
        command(['docker','exec',BACKEND,'python','-m','backend.integration_check'],'integration-gpu.log')
    # No operation can target a container outside our new namespace.
    for service in ('backend','qdrant','prometheus','vllm'):
        info=json.loads(command(['docker','inspect',NAMESPACE+'-'+service+'-1']).stdout)[0]
        assert info['Config']['Labels']['com.docker.compose.project']==NAMESPACE
        if service=='backend':
            assert info['Image']==json.loads((EVIDENCE/'build-final.json').read_text())['image_id']
            assert all(m['Destination']!='/app' for m in info['Mounts'])
    copy('integration-result.json','integration-gpu.json')
    command(['docker','exec',BACKEND,'python','-m','backend.gpu_check'],'gpu-regression.log')
    copy('gpu-regression.json')
    command(['docker','exec',BACKEND,'python','-m','backend.evaluate','--gpu','--output','/app/data/eval-report.json'],'eval-gpu.log',check=False)
    copy('eval-report.json','eval-gpu.json')
    # Benchmark runs without competing tests/evaluation/offline installation.
    command(['docker','exec',BACKEND,'python','-m','backend.benchmark','--url','http://gateway:18080','--requests','48','--concurrency','4','--output','/app/data/benchmark-gpu-final.json'],'benchmark-gpu.log')
    copy('benchmark-gpu-final.json','benchmark-gpu.json')
    base=['docker','run','--rm','--network','none','--mount',f'type=bind,source={ROOT.as_posix()},target=/app,readonly',
          '--mount',f'type=bind,source={EVIDENCE.as_posix()},target=/evidence',
          '-e','PYTHONDONTWRITEBYTECODE=1','-e','DB_PATH=/tmp/unit.db','-e','AUTH_FILE=/tmp/absent.json',
          '-e','COVERAGE_FILE=/tmp/.coverage','-e','MYPY_CACHE_DIR=/tmp/mypy','-e','RUFF_CACHE_DIR=/tmp/ruff']
    command(base+['--entrypoint','python','course-remediation-tools:20261020','tools/verify.py','--output','/evidence/verification.json'],'verification-run.log')
    command(base+['--mount',f'type=bind,source={WHEELS.as_posix()},target=/wheels,readonly','--entrypoint','python',
                 'course-remediation-tools:20261020','tools/offline_smoke.py','--wheels','/wheels','--output','/evidence/offline-smoke.json'],'offline-smoke.log')
    command(['docker','exec',NAMESPACE+'-prometheus-1','promtool','check','config','/etc/prometheus/prometheus.yml'],'promtool.log')
    # A required dependency failure must affect readiness and requests, not liveness.
    token=next(i['token'] for i in json.loads((DATA/'identities.json').read_text()) if i['user']=='engineer-b')
    statuses={'ready_before':get('http://127.0.0.1:18080/ready')[0]}
    command(['docker','stop',NAMESPACE+'-qdrant-1'])
    try:
        statuses['ready_dependency_down']=get('http://127.0.0.1:18080/ready')[0]
        statuses['health_dependency_down']=get('http://127.0.0.1:18080/health')[0]
        statuses['query_dependency_down']=get('http://127.0.0.1:18080/query',{'question':'Как связан Н-17 с Д-8?'},token)[0]
    finally:command(['docker','start',NAMESPACE+'-qdrant-1'])
    for _ in range(30):
        code,_=get('http://127.0.0.1:18080/ready')
        if code==200:break
        time.sleep(1)
    statuses['ready_recovered']=code
    statuses['decision']='PASS' if statuses=={'ready_before':200,'ready_dependency_down':503,'health_dependency_down':200,'query_dependency_down':503,'ready_recovered':200} else 'FAIL'
    (EVIDENCE/'readiness-failure.json').write_text(json.dumps(statuses,indent=2))
    assert statuses['decision']=='PASS',statuses
    # Validate every real dashboard expression against running Prometheus.
    dashboard=json.loads((ROOT/'infra/grafana/dashboards/knowledge.json').read_text())
    expressions=[]
    for panel in dashboard['panels']:
        for target in panel.get('targets',[]):
            expression=target.get('expr')
            if expression:
                expression=expression.replace('$__rate_interval','2m').replace('$__interval','15s')
                status,response=get('http://127.0.0.1:19090/api/v1/query?'+urllib.parse.urlencode({'query':expression}))
                expressions.append({'panel':panel['title'],'status':status,'success':response.get('status')=='success','series':len(response.get('data',{}).get('result',[]))})
    _,targets=get('http://127.0.0.1:19090/api/v1/targets')
    jobs=[{'job':x['labels'].get('job'),'health':x['health']} for x in targets['data']['activeTargets']]
    _,traces=get('http://127.0.0.1:16686/api/traces?service=knowledge-platform&limit=100')
    operations=sorted({s['operationName'] for trace in traces.get('data',[]) for s in trace.get('spans',[])})
    report={'decision':'PASS' if all(x['success'] for x in expressions) and all(j['health']=='up' for j in jobs) else 'FAIL',
            'timestamp':time.time(),'expressions':expressions,'targets':jobs,'trace_operations':operations,
            'missing_cost_series':'Expected when local price/power inputs are not configured; no fabricated zero'}
    (EVIDENCE/'observability.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    assert report['decision']=='PASS',report
    print('FINAL RUNTIME CHECKS COMPLETE',flush=True)


if __name__=='__main__':main()

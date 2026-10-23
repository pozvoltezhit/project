"""Isolated final verification harness. No commands target other Docker projects.

Host Python stdlib only. Evidence is append-only by phase/run name. Runtime data
and credentials remain ignored under data/final-20261020, weights read-only.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'data/final-20261020'
EVIDENCE = ROOT/'docs/remediation/evidence/final-20261020'
NAMESPACE = 'course-final-20261020'
OLD = 'sha256:6ee26fe97239ead672a5fabb03b995d6e22584485dfa96cf5b36862a00274e1e'
TOOLS = 'course-remediation-tools:20261020'
CONFIG = BASE/'compose.json'


def command(args, log=None, check=True):
    print('RUN', ' '.join(args[:6]), flush=True)
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if log:
        target = EVIDENCE/log
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(result.stdout+result.stderr, encoding='utf-8')
    if check and result.returncode:
        raise RuntimeError(str(args[:5])+': '+result.stderr[-1200:]+' '+result.stdout[-1200:])
    return result


def docker(*args, **kwargs):
    return command(['docker', *args], **kwargs)


def compose(*args, **kwargs):
    return docker('compose', '-p', NAMESPACE, '-f', str(CONFIG), *args, **kwargs)


def owned(service):
    info = json.loads(docker('inspect', NAMESPACE+'-'+service+'-1').stdout)[0]
    assert info['Config']['Labels']['com.docker.compose.project'] == NAMESPACE
    return info


def execute(module, args=(), log=None, env=()):
    owned('backend')
    prefix = [item for pair in env for item in ('-e', pair)]
    return docker('exec', *prefix, NAMESPACE+'-backend-1', 'python', '-m', module, *args, log=log)


def copy_data(source, target):
    path = EVIDENCE/target
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((BASE/'runtime'/source).read_bytes())


def operations():
    identities = json.loads((BASE/'runtime/identities.json').read_text())
    token = next(i['token'] for i in identities if i['user']=='engineer-b')
    def get(path, question=None):
        req = urllib.request.Request('http://127.0.0.1:18080'+path,
            data=json.dumps({'question':question}).encode() if question else None,
            headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=20) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code
    results = {'ready_before':get('/ready')}
    owned('qdrant')
    docker('stop', NAMESPACE+'-qdrant-1')
    try:
        results.update(ready_down=get('/ready'),health_down=get('/health'),
                       query_down=get('/query','Как связан насос Н-17 с датчиком Д-8?'))
    finally:
        docker('start', NAMESPACE+'-qdrant-1')
    for _ in range(30):
        code = get('/ready')
        if code == 200: break
        time.sleep(1)
    results['ready_recovered'] = code
    results['decision'] = 'PASS' if results == {'ready_before':200,'ready_down':503,'health_down':200,
                                               'query_down':503,'ready_recovered':200} else 'FAIL'
    (EVIDENCE/'candidate/dependency-recovery.json').write_text(json.dumps(results,indent=2))
    assert results['decision']=='PASS',results
    owned('prometheus')
    docker('exec',NAMESPACE+'-prometheus-1','promtool','check','config','/etc/prometheus/prometheus.yml',log='candidate/promtool.log')
    for path,name in (('/api/v1/targets','targets'),('/api/v1/query?query=knowledge_http_requests_total','http-series')):
        with urllib.request.urlopen('http://127.0.0.1:19090'+path,timeout=10) as response:
            (EVIDENCE/('candidate/'+name+'.json')).write_bytes(response.read())
    owned('vllm')
    docker('logs',NAMESPACE+'-vllm-1',log='candidate/vllm.log')
    docker('exec',NAMESPACE+'-backend-1','python','/instrument/generation_probe.py',log='candidate/generation-probe.log')
    copy_data('generation-diagnostic.json','candidate/generation-diagnostic.json')
    for name in ('backend','vllm','qdrant','neo4j','gateway'):
        info = owned(name)
        description = {'image_id':info['Image'],'command':info['Config']['Cmd'],
                       'environment':{k:v for k,v in (s.split('=',1) for s in info['Config']['Env'])
                                      if k in ('LLM_URL','LLM_MAX_MODEL_LEN','LLM_OUTPUT_TOKENS','LLM_SAFETY_MARGIN',
                                               'TEST_NAMESPACE','PROFILE_WAL_ANCHOR','HF_HUB_OFFLINE','TRANSFORMERS_OFFLINE')},
                       'mounts':[{k:m[k] for k in ('Type','Source','Destination','RW')} for m in info['Mounts']]}
        (EVIDENCE/('candidate/'+name+'-configuration.json')).write_text(json.dumps(description,indent=2))
    execute('backend.bundle',log='candidate/bundle-module.log')
    docker('exec',NAMESPACE+'-backend-1','python','-c',
           'import json; from backend.bundle import identity; print(json.dumps(identity()))',log='candidate/image-bundle.json')
    info = json.loads(docker('info','--format','{{json .}}').stdout)
    safe = {k:info.get(k) for k in ('ServerVersion','NCPU','MemTotal','OperatingSystem','KernelVersion','Driver')}
    (EVIDENCE/'candidate/docker-info.json').write_text(json.dumps(safe,indent=2))
    docker('exec',NAMESPACE+'-backend-1','python','-c',
           'import os,json; from backend.core import Store; s=Store(os.environ["DB_PATH"]); '
           'db=s.connect(); c=db.__enter__(); print(json.dumps(dict(c.execute("SELECT * FROM index_releases WHERE version=(SELECT value FROM service_state WHERE name=\'active_index\')").fetchone()))); db.__exit__(None,None,None)',
           log='candidate/active-index.json')


def tools(output, independent=False):
    target = EVIDENCE/output
    if (target/'run.log').exists():
        raise ValueError('Choose a new evidence label; prior run is preserved')
    target.mkdir(parents=True, exist_ok=True)
    args = ['run','--rm','--network','none','--mount',f'type=bind,source={ROOT.as_posix()},target=/app,readonly',
            '--mount',f'type=bind,source={target.as_posix()},target=/evidence',
            '-e','DB_PATH=/tmp/test.db','-e','AUTH_FILE=/tmp/absent.json','-e','PYTHONDONTWRITEBYTECODE=1',
            '-e','COVERAGE_FILE=/tmp/.coverage','-e','MYPY_CACHE_DIR=/tmp/mypy','-e','RUFF_CACHE_DIR=/tmp/ruff',
            '--entrypoint','python',TOOLS]
    if independent:
        args += ['-m','pytest','tests/test_independent_final.py','-q','-p','no:cacheprovider','--junitxml=/evidence/junit.xml']
    else:
        args += ['tools/verify.py','--output','/evidence/verification.json']
    return docker(*args, log=output+'/run.log', check=not independent)


def prepare():
    if CONFIG.exists():
        raise ValueError('This stand already exists; use configure instead of prepare')
    BASE.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    runtime = BASE/'runtime'
    runtime.mkdir(exist_ok=True)
    # Resolve existing config without starting or changing the user's stack.
    config = json.loads(docker('compose','-f','infra/compose.yaml','-f','infra/compose.indexes.yaml',
                               '-f','infra/compose.gpu.yaml','config','--format','json').stdout)
    config['name'] = NAMESPACE
    for volume in config.get('volumes', {}).values():
        volume.pop('name', None)
    for network in config['networks'].values():
        network.pop('name', None)
    backend = config['services']['backend']
    backend.pop('build', None)
    backend['image'] = OLD
    backend['volumes'] = [{'type':'bind','source':runtime.as_posix(),'target':'/app/data'}]
    backend['environment']['TEST_NAMESPACE'] = NAMESPACE
    backend['environment']['PYTHONDONTWRITEBYTECODE'] = '1'
    backend['environment'].pop('LLM_URL', None)
    backend['depends_on'].pop('vllm', None)
    neo4j = config['services']['neo4j']
    for volume in neo4j['volumes']:
        if volume['type'] == 'bind':
            volume['source'] = (runtime/'neo4j-password.txt').as_posix()
    for service in config['services'].values():
        for volume in service.get('volumes', []):
            if volume['type'] == 'volume' and volume['source'].startswith('course-knowledge_'):
                volume['source'] = volume['source'].removeprefix('course-knowledge_')
    # Include only disposable vLLM service; same weights mounted read-only.
    config['services']['vllm']['profiles'] = ['gpu']
    CONFIG.write_text(json.dumps(config, indent=2), encoding='utf-8')
    docker('run','--rm','--network','none','--mount',f'type=bind,source={runtime.as_posix()},target=/app/data',
           '--entrypoint','python',OLD,'-m','backend.init_demo',log='baseline/init.log')
    docker('ps','-a','--format','{{.ID}} {{.Names}} {{.Status}}',log='baseline/docker-before.txt')
    docker('image','inspect',OLD,'--format','{{.Id}}',log='baseline/image-id.txt')
    compose('up','-d','--no-build','--pull','never',log='baseline/start-cpu.log')


def configure(image, gpu=False, profile=False, anchor=False, lifecycle=False):
    config = json.loads(CONFIG.read_text(encoding='utf-8'))
    backend = config['services']['backend']
    backend['image'] = image
    backend['volumes'] = [v for v in backend['volumes'] if v['target'] != '/instrument']
    backend['volumes'].append({'type':'bind','source':(ROOT/'tools').as_posix(),'target':'/instrument','read_only':True})
    backend.pop('entrypoint', None)
    backend['environment'].pop('PROFILE_OUTPUT', None)
    backend['environment']['PROFILE_WAL_ANCHOR'] = '1' if anchor else '0'
    backend['environment']['PROFILE_HTTP'] = '1' if lifecycle else '0'
    if profile:
        backend['entrypoint'] = ['python','/instrument/profile_server.py']
        backend['environment']['PROFILE_OUTPUT'] = '/app/data/profile.jsonl'
    if gpu:
        backend['environment']['LLM_URL'] = 'http://vllm:8000'
        backend['depends_on']['vllm'] = {'condition':'service_healthy','required':True}
    else:
        backend['environment'].pop('LLM_URL', None)
        backend['depends_on'].pop('vllm', None)
    CONFIG.write_text(json.dumps(config, indent=2), encoding='utf-8')
    compose(*(['--profile','gpu'] if gpu else []),'up','-d','--no-build','--pull','never',log='startup-'+str(time.time_ns())+'.log')


def benchmark(label, count, concurrency):
    target = label+'.json'
    if (EVIDENCE/target).exists() or (EVIDENCE/(label+'.log')).exists():
        raise ValueError('Evidence already exists: '+target)
    # Warmup is separate, never counted in the measured run.
    execute('backend.benchmark', ['--url','http://gateway:18080','--requests','8','--concurrency',str(concurrency),
                                '--output','/app/data/warmup.json'],log=label+'-warmup.log')
    profile = BASE/'runtime/profile.jsonl'
    offset = profile.stat().st_size if profile.exists() else 0
    info = owned('backend')
    profiled = any(m['Destination']=='/instrument' for m in info['Mounts'])
    if profiled:
        with (EVIDENCE/(label+'-gpu.csv')).open('w', encoding='utf-8') as gpu_samples:
            sampler = subprocess.Popen(['nvidia-smi','--query-gpu=timestamp,utilization.gpu,memory.used,power.draw,temperature.gpu',
                                        '--format=csv','-l','1'],stdout=gpu_samples,stderr=subprocess.DEVNULL)
            try:
                docker('exec', NAMESPACE+'-backend-1', 'python', '/instrument/measure_http.py',
                       '--requests',str(count),'--concurrency',str(concurrency),
                       '--output','/app/data/measurement.json',log=label+'.log')
            finally:
                sampler.terminate()
                sampler.wait(timeout=10)
        copy_data('measurement.samples.json',label+'-samples.json')
        if any(x.startswith('LLM_URL=') for x in info['Config']['Env']):
            for suffix in ('before','after'):
                copy_data('measurement.'+suffix+'.prom',label+'-'+suffix+'.prom')
    else:
        execute('backend.benchmark', ['--url','http://gateway:18080','--requests',str(count),'--concurrency',str(concurrency),
                                    '--output','/app/data/measurement.json'],log=label+'.log')
    copy_data('measurement.json', target)
    server_profile = 'PROFILE_OUTPUT=/app/data/profile.jsonl' in info['Config']['Env']
    if profile.exists() and server_profile:
        with profile.open('rb') as source:
            source.seek(offset)
            (EVIDENCE/(label+'-profile.jsonl')).write_bytes(source.read())
    info = owned('backend')
    (EVIDENCE/(label+'-artifact.json')).write_text(json.dumps({'image_id':info['Image'],'server_profiling':server_profile,
        'environment':{k:v for k,v in (x.split('=',1) for x in info['Config']['Env'])
                       if k in ('LLM_URL','LLM_MAX_MODEL_LEN','LLM_OUTPUT_TOKENS','LLM_SAFETY_MARGIN')},
        'timestamp':time.time()},indent=2))
    print((EVIDENCE/target).read_text(), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['prepare','independent','unit','configure','benchmark','checks','build','operations','stop'])
    parser.add_argument('--label', default='candidate')
    parser.add_argument('--image', default=OLD)
    parser.add_argument('--gpu', action='store_true')
    parser.add_argument('--profile', action='store_true')
    parser.add_argument('--anchor', action='store_true')
    parser.add_argument('--lifecycle', action='store_true')
    parser.add_argument('--count', type=int, default=48)
    parser.add_argument('--concurrency', type=int, default=4)
    args = parser.parse_args()
    if args.phase == 'prepare': prepare()
    elif args.phase == 'configure': configure(args.image,args.gpu,args.profile,args.anchor,args.lifecycle)
    elif args.phase == 'independent': tools(args.label,True)
    elif args.phase == 'unit': tools(args.label)
    elif args.phase == 'benchmark': benchmark(args.label,args.count,args.concurrency)
    elif args.phase == 'operations': operations()
    elif args.phase == 'build':
        docker('build','--network','none','-f','infra/Dockerfile.offline','-t','course-knowledge-final:20261020','.',log=args.label+'/build.log')
        image = docker('image','inspect','course-knowledge-final:20261020','--format','{{.Id}}').stdout.strip()
        (EVIDENCE/args.label/'build.json').write_text(json.dumps({'image_id':image,'timestamp':time.time(),'method':'offline prepared OS/OCR rebase'}))
    elif args.phase == 'checks':
        if (EVIDENCE/args.label/'integration.log').exists():
            raise ValueError('Choose a new label; existing integration evidence is preserved')
        execute('backend.integration_check',log=args.label+'/integration.log')
        copy_data('integration-result.json',args.label+'/integration.json')
        execute('backend.evaluate', ['--output','/app/data/evaluation.json']+(['--gpu'] if args.gpu else []),log=args.label+'/eval.log')
        copy_data('evaluation.json',args.label+'/eval.json')
        if args.gpu:
            execute('backend.gpu_check',log=args.label+'/gpu-regression.log')
            copy_data('gpu-regression.json',args.label+'/gpu-regression.json')
        else:
            execute('backend.stack_check',log=args.label+'/stack.log')
            copy_data('stack-regression.json',args.label+'/stack.json')
    elif args.phase == 'stop':
        for service in json.loads(CONFIG.read_text())['services']:
            owned(service)
        compose('--profile','gpu','stop',log='stop.log')


if __name__ == '__main__': main()

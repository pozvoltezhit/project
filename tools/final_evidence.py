"""Summarize existing numeric evidence and inventory the delivered sources."""
import argparse
import hashlib
import json
import math
import statistics
import subprocess
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT/'docs/remediation/evidence/final-20261020'


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda:source.read(8*1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def percentiles(values):
    values = sorted(values)
    return {'p50':statistics.median(values),'p95':values[min(len(values)-1,int(.95*len(values)))],
            'p99':values[min(len(values)-1,int(.99*len(values)))], 'mean':statistics.mean(values),
            'total':sum(values), 'observations':len(values)}


def summary():
    result = {'timestamp':time.time(), 'runs':{}}
    for path in EVIDENCE.rglob('*-profile.jsonl'):
        name = path.relative_to(EVIDENCE).as_posix().removesuffix('-profile.jsonl')
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        stages = sorted({stage for row in rows for stage in row['stages']})
        record = {'requests':len(rows),'inclusive_stages_ms':{}, 'mode_counts':{},
                  'note':'Inclusive timings overlap. SQL execute excludes cursor consumption; thread CPU only. '
                         'Dependency-internal retries are unknown; legacy retries=0 was a default, not a measured retry count.'}
        for stage in stages:
            samples = [row['stages'][stage] for row in rows if stage in row['stages']]
            record['inclusive_stages_ms'][stage] = {
                **percentiles([x['seconds']*1000 for x in samples]),
                'invocations':sum(x['calls'] for x in samples),
                'thread_cpu_seconds':sum(x['cpu_seconds'] for x in samples)}
        for row in rows:
            mode = row.get('mode',row.get('error_type','unknown'))
            record['mode_counts'][mode] = record['mode_counts'].get(mode,0)+1
        record['tokenize_calls'] = sum(r['stages'].get('Generator.count_tokens',{}).get('calls',0) for r in rows)
        record['tokenize_bytes'] = sum(r.get('tokenize_request_bytes',0) for r in rows)
        record['input_tokens'] = sum(r.get('usage',{}).get('input_tokens',0) for r in rows)
        record['output_tokens'] = sum(r.get('usage',{}).get('output_tokens',0) for r in rows)
        before, after = [EVIDENCE/(name+'-'+s+'.prom') for s in ('before','after')]
        if before.exists() and after.exists():
            def metrics(path):
                return {line.split()[0]:float(line.split()[1]) for line in path.read_text().splitlines()
                        if line.startswith('vllm:') and len(line.split())>=2}
            first, last = metrics(before), metrics(after)
            delta = {key:last[key]-first.get(key,0) for key in last if key in first
                     and any(x in key for x in ('_sum{','_count{','_total{'))}
            record['vllm_deltas'] = delta
        result['runs'][name] = record
    (EVIDENCE/'profile-summary.json').write_text(json.dumps(result,indent=2))


def inventory():
    paths = []
    for folder in ('backend','frontend','eval','infra','tools','tests','.github','examples'):
        paths += [p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts
                  and p.name not in ('.env',) and p.suffix not in ('.pyc',)]
    paths += [ROOT/name for name in ('requirements.txt','requirements-lock.txt','requirements-dev.txt',
                                   'requirements-semantic.txt','pyproject.toml','.gitignore','.dockerignore',
                                   '.gitattributes','README.md','models/qwen-manifest.json')]
    files = {p.relative_to(ROOT).as_posix():{'sha256':sha(p),'size':p.stat().st_size} for p in sorted(set(paths))}
    digest = hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()
    report = {'format':'source-delivery-inventory-v1','timestamp':time.time(),'sha256':digest,'files':files,
              'scope':'Explicit source/config/test/tool allowlist; runtime credentials/data/weights/.git excluded',
              'runtime_bundle':'Separately compared with content-addressed application image'}
    (EVIDENCE/'source-inventory.json').write_text(json.dumps(report,indent=2))
    status = subprocess.run(['git','status','--porcelain=v1'],cwd=ROOT,capture_output=True,text=True,check=True)
    (EVIDENCE/'git-status.txt').write_text(status.stdout,encoding='utf-8')
    tracked = subprocess.run(['git','ls-files','-z'],cwd=ROOT,capture_output=True,check=True).stdout.decode().split('\0')
    risks = [name for name in tracked if name and (name.startswith('data/') or
             (name.startswith('models/') and name != 'models/qwen-manifest.json'))]
    large = [{'path':name,'bytes':(ROOT/name).stat().st_size} for name in tracked if name and (ROOT/name).exists()
             and (ROOT/name).stat().st_size>10*1024*1024]
    (EVIDENCE/'git-hygiene.json').write_text(json.dumps({'tracked_runtime_artifacts':risks,'large_tracked':large,
        'commit':'NOT CREATED','remote_ci':'NOT RUN','staged_changes':'Preserved; no add/reset/commit performed'},indent=2))
    model = json.loads((ROOT/'models/qwen-manifest.json').read_text())
    model_records = []
    for item in model['files']:
        path = ROOT/'models/qwen-awq'/item['name']
        actual = sha(path)
        model_records.append({'name':item['name'],'sha256':actual,'size':path.stat().st_size,
                              'matches':actual==item['sha256'] and path.stat().st_size==item['size']})
    (EVIDENCE/'model-hashes.json').write_text(json.dumps({'repository':model['repository'],'revision':model['revision'],
        'timestamp':time.time(),'files':model_records,'decision':'PASS' if all(r['matches'] for r in model_records) else 'FAIL'},indent=2))
    archive = ROOT/'data/final-20261020/source-bundle.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(2026,10,20,0,0,0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            bundle.writestr(info,(ROOT/name).read_bytes())
    (EVIDENCE/'source-archive.json').write_text(json.dumps({'path':'data/final-20261020/source-bundle.zip',
        'sha256':sha(archive),'size':archive.stat().st_size,'inventory_sha256':digest,
        'scope':'Reproducible source/config/test fixtures; documentation/video/evidence delivered separately'},indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['summary','inventory'])
    args = parser.parse_args()
    summary() if args.phase == 'summary' else inventory()

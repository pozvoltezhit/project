"""Bind the unchanged release gate to this iteration's actual image and evidence."""
import argparse
import hashlib
import json
import shutil
import sys
import time
import zipfile
from pathlib import Path

import llm_quality_runtime as runtime
from final_evidence import sha

stand=runtime.stand
ROOT=stand.ROOT
EVIDENCE=runtime.EVIDENCE
sys.path.insert(0,str(ROOT))


def read(name):
    return json.loads((EVIDENCE/name).read_text(encoding='utf-8'))


def collect():
    for service in ('backend','vllm','qdrant','neo4j','gateway'):
        info=stand.owned(service)
        safe={'image_id':info['Image'],'command':info['Config']['Cmd'],
              'mounts':[{k:m[k] for k in ('Type','Source','Destination','RW')} for m in info['Mounts']],
              'environment':{k:v for k,v in (item.split('=',1) for item in info['Config']['Env'])
                             if k in ('LLM_URL','LLM_MAX_MODEL_LEN','LLM_OUTPUT_TOKENS','LLM_SAFETY_MARGIN',
                                      'HF_HUB_OFFLINE','TRANSFORMERS_OFFLINE','TEST_NAMESPACE')}}
        (EVIDENCE/('selected/'+service+'-configuration.json')).write_text(json.dumps(safe,indent=2))
    stand.docker('exec',stand.NAMESPACE+'-backend-1','python','-c',
                 'import json; from backend.bundle import identity; print(json.dumps(identity()))',
                 log='selected/image-bundle.json')
    stand.docker('exec',stand.NAMESPACE+'-backend-1','python','-c',
                 'import json,os; from backend.core import Store; s=Store(os.environ["DB_PATH"]); '
                 'db=s.connect(); c=db.__enter__(); '
                 'print(json.dumps(dict(c.execute("SELECT * FROM index_releases WHERE version=(SELECT value FROM service_state WHERE name=\'active_index\')").fetchone()))); '
                 'db.__exit__(None,None,None)',log='selected/active-index.json')
    model=json.loads((ROOT/'models/qwen-manifest.json').read_text())
    records=[]
    for item in model['files']:
        path=ROOT/'models/qwen-awq'/item['name']
        actual=sha(path)
        records.append({'name':item['name'],'sha256':actual,'size':path.stat().st_size,
                        'matches':actual==item['sha256'] and path.stat().st_size==item['size']})
    (EVIDENCE/'selected/model-hashes.json').write_text(json.dumps({'timestamp':time.time(),
        'repository':model['repository'],'revision':model['revision'],'files':records,
        'decision':'PASS' if all(r['matches'] for r in records) else 'FAIL'},indent=2))


def manifest():
    target=EVIDENCE/'release-manifest.json'
    if target.exists(): raise ValueError('Prior manifest is retained; do not overwrite')
    from backend.bundle import identity
    current=identity()
    assert read('selected/image-bundle.json')==current
    assert current==read('selected-freeze.json')['bundle']
    prior=json.loads((ROOT/'docs/remediation/evidence/final-20261020/release-manifest.json').read_text(encoding='utf-8'))
    assert all(current['files'][name]==prior['bundle']['files'][name] for name in ('eval/golden.json','eval/corpus.json','backend/release.py'))
    for name in ('selected/gpu/holdout.json','selected/cpu/holdout.json','selected/gpu/tuning.json','selected/cpu/tuning.json',
                 'selected/gpu/validation.json'):
        report=read(name)
        assert report['decision']=='PASS' and report['bundle_hash']==current['tree_sha256'],name
    assert read('selected/gpu/holdout.json')['quality']['direct_valid_llm_answer_rate']>=read('baseline/holdout.json')['quality']['direct_valid_llm_answer_rate']
    assert read('selected/gpu/golden-detail.json')['quality']['direct_valid_llm_answers']>=read('baseline/golden-detail.json')['quality']['direct_valid_llm_answers']
    for name in ('selected/gpu-48-c4.json','selected/gpu-192-c4.json'):
        report=read(name)
        assert report['errors']==0 and report['generation_modes']==['vllm'],name
        assert report['successful_rps']>=2.53 and report['p95_ms']<=1631.63,name
    assert read('selected/model-hashes.json')['decision']=='PASS'
    inputs={'eval':'selected/gpu/eval.json','unit':'selected/final-tests/verification.json',
            'cpu':'selected/cpu/integration.json','gpu':'selected/gpu/integration.json',
            'gpu-regression':'selected/gpu/gpu-regression.json'}
    image=read('selected/build.json')['image_id']
    command=['--image-digest',image]
    for key,name in inputs.items():
        filename='quality-release-'+key+'.json'
        shutil.copyfile(EVIDENCE/name,stand.BASE/'runtime'/filename)
        command+=['--'+key,'/app/data/'+filename]
    command+=['--output','/app/data/quality-release-manifest.json']
    stand.execute('backend.release',command,log='release-manifest.log')
    stand.copy_data('quality-release-manifest.json','release-manifest.json')
    result=read('release-manifest.json')
    assert result['readiness']['decision']=='GO' and result['bundle']==current
    for key,name in inputs.items():
        manifest_key='gpu_regression' if key=='gpu-regression' else key
        assert result['evidence_sha256'][manifest_key]==hashlib.sha256(json.dumps(read(name),sort_keys=True).encode()).hexdigest()
    supplemental=['selected/gpu/holdout.json','selected/cpu/holdout.json','selected/gpu/tuning.json',
                  'selected/cpu/tuning.json','selected/gpu/golden-detail.json','selected/model-hashes.json',
                  'selected/gpu-48-c4.json','selected/gpu-192-c4.json','selected/image-bundle.json','selected-freeze.json',
                  'selected/gpu/validation.json','selected/cpu/stack.json','selected/active-index.json']
    result['supplemental_evidence_sha256']={name:sha(EVIDENCE/name) for name in supplemental}
    result['runtime_configuration_sha256']={name+'-configuration.json':sha(EVIDENCE/('selected/'+name+'-configuration.json'))
                                           for name in ('backend','vllm','qdrant','neo4j','gateway')}
    result['supplemental_scope']='Frozen author-generated holdout and measured performance; production approval remains false'
    result['prepared_base_image_id']=read('selected/build.json')['base_image_id']
    result['evidence_contract']='LLM-selected canonical semantic units; server-resolved exact source text and offsets; final ACL unchanged'
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (EVIDENCE/'manifest-validation.json').write_text(json.dumps({'status':'PASS','timestamp':time.time(),
        'image_id':image,'runtime_bundle':current['tree_sha256'],'readiness':result['readiness'],
        'same_bundle_reports':True,'core_evidence_hashes_verified':True,'supplemental_evidence_hashes_verified':True,
        'commit_created':False,'remote_ci':'NOT RUN'},indent=2))


def inventory():
    paths=[]
    for folder in ('backend','frontend','eval','infra','tools','tests','.github','examples'):
        paths.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts
                     and p.name!='.env' and p.suffix!='.pyc')
    paths.extend(ROOT/name for name in ('requirements.txt','requirements-lock.txt','requirements-dev.txt',
        'requirements-semantic.txt','pyproject.toml','.gitignore','.dockerignore','.gitattributes','README.md','models/qwen-manifest.json'))
    files={p.relative_to(ROOT).as_posix():{'sha256':sha(p),'size':p.stat().st_size} for p in sorted(set(paths))}
    digest=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()
    (EVIDENCE/'source-inventory.json').write_text(json.dumps({'timestamp':time.time(),'sha256':digest,'files':files,
        'scope':'Explicit source/config/test/tool allowlist; runtime secrets/data/weights/.git excluded'},indent=2))
    archive=ROOT/'data/llm-quality-20261020/source-bundle.zip'
    archive.parent.mkdir(parents=True,exist_ok=True)
    if archive.exists(): raise ValueError('Archive already exists; preserve previous evidence')
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as output:
        for name in sorted(files):
            info=zipfile.ZipInfo(name,date_time=(2026,10,20,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o644<<16
            output.writestr(info,(ROOT/name).read_bytes())
    record={'path':archive.relative_to(ROOT).as_posix(),'sha256':sha(archive),'size':archive.stat().st_size,
            'inventory_sha256':digest,'scope':'Documentation/video/evidence delivered separately'}
    (EVIDENCE/'source-archive.json').write_text(json.dumps(record,indent=2))
    result=read('release-manifest.json')
    result['source_inventory_sha256']=digest;result['source_archive']=record
    (EVIDENCE/'release-manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    assert all(sha(ROOT/name)==item['sha256'] for name,item in files.items())


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['collect','manifest','inventory'])
    args=parser.parse_args()
    {'collect':collect,'manifest':manifest,'inventory':inventory}[args.phase]()

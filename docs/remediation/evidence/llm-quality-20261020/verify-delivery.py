"""Independent stdlib verification of the already tested local delivery."""
import hashlib
import json
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

E=Path(__file__).resolve().parent
ROOT=E.parents[3]
sys.path.insert(0,str(ROOT))
from backend.bundle import identity


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))


m=read(E/'release-manifest.json')
assert m['readiness']=={'decision':'GO','scope':'synthetic_mvp','production_approval':False,'reasons':[]}
assert identity()==m['bundle']==read(E/'selected/image-bundle.json')==read(E/'selected-freeze.json')['bundle']
inventory=read(E/'source-inventory.json')
assert hashlib.sha256(json.dumps(inventory['files'],sort_keys=True).encode()).hexdigest()==inventory['sha256']==m['source_inventory_sha256']
assert all(sha(ROOT/name)==item['sha256'] for name,item in inventory['files'].items())
archive=read(E/'source-archive.json')
assert archive==m['source_archive'] and sha(ROOT/archive['path'])==archive['sha256']
with zipfile.ZipFile(ROOT/archive['path']) as source:
    assert set(source.namelist())==set(inventory['files'])
    assert all(hashlib.sha256(source.read(name)).hexdigest()==item['sha256'] for name,item in inventory['files'].items())
inputs={'unit':'selected/final-tests/verification.json','cpu':'selected/cpu/integration.json',
        'gpu':'selected/gpu/integration.json','gpu_regression':'selected/gpu/gpu-regression.json','eval':'selected/gpu/eval.json'}
for key,name in inputs.items():
    report=read(E/name)
    assert report['bundle_hash']==m['bundle']['tree_sha256']
    assert m['evidence_sha256'][key]==hashlib.sha256(json.dumps(report,sort_keys=True).encode()).hexdigest()
for name,digest in m['supplemental_evidence_sha256'].items(): assert sha(E/name)==digest,name
for name,digest in m['runtime_configuration_sha256'].items(): assert sha(E/'selected'/name)==digest,name
assert read(E/'selected/backend-configuration.json')['image_id']==m['image_digest']
model=read(E/'selected/model-hashes.json')
assert model['decision']=='PASS' and len(model['files'])==11 and all(row['matches'] for row in model['files'])
assert {r['name']:r['sha256'] for r in model['files']}=={r['name']:r['sha256'] for r in m['model_manifest']['files']}
junit=ET.parse(E/'selected/final-tests/junit.xml')
assert sum(int(s.get('tests',0)) for s in junit.iter('testsuite'))==69
assert all(int(s.get(k,0))==0 for s in junit.iter('testsuite') for k in ('errors','failures','skipped'))
frozen=read(E/'validation-freeze.json')
validation=read(E/'selected/gpu/validation.json')
assert frozen['dataset_sha256']==sha(ROOT/'eval/llm-quality-validation.json')==validation['dataset_hash']
assert frozen['timestamp']<read(E/'selected-freeze.json')['timestamp']<validation['timestamp']
assert validation['decision']=='PASS' and validation['quality']['direct_valid_llm_answers']==16
raw=ROOT/'data/final-20261020/runtime/quality-release-manifest.json'
assert read(raw)['readiness']==m['readiness']
assert read(raw)['bundle']==m['bundle'] and read(raw)['evidence_sha256']==m['evidence_sha256']
shutil.copyfile(raw,E/'release-manifest.gate.json')
documentation=['README.md','docs/SYSTEM-MODEL-CARD.md']+['docs/remediation/'+name for name in (
    'FINAL-READINESS.md','LLM-QUALITY-INVESTIGATION.md','QUALITY-REPORT.md','PERFORMANCE-ANALYSIS.md',
    'RUNBOOK.md','DEFENSE-PACK.md','REGRESSION-RESULTS.md','RELEASE-READINESS.md','REMEDIATION-REPORT.md',
    'INDEPENDENT-VERIFICATION.md','TECH-DEBT.md')]
m['documentation_sha256']={name:sha(ROOT/name) for name in documentation}
m['supplemental_evidence_sha256']['verify-delivery.py']=sha(Path(__file__))
m['supplemental_evidence_sha256']['release-manifest.gate.json']=sha(E/'release-manifest.gate.json')
m['supplemental_evidence_sha256']['performance-summary.json']=sha(E/'performance-summary.json')
(E/'release-manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2),encoding='utf-8')
status=subprocess.run(['git','-c','safe.directory='+str(ROOT),'status','--porcelain=v1'],cwd=ROOT,
                      capture_output=True,text=True,encoding='utf-8',check=True)
(E/'git-status-final.txt').write_text(status.stdout,encoding='utf-8')
result={'status':'PASS','timestamp':time.time(),'manifest_sha256':sha(E/'release-manifest.json'),
        'image_id':m['image_digest'],'bundle':m['bundle']['tree_sha256'],
        'source_files':len(inventory['files']),'archive_sha256':archive['sha256'],
        'core_reports_verified':len(inputs),'supplemental_files_verified':len(m['supplemental_evidence_sha256']),
        'documentation_files_bound':len(documentation),'model_files_verified':11,'tests':69,'failures':0,'skipped':0,
        'frozen_validation_order_verified':True,'raw_strict_gate_preserved':True,
        'readiness':m['readiness'],'commit_created':False,'remote_ci':'NOT RUN'}
(E/'delivery-validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))

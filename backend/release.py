"""Evidence-bound local release manifest. Missing GPU/evaluation means HOLD."""
import argparse
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path
from backend.bundle import identity
from backend.evaluate import ROOT, fingerprint, gate
from backend.budget import PROMPT_VERSION


def decision(evaluation, unit, cpu, gpu, gpu_regression, current_bundle, now=None):
    now=time.time() if now is None else now
    evaluation,unit,cpu,gpu,gpu_regression=[r if isinstance(r,dict) else {} for r in (evaluation,unit,cpu,gpu,gpu_regression)]
    expected={'dataset_hash':fingerprint(ROOT/'eval/golden.json'),'corpus_hash':fingerprint(ROOT/'eval/corpus.json'),
              'model_version':'qwen-local','prompt_version':PROMPT_VERSION}
    reasons=list(gate(evaluation,expected,now)['reasons'])
    reports={'unit':unit,'cpu':cpu,'gpu':gpu,'gpu_regression':gpu_regression,'eval':evaluation}
    for name,report in reports.items():
        if not isinstance(report,dict) or report.get('bundle_hash')!=current_bundle:
            reasons.append(name+':missing_or_different_bundle')
        timestamp=report.get('timestamp',0)
        if type(timestamp) not in (int,float) or not 0 <= now-timestamp <= 86400:
            reasons.append(name+':stale_or_missing_timestamp')
    if unit.get('exit_code')!=0 or unit.get('tests',0)<=0: reasons.append('unit:not_passed')
    for name,report in (('cpu',cpu),('gpu',gpu)):
        if not str(report.get('checks','')).startswith('PASS'): reasons.append(name+':not_passed')
    if gpu.get('generation_mode')!='vllm': reasons.append('gpu:not_real_generation')
    if cpu.get('generation_mode')!='extractive': reasons.append('cpu:wrong_profile')
    if gpu_regression.get('decision')!='PASS': reasons.append('gpu_regression:not_passed')
    return {'decision':'HOLD' if reasons else 'GO','scope':'synthetic_mvp','production_approval':False,'reasons':reasons}


def create_manifest(image_digest, evaluation, unit, cpu, gpu, gpu_regression):
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',image_digest): raise ValueError('Content-addressed image identity required')
    bundle=identity()
    verdict=decision(evaluation,unit,cpu,gpu,gpu_regression,bundle['tree_sha256'])
    try:
        commit=subprocess.run(['git','rev-parse','HEAD'],capture_output=True,text=True,check=True,cwd=ROOT).stdout.strip()
    except (OSError,subprocess.CalledProcessError): commit=None
    model_path=ROOT/'models/qwen-manifest.json'
    model=json.loads(model_path.read_text()) if model_path.exists() else None
    return {'format':'knowledge-release-v1','timestamp':time.time(),'commit_sha':commit,'bundle':bundle,
            'image_digest':image_digest,'digest_kind':'docker_content_addressed_local_image_id',
            'model_manifest':model,'tokenizer_identity':'same local vLLM artifact and chat template',
            'index_schema':'v2-versioned-sql-pointer','prompt_version':evaluation.get('prompt_version'),
            'serving_budget':gpu_regression.get('cases',[{}])[0].get('usage',{}) if gpu_regression.get('cases') else {},
            'evaluation':{k:evaluation.get(k) for k in ('dataset_version','corpus_version','dataset_hash','corpus_hash','model_version','timestamp','gate')},
            'evidence_sha256':{name:hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest() for name,value in
                (('unit',unit),('cpu',cpu),('gpu',gpu),('gpu_regression',gpu_regression),('eval',evaluation))},
            'readiness':verdict,'promotion':'Use the same content-addressed image. Never rebuild for promotion.',
            'rollback':'Retain prior image and compatible index version; re-run readiness/security smoke before routing'}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--image-digest',required=True)
    for name in ('eval','unit','cpu','gpu','gpu-regression'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    def read(path):
        try:return json.loads(path.read_text()) if path.exists() else {}
        except (ValueError,OSError):return {}
    manifest=create_manifest(args.image_digest,read(args.eval),read(args.unit),read(args.cpu),read(args.gpu),read(args.gpu_regression))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest['readiness']))
    return 0 if manifest['readiness']['decision']=='GO' else 1


if __name__=='__main__': raise SystemExit(main())

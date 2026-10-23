"""Reuse only the owned synthetic stand; preserve all prior iteration evidence."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

import finalize_runtime as stand

EVIDENCE = stand.ROOT/'docs/remediation/evidence/llm-quality-20261020'
BASELINE = 'sha256:2945daf417c2ff073a4cb3be97bbb5036fae0936710ee09545cac429459bd3bd'
stand.EVIDENCE = EVIDENCE


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase',choices=['start','probe','benchmark','checks','unit','build','stop','tuning','holdout','validation','golden-detail','stack'])
    parser.add_argument('--image',default=BASELINE)
    parser.add_argument('--label',default='baseline')
    parser.add_argument('--gpu',action='store_true')
    parser.add_argument('--count',type=int,default=48)
    parser.add_argument('--prompt',default='original')
    args = parser.parse_args()
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    if args.phase == 'start':
        stand.configure(args.image,args.gpu)
    elif args.phase == 'probe':
        target = EVIDENCE/(args.label+'.json')
        if target.exists(): raise ValueError('Prior evidence must be retained; choose a new label')
        stand.owned('backend')
        stand.docker('exec',stand.NAMESPACE+'-backend-1','python','/instrument/llm_quality_probe.py',
                     '--output','/app/data/quality-probe.json','--prompt',args.prompt,
                     log=args.label+'.log')
        stand.copy_data('quality-probe.json',args.label+'.json')
    elif args.phase == 'benchmark':
        stand.benchmark(args.label,args.count,4)
    elif args.phase == 'unit':
        stand.tools(args.label)
    elif args.phase in ('tuning','holdout','validation','golden-detail'):
        target=EVIDENCE/(args.label+'.json')
        if target.exists(): raise ValueError('Prior evidence must be retained; choose a new label')
        stand.owned('backend')
        if args.phase == 'golden-detail':
            command=['python','/instrument/llm_quality_golden.py','--output','/app/data/quality-golden.json']
            filename='quality-golden.json'
        else:
            filename='quality-evaluation.json'
            name={'tuning':'golden.json','holdout':'llm-quality-holdout.json','validation':'llm-quality-validation.json'}[args.phase]
            dataset='/app/eval/'+name
            if args.phase in ('holdout','validation'):
                # Same frozen bytes can be evaluated by both the old image and
                # the candidate without rebuilding or modifying either image.
                dataset='/app/data/quality-holdout-frozen.json'
                shutil.copyfile(stand.ROOT/'eval'/name,stand.BASE/'runtime/quality-holdout-frozen.json')
            command=['python','/instrument/llm_quality_holdout.py','--dataset',dataset,
                     '--expected-sha',hashlib.sha256((stand.ROOT/'eval'/name).read_bytes()).hexdigest(),
                     '--output','/app/data/'+filename,'--prompt',args.prompt]
            if args.phase=='tuning': command.append('--tuning')
        if not args.gpu: command.append('--cpu')
        result=stand.docker('exec',stand.NAMESPACE+'-backend-1',*command,log=args.label+'.log',check=False)
        stand.copy_data(filename,args.label+'.json')
        if result.returncode: raise RuntimeError('Quality evaluation failed; retained '+str(target))
    elif args.phase == 'build':
        base=stand.docker('image','inspect','course-knowledge-audit:20261020','--format','{{.Id}}').stdout.strip()
        assert base=='sha256:185bfd1525b668d3483118d9203e2d80e4e502f14174a6b9b48fcb7ebb5227d1'
        # BuildKit treats a bare image ID in FROM as a registry repository.
        # Resolve and verify the retained local base tag before offline build.
        build_log=args.label+('/build-success.log' if (EVIDENCE/args.label/'build.log').exists() else '/build.log')
        stand.docker('build','--pull=false','--network','none','--build-arg',
            'BASE_IMAGE=course-knowledge-audit:20261020',
            '-f','infra/Dockerfile.offline','-t','course-knowledge-quality:20261020','.',log=build_log)
        image=stand.docker('image','inspect','course-knowledge-quality:20261020','--format','{{.Id}}').stdout.strip()
        (EVIDENCE/args.label/'build.json').write_text(json.dumps({'image_id':image,'base_image_id':base,'method':'offline prepared OS/OCR rebase'}))
    elif args.phase == 'checks':
        for module,filename in [('backend.integration_check','integration-result.json'),('backend.evaluate','evaluation.json')]:
            extra=['--output','/app/data/evaluation.json']+(['--gpu'] if args.gpu else []) if module.endswith('evaluate') else []
            stand.execute(module,extra,log=args.label+'/'+module.split('.')[-1]+'.log')
            stand.copy_data(filename,args.label+'/'+('eval.json' if module.endswith('evaluate') else 'integration.json'))
        if args.gpu:
            stand.execute('backend.gpu_check',log=args.label+'/gpu-regression.log')
            stand.copy_data('gpu-regression.json',args.label+'/gpu-regression.json')
    elif args.phase == 'stack':
        stand.execute('backend.stack_check',log=args.label+'/stack.log')
        stand.copy_data('stack-regression.json',args.label+'/stack.json')
    elif args.phase == 'stop':
        for service in json.loads(stand.CONFIG.read_text())['services']: stand.owned(service)
        stand.compose('--profile','gpu','stop',log='stop.log')


if __name__ == '__main__': main()

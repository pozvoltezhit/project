"""Observe the unchanged Golden evaluator, retaining pre-grounding model output."""
import argparse
import hashlib
import io
import json
import os
import sys
from collections import Counter
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,'/app')
from backend import core, evaluate, budget
from llm_quality_holdout import rejection_reasons


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    parser.add_argument('--cpu',action='store_true')
    args=parser.parse_args()
    traces=[]
    run=core.Agent.run
    network=core.urlopen
    pack=budget.TokenBudget.pack
    def capture(self,query,principal,*extra,**kwargs):
        raw=[];packed=[]
        def capture_pack(self,question,chunks):
            selected,count=pack(self,question,chunks)
            packed[:]=selected
            return selected,count
        def response(request,**options):
            with network(request,**options) as result: body=result.read()
            if request.full_url.endswith('/v1/chat/completions'): raw.append(json.loads(body))
            return io.BytesIO(body)
        sources={c['id']:c for c in self.store.allowed(principal)}
        with patch.object(core,'urlopen',side_effect=response), patch.object(budget.TokenBudget,'pack',capture_pack):
            result=run(self,query,principal,*extra,**kwargs)
        reasons=[reason for r in raw for reason in rejection_reasons(r,{c['id']:c for c in packed} if packed else sources)]
        traces.append({'query':query,'usage':result['usage'],'evidence':result['evidence'],
                       'status':result['status'],'raw_qwen_responses':raw,'grounding_rejections':reasons})
        return result
    with patch.object(core.Agent,'run',capture):
        report=evaluate.evaluate(llm_url=None if args.cpu else os.environ['LLM_URL'])
    by_query={r['query']:r for r in traces}
    golden=json.loads((evaluate.ROOT/'eval/golden.json').read_text(encoding='utf-8'))
    for case,row in zip([c for c in golden['cases'] if c['split']=='holdout'],report['cases']):
        trace=by_query.get(case['query'])
        if trace is None: trace=next((t for t in traces if t['query'].startswith(case['query'])),None)
        if trace: row['generation_trace']=trace
    report['prompt_sha256']=hashlib.sha256(budget.SYSTEM.encode()).hexdigest()
    report['grounding_rejections']=dict(Counter(reason for t in traces for reason in t['grounding_rejections']))
    report['modes']=dict(Counter(r['mode'] for r in report['cases']))
    positives=[r for c,r in zip([c for c in golden['cases'] if c['split']=='holdout'],report['cases'])
               if c['expected_behavior']=='answered' and c['id'] not in ('conflicts','oversized')]
    report['quality']={'direct_valid_llm_answers':sum(r['mode']=='vllm' and r['status']=='PASS' for r in positives),
                       'answerable_non_conflict_non_oversized_cases':len(positives),
                       'invalid_generation_fallbacks':report['modes'].get('extractive-invalid-generation',0),
                       'unreliable_answers_or_errors':report['failures']+report['invalid'],
                       'faithfulness_proxy':report['metrics']['extractive_groundedness'],
                       'annotated_answer_relevancy_proxy':1-(report['failures']+report['invalid'])/report['expected'],
                       'calibrated_semantic_entailment':None}
    report['tokens']={key:sum(t['usage'].get(key,0) for t in traces) for key in ('input_tokens','output_tokens')}
    report['limitations']=['Original Golden is a known regression set; adversarial generators are test fixtures, not Qwen',
                          'Source extraction and annotated coverage are proxies; no calibrated semantic judge']
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('completed','failures','invalid','gate','modes','quality')}))
    return 0 if report['gate']['decision']=='GO' else 1


if __name__=='__main__': raise SystemExit(main())

"""Evaluate frozen synthetic annotations; faithful extraction != arbitrary entailment."""
import argparse
import hashlib
import io
import json
import os
import statistics
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,'/app')
import backend.core as core
import backend.budget as budget
from backend.budget import PROMPT_VERSION, SYSTEM
from backend.bundle import identity
from backend.ingest import read_pages


def rejection_reasons(response,sources):
    try:
        evidence=json.loads(response['choices'][0]['message']['content'])['evidence']
    except (KeyError,IndexError,TypeError,ValueError):
        return ['schema_parsing']
    if not isinstance(evidence,list): return ['invalid_evidence_schema']
    if any(isinstance(e,dict) and 'source_id' in e for e in evidence):
        return [] if core.resolve_model_evidence(evidence,list(sources.values())) is not None else ['invalid_source_selection']
    reasons=[]
    for e in evidence:
        if not isinstance(e,dict) or e.get('chunk_id') not in sources:
            reasons.append('unknown_source_or_schema')
        elif not isinstance(e.get('quote'),str): reasons.append('invalid_quote_type')
        elif core.verified_span(sources[e['chunk_id']]['text'],e['quote']) is None:
            reasons.append('not_exact_substring' if e['quote'].strip() not in sources[e['chunk_id']]['text'] else 'boundary_or_ambiguity')
    return reasons


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--dataset',required=True)
    parser.add_argument('--expected-sha',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--cpu',action='store_true')
    parser.add_argument('--tuning',action='store_true')
    parser.add_argument('--prompt',default='original')
    args=parser.parse_args()
    dataset=Path(args.dataset)
    digest=hashlib.sha256(dataset.read_bytes()).hexdigest()
    assert digest==args.expected_sha,'Frozen annotations changed'
    data=json.loads(dataset.read_text(encoding='utf-8'))
    if args.prompt != 'original':
        budget.SYSTEM=json.loads(Path('/instrument/llm-quality-prompts.json').read_text(encoding='utf-8'))[args.prompt]
    if args.tuning:
        corpus=json.loads(Path('/app/eval/corpus.json').read_text(encoding='utf-8'))
        data={'version':data['version']+'-tuning','ocr_limitation':'No OCR cases in original tuning split',
              'cases':[dict(c,documents=corpus['documents'],roles=c['role'].split(','),
                            category='no_evidence' if c['expected_behavior']=='no_evidence' else 'original_tuning')
                       for c in data['cases'] if c['split']=='tuning']}
    report={'dataset_hash':digest,'dataset_version':data['version'],'synthetic':True,'timestamp':time.time(),
            'bundle_hash':identity()['tree_sha256'],'prompt_version':PROMPT_VERSION,
            'prompt_sha256':hashlib.sha256(budget.SYSTEM.encode()).hexdigest(),'cases':[],
            'limitations':['Author-generated annotations, not independent domain expert evaluation',
                          data['ocr_limitation'],'No proof of absence of overfitting or arbitrary semantic entailment']}
    modes=Counter();reasons=Counter();citations=[];durations=[]
    for case in data['cases']:
        start=time.perf_counter();raw=[];contexts=[]
        row={'id':case['id'],'category':case['category'],'query':case['query']}
        try:
            with tempfile.TemporaryDirectory() as tmp:
                store=core.Store(str(Path(tmp)/'holdout.db'))
                for d in case['documents']:
                    pages=read_pages(Path('/app')/d['ocr_file']) if 'ocr_file' in d else [d['text']]
                    store.ingest(d['id'],pages,d['tenant'],d['roles'])
                principal=core.Principal('holdout',case['tenant'],tuple(case['roles']))
                generator=core.Generator(None if args.cpu else os.environ['LLM_URL'])
                invoke=generator.invoke
                def captured(query,chunks):
                    contexts.extend(chunks)
                    return invoke(query,chunks)
                generator.invoke=captured
                original=core.urlopen
                def network(request,**kwargs):
                    with original(request,**kwargs) as response: body=response.read()
                    if request.full_url.endswith('/v1/chat/completions'): raw.append(json.loads(body))
                    return io.BytesIO(body)
                with patch.object(core,'urlopen',side_effect=network):
                    result=core.Agent(store,generator).run(case['query'],principal)
                sources={c['id']:c for c in store.allowed(principal)}
                valid=[]
                for e in result['evidence']:
                    c=sources.get(e['chunk_id'])
                    valid.append(bool(c and c['text'][e['start']:e['end']]==e['quote'] and c['version']==e['version']))
                citations.extend(valid)
                text=' '.join(e['quote'] for e in result['evidence'])
                returned={e['title'] for e in result['evidence']}
                facts=all(f in text for f in case['expected_facts'])
                support=set(case['expected_sources']).issubset(returned)
                support=set(case['expected_sources'])==returned
                if case['expected_behavior']=='no_evidence': support=not returned
                passed=result['status']==case['expected_behavior'] and facts and support and all(valid)
                if case['category']=='contradictory_evidence':
                    passed=passed and result['usage'].get('human_review_required') is True
                usage=result['usage'];mode=usage['mode'];modes[mode]+=1
                budget_ok=not usage['input_tokens'] or usage['input_tokens']+usage['reserved_output_tokens']+usage['safety_margin']<=usage['max_model_len']
                passed=passed and budget_ok
                failures=[]
                for response in raw: failures+=rejection_reasons(response,{c['id']:c for c in contexts})
                reasons.update(failures)
                row.update(status='PASS' if passed else 'FAIL',actual=result['status'],mode=mode,
                    usage=usage,llm_calls=len(raw),returned_sources=sorted(returned),facts_covered=facts,
                    citation_valid=all(valid),token_budget_ok=budget_ok,grounding_rejections=failures,
                    evidence=result['evidence'],raw_qwen_responses=raw)
        except Exception as error:
            row.update(status='INVALID',error_type=type(error).__name__,error=str(error),
                       llm_calls=len(raw),raw_qwen_responses=raw,
                       grounding_rejections=[reason for response in raw for reason in rejection_reasons(response,{c['id']:c for c in contexts})])
        elapsed=(time.perf_counter()-start)*1000;durations.append(elapsed)
        row['latency_ms']=round(elapsed,3);report['cases'].append(row)
    rows=report['cases'];completed=[r for r in rows if r['status']!='INVALID']
    report.update(expected=len(data['cases']),completed=len(completed),failures=sum(r['status']!='PASS' for r in rows),
        modes=dict(modes),grounding_rejections=dict(reasons),llm_calls=sum(r.get('llm_calls',0) for r in rows))
    positive=[r for r,c in zip(rows,data['cases']) if c['expected_behavior']=='answered' and c['category']!='contradictory_evidence']
    direct=sum(r.get('mode')=='vllm' and r.get('actual')=='answered' and r['status']=='PASS' for r in positive)
    report['quality']={'direct_valid_llm_answers':direct,'answerable_non_conflict_cases':len(positive),
        'direct_valid_llm_answer_rate':direct/len(positive),
        'correct_fallbacks':sum(r['status']=='PASS' and r.get('mode','').startswith('extractive') for r in rows),
        'invalid_generation_fallbacks':sum(r.get('mode')=='extractive-invalid-generation' for r in rows),
        'valid_llm_abstentions':sum(r['status']=='PASS' and r.get('actual')=='no_evidence' and r.get('mode')=='vllm' for r in rows),
        'unreliable_answers_or_errors':report['failures'],
        'citation_correctness':statistics.mean(citations) if citations else None,
        'extractive_source_faithfulness_proxy':statistics.mean(citations) if citations else None,
        'annotated_answer_relevancy_proxy':sum(r['status']=='PASS' for r in rows)/len(rows),
        'calibrated_llm_judge_faithfulness':None,'calibrated_llm_judge_answer_relevancy':None}
    durations.sort()
    report['latency_ms']={n:durations[min(len(durations)-1,int(q*len(durations)))] for n,q in [('p50',.5),('p95',.95),('p99',.99)]}
    report['tokens']={key:sum(r.get('usage',{}).get(key,0) for r in rows) for key in ('input_tokens','output_tokens')}
    report['decision']='PASS' if report['failures']==0 and len(completed)==len(rows) else 'FAIL'
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('expected','completed','failures','modes','quality','decision')}))
    return 0 if report['decision']=='PASS' else 1


if __name__=='__main__': raise SystemExit(main())

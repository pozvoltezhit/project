"""Versioned local synthetic evaluation. Deterministic proxies, no cloud judge."""
import argparse
import hashlib
import json
import math
import os
import random
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

from backend.budget import PROMPT_VERSION
from backend.core import Agent, Generator, Principal, Store, clean
from backend.bundle import identity

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {'id','query','expected_behavior','expected_sources','expected_facts','role','tenant','document_type','difficulty','tags','corpus_version','split'}
THRESHOLDS = {'recall_at_6':.9,'context_precision':.5,'citation_correctness':1.,'extractive_groundedness':1.,'annotated_fact_coverage':.9,'no_evidence_precision':1.}


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def gate(report, expected=None, now=None):
    if not isinstance(report,dict):
        return {'decision':'HOLD','scope':'synthetic_mvp_only','reasons':['invalid_report'],'production_approval':False,'threshold_status':'provisional'}
    reasons = []
    now = time.time() if now is None else now
    if type(report.get('expected')) is not int or report.get('expected',0) <= 0 or type(report.get('completed')) is not int or report.get('completed') != report.get('expected'):
        reasons.append('incomplete')
    if report.get('coverage') != 1 or report.get('invalid',1) != 0 or report.get('failures',1) != 0:
        reasons.append('invalid_or_failed_cases')
    if any(type(report.get(k)) is not int or report[k]<0 for k in ('invalid','failures','acl_leakage_count','token_budget_violations')):
        reasons.append('invalid_counter_types')
    if report.get('acl_leakage_count',1) != 0 or report.get('token_budget_violations',1) != 0:
        reasons.append('critical_invariant')
    timestamp=report.get('timestamp',0)
    if not isinstance(timestamp,(int,float)) or not math.isfinite(timestamp) or timestamp > now+60 or now-timestamp > 86400:
        reasons.append('stale_timestamp')
    if expected and any(report.get(k)!=v for k,v in expected.items()):
        reasons.append('bundle_mismatch')
    for name,minimum in THRESHOLDS.items():
        value = report.get('metrics',{}).get(name)
        if type(value) not in (int,float) or not math.isfinite(value) or not minimum <= value <= 1:
            reasons.append('metric:'+name)
    return {'decision':'HOLD' if reasons else 'GO','scope':'synthetic_mvp_only','reasons':reasons,'production_approval':False,'threshold_status':'provisional'}


class CapturingAgent(Agent):
    def rerank(self, state):
        result=super().rerank(state)
        self.retrieved=result['chunks']
        return result


class AdversarialGenerator:
    def __init__(self, scenario, store):
        self.scenario,self.store=scenario,store

    def invoke(self, query, rows):
        row=next((c for c in rows if c['title']=='negation'),rows[0])
        quote='разрешена.' if self.scenario=='clip' else 'Выдуманный факт.'
        if self.scenario=='revoked':
            with self.store.connect() as db: db.execute('DELETE FROM grants WHERE doc_id=?',(row['doc_id'],))
            quote=row['text']
        return [{'chunk_id':row['id'],'quote':quote}],{'mode':'adversarial-fixture','input_tokens':0,'output_tokens':0}


def load_fixture(dataset,corpus):
    golden=json.loads(Path(dataset).read_text(encoding='utf-8'))
    content=json.loads(Path(corpus).read_text(encoding='utf-8'))
    cases=golden['cases']
    if not cases or len({c['id'] for c in cases})!=len(cases):
        raise ValueError('Empty dataset or duplicate case IDs')
    for case in cases:
        if not REQUIRED <= case.keys() or case['split'] not in ('tuning','holdout') or case['corpus_version']!=content['version']:
            raise ValueError('Dataset schema/split/corpus mismatch')
        if not isinstance(case['expected_sources'],list) or not isinstance(case['expected_facts'],list):
            raise ValueError('Invalid annotations')
    if {c['split'] for c in cases}!={'tuning','holdout'}:
        raise ValueError('Independent tuning and holdout splits required')
    split_queries={split:{clean(c['query']).casefold().strip() for c in cases if c['split']==split} for split in ('tuning','holdout')}
    if split_queries['tuning'] & split_queries['holdout']:
        raise ValueError('Query contamination across tuning/holdout')
    return golden,content


def evaluate(dataset=ROOT/'eval/golden.json', corpus=ROOT/'eval/corpus.json', llm_url=None, limit=None):
    golden,content=load_fixture(dataset,corpus)
    holdout=[c for c in golden['cases'] if c['split']=='holdout']
    report=dict(dataset_version=golden['version'],corpus_version=content['version'],dataset_hash=fingerprint(dataset),
                corpus_hash=fingerprint(corpus),model_version='qwen-local' if llm_url else 'extractive-offline',
                prompt_version=PROMPT_VERSION,synthetic=True,expected=len(holdout),completed=0,coverage=0,
                invalid=0,failures=0,acl_leakage_count=0,token_budget_violations=0,cases=[],timestamp=time.time())
    report['bundle_hash']=identity()['tree_sha256']
    recalls=[];precisions=[];citations=[];grounding=[];facts=[];durations=[];no_evidence=[]
    for case in holdout[:limit]:
        started=time.perf_counter()
        row: dict[str,Any]={'id':case['id'],'tags':case['tags'],'document_type':case['document_type'],'tenant':case['tenant'],'role':case['role']}
        result: dict[str,Any]
        retrieved: list[dict[str,Any]]=[]
        try:
            with tempfile.TemporaryDirectory() as directory:
                store=Store(str(Path(directory)/'eval.db'))
                for document in content['documents']:
                    store.ingest(document['id'],[document['text']],document['tenant'],document['roles'])
                if case['id']=='poison':
                    try: store.ingest('poison',[case['query']],'factory',['staff'])
                    except ValueError: actual='quarantined'
                    else: actual='unsafe_ingest'
                    result={'status':actual,'evidence':[],'usage':{}}
                    retrieved=[]
                else:
                    query=case['query']
                    if case['id']=='ocr':
                        from backend.ingest import read_pages
                        store.ingest('ocr',read_pages(ROOT/'examples/scan-regulation.pdf'),'factory',['staff'])
                    if case['id']=='oversized':
                        rng=random.Random(20261020)
                        for i in range(6):
                            store.ingest('large-'+str(i),['Т-90 '+''.join(rng.choice('0123456789abcdefXYZ') for _ in range(970))],'factory',['staff'])
                        query += ' '+''.join(rng.choice('0123456789abcdefXYZ') for _ in range(1900))
                    p=Principal('eval-user',case['tenant'],tuple(case['role'].split(',')))
                    generator=AdversarialGenerator(case['id'],store) if case['id'] in ('clip','hallucination','revoked') else Generator(llm_url)
                    agent=CapturingAgent(store,generator)
                    result=agent.run(query,p)
                    retrieved=getattr(agent,'retrieved',[])
                    allowed={c['id']:c for c in store.allowed(p)}
                    for evidence in result['evidence']:
                        source=allowed.get(evidence['chunk_id'])
                        valid=source is not None and source['text'][evidence['start']:evidence['end']]==evidence['quote'] and source['version']==evidence['version']
                        citations.append(float(valid));grounding.append(float(valid and source is not None and evidence['quote']==source['text']))
                        report['acl_leakage_count']+=int(source is None)
                    usage=result['usage']
                    if usage.get('mode')=='vllm':
                        violation=usage['input_tokens']+usage['reserved_output_tokens']+usage['safety_margin']>usage['max_model_len']
                        report['token_budget_violations']+=int(violation)
                actual=result['status']
                text=' '.join(e['quote'] for e in result['evidence'])
                covered=all(f in text for f in case['expected_facts'])
                expected_sources=set(case['expected_sources'])
                selected={c['title'] for c in retrieved}
                if expected_sources:
                    recalls.append(len(selected&expected_sources)/len(expected_sources))
                    ranked=[]
                    for c in retrieved:
                        if c['title'] not in ranked: ranked.append(c['title'])
                    hits=0;total=0.
                    for i,title in enumerate(ranked,1):
                        if title in expected_sources: hits+=1;total+=hits/i
                    precisions.append(total/max(hits,1))
                    facts.append(float(covered))
                if actual=='no_evidence': no_evidence.append(float(case['expected_behavior']=='no_evidence'))
                row.update(status='PASS' if actual==case['expected_behavior'] and covered else 'FAIL',actual=actual,
                           retrieved_sources=sorted(selected),returned_sources=sorted({e['title'] for e in result['evidence']}),
                           expected_sources=case['expected_sources'],facts_covered=covered,mode=result['usage'].get('mode','none'))
                report['completed']+=1
                report['failures']+=int(row['status']=='FAIL')
        except Exception as error:
            row.update(status='INVALID',error_type=type(error).__name__)
            report['invalid']+=1
        elapsed=(time.perf_counter()-started)*1000
        durations.append(elapsed);row['latency_ms']=round(elapsed,2);report['cases'].append(row)
    report['coverage']=report['completed']/report['expected']
    mean=lambda values:statistics.mean(values) if values else None
    report['metrics']={'recall_at_6':mean(recalls),'context_precision':mean(precisions),'citation_correctness':mean(citations),
                       'extractive_groundedness':mean(grounding),'annotated_fact_coverage':mean(facts),'no_evidence_precision':mean(no_evidence),
                       'llm_judge_faithfulness':None,'llm_judge_answer_relevancy':None}
    durations.sort()
    report['latency_ms']={name:round(durations[min(len(durations)-1,int(q*len(durations)))],2) if durations else None for name,q in (('p50',.5),('p95',.95),('p99',.99))}
    report['slices']={}
    for key in ('document_type','tenant','role'):
        report['slices'][key]={value:{'n':sum(r[key]==value for r in report['cases']),'passed':sum(r[key]==value and r['status']=='PASS' for r in report['cases'])} for value in {r[key] for r in report['cases']}}
    report['gate']=gate(report)
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--dataset',type=Path,default=ROOT/'eval/golden.json')
    parser.add_argument('--corpus',type=Path,default=ROOT/'eval/corpus.json')
    parser.add_argument('--output',type=Path,default=ROOT/'data/eval-report.json')
    parser.add_argument('--gpu',action='store_true')
    parser.add_argument('--limit',type=int)
    args=parser.parse_args()
    if args.gpu and not os.environ.get('LLM_URL'): parser.error('GPU evaluation NOT RUN: LLM_URL required')
    try:
        report=evaluate(args.dataset,args.corpus,os.environ.get('LLM_URL') if args.gpu else None,args.limit)
    except (ValueError,KeyError,TypeError,OSError) as error:
        report={'expected':0,'completed':0,'coverage':0,'invalid':1,'failures':1,'error_type':type(error).__name__,'timestamp':time.time()}
        report['gate']=gate(report)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('expected','completed','coverage','invalid','failures','gate')},ensure_ascii=False))
    return 0 if report['gate']['decision']=='GO' else 1


if __name__=='__main__':
    raise SystemExit(main())

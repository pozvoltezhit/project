"""Authorized synthetic-only full lifecycle diagnostic, never production telemetry."""
import argparse
import difflib
import hashlib
import io
import json
import os
import sys
import time
import unicodedata
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,'/app')
import backend.core as core
import backend.budget as budget
from backend.bundle import identity
from backend.index_admin import configured

QUESTION = 'Как связан насос Н-17 с датчиком Д-8?'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    parser.add_argument('--prompt',default='original')
    args=parser.parse_args()
    if os.environ.get('TEST_NAMESPACE') != 'course-final-20261020':
        raise RuntimeError('Full-content debug is restricted to the owned synthetic stand')
    trace={'synthetic':True,'query':QUESTION,'expected_documents':['01-equipment.txt','02-control.txt'],
           'prompt_variant':args.prompt,'bundle_hash':identity()['tree_sha256'],'stages':{},'tokenization':[]}
    if args.prompt != 'original':
        prompts=json.loads(Path('/instrument/llm-quality-prompts.json').read_text(encoding='utf-8'))
        budget.SYSTEM=prompts[args.prompt]
    trace['system_prompt']=budget.SYSTEM
    trace['system_prompt_sha256']=hashlib.sha256(budget.SYSTEM.encode()).hexdigest()
    store=core.Store(os.environ['DB_PATH'])
    p=core.Principal('engineer-b','factory',('staff',))
    index=configured()
    trace['index_release']=index.active_release()
    patches=[]
    for name in ('retrieve','expand','rerank','validate'):
        original=getattr(core.Agent,name)
        def capture(self,state,fn=original,stage=name):
            update=fn(self,state)
            trace['stages'][stage]=update
            return update
        patches.append(patch.object(core.Agent,name,capture))
    original_pack=budget.TokenBudget.pack
    def pack(self,query,chunks):
        selected,count=original_pack(self,query,chunks)
        trace['packed_context']=selected
        trace['packed_messages']=budget.messages_for(query,selected)
        trace['budget']={'input_tokens':count,'output_reserve':self.output_tokens,'margin':self.margin,'limit':self.max_model_len}
        return selected,count
    patches.append(patch.object(budget.TokenBudget,'pack',pack))
    network=core.urlopen
    def capture_response(request,**kwargs):
        start=time.perf_counter()
        with network(request,**kwargs) as response:
            body=response.read()
        payload=json.loads(body)
        if request.full_url.endswith('/tokenize'):
            trace['tokenization'].append({'result':payload,'latency_ms':(time.perf_counter()-start)*1000})
        else:
            trace['raw_qwen_response']=payload
            trace['generation_latency_ms']=(time.perf_counter()-start)*1000
        return io.BytesIO(body)
    patches.append(patch.object(core,'urlopen',side_effect=capture_response))
    try:
        for item in patches: item.start()
        start=time.perf_counter()
        result=core.Agent(store,core.Generator(os.environ['LLM_URL']),index).run(QUESTION,p)
        trace['latency_ms']=(time.perf_counter()-start)*1000
        trace['final_result']=result
        content=trace.get('raw_qwen_response',{}).get('choices',[{}])[0].get('message',{}).get('content','{}')
        trace['raw_model_content']=content
        evidence=json.loads(content).get('evidence',[])
        sources={c['id']:c for c in trace.get('packed_context',[])}
        labels={f'S{i}':c for i,c in enumerate(trace.get('packed_context',[]),1)}
        diagnoses=[]
        for e in evidence:
            cid=e.get('chunk_id');quote=e.get('quote')
            d={'model_evidence':e}
            if 'source_id' in e:
                c=labels.get(e['source_id'])
                if c and set(e)=={'source_id'}:
                    cid=c['id'];quote=c['text']
                    d.update(resolved_chunk_id=cid,resolution='whitelisted complete source unit; no model-supplied quote or offset')
            if cid not in sources: d['reason']='unknown_source'
            elif not isinstance(quote,str): d['reason']='invalid_quote_type'
            else:
                text=sources[cid]['text']
                normalized=unicodedata.normalize('NFKC',quote).strip()
                d.update(source_text=text,source_title=sources[cid]['title'])
                span=core.verified_span(text,quote)
                d['reason']='accepted' if span else ('not_exact_substring' if normalized not in text else 'ambiguous_or_incomplete_boundary')
                d['diff']=list(difflib.ndiff(text.splitlines(),normalized.splitlines()))
                d['verified_span']=span
            diagnoses.append(d)
        trace['citation_diagnoses']=diagnoses
        # These markers belong only to restricted demo content, never staff context.
        assert all(c['tenant']=='factory' and not c['title'].startswith('secret') for c in trace.get('packed_context',[]))
        assert '987654321' not in json.dumps(trace,ensure_ascii=False)
        trace['index_unchanged']=index.active_release()==trace['index_release']
    finally:
        for item in reversed(patches): item.stop()
        index.qdrant.close();index.neo4j.close()
    Path(args.output).write_text(json.dumps(trace,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__': main()

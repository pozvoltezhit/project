"""Real GPU regression; requires local vLLM. Never touches serving indices."""
import json
import os
import random
import tempfile
import time
from pathlib import Path

from backend.budget import BudgetExceeded
from backend.core import Agent, Generator, Principal, Store
from backend.bundle import identity


def check():
    url = os.environ.get('LLM_URL')
    if not url:
        raise RuntimeError('GPU check NOT RUN: LLM_URL is required')
    records = []
    with tempfile.TemporaryDirectory() as directory:
        store = Store(str(Path(directory)/'gpu.db'))
        p = Principal('probe', 'synthetic', ('staff',))
        rng = random.Random(20261020)
        for i in range(6):
            text = 'Н-17 К-2: ' + ''.join(rng.choice('0123456789abcdefXYZ') for _ in range(970))
            store.ingest('technical-'+str(i), [text], 'synthetic', ['staff'])
        question = 'Н-17 К-2: ' + ''.join(rng.choice('0123456789abcdefXYZ') for _ in range(1900))
        result = Agent(store, Generator(url)).run(question, p)
        usage = result['usage']
        assert usage['mode'] == 'extractive-context-limited'
        assert usage['budget_input_tokens'] + usage['reserved_output_tokens'] + usage['safety_margin'] <= usage['max_model_len']
        records.append({'case':'F02-original','status':'PASS','usage':usage})
        store = Store(str(Path(directory)/'short.db'))
        store.ingest('short', ['Насос Н-17 подключен к контуру К-2.'], 'synthetic', ['staff'])
        result = Agent(store, Generator(url)).run('К чему подключен Н-17?', p)
        assert result['status'] == 'answered', result
        assert result['usage']['mode'] == 'vllm'
        usage = result['usage']
        assert usage['input_tokens'] + usage['reserved_output_tokens'] + usage['safety_margin'] <= usage['max_model_len']
        records.append({'case':'real-generation','status':'PASS','usage':usage})
        generator = Generator(url)
        try:
            generator.invoke('🧬'*2000, store.allowed(p))
        except BudgetExceeded:
            records.append({'case':'oversized-question','status':'PASS','outcome':'controlled-422'})
        else:
            raise AssertionError('Oversized token question not rejected')
    output = Path(os.environ.get('GPU_REPORT', '/app/data/gpu-regression.json'))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'decision':'PASS','timestamp':time.time(),'bundle_hash':identity()['tree_sha256'],'cases':records}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(records, ensure_ascii=False))


if __name__ == '__main__':
    check()

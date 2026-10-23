"""Original HTTP workload plus raw latency samples and vLLM metric snapshots."""
import argparse
import asyncio
import json
import os
import statistics
import sys
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, '/app')
from backend import benchmark


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--requests', type=int, required=True)
    parser.add_argument('--concurrency', type=int, required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    path = Path(args.output)
    original = statistics.median
    def median(samples):
        path.with_suffix('.samples.json').write_text(json.dumps({'sorted_http_ms':samples}))
        return original(samples)
    statistics.median = median
    def metrics(suffix):
        if os.environ.get('LLM_URL'):
            with urlopen(os.environ['LLM_URL']+'/metrics', timeout=5) as response:
                path.with_suffix(suffix+'.prom').write_bytes(response.read())
    metrics('.before')
    asyncio.run(benchmark.main(args.requests, args.concurrency, args.output, 'http://gateway:18080'))
    metrics('.after')


if __name__ == '__main__': main()

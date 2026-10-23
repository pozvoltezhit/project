"""Classify real model citation rejection on synthetic data without logging text."""
import io
import json
import os
import sys
import unicodedata
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, '/app')
import backend.core as core


def main():
    store = core.Store(os.environ['DB_PATH'])
    principal = core.Principal('engineer-b', 'factory', ('staff',))
    sources = {c['id']:c for c in store.allowed(principal)}
    urlopen = core.urlopen
    diagnostic = {}
    def capture(request, **kwargs):
        with urlopen(request, **kwargs) as response:
            body = response.read()
        if request.full_url.endswith('/v1/chat/completions'):
            result = json.loads(body)
            content = json.loads(result['choices'][0]['message']['content'])
            reasons = []
            for evidence in content.get('evidence', []):
                cid, quote = evidence.get('chunk_id'), evidence.get('quote')
                if cid not in sources:
                    reasons.append('unknown_source_id')
                elif not isinstance(quote, str):
                    reasons.append('malformed_quote')
                elif unicodedata.normalize('NFKC', quote).strip() not in sources[cid]['text']:
                    reasons.append('not_exact_substring')
                elif core.verified_span(sources[cid]['text'], quote) is None:
                    reasons.append('ambiguous_or_incomplete_unit_boundary')
                else:
                    reasons.append('accepted_span')
            diagnostic.update(evidence_count=len(reasons), reasons=reasons, usage=result['usage'])
        return io.BytesIO(body)
    with patch.object(core, 'urlopen', side_effect=capture):
        result = core.Agent(store, core.Generator(os.environ['LLM_URL'])).run(
            'Как связан насос Н-17 с датчиком Д-8?', principal)
    diagnostic.update(status=result['status'], mode=result['usage']['mode'],
                      note='Real inference; no prompt, quote, source ID or credentials logged')
    Path('/app/data/generation-diagnostic.json').write_text(json.dumps(diagnostic, indent=2))


if __name__ == '__main__': main()

"""Conservative extractive spans; no inference of semantic entailment."""
import re
import unicodedata


def resolve_model_evidence(evidence, chunks: list[dict]) -> list[dict] | None:
    """Resolve whitelisted local selections; never repair generated quotations.

    Legacy exact quotations remain accepted for callers using that schema.
    Mixed schemas, unknown labels and fabricated offsets fail closed.
    """
    if not isinstance(evidence,list) or len(evidence)>6:
        return None
    if any(isinstance(e,dict) and 'source_id' in e for e in evidence):
        sources={f'S{i}':c for i,c in enumerate(chunks,1)}
        selected=[]
        if len(evidence)>4: return None
        for e in evidence:
            if not isinstance(e,dict) or set(e)!={'source_id'}:
                return None
            label=e['source_id']
            if not isinstance(label,str) or label not in sources or label in selected:
                return None
            selected.append(label)
        resolved=[{'chunk_id':sources[label]['id'],'quote':sources[label]['text']} for label in selected]
    else:
        resolved=evidence
    sources={c['id']:c for c in chunks}
    if not all(isinstance(e,dict) and isinstance(e.get('chunk_id'),str) and e['chunk_id'] in sources
               and isinstance(e.get('quote'),str) and bool(e['quote'].strip())
               and verified_span(sources[e['chunk_id']]['text'],e['quote']) is not None for e in resolved):
        return None
    return resolved


def verified_span(text: str, quote: str) -> dict | None:
    quote = unicodedata.normalize('NFKC', quote).strip()
    if not quote or text.count(quote) != 1:
        return None
    start = text.index(quote)
    end = start + len(quote)
    if quote != text:
        before = text[:start].rstrip()
        if before and before[-1] not in '.!?':
            return None
        if end != len(text) and quote[-1] not in '.!?':
            return None
    # Return the whole semantic unit, including adjacent conditions/negations.
    # The selection remains verifiable, but never becomes a clipped assertion.
    return {'quote':text,'start':0,'end':len(text),'selection_start':start,'selection_end':end}


def semantic_chunks(text: str, target: int = 1000, max_unit: int = 4000) -> list[tuple[int, str]]:
    parts: list[tuple[int, str]] = []
    cursor = 0
    for paragraph in re.split(r'\n\s*\n', text):
        part = paragraph.strip()
        if not part:
            continue
        if len(part) > max_unit:
            raise ValueError('Semantic paragraph exceeds 4000 characters; split source at complete context boundaries')
        start = text.index(part, cursor)
        cursor = start + len(part)
        if parts and len(parts[-1][1]) + len(part) + 2 <= target:
            previous = parts.pop()
            parts.append((previous[0], text[previous[0]:cursor]))
        else:
            parts.append((start, part))
    return parts

"""Strict source binding and byte-preserving model evidence contracts."""
import json
from io import BytesIO
from unittest.mock import patch

import pytest

from backend.core import Generator
from backend.grounding import resolve_model_evidence
from backend.budget import messages_for


SOURCES = [
    {'id':'first','text':'Клапан М-42 связан с узлом У-31. При отказе запуск запрещён.'},
    {'id':'second','text':'Узел У-31 контролируется прибором Т-52. Порог 3.75 МПа.'},
]


def invoke(evidence):
    generator=Generator('http://localhost:8000')
    response={'usage':{'prompt_tokens':100,'completion_tokens':40},
              'choices':[{'message':{'content':json.dumps({'evidence':evidence},ensure_ascii=False)}}]}
    with patch.object(generator.budget,'counter',return_value=100), patch(
        'backend.core.urlopen',return_value=BytesIO(json.dumps(response).encode())
    ):
        return generator.invoke('Как связаны М-42 и Т-52?',SOURCES)


@pytest.mark.parametrize('evidence',[
    [{'chunk_id':'first','quote':'Узел У-31 контролируется прибором Т-52.'}],
    [{'chunk_id':'second','quote':'Клапан М-42 связан с узлом У-31.'}],
    [{'chunk_id':'invented','quote':SOURCES[0]['text']}],
    [{'chunk_id':'first','quote':'Клапан М-42 связан с узлом У-31。'}],
    [{'chunk_id':'first','quote':'Клапан М-42 связан с узлом У-31'}],
    [{'chunk_id':'second','quote':'Порог 3,75 МПа.'}],
])
def test_invalid_model_evidence_is_discarded_without_repair(evidence):
    result,usage=invoke(evidence)
    assert usage['mode']=='extractive-invalid-generation'
    assert result==[{'chunk_id':c['id'],'quote':c['text']} for c in SOURCES]


def test_valid_source_association_can_reverse_context_order():
    selected=[{'chunk_id':c['id'],'quote':c['text']} for c in reversed(SOURCES)]
    evidence,usage=invoke(selected)
    assert usage['mode']=='vllm'
    assert evidence==selected
    assert usage['input_tokens']==100 and usage['output_tokens']==40


def test_negation_condition_abbreviations_and_decimal_remain_verbatim():
    text='По ГОСТ Р 123.4, п. 3.2, запуск не разрешён.\nИсключение: только при 3.75 МПа и исправном У-31.'
    with patch.dict(SOURCES[0],text=text):
        selected=[{'chunk_id':'first','quote':text}]
        evidence,usage=invoke(selected)
    assert usage['mode']=='vllm' and evidence==selected


@pytest.mark.parametrize('selection',[
    [{'source_id':'S0'}], [{'source_id':'S3'}], [{'source_id':'S1'},{'source_id':'S1'}],
    [{'source_id':1}], [{'source_id':['S1']}], [{'source_id':'S1','start':0,'end':8}],
    [{'source_id':'S1','quote':'Подмена.'}], [{'source_id':'S1'},{'chunk_id':'second','quote':SOURCES[1]['text']}],
])
def test_selector_rejects_unknown_duplicate_offsets_and_mixed_schemas(selection):
    assert resolve_model_evidence(selection,SOURCES) is None
    evidence,usage=invoke(selection)
    assert usage['mode']=='extractive-invalid-generation'
    assert evidence==[{'chunk_id':c['id'],'quote':c['text']} for c in SOURCES]


def test_selector_resolves_only_the_selected_source_and_real_span():
    evidence,usage=invoke([{'source_id':'S2'}])
    assert usage['mode']=='vllm'
    assert evidence==[{'chunk_id':'second','quote':SOURCES[1]['text']}]
    assert resolve_model_evidence([{'source_id':'S2'}],list(reversed(SOURCES)))==[
        {'chunk_id':'first','quote':SOURCES[0]['text']}]
    wire=json.loads(messages_for('Вопрос',SOURCES)[1]['content'])
    assert wire['CONTEXT']==[{'source_id':f'S{i}','text':c['text']} for i,c in enumerate(SOURCES,1)]


def test_selector_abstention_remains_empty():
    assert resolve_model_evidence([],SOURCES)==[]

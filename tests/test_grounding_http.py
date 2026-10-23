import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.core import Agent, Generator, Principal, Store
from backend.grounding import semantic_chunks, verified_span


class GroundingTests(unittest.TestCase):
    def test_valid_empty_model_evidence_remains_an_abstention(self):
        from io import BytesIO
        source={'id':'source','text':'Работа Н-99 не разрешена.'}
        generator=Generator('http://localhost:8000')
        data={'usage':{'prompt_tokens':100,'completion_tokens':20},
              'choices':[{'message':{'content':json.dumps({'evidence':[]})}}]}
        with patch.object(generator.budget,'counter',return_value=100),patch('backend.core.urlopen',return_value=BytesIO(json.dumps(data).encode())):
            evidence,usage=generator.invoke('Н-99',[source])
        self.assertEqual(evidence,[])
        self.assertEqual(usage['mode'],'vllm')

    def test_budget_full_context_fast_path_is_exact_and_one_call(self):
        from backend.budget import TokenBudget, messages_for
        from unittest.mock import Mock
        counter=Mock(return_value=100)
        chunks=[{'id':'one','text':'Полный контекст.'}]
        packed,count=TokenBudget(counter).pack('Вопрос',chunks)
        counter.assert_called_once_with(messages_for('Вопрос',chunks))
        self.assertEqual((packed,count),(chunks,100))

    def test_real_generator_discards_invalid_model_quote_before_safe_fallback(self):
        from io import BytesIO
        source={'id':'source','text':'Работа Н-99 не разрешена.'}
        generator=Generator('http://localhost:8000')
        data={'usage':{'prompt_tokens':100,'completion_tokens':20},
              'choices':[{'message':{'content':json.dumps({'evidence':[{'chunk_id':'source','quote':'разрешена.'}]})}}]}
        with patch.object(generator.budget,'counter',return_value=100),patch('backend.core.urlopen',return_value=BytesIO(json.dumps(data).encode())):
            evidence,usage=generator.invoke('Разрешена ли работа Н-99?',[source])
        self.assertEqual(usage['mode'],'extractive-invalid-generation')
        self.assertEqual(evidence,[{'chunk_id':'source','quote':source['text']}])
        self.assertEqual(usage['input_tokens'],100)

    def test_negations_conditions_numbers_units_dates_preserved(self):
        examples=[
            ('Работа Н-99 не разрешена.','разрешена.'),
            ('Давление Н-17 не более 6 бар.','6 бар.'),
            ('Доступ только с 10.10.2026 до 20.10.2026.','20.10.2026.'),
            ('Запуск допускается, только если К-2 отключен.','К-2 отключен.'),
            ('Диапазон: от 5 до 10 °C.','10 °C.'),
        ]
        for text,clip in examples:
            with self.subTest(text=text):
                self.assertIsNone(verified_span(text,clip))
                span=verified_span(text,text)
                self.assertEqual(span['quote'],text)
                self.assertEqual(text[span['start']:span['end']],text)

    def test_previous_and_following_conditions_remain(self):
        text='Если контур отключен. Запуск Н-17 разрешен. Только после осмотра.'
        self.assertEqual(verified_span(text,'Запуск Н-17 разрешен.')['quote'],text)
        self.assertIsNone(verified_span(text,'Выдуманный факт.'))

    def test_paragraphs_are_never_sliced(self):
        text='Не разрешено '+('слово '*200)+'.'
        self.assertEqual(semantic_chunks(text)[0][1],text)
        with self.assertRaises(ValueError): semantic_chunks('x'*4001)

    def test_graph_cycles_limits_and_tenant(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(str(Path(tmp)/'graph.db'))
            p=Principal('b','factory',('staff',))
            for title,text,tenant,roles in [
                ('one','Н-17 связан с К-2.','factory',['staff']),
                ('two','К-2 связан с Д-8.','factory',['staff']),
                ('three','Д-8 связан с Н-17.','factory',['staff']),
                ('single','К-2 отключается при 120 °C.','factory',['staff']),
                ('secret','К-2 связан с П-99.','factory',['restricted']),
                ('other','К-2 связан с П-88.','other',['staff'])]:
                store.ingest(title,[text],tenant,roles)
            seeds=[c['id'] for c in store.allowed(p) if c['title']=='one']
            first=store.graph(p,seeds)
            self.assertEqual(first,store.graph(p,seeds))
            self.assertEqual({c['title'] for c in first[0]}, {'one','two','three','single'})
            self.assertNotIn('П-99',json.dumps(first,ensure_ascii=False))
            self.assertLessEqual(len(store.graph(p,seeds,max_chunks=2)[0]),2)


class HTTPTests(unittest.TestCase):
    def test_all_statuses_and_bounded_labels(self):
        from fastapi.testclient import TestClient
        import backend.api as api
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(str(Path(tmp)/'http.db'))
            store.ingest('doc',['Н-17 подключен к К-2.'],'factory',['staff'])
            p=Principal('a','factory',('staff',))
            agent=Agent(store)
            client=TestClient(api.app,raise_server_exceptions=False)
            api.app.dependency_overrides[api.principal]=lambda:p
            try:
                with patch.object(api,'store',store),patch.object(api,'agent',agent):
                    for exception,code in [(None,200),(PermissionError(),403),(ValueError(),422),(OSError(),503),(RuntimeError(),500)]:
                        before=sum(s.value for m in api.http_requests.collect() for s in m.samples if s.name=='knowledge_http_requests_total')
                        if exception is None:
                            response=client.post('/query',json={'question':'Н-17'})
                        else:
                            with patch.object(agent,'run',side_effect=exception):
                                response=client.post('/query',json={'question':'Н-17'})
                        self.assertEqual(response.status_code,code,response.text)
                        after=sum(s.value for m in api.http_requests.collect() for s in m.samples if s.name=='knowledge_http_requests_total')
                        self.assertEqual(after-before,1)
                    for value in ('user-one','user-two','token-secret'):
                        client.get('/missing/'+value)
                    names={s.labels.get('route') for m in api.http_requests.collect() for s in m.samples}
                    self.assertFalse(any('/missing/' in (n or '') for n in names))
                    schema=client.get('/openapi.json').json()
                    self.assertIn('BearerToken',schema['components']['securitySchemes'])
                    self.assertEqual(client.get('/ready').status_code,503)  # no provisioned identity
            finally:
                api.app.dependency_overrides.pop(api.principal,None)

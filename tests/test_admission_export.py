import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.admission import Admission
from backend.budget import TokenBudget
from backend.grounding import semantic_chunks, verified_span
from backend.quality_export import EvaluationCollector


class AdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_bounded_queue_and_rejection(self):
        entered,released=asyncio.Event(),asyncio.Event()
        async def app(scope,receive,send):
            entered.set();await released.wait()
            await send({'type':'http.response.start','status':200,'headers':[]})
            await send({'type':'http.response.body','body':b'ok'})
        with patch.dict(os.environ,{'MAX_ACTIVE_QUERIES':'1','MAX_QUEUED_QUERIES':'1','MAX_REQUESTS_PER_MINUTE':'10'}):
            admission=Admission(app)
        outputs=[]
        async def receive():return {'type':'http.request','body':b'','more_body':False}
        async def send(message):outputs.append(message)
        def run():return admission({'type':'http','path':'/query','method':'POST'},receive,send)
        first=asyncio.create_task(run());await entered.wait()
        second=asyncio.create_task(run());await asyncio.sleep(0)
        await run()
        self.assertTrue(any(m.get('status')==429 for m in outputs))
        released.set();await first;await second
        self.assertEqual(admission.running,0);self.assertEqual(admission.queued,0)

    async def test_invalid_limits_rejected(self):
        with patch.dict(os.environ,{'MAX_ACTIVE_QUERIES':'0'}):
            with self.assertRaises(ValueError):Admission(None)


class ExportPolicyTests(unittest.TestCase):
    def test_missing_and_malformed_eval_never_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'eval.json'
            with patch.dict(os.environ,{'QUALITY_REPORT_FILE':str(path)}):
                self.assertEqual(list(EvaluationCollector().collect()),[])
                for value in ('bad-json','[]','{"coverage":[]}'):
                    path.write_text(value)
                    metrics=list(EvaluationCollector().collect())
                    valid=next(m for m in metrics if m.name=='knowledge_eval_valid')
                    self.assertEqual(valid.samples[0].value,0)

    def test_budget_invalid_counts_and_configuration(self):
        for args in ((0,1,0),(1,1,0),(10,1,-1)):
            with self.assertRaises(ValueError):TokenBudget(lambda _:0,*args)
        with self.assertRaises(OSError):TokenBudget(lambda _:'wrong').pack('q',[])
        self.assertTrue(TokenBudget(lambda _:0).fits(0))
        self.assertEqual(semantic_chunks('\n\n'),[])
        self.assertEqual(len(semantic_chunks('First.\n\nSecond.')),1)
        self.assertIsNone(verified_span('First sentence. Second sentence.','First'))

import copy
import os
import time
import unittest
from unittest.mock import patch
from backend.evaluate import ROOT, THRESHOLDS, fingerprint
from backend.release import create_manifest, decision
from backend.finops import CostCollector
from backend.budget import PROMPT_VERSION
from prometheus_client import CollectorRegistry, Counter


class ReleaseTests(unittest.TestCase):
    def reports(self):
        evaluation=dict(expected=23,completed=23,coverage=1,invalid=0,failures=0,acl_leakage_count=0,
                        token_budget_violations=0,timestamp=time.time(),metrics={k:1 for k in THRESHOLDS},
                        dataset_hash=fingerprint(ROOT/'eval/golden.json'),corpus_hash=fingerprint(ROOT/'eval/corpus.json'),bundle_hash='tree')
        evaluation.update(model_version='qwen-local',prompt_version=PROMPT_VERSION)
        unit=dict(bundle_hash='tree',exit_code=0,tests=5,timestamp=time.time())
        cpu=dict(bundle_hash='tree',checks='PASS: isolated',generation_mode='extractive',timestamp=time.time())
        gpu=dict(bundle_hash='tree',checks='PASS: isolated',generation_mode='vllm',timestamp=time.time())
        regression=dict(bundle_hash='tree',decision='PASS',timestamp=time.time())
        return evaluation,unit,cpu,gpu,regression

    def test_all_bound_evidence_required(self):
        reports=self.reports()
        self.assertEqual(decision(*reports,'tree')['decision'],'GO')
        for i in range(len(reports)):
            bad=list(copy.deepcopy(reports));bad[i]={}
            self.assertEqual(decision(*bad,'tree')['decision'],'HOLD')
        bad=list(copy.deepcopy(reports));bad[3]['generation_mode']='extractive'
        self.assertEqual(decision(*bad,'tree')['decision'],'HOLD')
        with self.assertRaises(ValueError):create_manifest('latest',*reports)
        manifest=create_manifest('sha256:'+'0'*64,*reports)
        self.assertEqual(manifest['readiness']['decision'],'HOLD')  # deliberate fixture bundle mismatch
        self.assertFalse(manifest['readiness']['production_approval'])

    def test_finops_absence_and_configured_assumptions(self):
        counter=Counter('knowledge_requests','fixture',['status'],registry=CollectorRegistry())
        collector=CostCollector(counter)
        with patch.dict(os.environ,{},clear=True):self.assertEqual(list(collector.collect()),[])
        counter.labels('answered').inc(2)
        with patch.dict(os.environ,{'COST_LOCAL_RUB_PER_HOUR':'60','COST_ESTIMATED_POWER_WATTS':'200','COST_RUB_PER_KWH':'6'}):
            metrics=list(collector.collect())
        self.assertTrue(metrics)
        self.assertTrue(any('rub_per_answer' in metric.name for metric in metrics))

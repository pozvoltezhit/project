import copy
import json
import tempfile
import time
import unittest
from pathlib import Path

from backend.evaluate import ROOT, THRESHOLDS, gate, load_fixture


class QualityGateTests(unittest.TestCase):
    def valid_report(self):
        return dict(expected=23,completed=23,coverage=1,invalid=0,failures=0,acl_leakage_count=0,
                    token_budget_violations=0,timestamp=time.time(),metrics={k:1. for k in THRESHOLDS},dataset_hash='current')

    def test_complete_report_can_pass_only_synthetic_scope(self):
        result=gate(self.valid_report(),{'dataset_hash':'current'})
        self.assertEqual(result['decision'],'GO')
        self.assertFalse(result['production_approval'])

    def test_missing_stale_incomplete_invalid_and_critical_hold(self):
        changes=[{'completed':22},{'expected':0},{'coverage':.99},{'invalid':1},{'failures':1},
                 {'acl_leakage_count':1},{'token_budget_violations':1},
                 {'timestamp':time.time()-86401},{'metrics':{}},{'metrics':{k:float('nan') for k in THRESHOLDS}}]
        for change in changes:
            report=self.valid_report();report.update(change)
            self.assertEqual(gate(report)['decision'],'HOLD',change)
        self.assertEqual(gate(self.valid_report(),{'dataset_hash':'old'})['decision'],'HOLD')
        self.assertEqual(gate({})['decision'],'HOLD')

    def test_duplicate_ids_and_split_contamination_rejected(self):
        original=json.loads((ROOT/'eval/golden.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bad.json'
            for scenario in ('duplicate','split','version','missing'):
                data=copy.deepcopy(original)
                if scenario=='duplicate':data['cases'][1]['id']=data['cases'][0]['id']
                if scenario=='split':data['cases'][4]['query']=data['cases'][0]['query']
                if scenario=='version':data['cases'][4]['corpus_version']='wrong'
                if scenario=='missing':del data['cases'][4]['tenant']
                path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):load_fixture(path,ROOT/'eval/corpus.json')

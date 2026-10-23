"""Evaluation telemetry is absent when no report exists; never substitute zero."""
import json
import os
import math
from pathlib import Path
from prometheus_client.core import GaugeMetricFamily
from backend.bundle import identity
from backend.evaluate import ROOT, fingerprint, gate


class EvaluationCollector:
    def collect(self):
        path=Path(os.environ.get('QUALITY_REPORT_FILE',str(ROOT/'data/eval-report.json')))
        if not path.exists():return
        try:
            report=json.loads(path.read_text())
            if not isinstance(report,dict): raise ValueError('Invalid evaluation report')
            expected={'dataset_hash':fingerprint(ROOT/'eval/golden.json'),'corpus_hash':fingerprint(ROOT/'eval/corpus.json')}
            good=gate(report,expected)['decision']=='GO' and report.get('bundle_hash')==identity()['tree_sha256']
            mode='qwen-local' if os.environ.get('LLM_URL') else 'extractive-offline'
            good=good and report.get('model_version')==mode
            values={'valid':int(good),'expected':report.get('expected',0),'completed':report.get('completed',0),
                    'coverage':report.get('coverage',0),'invalid':report.get('invalid',1),'failures':report.get('failures',1),
                    'last_completed_timestamp_seconds':report.get('timestamp',0)}
            if any(type(value) not in (int,float) or not math.isfinite(value) for value in values.values()):
                raise ValueError('Invalid evaluation metrics')
        except (ValueError,KeyError,TypeError,OSError):
            values={'valid':0,'invalid':1}
        for name,value in values.items():
            metric=GaugeMetricFamily('knowledge_eval_'+name,'Synthetic evaluation snapshot; no production approval')
            metric.add_metric([],value);yield metric

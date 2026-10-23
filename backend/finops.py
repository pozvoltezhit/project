"""Opt-in configured local-cost estimates. Not billing or measured power."""
import os
import time
import math
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily


class CostCollector:
    def __init__(self, business_requests):
        self.business_requests=business_requests
        self.started=time.monotonic()

    def collect(self):
        rate=os.environ.get('COST_LOCAL_RUB_PER_HOUR')
        power=os.environ.get('COST_ESTIMATED_POWER_WATTS')
        electricity=os.environ.get('COST_RUB_PER_KWH')
        if rate is None or power is None or electricity is None:
            return  # Absence means unconfigured, never a fictitious zero bill.
        try:hourly,watts,kwh=map(float,(rate,power,electricity))
        except ValueError:return
        if min(hourly,watts,kwh)<0 or not all(math.isfinite(v) for v in (hourly,watts,kwh)): return
        seconds=time.monotonic()-self.started
        cost=seconds*(hourly/3600+watts*kwh/3_600_000)
        total=CounterMetricFamily('knowledge_estimated_cost_rub','Configured local cost allocation, includes idle time')
        total.add_metric([],cost);yield total
        hours=CounterMetricFamily('knowledge_estimated_gpu_hours','Uptime allocation, not measured active GPU work')
        hours.add_metric([],seconds/3600 if os.environ.get('LLM_URL') else 0);yield hours
        successful=sum(sample.value for metric in self.business_requests.collect() for sample in metric.samples if sample.name=='knowledge_requests_total' and sample.labels.get('status')=='answered')
        if successful>0:
            per=GaugeMetricFamily('knowledge_estimated_rub_per_answer','Configured cost / answered queries; not price per API token')
            per.add_metric([],cost/successful);yield per

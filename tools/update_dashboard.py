"""Adapt existing dashboard; preserve measured vLLM panels."""
import copy
import json
from pathlib import Path

path=Path(__file__).resolve().parents[1]/'infra/grafana/dashboards/knowledge.json'
dashboard=json.loads(path.read_text())
dashboard['version']=2
dashboard['title']='GraphRAG: HTTP, stages, readiness and synthetic evaluation'
dashboard['panels']=[p for p in dashboard['panels'] if p['id']<=6]
dashboard['panels'][0]['title']='Query HTTP RPS — all completed outcomes'
dashboard['panels'][0]['targets'][0]['expr']='sum(rate(knowledge_http_requests_total{route=~"/query.*"}[5m]))'
dashboard['panels'][1]['title']='Query HTTP p95 / p99 — includes admission'
for target,q in zip(dashboard['panels'][1]['targets'],(.95,.99)):
    target['expr']=f'histogram_quantile({q}, sum by (le) (rate(knowledge_http_latency_seconds_bucket{{route=~"/query.*"}}[5m])))'
dashboard['panels'][2]['title']='Business outcomes / second — excludes auth and schema failures'
panels=[
 (7,'Agent stages p95','histogram_quantile(0.95, sum by (stage,le) (rate(knowledge_stage_latency_seconds_bucket[5m])))','s'),
 (8,'Query 5xx / completed HTTP requests','sum(rate(knowledge_http_requests_total{route=~"/query.*",status_class="5xx"}[5m])) / (sum(rate(knowledge_http_requests_total{route=~"/query.*"}[5m])) > 0)','percentunit'),
 (9,'Readiness / required dependencies','knowledge_dependency_ready','bool'),
 (10,'Admission: active / waiting','knowledge_waiting_queries','short'),
 (11,'Admission wait p95','histogram_quantile(0.95,sum by(le)(rate(knowledge_admission_wait_seconds_bucket[5m])))','s'),
 (12,'Synthetic evaluation coverage / validity','knowledge_eval_coverage','percentunit'),
 (13,'Evaluation age — must be <=24h','time() - knowledge_eval_last_completed_timestamp_seconds','s'),
 (14,'Estimated RUB / answered query — configured assumptions','knowledge_estimated_rub_per_answer','currencyRUB'),
 (15,'Budget rejection rate','rate(knowledge_budget_rejections_total[5m])','reqps'),
 (16,'Synthetic eval failures / invalid cases','knowledge_eval_failures','short'),
]
for pid,title,expression,unit in panels:
    panel=copy.deepcopy(dashboard['panels'][0])
    panel.update(id=pid,title=title,gridPos={'x':0 if pid%2 else 12,'y':24+((pid-7)//2)*8,'w':12,'h':8})
    panel['targets']=[{'refId':'A','expr':expression}]
    panel['fieldConfig']['defaults']['unit']=unit
    if pid==10:panel['targets'].append({'refId':'B','expr':'knowledge_active_queries'})
    if pid==12:panel['targets'].append({'refId':'B','expr':'knowledge_eval_valid'})
    if pid==16:panel['targets'].append({'refId':'B','expr':'knowledge_eval_invalid'})
    if pid==14:panel['description']='No data unless rates/power assumptions are configured and answered>0. Includes allocated idle uptime, not measured power or billing.'
    dashboard['panels'].append(panel)
path.write_text(json.dumps(dashboard,ensure_ascii=False,indent=2),encoding='utf-8')
print('Updated 16 panels; no source/customer IDs used as labels')

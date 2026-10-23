"""Freeze new synthetic annotations before prompt tuning; never overwrite them."""
import argparse
import hashlib
import json
import random
import secrets
import time
import unicodedata
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--validation',action='store_true')
args=parser.parse_args()
name='llm-quality-validation.json' if args.validation else 'llm-quality-holdout.json'
path=ROOT/'eval'/name
if path.exists(): raise SystemExit('Holdout already frozen; refusing overwrite')
seed=secrets.randbits(64)
rng=random.Random(seed)
cases=[]


def add(name,query,texts,facts,category,behavior='answered',expected=None):
    documents=[{'id':f'{name}-{i}','text':text,'tenant':'factory','roles':['staff']} for i,text in enumerate(texts)]
    cases.append({'id':name,'query':query,'documents':documents,'expected_behavior':behavior,
        'expected_sources':expected if expected is not None else [d['id'] for d in documents],
        'expected_facts':facts,'category':category,'tenant':'factory','roles':['staff']})


for i in range(2):
    asset=f'Т-{rng.randrange(200,900)}';value=rng.randrange(100,180)
    add(f'factual-{i}',f'Укажи порог отключения {asset}.',
        [f'Узел {asset} отключают при достижении {value} °C.'],[f'{value} °C'],'factual_units')
asset=f'Н-{rng.randrange(200,900)}';value=rng.randrange(3,9)
add('pressure',f'Каково допустимое давление насоса {asset}?',
    [f'Давление насоса {asset} не должно превышать {value} бар.'],[f'не должно превышать {value} бар'],'numbers')
asset=f'П-{rng.randrange(200,900)}'
add('negation',f'Разрешена ли работа {asset}?',[f'Работа агрегата {asset} не разрешена.'],['не разрешена'],'negation')
asset=f'А-{rng.randrange(200,900)}';sensor=f'Д-{rng.randrange(200,900)}'
add('condition',f'Когда допускается запуск {asset}?',
    [f'Запуск узла {asset} допускается только при исправном датчике {sensor}. При отказе датчика запуск запрещён.'],
    [f'только при исправном датчике {sensor}','запуск запрещён'],'condition')
asset=f'К-{rng.randrange(200,900)}'
add('exception',f'Опиши порядок обслуживания {asset} и исключение из него.',
    [f'Клапан {asset} закрывают перед обслуживанием. Исключение: продувка разрешается после согласования с диспетчером.'],
    ['закрывают перед обслуживанием','после согласования с диспетчером'],'exception')
for i in range(2):
    asset=f'Н-{rng.randrange(1000,9000)}';bridge=f'К-{rng.randrange(1000,9000)}';sensor=f'Д-{rng.randrange(1000,9000)}'
    add(f'bridge-{i}',f'Через какой контур {asset} связан с {sensor}?',
        [f'Насос {asset} подключён к контуру {bridge}.',f'Контур {bridge} контролируется датчиком {sensor}.'],
        [f'{asset} подключён к контуру {bridge}',f'{bridge} контролируется датчиком {sensor}'],'multi_hop')
asset=f'У-{rng.randrange(200,900)}';value=rng.randrange(100,180)
add('two-sources',f'Приведи правила для узла {asset} из обеих инструкций.',
    [f'Узел {asset} отключается при {value} °C.',f'Перед ремонтом узла {asset} питание отключают.'],
    [f'{value} °C','питание отключают'],'multiple_sources')
asset=f'Н-{rng.randrange(200,900)}';value=rng.randrange(100,180)
add('abbreviation',f'Что требует п. 3.2 для {asset}?',
    [f'ГОСТ Р 123.4, п. 3.2: насос {asset} останавливают при {value} °C. Работу возобновляют только после проверки.'],
    ['ГОСТ Р 123.4','п. 3.2',f'{value} °C','только после проверки'],'technical_abbreviations')
asset=f'Р-{rng.randrange(200,900)}'
add('decimal',f'Какое значение установлено для {asset}?',
    [f'Для регулятора {asset} установлено значение 3,75 МПа. Самовольное изменение запрещено.'],
    ['3,75 МПа','изменение запрещено'],'numbers_units')
asset=f'Н-{rng.randrange(200,900)}'
add('contradiction',f'Какое давление {asset}?',
    [f'Давление насоса {asset}: 3 бар.',f'Давление насоса {asset}: 9 бар.'],
    ['3 бар','9 бар'],'contradictory_evidence')
asset=f'З-{rng.randrange(2000,9000)}'
add('missing',f'Какова масса {asset}?',['Узел Л-11 имеет паспорт.'],[],
    'no_evidence','no_evidence',[])
asset=f'З-{rng.randrange(2000,9000)}';other=f'З-{rng.randrange(100,900)}'
add('wrong-asset',f'Какое давление {asset}?',[f'Давление узла {other}: 5 бар.'],[],
    'no_evidence','no_evidence',[])
asset=f'Г-{rng.randrange(200,900)}'
add('shared-tenant',f'Назови правило для {asset}.',[f'Узел {asset} осматривают перед сменой.'],
    ['осматривают перед сменой'],'tenant_isolation')
cases[-1]['documents'].append({'id':'foreign-shared','text':f'Узел {asset}: закрытый синтетический показатель 864209753.',
                               'tenant':'other','roles':['staff']})
cases.append({'id':'ocr-new-query','query':'Что в регламенте сказано о контуре К-2 и датчике Д-8?',
    'documents':[{'id':'scan','ocr_file':'examples/scan-regulation.pdf','tenant':'factory','roles':['staff']}],
    'expected_behavior':'answered','expected_sources':['scan'],'expected_facts':['К-2','Д-8'],
    'category':'ocr','tenant':'factory','roles':['staff']})
if args.validation:
    cases[-1]['query']='Приведи регламентную связь датчика Д-8 с контуром К-2.'
    asset=f'Б-{rng.randrange(10000,90000)}'
    add('same-asset-missing',f'Каково напряжение питания {asset}?',
        [f'Блок {asset} осматривают после смены.'],[],'no_evidence','no_evidence',[])
    asset=f'Б-{rng.randrange(10000,90000)}';value=rng.choice([24,48,110])
    add('selective-source',f'Укажи напряжение питания {asset}.',
        [f'Напряжение питания блока {asset}: {value} В.',f'Корпус блока {asset} окрашен в серый цвет.'],
        [f'{value} В'],'irrelevant_source_selection',expected=['selective-source-0'])
    asset=f'Н-{rng.randrange(10000,90000)}';bridge=f'К-{rng.randrange(10000,90000)}';sensor=f'Д-{rng.randrange(10000,90000)}'
    add('bridge-with-decoy',f'Как связан {asset} с {sensor}?',
        [f'Установка {asset} имеет синюю маркировку.',f'Насос {asset} соединён с контуром {bridge}.',
         f'Контур {bridge} передаёт показания датчику {sensor}.'],
        [f'{asset} соединён с контуром {bridge}',f'{bridge} передаёт показания датчику {sensor}'],
        'multi_hop_decoy',expected=['bridge-with-decoy-1','bridge-with-decoy-2'])
    asset=f'Б-{rng.randrange(10000,90000)}';value=rng.choice([12,36,220])
    add('late-source',f'Какое напряжение питания указано для {asset}?',
        [f'Блок {asset} осматривают ежемесячно.',f'Для блока {asset} предусмотрен защитный кожух.',
         f'Питание блока {asset}: {value} В.'],[f'{value} В'],'context_order',expected=['late-source-2'])
old=json.loads((ROOT/'eval/golden.json').read_text(encoding='utf-8'))
normalize=lambda q:unicodedata.normalize('NFKC',q).casefold().strip()
assert not {normalize(c['query']) for c in cases}&{normalize(c['query']) for c in old['cases']}
if args.validation:
    consumed=json.loads((ROOT/'eval/llm-quality-holdout.json').read_text(encoding='utf-8'))
    assert not {normalize(c['query']) for c in cases}&{normalize(c['query']) for c in consumed['cases']}
dataset={'version':'llm-quality-validation-v2' if args.validation else 'llm-quality-holdout-v1','synthetic':True,'frozen_before_prompt_tuning':True,
         'timestamp':time.time(),'seed':seed,'annotation':'Author-generated, not independent domain expert labels',
         'ocr_limitation':'New query reuses the existing synthetic image-only OCR source; text cases are newly generated',
         'cases':cases}
path.write_text(json.dumps(dataset,ensure_ascii=False,indent=2),encoding='utf-8')
report={'dataset_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'cases':len(cases),'timestamp':dataset['timestamp'],
        'query_overlap_with_golden':0,'policy':'Frozen once, evaluate only after prompt candidate is selected; no expected answer edits'}
out=ROOT/'docs/remediation/evidence/llm-quality-20261020'/('validation-freeze.json' if args.validation else 'holdout-freeze.json')
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps(report,indent=2))
print(json.dumps({'frozen_cases':len(cases),'dataset_sha256':report['dataset_sha256']}))

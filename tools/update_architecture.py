"""Preserve current Draw.io pages; update runtime labels and render PDFs.

Reuses only selected, inspected local rendering functions, never the course
artifact generator's main routine or its other homework definitions.
"""
import ast
import html
import xml.etree.ElementTree as ET
from pathlib import Path

root=Path(__file__).resolve().parents[1]
course=root.parents[2]
helper=course/'tmp/make_artifacts.py'
tree=ast.parse(helper.read_text(encoding='utf-8'))
for constant in ast.walk(tree):
    if isinstance(constant,ast.Constant) and isinstance(constant.value,str):
        constant.value=constant.value.replace('05.10.2026','20.10.2026')
first=next(i for i,node in enumerate(tree.body) if isinstance(node,ast.FunctionDef))
namespace={'__file__':str(helper),'__name__':'remediation_renderer'}
exec(compile(ast.Module(body=tree.body[:first],type_ignores=[]),str(helper),'exec'),namespace)
namespace.update(W=1190,H=842)
names={'inline','markdown_pdf','N','flow','sequence','E','box','arrow','diagrams'}
for node in tree.body:
    if isinstance(node,ast.FunctionDef) and node.name in names:
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(helper),'exec'),namespace)
assert (namespace['OUT']/'Проект').resolve()==root.resolve()

def label(cell):return html.unescape(cell.attrib.get('value','')).replace('<br>','\n').replace('<br/>','\n')
pages=[]
for diagram in ET.parse(root/'docs/архитектура.drawio').getroot().findall('diagram'):
    cells=list(diagram.iter('mxCell'))
    title=diagram.attrib['name']
    vertices=[c for c in cells if c.attrib.get('vertex')=='1' and c.attrib.get('id','').isdigit() and 2<=int(c.attrib['id'])<100]
    vertices.sort(key=lambda c:int(c.attrib['id']))
    mapping={c.attrib['id']:i for i,c in enumerate(vertices)}
    edges=[(mapping[c.attrib['source']],mapping[c.attrib['target']],label(c)) for c in cells if c.attrib.get('edge')=='1' and c.attrib.get('source') in mapping and c.attrib.get('target') in mapping]
    if title.startswith('Sequence'):
        events=[]
        for a,b,text in edges:
            if 'Re-author' in text or text.startswith('10.'):text='10. BEGIN IMMEDIATE: ACL / version / tenant / session'
            if 'Validated evidence' in text:text='11. Freeze evidence + graph; history / audit; commit'
            if 'bounded context' in text:text='8. Tokenize / pack complete units / local inference'
            if 'Exact quote' in text:text='9. Full semantic spans + model usage validation'
            events.append((a,b,text))
        actors=[label(c).replace('\n',' ') for c in vertices]
        actors[-1]='Validator / SQL release'
        page=namespace['sequence'](title,actors,events,'Авторизация действительна на commit SQL snapshot. SSE отправляет один проверенный результат; переданные байты не отзываются.')
    else:
        nodes=[]
        for cell in vertices:
            geo=cell.find('mxGeometry')
            node={'label':label(cell),'x':float(geo.attrib['x']),'y':float(geo.attrib['y']),
                  'w':float(geo.attrib['width']),'h':float(geo.attrib['height']),
                  'kind':'person' if '#F1E6D3' in cell.attrib.get('style','') else 'component'}
            text=node['label']
            if title.startswith('C3'):
                if text.startswith('Generator'):node['label']='TokenBudget + Generator\nReal /tokenize + full-unit packing\nLocal Qwen / extractive fallback'
                if text.startswith('Output Validator'):node['label']='Output Validator\nFull semantic units + offsets\nReject clipped negations / conditions'
                if text.startswith('Store / Authorizer'):node['label']='Store / final Authorizer\nBEGIN IMMEDIATE / ACL epoch\nEvidence + graph + history / audit'
                if text.startswith('Trace / Audit'):node['label']='Trace / Audit integrity\nStage / HTTP / quality metrics\nLocal release HOLD / GO'
            if title.startswith('C4'):
                if text.startswith('Store'):
                    node['label']='Store: canonical SQL\nallowed / graph / public_view\nfinalize: SQL release snapshot\nhistory / audit chain / retention';node['h']=120
                if text.startswith('Generator'):
                    node['label']='Generator + TokenBudget\nReal chat template / output reserve\nComplete context / safe fallback';node['h']=120
                if text.startswith('Indexes'):
                    node['label']='Indexes: adapters.py\nBuild / validate / publish\nActive SQL version / rollback\nQdrant + Neo4j retained versions';node['h']=120
            if title.startswith('Data Flow'):
                if text.startswith('Derived index sync'):node['label']='Versioned derived index build\nValidate hashes / ACL / coverage\nPublish one SQL active pointer'
                if text.startswith('Generate quotes'):node['label']='Budgeted local generation\nFull semantic units / offsets\nSafe extractive fallbacks'
                if text.startswith('Reauthorize'):node['label']='SQL release snapshot / commit\nEvidence + graph + session / ACL\nHistory + chained audit / HTTP metrics'
            nodes.append(node)
        if title.startswith('ER') and not any(n['label'].startswith('Version / integrity metadata') for n in nodes):
            nodes.append({'label':'Version / integrity metadata\nindex_releases + service_state (active version)\naudit_chain + history_time (retention)',
                          'x':55,'y':550,'w':650,'h':100,'kind':'component'})
        notes={
            'C1':'Демонстрационный корпус синтетический. ERP/CRM — проектные коннекторы; runtime inference без внешних API.',
            'C2':'Control / Data Plane сохранены. Readiness проверяет обязательные зависимости; quality gate является отдельным release gate.',
            'C3':'Bounded LangGraph: два прохода, до двух hops, 32 chunks / 128 entities, затем top-6 и фактический token budget.',
            'C4':'API 1.1: offsets, согласованная финальная авторизация, token budget, versioned indexes. Одна process replica MVP.',
            'ER':'Права наследуются от canonical document grants. CO_MENTION не означает физическую связь; legacy данные не удаляются.',
            'Data Flow':'OCR извлекает текст; геометрия чертежей не интерпретируется. Неизменяемые индексы публикуются после проверки обоих stores.',
            'Deployment':'Production zones / HA / Vault / mTLS — проектные prerequisites. Реально проверен single-host Compose, loopback и закрытая runtime сеть.'}
        note=next((value for prefix,value in notes.items() if title.startswith(prefix)),'')
        page=namespace['flow'](title,nodes,edges,note)
    pages.append(page)

# The renderer writes only the selected project's architecture files.
namespace['diagrams']('Проект/docs',pages)
for name in ('ADD','ADR','проверки'):
    namespace['markdown_pdf'](root/'docs'/f'{name}.md')
print('Updated current project Draw.io / architecture PDF and ADD / ADR / checks PDFs')

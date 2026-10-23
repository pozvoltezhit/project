import json
import secrets
from pathlib import Path
from backend.core import Store
from backend.ingest import read_pages

def initialize(root: Path):
    data=root/'data'; data.mkdir(exist_ok=True)
    identities=data/'identities.json'
    if not identities.exists():
        identities.write_text(json.dumps([{'user':'engineer-a','tenant':'factory','roles':['staff','restricted'],'token':secrets.token_urlsafe(32)},{'user':'engineer-b','tenant':'factory','roles':['staff'],'token':secrets.token_urlsafe(32)},{'user':'outsider','tenant':'other','roles':['restricted','staff'],'token':secrets.token_urlsafe(32)}],ensure_ascii=False,indent=2),encoding='utf-8')
    password=data/'neo4j-password.txt'
    if not password.exists(): password.write_text(secrets.token_urlsafe(32),encoding='utf-8')
    db=Store(str(data/'knowledge.db'))
    for file in sorted((root/'examples').glob('*.txt')):
        db.ingest(file.name,read_pages(file),'factory',['restricted'] if file.name.startswith('secret') else ['staff'])
    print('Demo corpus ingested. Identity credentials are in data/identities.json (keep private).')

if __name__=='__main__': initialize(Path(__file__).resolve().parents[1])

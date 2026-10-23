from pathlib import Path
from datetime import datetime, timezone
from urllib.request import urlopen,Request
from concurrent.futures import ThreadPoolExecutor
import json,hashlib,time
ROOT=Path(__file__).resolve().parents[1]/'models/qwen-awq';ROOT.mkdir(parents=True,exist_ok=True)
REPO='Qwen/Qwen2.5-7B-Instruct-AWQ'
revision='b25037543e9394b818fdfca67ab2a00ecc7dd641'
metadata=json.load(urlopen('https://huggingface.co/api/models/'+REPO+'/revision/'+revision+'?blobs=true',timeout=30))
assert metadata['sha']==revision
files=[s['rfilename'] for s in metadata['siblings'] if '/' not in s['rfilename'] and (s['rfilename'].endswith(('.json','.safetensors','.txt','.model','.jinja')) or s['rfilename'] in ('LICENSE','README.md'))]
def download(name):
    target=ROOT/name
    if target.exists():return name
    for attempt in range(4):
        partial=target.with_name(target.name+'.part');size=partial.stat().st_size if partial.exists() else 0
        try:
            url=f'https://huggingface.co/{REPO}/resolve/{revision}/{name}?download=true'
            if name.endswith('.safetensors'):
                with urlopen(Request(url,headers={'Range':'bytes=0-0'}),timeout=45) as info:
                    assert info.status==206
                    total=int(info.headers['Content-Range'].split('/')[-1]);info.read()
                with partial.open('ab') as out:
                    while size<total:
                        end=min(total-1,size+16*1024*1024-1)
                        with urlopen(Request(url,headers={'Range':f'bytes={size}-{end}'}),timeout=90) as response:
                            assert response.status==206 and response.headers['Content-Range'].startswith(f'bytes {size}-')
                            block=response.read();assert len(block)==end-size+1
                        out.write(block);out.flush();size=end+1
                        print('Progress',name,size,'/',total,flush=True)
            else:
                with urlopen(url,timeout=90) as response,partial.open('wb') as out:out.write(response.read())
            partial.replace(target);print('Downloaded',name,target.stat().st_size,flush=True);return name
        except Exception as e:
            print('Retry',name,type(e).__name__,flush=True)
            if attempt==3:raise
            time.sleep(3)
with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(download,files))
manifest={'repository':REPO,'revision':revision,'date':datetime.now(timezone.utc).isoformat(),'files':[]}
for name in files:
    digest=hashlib.sha256()
    with (ROOT/name).open('rb') as stream:
        while block:=stream.read(1024*1024):digest.update(block)
    expected=next(s for s in metadata['siblings'] if s['rfilename']==name).get('lfs',{}).get('sha256')
    if expected:assert digest.hexdigest()==expected, 'SHA256 mismatch: '+name
    manifest['files'].append({'name':name,'size':(ROOT/name).stat().st_size,'sha256':digest.hexdigest(),'official_lfs_verified':bool(expected)})
(ROOT.parent/'qwen-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print('Verified local artifact manifest',len(files),flush=True)

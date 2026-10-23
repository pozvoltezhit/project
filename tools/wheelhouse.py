"""Inventory and verify explicit offline wheels; no network or install here."""
import argparse
import hashlib
import json
import re
import zipfile
from email.parser import BytesParser
from pathlib import Path


def normalize(name):return re.sub('[-_.]+','-',name).lower()


def inventory(directory, lock):
    directory=Path(directory)
    required={normalize(line.split('==')[0]):line.split('==')[1] for line in Path(lock).read_text().splitlines() if '==' in line}
    files={};packages={}
    for wheel in sorted(directory.glob('*.whl')):
        if wheel.is_symlink():raise ValueError('Symlink wheel refused')
        with zipfile.ZipFile(wheel) as archive:
            name=next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))
            metadata=BytesParser().parsebytes(archive.read(name))
        package=normalize(metadata['Name']);version=metadata['Version']
        packages[package]=version
        files[wheel.name]=hashlib.sha256(wheel.read_bytes()).hexdigest()
    missing={name:version for name,version in required.items() if packages.get(name)!=version}
    if missing:raise ValueError('Incomplete wheelhouse: '+','.join(sorted(missing)))
    return {'format':'wheelhouse-v1','lock_sha256':hashlib.sha256(Path(lock).read_bytes()).hexdigest(),'files':files,'packages':packages,
            'limitation':'Hash inventory is not a signature or provenance attestation; platform-specific wheels'}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=('create','verify'))
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--lock',type=Path,default=Path('requirements-lock.txt'))
    args=parser.parse_args()
    current=inventory(args.directory,args.lock)
    manifest=args.directory/'manifest.json'
    if args.command=='create':
        if manifest.exists():raise ValueError('Refuse to overwrite an existing wheel manifest')
        manifest.write_text(json.dumps(current,indent=2),encoding='utf-8')
    elif current!=json.loads(manifest.read_text()):
        raise ValueError('Wheelhouse integrity mismatch')
    print(json.dumps({'status':'PASS','wheels':len(current['files']),'lock_sha256':current['lock_sha256']}))


if __name__=='__main__':main()

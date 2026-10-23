"""Private, integrity-checked SQLite/source backup; never overwrites a restore."""
import argparse
import hashlib
import json
import shutil
import sqlite3
import time
from pathlib import Path, PureWindowsPath


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block:=stream.read(1024*1024): digest.update(block)
    return digest.hexdigest()


def create(destination, store, identities, sources, model_manifest=None):
    destination=Path(destination)
    if destination.exists(): raise ValueError('Backup destination must be new')
    identities,sources=Path(identities),Path(sources)
    if not identities.is_file() or not sources.is_dir(): raise ValueError('Provisioned identities and explicit source directory required')
    if destination.resolve().is_relative_to(sources.resolve()): raise ValueError('Backup must be outside source directory')
    destination.mkdir(parents=True,mode=0o700)
    with store.connect() as source, sqlite3.connect(destination/'knowledge.db') as target:
        source.backup(target)
    shutil.copy2(identities,destination/'identities.json')
    for path in sources.rglob('*'):
        if path.is_symlink(): raise ValueError('Symlinks in source archive are refused')
        if path.is_file():
            copied=destination/'sources'/path.relative_to(sources)
            copied.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,copied)
    if model_manifest:
        shutil.copy2(model_manifest,destination/'model-manifest.json')
    files={p.relative_to(destination).as_posix():sha(p) for p in destination.rglob('*') if p.is_file()}
    for name in files: (destination/name).chmod(0o600)
    manifest={'format':'knowledge-backup-v1','timestamp':time.time(),'files':files,
              'source_scope':'Only supplied directory; original PDFs outside it are not automatically recoverable',
              'model_weights':'External immutable artifacts; verify separately using model-manifest.json'}
    (destination/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    return manifest


def restore(backup, destination):
    backup,destination=Path(backup),Path(destination)
    if destination.exists(): raise ValueError('Restore destination must be new')
    manifest=json.loads((backup/'manifest.json').read_text())
    if manifest.get('format')!='knowledge-backup-v1' or not {'knowledge.db','identities.json'} <= manifest['files'].keys():
        raise ValueError('Invalid backup manifest')
    for name,digest in manifest['files'].items():
        if Path(name).is_absolute() or PureWindowsPath(name).drive or '..' in Path(name).parts:
            raise ValueError('Unsafe backup path')
        path=(backup/name).resolve()
        if not path.is_relative_to(backup.resolve()) or path.is_symlink() or sha(path)!=digest:
            raise ValueError('Backup file integrity/path mismatch')
    destination.mkdir(parents=True,mode=0o700)
    for name in manifest['files']:
        target=destination/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(backup/name,target)
    with sqlite3.connect(destination/'knowledge.db') as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Restored SQL failed integrity checks')
        # This changes only the new restored SQL; no external DB is contacted.
        db.execute("DELETE FROM service_state WHERE name='active_index'")
    return manifest


def main():
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest='command',required=True)
    make=sub.add_parser('create')
    make.add_argument('--db',type=Path,required=True)
    make.add_argument('--identities',type=Path,required=True)
    make.add_argument('--sources',type=Path,required=True)
    make.add_argument('--model-manifest',type=Path)
    make.add_argument('--output',type=Path,required=True)
    recover=sub.add_parser('restore')
    recover.add_argument('--backup',type=Path,required=True)
    recover.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='create':
        from backend.core import Store
        create(args.output,Store(str(args.db)),args.identities,args.sources,args.model_manifest)
    else:
        restore(args.backup,args.output)
    print('Backup operation complete; credentials remain private in destination')


if __name__=='__main__': main()

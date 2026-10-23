"""Identity of code/config present in both checkout and offline runtime image."""
import hashlib
from pathlib import Path


def identity(root=None):
    root=Path(root) if root else Path(__file__).resolve().parents[1]
    paths=[]
    for folder in ('backend','frontend','eval'):
        paths.extend(p for p in (root/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.json','.html','.js','.css'))
    paths.append(root/'requirements-lock.txt')
    files={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    digest=hashlib.sha256(''.join(f'{name}:{value}\n' for name,value in sorted(files.items())).encode()).hexdigest()
    return {'tree_sha256':digest,'files':files,'dependency_lock_sha256':files['requirements-lock.txt']}

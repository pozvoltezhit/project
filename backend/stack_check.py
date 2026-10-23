"""Mutating tests strictly opt-in for an isolated remediation namespace."""
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from backend.adapters import Indexes
from backend.backup import create, restore
from backend.bundle import identity
from backend.core import Agent, Principal, Store
from backend.index_admin import configured
from backend.init_demo import initialize


def check():
    namespace=os.environ.get('TEST_NAMESPACE','')
    if not (namespace.startswith('course-remediation-') or namespace == 'course-final-20261020'):
        raise RuntimeError('Mutating tests require an explicitly isolated remediation namespace')
    root=Path(__file__).resolve().parents[1]
    index=configured()
    try:
        first=index.active_release()
        assert first and index.ready()
        second=index.sync(force=True)
        assert first['version']!=second['version']
        assert index.qdrant.collection_exists(first['collection'])
        index.rollback(first['version'])
        assert index.active_release()['version']==first['version']
        with patch.object(index,'validate',side_effect=OSError('deliberate staged validation failure')):
            try:index.sync(force=True)
            except OSError:pass
            else:raise AssertionError('Invalid staged build was published')
        assert index.active_release()['version']==first['version']
        retirement=index.retire(second['version'])
        assert retirement['dry_run'] and not retirement['deleted']
    finally:
        index.qdrant.close();index.neo4j.close()
    with tempfile.TemporaryDirectory() as directory:
        local=Path(directory)
        shutil.copytree(root/'examples',local/'examples')
        initialize(local)
        source=Store(str(local/'data/knowledge.db'))
        snapshot=create(local/'backup',source,local/'data/identities.json',local/'examples',root/'models/qwen-manifest.json')
        started=time.perf_counter()
        restore(local/'backup',local/'restored')
        restored=Store(str(local/'restored/knowledge.db'))
        b=Agent(restored).run('Бюджет проекта П-9',Principal('b','factory',('staff',)))
        a=Agent(restored).run('Бюджет проекта П-9',Principal('a','factory',('staff','restricted')))
        assert b['status']=='no_evidence' and not b['evidence']
        assert '987654321' in json.dumps(a) and restored.verify_audit()
        derived=Indexes(restored,os.environ['QDRANT_URL'],os.environ['NEO4J_URL'],Path(os.environ['NEO4J_PASSWORD_FILE']).read_text().strip())
        try:
            derived.sync()
            assert derived.ready()
        finally:
            derived.qdrant.close();derived.neo4j.close()
        rto=time.perf_counter()-started
        result={'decision':'PASS','namespace':namespace,'timestamp':time.time(),'bundle_hash':identity()['tree_sha256'],
                'versioned_index':'PASS: build, validate, publish, retain, rollback, reject staged failure',
                'retirement':'Dry-run only; active/recent versions protected',
                'restore':'PASS: new directory, SQL integrity, A/B, audit chain, Qdrant/Neo4j rebuild',
                'restore_seconds':round(rto,4),'snapshot_age_seconds':round(time.time()-snapshot['timestamp'],4),
                'rpo':'No fixture documents lost; production RPO remains unestablished'}
    (root/'data/stack-regression.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':check()

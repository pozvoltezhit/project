import tempfile
import unittest
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch
from qdrant_client import QdrantClient

from backend.adapters import Indexes
from backend.core import Principal, Store


class Reply:
    def __init__(self,n=0):self.n=n
    def consume(self):return None
    def single(self):return {'n':self.n}


class Graph:
    def __init__(self):self.nodes=defaultdict(set);self.edges=defaultdict(set)
    def session(self,**kwargs):return self
    def __enter__(self):return self
    def __exit__(self,*args):return None
    def run(self,query,**p):
        v=p['v']
        if query.startswith('MERGE (d:'):
            self.nodes[v].update((('document',p['doc']),('chunk',p['cid'])))
            self.edges[v].add(('contains',p['doc'],p['cid']))
        elif 'MERGE (e:' in query:
            self.nodes[v].add(('entity',p['tenant'],p['name']))
            self.edges[v].add(('mentions',p['cid'],p['name']))
        elif 'MERGE (a)-[r:CO_MENTION' in query:
            self.edges[v].add(('co',p['src'],p['dst'],p['cid']))
        elif query.startswith('MATCH (n:'):
            return Reply(len(self.nodes[v]))
        elif 'RETURN count(r)' in query:
            return Reply(len(self.edges[v]))
        else:raise AssertionError(query)
        return Reply()


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(str(Path(self.tmp.name)/'index.db'))
        self.doc=self.store.ingest('public',['Н-17 подключен к К-2.'],'factory',['staff'])
        self.store.ingest('secret',['Н-17: проект П-9, число 987654321.'],'factory',['restricted'])
        self.index=Indexes.__new__(Indexes)
        self.index.store=self.store;self.index.qdrant=QdrantClient(':memory:');self.index.neo4j=Graph()
        self.index.encoder=None;self.index.dimensions=256;self.index.collection='knowledge_chunks'
        self.addCleanup(self.index.qdrant.close)

    def test_build_validate_publish_retain_and_rollback(self):
        first=self.index.sync()
        self.assertEqual(self.index.sync(),first)
        second=self.index.sync(force=True)
        self.assertNotEqual(first['version'],second['version'])
        self.assertTrue(self.index.qdrant.collection_exists(first['collection']))
        self.assertTrue(self.index.ready())
        p=Principal('b','factory',('staff',))
        self.assertLessEqual(set(self.index.search('Н-17 бюджет',p)),{c['id'] for c in self.store.allowed(p)})
        self.index.rollback(first['version'])
        self.assertEqual(self.index.active_release()['version'],first['version'])

    def test_failed_build_does_not_publish(self):
        first=self.index.sync()
        with patch.object(self.index,'validate',side_effect=OSError('invalid staged build')):
            with self.assertRaises(OSError):self.index.sync(force=True)
        self.assertEqual(self.index.active_release(),first)

    def test_canonical_change_during_build_refuses_publication(self):
        first=self.index.sync()
        original=self.index.validate
        def mutate(release,data):
            original(release,data)
            with self.store.connect() as db:db.execute('DELETE FROM grants WHERE doc_id=?',(self.doc,))
        with patch.object(self.index,'validate',side_effect=mutate):
            with self.assertRaises(OSError):self.index.sync(force=True)
        self.assertEqual(self.index.active_release(),first)
        self.assertFalse(self.index.ready())
        with self.assertRaises(ValueError):self.index.rollback(first['version'])

    def test_validation_detects_corrupt_payload_and_graph(self):
        first=self.index.sync()
        data,_,_=self.index.snapshot()
        self.index.neo4j.nodes[first['version']].clear()
        with self.assertRaises(OSError):self.index.validate(first,data)

    def test_duplicate_ingestion_is_idempotent(self):
        with self.store.connect() as db:before=db.execute('SELECT value FROM security_epoch').fetchone()[0]
        self.store.ingest('public',['Н-17 подключен к К-2.'],'factory',['staff'])
        with self.store.connect() as db:after=db.execute('SELECT value FROM security_epoch').fetchone()[0]
        self.assertEqual(before,after)

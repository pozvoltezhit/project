"""Immutable derived versions published through one atomic SQL pointer.

Qdrant and Neo4j do not share a distributed commit. Old versions are retained.
"""
import hashlib
import json
import os
import time
import uuid
import re

from backend.core import Principal, embedding


class Indexes:
    def __init__(self, store, qdrant_url, neo4j_url, neo4j_password):
        from qdrant_client import QdrantClient
        from neo4j import GraphDatabase
        self.store = store
        self.qdrant = QdrantClient(url=qdrant_url, timeout=5)
        self.neo4j = GraphDatabase.driver(neo4j_url, auth=('neo4j',neo4j_password), connection_timeout=5)
        self.encoder = None
        directory = os.environ.get('EMBEDDING_MODEL_DIR')
        if directory:
            from sentence_transformers import SentenceTransformer
            self.encoder = SentenceTransformer(directory,local_files_only=True,device='cpu')
        self.dimensions = self.encoder.get_sentence_embedding_dimension() if self.encoder else 256
        release = self.active_release()
        self.collection = release['collection'] if release else 'knowledge_chunks'

    def encode(self, text, query=False):
        if self.encoder:
            return self.encoder.encode(('query: ' if query else 'passage: ')+text,normalize_embeddings=True).tolist()
        return embedding(text)

    def active_release(self):
        with self.store.connect() as db:
            row = db.execute("SELECT r.* FROM index_releases r JOIN service_state s ON s.value=r.version WHERE s.name='active_index'").fetchone()
            return dict(row) if row else None

    def snapshot(self):
        with self.store.connect() as db:
            db.execute('BEGIN')
            data = {table:[dict(r) for r in db.execute('SELECT * FROM '+table+' ORDER BY rowid')]
                    for table in ('documents','grants','chunks','mentions','edges')}
            epoch = db.execute('SELECT value FROM security_epoch WHERE id=1').fetchone()[0]
        for rows in data.values():
            rows.sort(key=lambda row:json.dumps(row,sort_keys=True))
        digest = hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        return data,epoch,digest

    def sync(self, force=False):
        from qdrant_client import models as m
        data,epoch,digest = self.snapshot()
        current = self.active_release()
        if not force and current and current['corpus_hash']==digest and current['dimensions']==self.dimensions:
            if self.qdrant.collection_exists(current['collection']):
                self.validate(current,data)
                self.collection = current['collection']
                return current
        version = 'v2_'+digest[:12]+'_'+uuid.uuid4().hex[:8]
        collection = 'knowledge_chunks_'+version
        docs = {d['id']:d for d in data['documents']}
        chunks = {c['id']:c for c in data['chunks']}
        grants = {doc:[g['role'] for g in data['grants'] if g['doc_id']==doc] for doc in docs}
        self.qdrant.create_collection(collection,vectors_config=m.VectorParams(size=self.dimensions,distance=m.Distance.COSINE))
        points = []
        for c in chunks.values():
            d = docs[c['doc_id']]
            points.append(m.PointStruct(id=str(uuid.uuid5(uuid.NAMESPACE_URL,c['id'])),vector=self.encode(c['text']),
                payload={'chunk_id':c['id'],'tenant':d['tenant'],'roles':grants[d['id']],
                         'document_hash':d['hash'],'document_version':d['version'],'index_version':version}))
        for offset in range(0,len(points),128):
            self.qdrant.upsert(collection,points[offset:offset+128],wait=True)
        with self.neo4j.session(database='neo4j') as session:
            for c in chunks.values():
                d = docs[c['doc_id']]
                session.run('MERGE (d:KnowledgeDemo:Document {id:$doc,index_version:$v}) SET d.tenant=$tenant,d.title=$title,d.source_hash=$hash MERGE (c:KnowledgeDemo:Chunk {id:$cid,index_version:$v}) SET c.roles=$roles,c.tenant=$tenant MERGE (d)-[:CONTAINS]->(c)',doc=d['id'],cid=c['id'],v=version,tenant=d['tenant'],title=d['title'],hash=d['hash'],roles=grants[d['id']]).consume()
            for mention in data['mentions']:
                c = chunks[mention['chunk_id']]; d = docs[c['doc_id']]
                session.run('MATCH (c:KnowledgeDemo:Chunk {id:$cid,index_version:$v}) MERGE (e:KnowledgeDemo:Entity {name:$name,tenant:$tenant,index_version:$v}) MERGE (c)-[:MENTIONS]->(e)',cid=c['id'],v=version,name=mention['entity'],tenant=d['tenant']).consume()
            for edge in data['edges']:
                c = chunks[edge['chunk_id']]; d = docs[c['doc_id']]
                session.run('MATCH (a:KnowledgeDemo:Entity {name:$src,tenant:$tenant,index_version:$v}),(b:KnowledgeDemo:Entity {name:$dst,tenant:$tenant,index_version:$v}) MERGE (a)-[r:CO_MENTION {chunk_id:$cid,index_version:$v}]->(b) SET r.roles=$roles,r.tenant=$tenant',src=edge['src'],dst=edge['dst'],cid=c['id'],v=version,tenant=d['tenant'],roles=grants[d['id']]).consume()
        release = dict(version=version,collection=collection,corpus_hash=digest,dimensions=self.dimensions,chunk_count=len(chunks),created_at=time.time())
        self.validate(release,data)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT value FROM security_epoch WHERE id=1').fetchone()[0] != epoch:
                raise OSError('Canonical data changed during index build; publication refused')
            db.execute('INSERT INTO index_releases VALUES(?,?,?,?,?,?)',tuple(release.values()))
            db.execute("INSERT INTO service_state VALUES('active_index',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",(version,))
            db.execute("INSERT INTO service_state VALUES('index_last_switch_at',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",(str(time.time()),))
        self.collection = collection
        return release

    def validate(self, release, data):
        expected = {c['id']:c for c in data['chunks']}
        docs = {d['id']:d for d in data['documents']}
        found = {}
        offset = None
        while True:
            points,offset = self.qdrant.scroll(release['collection'],limit=128,offset=offset,with_payload=True)
            for point in points:
                payload = point.payload
                cid = payload['chunk_id']; c = expected[cid]; d = docs[c['doc_id']]
                roles = {g['role'] for g in data['grants'] if g['doc_id']==d['id']}
                if payload['tenant']!=d['tenant'] or set(payload['roles'])!=roles or payload['document_hash']!=d['hash'] or payload['document_version']!=d['version'] or payload['index_version']!=release['version']:
                    raise OSError('Derived index provenance/ACL mismatch')
                found[cid] = point.id
            if offset is None: break
        if set(found)!=set(expected):
            raise OSError('Derived index coverage mismatch')
        entities = {(docs[expected[r['chunk_id']]['doc_id']]['tenant'],r['entity']) for r in data['mentions']}
        with self.neo4j.session(database='neo4j') as session:
            count = session.run('MATCH (n:KnowledgeDemo {index_version:$v}) RETURN count(n) AS n',v=release['version']).single()['n']
            relations = session.run('MATCH (:KnowledgeDemo {index_version:$v})-[r]->(:KnowledgeDemo {index_version:$v}) RETURN count(r) AS n',v=release['version']).single()['n']
        if count!=len(docs)+len(expected)+len(entities) or relations!=len(expected)+len(data['mentions'])+len(data['edges']):
            raise OSError('Derived graph consistency mismatch')

    def ready(self):
        release = self.active_release()
        data,_,digest = self.snapshot()
        if not release or release['corpus_hash']!=digest or release['dimensions']!=self.dimensions:
            return False
        self.validate(release,data)
        return True

    def rollback(self, version):
        data,epoch,digest = self.snapshot()
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM index_releases WHERE version=?',(version,)).fetchone()
        if not row or row['corpus_hash']!=digest or row['dimensions']!=self.dimensions:
            raise ValueError('Rollback incompatible with current canonical corpus/encoder')
        release = dict(row)
        self.validate(release,data)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT value FROM security_epoch WHERE id=1').fetchone()[0]!=epoch:
                raise OSError('Canonical data changed before rollback')
            db.execute("UPDATE service_state SET value=? WHERE name='active_index'",(version,))
            db.execute("INSERT INTO service_state VALUES('index_last_switch_at',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",(str(time.time()),))
        self.collection = release['collection']

    def retire(self, version, apply=False, grace_seconds=3600):
        if grace_seconds < 300: raise ValueError('Retirement grace must exceed bounded request lifetime')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM index_releases WHERE version=?',(version,)).fetchone()
            active=db.execute("SELECT value FROM service_state WHERE name='active_index'").fetchone()
            switched=db.execute("SELECT value FROM service_state WHERE name='index_last_switch_at'").fetchone()
            if not row or not re.fullmatch(r'knowledge_chunks_v2_[0-9a-f]{12}_[0-9a-f]{8}',row['collection']):
                raise ValueError('Only manifest-owned v2 index versions may be retired')
            eligible=bool(active and active[0]!=version and switched and time.time()-float(switched[0])>=grace_seconds)
            if apply and not eligible: raise ValueError('Active or recently active index must be retained')
            if apply:
                if self.qdrant.collection_exists(row['collection']):self.qdrant.delete_collection(row['collection'])
                with self.neo4j.session(database='neo4j') as session:
                    session.run('MATCH (n:KnowledgeDemo {index_version:$v}) DETACH DELETE n',v=version).consume()
                db.execute('DELETE FROM index_releases WHERE version=?',(version,))
        return {'version':version,'eligible':eligible,'deleted':bool(apply),'dry_run':not apply}

    def search(self, query: str, principal: Principal) -> list[str]:
        from qdrant_client import models as m
        from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
        release = self.active_release() if hasattr(self,'store') else None
        collection = release['collection'] if release else self.collection
        try:
            results = self.qdrant.query_points(collection,query=self.encode(query,query=True),query_filter=m.Filter(must=[m.FieldCondition(key='tenant',match=m.MatchValue(value=principal.tenant)),m.FieldCondition(key='roles',match=m.MatchAny(any=list(principal.roles)))]),limit=5).points
        except (ResponseHandlingException, UnexpectedResponse) as exc:
            raise OSError('Vector retrieval unavailable') from exc
        return [point.payload['chunk_id'] for point in results if point.score>=.15]

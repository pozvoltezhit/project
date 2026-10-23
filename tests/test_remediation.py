import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.core import Agent, Generator, Principal, Store


class SecurityRegression(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(str(Path(self.tmp.name) / 'test.db'))
        self.p = Principal('a', 'factory', ('staff',))
        self.doc = self.store.ingest('secret', ['Насос Н-17: контрольное значение 246813579.'], 'factory', ['staff'])

    def revoke(self):
        with self.store.connect() as db:
            db.execute('DELETE FROM grants WHERE doc_id=?', (self.doc,))

    def test_F01_after_validate_original_audit_hook(self):
        original = self.store.record
        def revoke_before_record(*args):
            self.revoke()
            return original(*args)
        with patch.object(self.store, 'record', side_effect=revoke_before_record):
            result = Agent(self.store).run('Н-17', self.p)
        self.assertNotIn('246813579', json.dumps(result))
        self.assertFalse(result['evidence'])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM history').fetchone()[0], 0)
            self.assertTrue(all(json.loads(row[0]) == [] for row in db.execute('SELECT chunk_ids FROM audit')))

    def test_F01_during_generation(self):
        owner = self
        class Revoke:
            def invoke(self, query, chunks):
                owner.revoke()
                return [{'chunk_id':c['id'], 'quote':c['text']} for c in chunks], {'mode':'test','input_tokens':0,'output_tokens':0}
        result = Agent(self.store, Revoke()).run('Н-17', self.p)
        self.assertEqual(result['status'], 'output_blocked')
        self.assertNotIn('246813579', json.dumps(result))

    def test_F01_concurrent_writer_before_finalization(self):
        agent = Agent(self.store)
        reached, released = threading.Event(), threading.Event()
        original = agent.validate
        def paused(state):
            value = original(state)
            reached.set()
            self.assertTrue(released.wait(5))
            return value
        # LangGraph captures node methods during construction.
        with patch.object(Agent, 'validate', side_effect=paused):
            agent = Agent(self.store)
        results, failures = [], []
        def run():
            try: results.append(agent.run('Н-17', self.p))
            except Exception as exc: failures.append(exc)
        thread = threading.Thread(target=run)
        thread.start()
        try:
            self.assertTrue(reached.wait(5))
            admin = Store(self.store.path)
            with admin.connect() as db: db.execute('DELETE FROM grants WHERE doc_id=?', (self.doc,))
        finally:
            released.set(); thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertFalse(failures)
        self.assertNotIn('246813579', json.dumps(results))

    def test_F01_document_tenant_and_version_change(self):
        for change in ('tenant', 'version'):
            with self.subTest(change=change):
                store = Store(str(Path(self.tmp.name) / (change + '.db')))
                doc = store.ingest('document', ['Н-17: значение 246813579.'], 'factory', ['staff'])
                original = store.record
                def mutate(*args):
                    with store.connect() as db:
                        if change == 'tenant':
                            db.execute('UPDATE documents SET tenant=? WHERE id=?', ('other',doc))
                        else:
                            db.execute('UPDATE documents SET version=version+1 WHERE id=?', (doc,))
                    return original(*args)
                with patch.object(store, 'record', side_effect=mutate):
                    result = Agent(store).run('Н-17', self.p)
                self.assertFalse(result['evidence'])
                self.assertFalse(result['graph'])

    def test_F01_session_owner_rechecked_at_release(self):
        original = self.store.record
        def mutate(*args):
            with self.store.connect() as db:
                db.execute('INSERT INTO sessions VALUES(?,?,?)', ('shared','other','factory'))
            return original(*args)
        with patch.object(self.store, 'record', side_effect=mutate):
            with self.assertRaises(PermissionError):
                Agent(self.store).run('Н-17', self.p, 'shared')

    def test_F01_sse_revocation(self):
        from fastapi.testclient import TestClient
        import backend.api as api
        original = self.store.record
        def revoke(*args):
            self.revoke()
            return original(*args)
        with patch.object(api, 'store', self.store), patch.object(api, 'agent', Agent(self.store)):
            api.app.dependency_overrides[api.principal] = lambda: self.p
            try:
                with patch.object(self.store, 'record', side_effect=revoke):
                    response = TestClient(api.app).post('/query/stream',json={'question':'Н-17'})
                self.assertEqual(response.status_code,200)
                self.assertNotIn('246813579',response.text)
                self.assertIn('output_blocked',response.text)
            finally:
                api.app.dependency_overrides.pop(api.principal,None)

    def test_F02_token_budget_is_enforced(self):
        from backend.budget import BudgetExceeded, TokenBudget, messages_for
        counter = lambda messages: len(json.dumps(messages, ensure_ascii=False))
        # Character counting is a unit-test stand-in, not the serving tokenizer.
        # Keep the same 500-character headroom regardless of prompt wording.
        limit = counter(messages_for('Н-17', [])) + 500
        budget = TokenBudget(counter, max_model_len=limit, output_tokens=80, margin=20)
        with self.assertRaises(BudgetExceeded):
            budget.pack('x' * 1000, [])
        chunks = [{'id':str(i), 'text':'x' * 200} for i in range(6)]
        packed, count = budget.pack('Н-17', chunks)
        self.assertLess(len(packed), len(chunks))
        self.assertLessEqual(count + 80 + 20, limit)

    def test_F03_clipped_negation(self):
        self.store.ingest('negation', ['Работа насоса Н-99 не разрешена.'], 'factory', ['staff'])
        class Clipped:
            def invoke(self, query, chunks):
                c = next(c for c in chunks if c['title'] == 'negation')
                return [{'chunk_id':c['id'], 'quote':'разрешена.'}], {'mode':'test','input_tokens':0,'output_tokens':0}
        self.assertEqual(Agent(self.store, Clipped()).run('Н-99', self.p)['status'], 'output_blocked')

    def test_F04_single_entity_neighbor(self):
        self.store.ingest('link', ['Н-17 связан с К-2.'], 'factory', ['staff'])
        self.store.ingest('single', ['К-2 имеет температуру отключения 120 °C.'], 'factory', ['staff'])
        seeds = [c['id'] for c in self.store.allowed(self.p) if c['title']=='link']
        chunks, _ = self.store.graph(self.p, seeds)
        self.assertIn('single', {c['title'] for c in chunks})

    def test_F05_rejected_http_requests_counted_once(self):
        from fastapi.testclient import TestClient
        import backend.api as api
        auth = Path(self.tmp.name) / 'auth.json'
        auth.write_text(json.dumps([dict(user='a',tenant='factory',roles=['staff'],token='test-token')]))
        def count():
            return sum(s.value for m in api.http_requests.collect() for s in m.samples if s.name=='knowledge_http_requests_total' and s.labels.get('route')=='/query')
        with patch.object(api, 'store', self.store), patch.object(api, 'agent', Agent(self.store)), patch.dict(os.environ, {'AUTH_FILE':str(auth)}):
            client = TestClient(api.app)
            before = count()
            self.assertEqual(client.post('/query', json={'question':'Н-17'}).status_code, 401)
            self.assertEqual(client.post('/query', json={'question':''},headers={'Authorization':'Bearer test-token'}).status_code, 422)
            self.assertEqual(client.post('/query', json={'question':'Н-17'},headers={'Authorization':'Bearer test-token'}).status_code, 200)
            self.assertEqual(count() - before, 3)


if __name__ == '__main__':
    unittest.main()

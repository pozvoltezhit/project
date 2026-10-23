import tempfile
import time
import unittest
from pathlib import Path
from backend.core import Agent, Principal, Store
from backend.retention import retain


class IntegrityTests(unittest.TestCase):
    def test_chain_detects_edit_and_retention_preserves_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(str(Path(tmp)/'audit.db'))
            store.ingest('doc',['Н-17 связан с К-2.'],'factory',['staff'])
            Agent(store).run('Н-17',Principal('a','factory',('staff',)))
            self.assertTrue(store.verify_audit())
            with store.connect() as db: db.execute('UPDATE history_time SET created_at=?',(time.time()-40*86400,))
            self.assertEqual(retain(store)['history_deleted'],0)
            self.assertEqual(retain(store,apply=True)['history_deleted'],1)
            self.assertTrue(store.verify_audit())
            with store.connect() as db: db.execute("UPDATE audit SET status='tampered' WHERE id=(SELECT max(id) FROM audit)")
            self.assertFalse(store.verify_audit())

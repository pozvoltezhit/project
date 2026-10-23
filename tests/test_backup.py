import json
import tempfile
import time
import unittest
from pathlib import Path

from backend.backup import create, restore
from backend.core import Agent, Principal, Store


class BackupTests(unittest.TestCase):
    def test_restore_security_and_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            store=Store(str(root/'source.db'))
            store.ingest('open',['Н-17 подключен к К-2.'],'factory',['staff'])
            store.ingest('closed',['Н-17: секретное число 246813579.'],'factory',['restricted'])
            identities=root/'auth.json'
            identities.write_text(json.dumps([dict(user='b',tenant='factory',roles=['staff'],token='synthetic-only')]))
            sources=root/'sources';sources.mkdir();(sources/'doc.txt').write_text('Synthetic source')
            snapshot=create(root/'backup',store,identities,sources)
            started=time.perf_counter()
            restore(root/'backup',root/'restored')
            restored=Store(str(root/'restored/knowledge.db'))
            result=Agent(restored).run('Н-17',Principal('b','factory',('staff',)))
            self.assertEqual(result['status'],'answered')
            self.assertNotIn('246813579',json.dumps(result))
            elapsed=time.perf_counter()-started
            self.assertLess(elapsed,30)
            with self.assertRaises(ValueError):restore(root/'backup',root/'restored')
            (root/'backup/sources/doc.txt').write_text('TAMPERED')
            with self.assertRaises(ValueError):restore(root/'backup',root/'tampered')

    def test_manifest_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'backup').mkdir()
            (root/'backup/manifest.json').write_text(json.dumps({'format':'knowledge-backup-v1','files':{'knowledge.db':'bad','identities.json':'bad','../outside':'bad'}}))
            with self.assertRaises((ValueError,FileNotFoundError)):restore(root/'backup',root/'restored')

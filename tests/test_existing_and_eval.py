import tempfile
import unittest
from pathlib import Path
from backend.core import Store
from backend.init_demo import initialize
from backend.evaluate import evaluate


class ExistingAndEvaluation(unittest.TestCase):
    def test_existing_security_suite(self):
        from backend.check import check
        check()

    def test_full_holdout_and_partial_hold(self):
        report=evaluate()
        self.assertEqual(report['gate']['decision'],'GO',report['cases'])
        self.assertEqual(report['coverage'],1)
        self.assertEqual(report['invalid'],0)
        partial=evaluate(limit=1)
        self.assertEqual(partial['gate']['decision'],'HOLD')

    def test_clean_demo_provisioning_without_credential_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'examples').mkdir()
            (root/'examples/open.txt').write_text('Н-17 подключен к К-2.',encoding='utf-8')
            initialize(root);initialize(root)
            self.assertTrue((root/'data/identities.json').exists())
            self.assertTrue(Store(str(root/'data/knowledge.db')).verify_audit())

"""Pure classification and receipt refusal only; no macOS sandbox execution."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.dont_write_bytecode=True
ROOT=Path(__file__).parent
spec=importlib.util.spec_from_file_location('nested_probe',ROOT/'diagnose_nested_sandbox.py')
d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)


class DiagnosticTests(unittest.TestCase):
    def test_single_empty_success(self):self.assertEqual(d.classify('single',0,b'',b''),'system-true-succeeded')
    def test_nested_empty_success(self):self.assertEqual(d.classify('nested',0,b'',b''),'system-true-succeeded')
    def test_exact_known_nested_failure(self):
        self.assertEqual(d.classify('nested',71,b'',b'sandbox-exec: sandbox_apply: Operation not permitted\n'),
                         'nested-sandbox-application-denied')
    def test_single_failure_not_misattributed(self):
        self.assertEqual(d.classify('single',71,b'',b'sandbox-exec: sandbox_apply: Operation not permitted\n'),
                         'unclassified-system-tool-result')
    def test_unknown_or_secret_suffix_remains_unclassified(self):
        for code,out,err in ((1,b'',b'unknown'),(71,b'secret',b'sandbox-exec: sandbox_apply: Operation not permitted'),
                             (71,b'',b'sandbox-exec: sandbox_apply: Operation not permitted\nsecret')):
            self.assertEqual(d.classify('nested',code,out,err),'unclassified-system-tool-result')
    def test_profile_unchanged(self):self.assertEqual(d.digest(ROOT/'runtime-offline.sb'),d.PROFILE_HASH)
    def test_pending_receipt_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'receipt.json';p.write_text('{"execution_approved":false}')
            q=subprocess.run([sys.executable,'-I',str(ROOT/'diagnose_nested_sandbox.py'),'--repository',temp,
                '--review-receipt',str(p)],capture_output=True,timeout=5)
            self.assertNotEqual(q.returncode,0);self.assertIn(b'not approved',q.stderr)


if __name__=='__main__':unittest.main()

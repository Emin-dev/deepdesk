"""First-party synthetic subprocess checks; no sandbox/dependency execution."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.dont_write_bytecode=True
ROOT=Path(__file__).parent
spec=importlib.util.spec_from_file_location('seatbelt_diagnostic',ROOT/'diagnose_seatbelt.py')
diag=importlib.util.module_from_spec(spec);spec.loader.exec_module(diag)


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def run_code(self,code,**kwargs):
        return diag.capture([sys.executable,'-I','-c',code],work=self.root,**kwargs)

    def test_parser_classification_contains_no_child_text(self):
        child=b'host must be * or localhost in network address\n::error::synthetic-secret'
        result=diag.classify(1,b'',child)
        self.assertEqual(result,'numeric-network-host-rejected-by-profile-parser')
        self.assertNotIn('secret',result)
        self.assertNotIn('::',result)

    def test_success_requires_no_output(self):
        self.assertEqual(diag.classify(0,b'',b''),'profile-compiled-and-system-true-succeeded')
        self.assertEqual(diag.classify(0,b'',b'host must be * or localhost'),'unclassified-failure-or-unexpected-output')

    def test_other_failure_remains_unclassified(self):
        self.assertEqual(diag.classify(1,b'',b'Operation not permitted'),'unclassified-failure-or-unexpected-output')

    def test_private_streams_separate_and_never_printed(self):
        console=io.StringIO()
        with contextlib.redirect_stdout(console):
            code,out,err=self.run_code('import sys;print("fixture-out");print("fixture-err",file=sys.stderr);sys.exit(2)')
        self.assertEqual((code,out,err),(2,b'fixture-out\n',b'fixture-err\n'))
        self.assertEqual(console.getvalue(),'')

    def test_output_cap(self):
        with self.assertRaisesRegex(RuntimeError,'output bound'):
            self.run_code('print("x"*9000)')

    def test_timeout(self):
        with self.assertRaisesRegex(RuntimeError,'deadline'):
            self.run_code('import time;time.sleep(5)',timeout=0.1)

    def test_closed_streams_timeout(self):
        with self.assertRaisesRegex(RuntimeError,'deadline'):
            self.run_code('import os,time;os.close(1);os.close(2);time.sleep(5)',timeout=0.1)

    def test_pending_receipt_fails_before_platform_or_spawn(self):
        receipt=self.root/'receipt.json';receipt.write_text(json.dumps({'execution_approved':False}))
        result=subprocess.run([sys.executable,'-I',str(ROOT/'diagnose_seatbelt.py'),'--repository',str(self.root),
            '--review-receipt',str(receipt)],capture_output=True,timeout=5)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'not approved',result.stderr)

    def test_unchanged_literal_profile(self):
        self.assertEqual(diag.digest(ROOT/'runtime-loopback.sb'),diag.PROFILE_HASH)
        code=(ROOT/'diagnose_seatbelt.py').read_text()
        self.assertIn('SERVER_ADDRESS=127.0.0.1:54321',code)
        self.assertNotIn('SERVER_ADDRESS=localhost:',code)


if __name__=='__main__': unittest.main()

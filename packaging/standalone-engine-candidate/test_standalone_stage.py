"""Static/first-party gate tests. No dependency code or subprocess is executed."""
import ast
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('standalone_stage',HERE/'standalone_stage.py')
stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)

class StageTests(unittest.TestCase):
    def test_shared_payload_download_notice_and_snapshot_logic_unchanged(self):
        base=ast.parse((HERE.parent/'engine-ci/runtime_asgi_stage.py').read_text())
        new=ast.parse((HERE/'standalone_stage.py').read_text())
        a={n.name:ast.dump(n) for n in base.body if isinstance(n,ast.FunctionDef)}
        b={n.name:ast.dump(n) for n in new.body if isinstance(n,ast.FunctionDef)}
        self.assertEqual(set(a),set(b))
        for name in a:
            if name!='main':self.assertEqual(a[name],b[name],name)
    def test_unapproved_receipt_fails_before_platform_or_network(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);receipt=root/'receipt.json';receipt.write_text(json.dumps({'execution_approved':False}))
            with patch.object(sys,'argv',['stage','--repository',d,'--review-receipt',str(receipt)]),patch.object(stage.platform,'system',side_effect=AssertionError('must not reach host check')):
                with self.assertRaisesRegex(RuntimeError,'not approved execution'):stage.main()
    def test_previous_asgi_approval_cannot_authorize_bundle(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);receipt=root/'receipt.json';receipt.write_text(json.dumps({'execution_approved':True,'scope':'complete-runtime-synthetic-asgi-only'}))
            with patch.object(sys,'argv',['stage','--repository',d,'--review-receipt',str(receipt)]):
                with self.assertRaisesRegex(RuntimeError,'not approved execution'):stage.main()
    def test_workflow_scope_and_no_uploads(self):
        text=(HERE/'standalone-core-macos.yml.template').read_text()
        for token in ['runs-on: macos-26','timeout-minutes: 25','contents: read','persist-credentials: false','engine-standalone-core-ci','github.event.repository.private == false']:
            self.assertIn(token,text)
        for token in ['upload-artifact@','cache@','secrets.','contents: write','brew install']:
            self.assertNotIn(token,text)
    def test_profile_only_tightens_passed_network_denial(self):
        text=(HERE/'standalone-offline.sb').read_text()
        self.assertIn('(deny network*)',text);self.assertNotIn('(allow network',text)
        for value in ['/opt/homebrew','/usr/local','/opt/local','ORIGINAL_PYTHON','ORIGINAL_RUNTIME','BUILD_ENV','SOURCE_TREE']:
            self.assertIn(value,text)
    def test_original_wrapper_is_not_overwritten(self):
        import hashlib
        self.assertEqual(hashlib.sha256((HERE.parent/'engine_entry.py').read_bytes()).hexdigest(),'c150823f009f0a9f004923413444894e95f3681d81f0fb94537be75cf7f778b9')

if __name__=='__main__':unittest.main()

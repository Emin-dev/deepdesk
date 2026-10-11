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
    def test_reviewed_production_wrapper_pin_matches(self):
        import hashlib
        self.assertEqual(hashlib.sha256((HERE.parent/'engine_entry.py').read_bytes()).hexdigest(),'7e4fdbe84458f1e8aed760d44852ff3a9823c729f56d161f3dd163120f118f65')

    def test_managed_policy_requires_its_own_execution_gate(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); receipt = root / 'receipt.json'
            for approval in (None, False):
                receipt.write_text(json.dumps({'execution_approved': True,
                    'scope': 'standalone-relocated-core-checks',
                    'managed_policy_execution_approved': approval}))
                with patch.object(sys, 'argv', ['stage','--repository',d,'--review-receipt',str(receipt)]), \
                     patch.object(stage.platform, 'system', side_effect=AssertionError('must not reach host check')):
                    with self.assertRaisesRegex(RuntimeError, 'managed policy review has not approved'):
                        stage.main()

    def test_managed_policy_runs_in_new_bounded_fixture_scope(self):
        source = (HERE / 'standalone_stage.py').read_text()
        self.assertIn("policy_scope = work / 'managed-policy-fixture-scope'", source)
        self.assertIn('cwd=policy_scope,writable=policy_scope,timeout=120', source)
        self.assertIn('managed_policy = policy_contract.parse_report(run([', source)
        self.assertIn("'managed_policy_contract':managed_policy", source)
        self.assertIn("if managed_policy['status'] != 'passed':", source)
        self.assertIn("'LDR_DATA_DIR':str(policy_scope / 'fixture/data')", source)

    def test_receipt_scope_and_all_available_candidate_pins_match(self):
        import hashlib
        root = HERE.parents[1]
        receipt = json.loads((HERE / 'review-receipt.json').read_text())
        for field in ('execution_approved','managed_policy_execution_approved','publication_approved','activation_approved'):
            self.assertIs(type(receipt[field]), bool)
        self.assertEqual(receipt['managed_policy_contract'], 'installed-wrapper-public-only-context-no-inference')
        for relative, expected in receipt['sha256'].items():
            self.assertEqual(hashlib.sha256((root / relative).read_bytes()).hexdigest(), expected, relative)

    def test_accepted_security_and_core_assertion_helpers_stay_byte_identical(self):
        import hashlib
        expected = {'packaging/standalone-engine-candidate/launcher.c': '148b2cddcedcc8b1d23daccd29bd834b900baf5e3a4d1dc7e0d534a50cbcbe1b', 'packaging/standalone-engine-candidate/standalone-offline.sb': '637bed3c29e86ae9b1640fe6edf018b50538ec597378113f7c1919bf255eee6e', 'packaging/engine-ci/runtime-offline.sb': '9d4f464140e5bb35efb2f937e820349b6f7a47482d4fcb2a618cc489b9bf4710', 'packaging/engine-ci/bounded_runtime.py': 'a94a58ba7e45f203fafd4d4d7a0d60ec91cd8366ac7ae8d55909c7d8b1d128f4', 'packaging/engine-ci/check_sqlcipher.py': '3064578960f0c3e02aabe4ccd1d2b860c3581102185f62fc5d9f310909e4eef1', 'packaging/engine-ci/smoke_asgi_authenticated.py': '15a536fc738b42bb1d957941b32335feb2e515bd5dc9757b3b552662c25ee4f3', 'packaging/engine-ci/runtime_checks.py': '3c075b235bc9a6ee98654926412097ffb663a01146a5ff2b9fbbb7a35de960f0', 'packaging/standalone-engine-candidate/relocate_check.py': '283bbf2900f6afe441aa7e4e48d2dcea786a6ceffbefc996d33a14a648ee586a'}
        for relative, value in expected.items():
            self.assertEqual(hashlib.sha256((HERE.parents[1] / relative).read_bytes()).hexdigest(), value, relative)

if __name__=='__main__':unittest.main()

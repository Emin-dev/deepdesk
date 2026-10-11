"""Relocation and approval tests use text files and fake runners only."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('relocate_check',Path(__file__).with_name('relocate_check.py'))
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

def inventory(root):
    return {str(p.relative_to(root)):p.read_text() for p in sorted(root.rglob('*')) if p.is_file()}

def output():
    return {'status':'passed','kind':'packaging-self-test','python':'3.12.15','sqlcipher':'4.7.0 community',
        'imported':r.EXPECTED_IMPORTS,'provider_sources':24,'network_research_tested':False,'authenticated_api_tested':False}

class RelocateTests(unittest.TestCase):
    def layout(self,root):
        source=root/'original'/'DeepdeskEngine.app';p=source/'Contents/MacOS/DeepdeskEngine';p.parent.mkdir(parents=True);p.write_text('synthetic-not-executable')
        parent=root/'relocated Ω';parent.mkdir();return source,parent/'DeepdeskEngine.app'
    def test_move_without_content_change(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source,destination=self.layout(root);manifest=inventory(source)
            result=r.relocate_bundle(source,destination,work_root=root,expected_manifest=manifest,inventory=inventory)
            self.assertFalse(source.exists());self.assertEqual(manifest,inventory(destination));self.assertFalse(result['native_code_executed'])
    def test_mutated_source_refused_before_move(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source,dest=self.layout(root)
            with self.assertRaisesRegex(ValueError,'source-bundle-manifest'):r.relocate_bundle(source,dest,work_root=root,expected_manifest={},inventory=inventory)
            self.assertTrue(source.exists());self.assertFalse(dest.exists())
    def test_outside_destination_refused(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as e:
            root=Path(d);source,dest=self.layout(root);outside=Path(e)/'DeepdeskEngine.app'
            with self.assertRaisesRegex(ValueError,'outside-disposable'):r.relocate_bundle(source,outside,work_root=root,expected_manifest=inventory(source),inventory=inventory)
    def test_existing_destination_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source,dest=self.layout(root);dest.mkdir()
            with self.assertRaisesRegex(ValueError,'invalid-relocation'):r.relocate_bundle(source,dest,work_root=root,expected_manifest=inventory(source),inventory=inventory)
    def test_plain_ascii_target_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source,dest=self.layout(root);(root/'ascii').mkdir();dest=root/'ascii'/'DeepdeskEngine.app'
            with self.assertRaisesRegex(ValueError,'space-and-unicode'):r.relocate_bundle(source,dest,work_root=root,expected_manifest=inventory(source),inventory=inventory)
    def test_output_contract(self):self.assertEqual(r.validate_self_test(json.dumps(output()).encode()),output())
    def test_raw_secret_field_refused(self):
        obj=output();obj['private']='SECRET'
        with self.assertRaisesRegex(ValueError,'schema'):r.validate_self_test(json.dumps(obj).encode())
    def test_secret_version_refused(self):
        obj=output();obj['sqlcipher']='::notice::SECRET'
        with self.assertRaisesRegex(ValueError,'format'):r.validate_self_test(json.dumps(obj).encode())
    def test_duplicate_output_refused(self):
        with self.assertRaisesRegex(ValueError,'duplicate'):r.validate_self_test(b'{"status":"passed","status":"passed"}')
    def test_oversized_output_refused(self):
        with self.assertRaisesRegex(ValueError,'size'):r.validate_self_test(b'x'*8193)
    def gate(self,manifest):
        return {'execution_approved':True,'scope':r.EXPECTED_SCOPE,'native_input_review_complete':True,
            'network_policy':'deny-all-tcp','original_build_read_denied':True,'bundle_write_denied':True,
            'bundle_manifest_sha256':r.manifest_digest(manifest)}
    def test_execution_unapproved_stops_before_runner(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);bundle,_=self.layout(root);calls=[]
            with self.assertRaisesRegex(ValueError,'not-approved'):
                r.checked_self_test(bundle,receipt={},expected_manifest=inventory(bundle),inventory=inventory,bounded_sandbox_runner=lambda *a,**k:calls.append(a))
            self.assertEqual(calls,[])
    def test_native_gate_false_stops_before_runner(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);bundle,_=self.layout(root);manifest=inventory(bundle);receipt=self.gate(manifest);receipt['native_input_review_complete']=False;calls=[]
            with self.assertRaisesRegex(ValueError,'gate-incomplete'):
                r.checked_self_test(bundle,receipt=receipt,expected_manifest=manifest,inventory=inventory,bounded_sandbox_runner=lambda *a,**k:calls.append(a))
            self.assertEqual(calls,[])
    def test_fake_runner_keeps_claim_narrow(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);bundle,_=self.layout(root);manifest=inventory(bundle);calls=[]
            def fake(command,**kwargs):calls.append((command,kwargs));return json.dumps(output()).encode()
            result=r.checked_self_test(bundle,receipt=self.gate(manifest),expected_manifest=manifest,inventory=inventory,bounded_sandbox_runner=fake)
            self.assertEqual(calls[0][0],[str(bundle/'Contents/MacOS/DeepdeskEngine'),'--self-test']);self.assertFalse(result['native_features_complete'])
    def test_core_scope_is_explicit_and_narrow(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);bundle,_=self.layout(root);manifest=inventory(bundle);receipt=self.gate(manifest)
            receipt.update(scope=r.CORE_SCOPE,native_input_review_complete=False)
            value=output();value.update(kind='packaging-core-self-test',imported=r.EXPECTED_IMPORTS[:-1]);calls=[]
            def fake(command,**kwargs):calls.append(command);return json.dumps(value).encode()
            result=r.checked_self_test(bundle,receipt=receipt,expected_manifest=manifest,inventory=inventory,bounded_sandbox_runner=fake,core_only=True)
            self.assertEqual(calls[0][-1],'--core-self-test');self.assertFalse(result['native_features_complete'])
    def test_core_record_cannot_pass_full_check(self):
        value=output();value.update(kind='packaging-core-self-test',imported=r.EXPECTED_IMPORTS[:-1])
        with self.assertRaisesRegex(ValueError,'contract-mismatch'):r.validate_self_test(json.dumps(value).encode())
    def test_runtime_mutation_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);bundle,_=self.layout(root);manifest=inventory(bundle)
            def fake(*a,**k):(bundle/'unexpected').write_text('changed');return json.dumps(output()).encode()
            with self.assertRaisesRegex(ValueError,'mutated-during'):
                r.checked_self_test(bundle,receipt=self.gate(manifest),expected_manifest=manifest,inventory=inventory,bounded_sandbox_runner=fake)

if __name__=='__main__':unittest.main()

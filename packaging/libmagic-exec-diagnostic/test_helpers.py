"""First-party synthetic tests; no Mac canary, native payload or source execution."""
import ast
import contextlib
import errno
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock
sys.dont_write_bytecode=True
HERE=Path(__file__).parent
spec=importlib.util.spec_from_file_location('diagnostic_stage_tests',HERE/'stage.py')
stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)

class Tests(unittest.TestCase):
    def test_closed_approval_before_other_inputs(self):
        with self.assertRaisesRegex(RuntimeError,'approval is closed'):
            stage.validate_receipt({'execution_approved':False},Path('/absent'),Path('/absent'))
    def test_scope_and_destination_cannot_change(self):
        with self.assertRaises(RuntimeError):stage.validate_receipt({'execution_approved':True,'scope':'engine'},HERE,HERE)
        with self.assertRaisesRegex(RuntimeError,'destination'):
            stage.validate_receipt({'execution_approved':True,'scope':stage.SCOPE,'base_commit':stage.BASE,'destination_branch':'main'},HERE,HERE)
    def test_exact_receipt_hashes_and_deployed_workflow_gate(self):
        receipt={'execution_approved':True,'scope':stage.SCOPE,'destination_branch':stage.BRANCH,'base_commit':stage.BASE,
            'source_downloads_allowed':False,'compiler_execution_allowed':False,'native_payload_execution_allowed':False,
            'profile_changes_allowed':False,'host_image_observation':'read-only-_NSGetExecutablePath-no-executable-selection',
            'sha256':{name:stage.sha(HERE/name) for name in stage.NAMES}}
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);workflow=root/'.github/workflows/engine-libmagic-exec-diagnostic-macos.yml';workflow.parent.mkdir(parents=True)
            workflow.write_bytes((HERE/'libmagic-exec-diagnostic-macos.yml.template').read_bytes())
            stage.validate_receipt(receipt,HERE,root)
            workflow.write_bytes(workflow.read_bytes()+b'changed')
            with self.assertRaisesRegex(RuntimeError,'workflow differs'):stage.validate_receipt(receipt,HERE,root)
        receipt['sha256']['probe.py']='0'*64
        with self.assertRaisesRegex(RuntimeError,'bytes differ'):stage.validate_receipt(receipt,HERE,HERE,deployed=False)

    def test_frozen_helper_and_profiles_are_exact(self):
        for name,digest in [('bounded_runtime.py',stage.BOUNDS_SHA),('offline.sb',stage.OFFLINE_SHA),('smoke-no-exec.sb',stage.SMOKE_SHA)]:
            self.assertEqual(stage.sha(HERE/name),digest)
    def test_probe_marker_complete_denial_requires_zero_exit(self):
        data=b'entered\nimports_ready\npermission_denied\n'
        self.assertTrue(stage.parse_probe_marker(data,'zero')['canary_passed'])
        self.assertEqual(stage.parse_probe_marker(data,'nonzero_exit')['classification'],'exit_marker_mismatch')
        for status in ['timeout','output_limit','work_limit','unknown']:
            self.assertEqual(stage.parse_probe_marker(data,status)['classification'],'child_inconclusive')
            self.assertFalse(stage.parse_probe_marker(data,status)['canary_passed'])
    def test_failure_results_preserve_failure_and_detect_zero_mismatch(self):
        for token,category in stage.OUTCOMES.items():
            if token=='permission_denied':continue
            data=b'entered\nimports_ready\n'+token.encode()+b'\n'
            parsed=stage.parse_probe_marker(data,'nonzero_exit')
            self.assertEqual(parsed['classification'],category);self.assertFalse(parsed['canary_passed'])
            self.assertEqual(stage.parse_probe_marker(data,'zero')['classification'],'exit_marker_mismatch')
        self.assertEqual(stage.parse_probe_marker(b'entered\nsetup_exception\n','nonzero_exit')['classification'],'entered_setup_exception')
    def test_incomplete_markers_never_prove_launch_denial_or_success(self):
        for data,progress in [(b'','python_entry_not_observed'),(b'entered\n','entered_before_imports_incomplete'),
                              (b'entered\nimports_ready\n','entered_probe_incomplete')]:
            parsed=stage.parse_probe_marker(data,'nonzero_exit')
            self.assertEqual(parsed['classification'],progress);self.assertFalse(parsed['canary_passed'])
            self.assertEqual(stage.parse_probe_marker(data,'zero')['classification'],'exit_marker_mismatch')
    def test_strict_order_and_marker_cap(self):
        for bad in [b'x'*129,b'entered',b'permission_denied\n',b'imports_ready\nentered\npermission_denied\n',
                    b'entered\nentered\n',b'entered\nimports_ready\npermission_denied\nextra\n',
                    b'entered\nimports_ready\n::error::synthetic\n',b'entered\r\n',b'\xff']:
            with self.assertRaises(RuntimeError):stage.parse_probe_marker(bad,'zero')
        with self.assertRaises(RuntimeError):stage.parse_probe_marker(b'','not-reviewed')
    def test_marker_symlink_oversize_hardlink_missing_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);target=root/'target';target.write_bytes(b'entered\n')
            link=root/'link';link.symlink_to(target)
            self.assertEqual(stage.evaluate_probe_marker(link,'zero')['classification'],'invalid_marker')
            large=root/'large';large.write_bytes(b'x'*129)
            self.assertEqual(stage.evaluate_probe_marker(large,'zero')['classification'],'invalid_marker')
            alias=root/'alias';os.link(target,alias)
            self.assertEqual(stage.evaluate_probe_marker(alias,'zero')['classification'],'invalid_marker')
            self.assertEqual(stage.evaluate_probe_marker(root/'missing','zero')['classification'],'invalid_marker')
            self.assertEqual(stage.evaluate_probe_marker(root,'zero')['classification'],'invalid_marker')
    def test_marker_regular_empty_and_fixed_data(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'marker';p.write_bytes(b'');self.assertEqual(stage.read_marker(p),b'')
            p.write_bytes(b'entered\nimports_ready\npermission_denied\n')
            self.assertTrue(stage.evaluate_probe_marker(p,'zero')['canary_passed'])
    def test_known_failures_and_secret_unknown(self):
        expected={'Bounded subprocess failed; raw output withheld':'nonzero_exit','Bounded subprocess timed out':'timeout',
            'No subprocess time budget remains':'timeout','Private output limit exceeded':'output_limit',
            'Bounded working-set limit exceeded':'work_limit','Bounded working-set limit exceeded at completion':'work_limit'}
        self.assertEqual(stage.FAILURES,expected)
        for message,category in expected.items():self.assertEqual(stage.failure_category(RuntimeError(message)),category)
        for error in [ValueError('synthetic-secret'),RuntimeError('synthetic-secret'),RuntimeError('Bounded subprocess timed out','synthetic-secret')]:
            self.assertEqual(stage.failure_category(error),'unknown')
    def test_private_child_never_forwards_workflow_commands_or_secret_errors(self):
        def fail(*args,**kwargs):print('::error::synthetic-secret');raise RuntimeError('synthetic-secret')
        public=io.StringIO()
        with contextlib.redirect_stdout(public):
            row,output=stage.private_child(types.SimpleNamespace(run_bounded=fail),[],phase='restrictive-exec-probe')
        self.assertEqual(public.getvalue(),'');self.assertIsNone(output)
        self.assertEqual(row,{'phase':'restrictive-exec-probe','child_status':'unknown','output_metadata_available':False})
        self.assertNotIn('synthetic-secret',json.dumps(row))
        with self.assertRaises(RuntimeError):stage.private_child(types.SimpleNamespace(run_bounded=fail),[],phase='::error::unreviewed')
    def test_private_child_success_parses_only_exact_helper_metadata(self):
        output=b'synthetic'
        summary={'bounded_step':'passed','stdout_bytes':len(output),'stdout_sha256':hashlib.sha256(output).hexdigest(),
                 'stderr_bytes':0,'stderr_sha256':hashlib.sha256(b'').hexdigest()}
        def helper(*args,**kwargs):print(json.dumps(summary));return output
        public=io.StringIO()
        with contextlib.redirect_stdout(public):row,value=stage.private_child(types.SimpleNamespace(run_bounded=helper),[],phase='sdk-path')
        self.assertEqual(public.getvalue(),'');self.assertEqual(value,output);self.assertEqual(row['child_status'],'zero')
        summary['unexpected']='::error::secret'
        row,value=stage.private_child(types.SimpleNamespace(run_bounded=helper),[],phase='sdk-path')
        self.assertEqual(row['child_status'],'unknown');self.assertIsNone(value)
    def run_mocked_probe(self,failure):
        with tempfile.TemporaryDirectory() as td:
            marker=Path(td)/'marker';marker.write_bytes(b'')
            fake=types.SimpleNamespace(run=mock.Mock(side_effect=failure),CalledProcessError=subprocess.CalledProcessError)
            with mock.patch.dict(sys.modules,{'subprocess':fake}),mock.patch.object(sys,'argv',['-c',str(marker)]):
                with self.assertRaises(SystemExit) as result:exec(compile((HERE/'probe.py').read_text(),str(HERE/'probe.py'),'exec'),{'__name__':'__main__'})
            return marker.read_bytes(),result.exception.code
    def test_probe_fixed_branches_with_mocked_subprocess_only(self):
        for error,expected,exitcode in [(OSError(errno.EPERM,'secret'),'permission_denied',0),(OSError(errno.EACCES,'secret'),'permission_denied',0),
            (OSError(errno.ENOENT,'secret'),'other_oserror',1),(subprocess.CalledProcessError(1,'secret'),'child_nonzero',1),
            (ValueError('secret'),'other_exception',1),(None,'exec_succeeded',1)]:
            data,code=self.run_mocked_probe(error)
            self.assertEqual(data,b'entered\nimports_ready\n'+expected.encode()+b'\n');self.assertEqual(code,exitcode)
            self.assertEqual(stage.parse_probe_marker(data,'zero' if code==0 else 'nonzero_exit')['canary_passed'],exitcode==0)
    def test_control_has_no_subprocess_and_writes_only_entry(self):
        self.assertNotIn('subprocess',(HERE/'control.py').read_text().split('\n',1)[1])
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'marker';p.write_bytes(b'')
            with mock.patch.object(sys,'argv',['-c',str(p)]):exec(compile((HERE/'control.py').read_text(),'control','exec'),{})
            self.assertEqual(p.read_bytes(),b'entered\n')
    def test_source_contract_no_compiler_invocation_or_download(self):
        text=(HERE/'stage.py').read_text();tree=ast.parse(text)
        self.assertNotIn('urllib',text);self.assertNotIn("run([clang",text);self.assertNotIn("run([fixture",text)
        self.assertIn("'-I','-c',(helpers/'probe.py').read_text()",text)
        self.assertIn("'-I','-c',(helpers/'control.py').read_text()",text)
        self.assertIn("'CC':clang",text);self.assertIn("timeout=min(10,remaining)",text)
        self.assertIn("reserved_output<=64*1024",text);self.assertIn('deadline=started+120',text)
        self.assertEqual(stage.PHASES,('sdk-path','compiler-path','control-entry','restrictive-exec-probe'))
    def test_exact_bounds_reject_output_timeout_disk_and_hide_failed_output(self):
        spec=importlib.util.spec_from_file_location('diag_bounds_test',HERE/'bounded_runtime.py')
        helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);common={'cwd':root,'env':{'PATH':os.defpath},'work':root,'timeout':2,'disk_limit':1024**2,'output_limit':128,'public_summary':True}
            for code,updates,category in [('print("x"*1000)',{},'output_limit'),('import time;time.sleep(1)',{'timeout':0.02},'timeout'),
                ('print("::error::hidden");raise SystemExit(1)',{},'nonzero_exit')]:
                args=dict(common);args.update(updates);public=io.StringIO()
                with contextlib.redirect_stdout(public):row,output=stage.private_child(helper,[sys.executable,'-B','-I','-c',code],phase='restrictive-exec-probe',**args)
                self.assertEqual(public.getvalue(),'');self.assertEqual(row['child_status'],category);self.assertIsNone(output)
            (root/'large').write_bytes(b'x'*200)
            args=dict(common,disk_limit=100)
            row,_=stage.private_child(helper,[sys.executable,'-B','-I','-c','pass'],phase='control-entry',**args)
            self.assertEqual(row['child_status'],'work_limit')
    def test_bounded_timeout_reaps_owned_process_and_temporary_directory(self):
        spec=importlib.util.spec_from_file_location('diag_cleanup_bounds_test',HERE/'bounded_runtime.py')
        helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);pidfile=root/'pid'
            code='import os,sys,time;open(sys.argv[1],"w").write(str(os.getpid()));time.sleep(60)'
            row,_=stage.private_child(helper,[sys.executable,'-B','-I','-c',code,str(pidfile)],phase='restrictive-exec-probe',
                cwd=root,env={'PATH':os.defpath},work=root,timeout=0.2,disk_limit=1024**2,output_limit=1024,public_summary=True)
            self.assertEqual(row['child_status'],'timeout');self.assertTrue(pidfile.is_file())
            pid=int(pidfile.read_text())
            with self.assertRaises(ProcessLookupError):os.kill(pid,0)
        self.assertFalse(root.exists())
    def test_top_level_unknown_error_has_only_fixed_output_and_nonzero_exit(self):
        tree=ast.parse((HERE/'stage.py').read_text());guard=tree.body[-1]
        self.assertIsInstance(guard,ast.If)
        namespace={'__name__':'__main__','json':json,'main':mock.Mock(side_effect=ValueError('synthetic-secret-unknown'))}
        public=io.StringIO();errors=io.StringIO()
        with contextlib.redirect_stdout(public),contextlib.redirect_stderr(errors):
            with self.assertRaises(SystemExit) as result:exec(compile(ast.Module(body=[guard],type_ignores=[]),'diagnostic_guard','exec'),namespace)
        self.assertEqual(result.exception.code,1);self.assertTrue(result.exception.__suppress_context__)
        self.assertEqual(json.loads(public.getvalue()),{'diagnostic_status':'failed','detail':'withheld'})
        self.assertEqual(errors.getvalue(),'');self.assertNotIn('synthetic-secret',public.getvalue())

    def test_host_image_observation_only_fixed_classes_hash_and_equality(self):
        with mock.patch.object(stage,'read_host_image_path',return_value='/Applications/Xcode.app/Contents/Developer/usr/bin/python3'):
            result=stage.host_image_observation(Path('/Applications/Xcode.app/Contents/Developer/usr/bin/python3'))
            self.assertTrue(result['host_image_matches_resolved_interpreter'])
            self.assertEqual(result['host_image_basename_class'],'python3')
        private='/Applications/Xcode.app/Private/Resources/Python.app/Contents/MacOS/Python'
        with mock.patch.object(stage,'read_host_image_path',return_value=private):
            result=stage.host_image_observation(Path('/usr/bin/python3'))
            self.assertFalse(result['host_image_matches_resolved_interpreter'])
            self.assertEqual(result['host_image_basename_class'],'Python')
            self.assertEqual(result['host_image_path_class'],'apple_applications')
            self.assertNotIn(private,json.dumps(result));self.assertNotIn('Private',json.dumps(result))
            self.assertRegex(result['host_image_path_sha256'],'^[0-9a-f]{64}$')
        with mock.patch.object(stage,'read_host_image_path',side_effect=RuntimeError('synthetic-secret')):
            result=stage.host_image_observation(Path('/usr/bin/python3'))
            self.assertEqual(result['host_image_observation'],'unavailable');self.assertIsNone(result['host_image_matches_resolved_interpreter'])
            self.assertNotIn('synthetic-secret',json.dumps(result))
    def test_host_image_observation_never_selects_new_executable(self):
        source=(HERE/'stage.py').read_text();tree=ast.parse(source)
        calls=[node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name)
               and node.func.id=='host_image_observation']
        self.assertEqual(len(calls),1);self.assertEqual(ast.dump(calls[0].args[0]),ast.dump(ast.Name(id='py',ctx=ast.Load())))
        self.assertIn('ctypes.CDLL(None)',source);self.assertIn('ctypes.create_string_buffer(16384)',source)
        self.assertNotIn("CDLL('/",source)
        for bad in ['relative/secret','/'+('x'*16385)]:
            with mock.patch.object(stage,'read_host_image_path',return_value=bad):
                self.assertEqual(stage.host_image_observation(Path('/usr/bin/python3'))['host_image_observation'],'unavailable')

    def test_workflow_template_scope(self):
        text=(HERE/'libmagic-exec-diagnostic-macos.yml.template').read_text()
        for required in ['runs-on: macos-26','timeout-minutes: 3','contents: read','persist-credentials: false','engine-libmagic-exec-diagnostic-ci','private == false']:
            self.assertIn(required,text)
        for forbidden in ['actions/upload-artifact@','actions/cache@','brew install','pip install']:
            self.assertNotIn(forbidden,text)

if __name__=='__main__':unittest.main()

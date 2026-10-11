"""Only stdlib/first-party helper tests. Never executes downloaded code or native builds."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import sys
sys.dont_write_bytecode=True
import tarfile
import tempfile
import types
import unittest
from unittest.mock import patch
HERE=Path(__file__).resolve().parent

def load(name):
    spec=importlib.util.spec_from_file_location('test_pdf_'+name,HERE/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
stage=load('stage');archives=load('archive_tools');bounds=load('bounds');native=load('native_checks')

class Stream:
    def __init__(self,fd):self.fd=fd;self.closed=False
    def fileno(self):return self.fd
    def close(self):self.closed=True
class Process:
    pid=12345
    def __init__(self,code):self.returncode=code;self.stdout=Stream(10);self.stderr=Stream(11)
    def poll(self):return self.returncode
    def wait(self,timeout=None):return self.returncode
class Selector:
    def __init__(self):self.keys={}
    def register(self,stream,event,data):self.keys[stream.fd]=types.SimpleNamespace(fileobj=stream,data=data)
    def unregister(self,stream):self.keys.pop(stream.fd)
    def get_map(self):return self.keys
    def select(self,timeout=None):return [(x,1) for x in list(self.keys.values())]
    def close(self):self.keys={}

class HelperTests(unittest.TestCase):
    def test_input_scans_throttled_deadlines_not_throttled(self):
        now=[0.0];scans=[]
        checker=stage.InputChecks(10,lambda:scans.append(now[0]),clock=lambda:now[0])
        for _ in range(9346):
            checker();now[0]+=0.00005
        self.assertEqual(checker.calls,9346);self.assertEqual(len(scans),1)
        now[0]=2.1;checker();self.assertEqual(len(scans),2)
        checker(force=True);self.assertEqual(len(scans),3)
        now[0]=10
        with self.assertRaises(stage.LaneError):checker()
        self.assertEqual(len(scans),3)
    def test_input_scan_cannot_overrun_deadline_silently(self):
        now=[0]
        def scan():now[0]=11
        checker=stage.InputChecks(10,scan,clock=lambda:now[0])
        with self.assertRaises(stage.LaneError):checker()
    def test_meson_actual_diagnostic_path(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td).resolve();work=root/'work';work.mkdir();lane=stage.Lane(root,HERE,work,(archives,bounds,native));phase=lane.directory('meson-probe')
            log=phase/'out/meson-logs/meson-log.txt';log.parent.mkdir(parents=True);log.write_bytes(b'compiler cannot compile programs')
            record={'status':'failed','failure_class':'child_exit','exit_code':1,'stdout_bytes':0,'stderr_bytes':0}
            with patch.object(bounds,'run',return_value=(record,b'',b'')),patch('sys.stdout',new=io.StringIO()):
                with self.assertRaises(stage.PhaseError) as caught:lane.run('meson-configure',['mock-never-executed'],directory=phase)
            self.assertEqual(caught.exception.record['private_diagnostics'][1]['sha256'],hashlib.sha256(log.read_bytes()).hexdigest())
    def test_meson_adapter_preserves_internal_args_and_flags(self):
        adapter=load('meson_entry')
        for argv in (['setup','out','source'],['--internal','copy','a','b'],['--internal','regenerate','source','.']):
            with self.subTest(argv=argv):
                executable='/reviewed/immutable/tree-python/python/bin/python3.12';calls=[]
                universal=types.SimpleNamespace(python_command=[executable]);mesonlib=types.SimpleNamespace(python_command=universal.python_command)
                def main_run(args,mainfile):
                    calls.append((args,universal.python_command+[mainfile,'--internal','regenerate','source','.']));return 0
                main=types.SimpleNamespace(run=main_run)
                modules={'mesonbuild.utils.universal':universal,'mesonbuild.mesonlib':mesonlib,'mesonbuild.mesonmain':main}
                fake=types.SimpleNamespace(executable=executable,flags=types.SimpleNamespace(isolated=1,no_site=1,ignore_environment=1),path=['stdlib'],argv=['adapter.py',*argv],stderr=io.StringIO())
                with patch.object(adapter,'sys',fake),patch.object(adapter,'validate_wheel') as validate,patch.object(adapter,'import_module',side_effect=modules.__getitem__):
                    self.assertEqual(adapter.run(),0)
                validate.assert_called_once_with(Path('/reviewed/immutable/tree-meson'))
                self.assertEqual(calls[0][0],argv);self.assertEqual(calls[0][1][:3],[executable,'-I','-S']);self.assertEqual(fake.argv,['adapter.py',*argv]);self.assertEqual(fake.path[0],'/reviewed/immutable/tree-meson')
    def test_meson_adapter_rejects_missing_isolation_before_import(self):
        adapter=load('meson_entry');fake=types.SimpleNamespace(flags=types.SimpleNamespace(isolated=0,no_site=0,ignore_environment=0),stderr=io.StringIO())
        with patch.object(adapter,'sys',fake),patch.object(adapter,'import_module') as load_package:
            self.assertEqual(adapter.run(['--internal','copy','a','b']),81)
        load_package.assert_not_called();self.assertEqual(fake.stderr.getvalue(),'deepdesk_meson_isolation_required\n')
    def test_meson_adapter_pins_match_exact_member_manifest(self):
        adapter=load('meson_entry');rows=json.loads((HERE/'members/meson.json').read_text())['members'];expected={r['path']:r.get('sha256') for r in rows}
        for name,sha in adapter.PINS.items():self.assertEqual(sha,expected[name])
        with self.assertRaises(ValueError):adapter.wheel_from_interpreter('/usr/bin/python3')
    def test_invalid_utf_requires_exact_source_defined_error(self):
        contract=json.loads((HERE/'utf8-contract.json').read_text());self.assertEqual(contract['required_value'],-23);self.assertEqual(contract['normal_nonmatch_value'],-1)
        source=(HERE/'provider_probe.c').read_text();self.assertIn('if(utf8_result!=PCRE2_ERROR_UTF8_ERR21)return 29;',source);self.assertIn('!=PCRE2_ERROR_NOMATCH)return 40;',source)
        self.assertNotIn('md,NULL)>=0)return 29',source)
        # First-party mock of the exact C equality guard; NOMATCH, partial and
        # unrelated errors cannot be credited as invalid-UTF rejection.
        for code in (-1,-2,-3,-22,-24,-44,0,1):self.assertNotEqual(code,contract['required_value'])
        self.assertEqual(-23,contract['required_value'])
    def test_ci_exercises_internal_helper_and_ninja_regeneration(self):
        source=(HERE/'stage.py').read_text();self.assertIn("'meson-internal-copy'",source);self.assertIn("'meson-ninja-regenerate'",source);self.assertIn("info.get('version')=='1.1'",source)
        self.assertNotIn("meson_entry.py',trees['meson']",source)
    def test_raw_child_bytes_never_in_public_record(self):
        payload=b'::error::private /Users/secret\nC compiler cannot create executables\n'
        reads={10:[payload,b''],11:[b'operation not permitted\n',b'']}
        with tempfile.TemporaryDirectory() as td, patch.object(bounds.subprocess,'Popen',return_value=Process(77)),patch.object(bounds.selectors,'DefaultSelector',Selector),patch.object(bounds.os,'read',side_effect=lambda fd,n:reads[fd].pop(0)),patch.object(bounds.os,'killpg',side_effect=ProcessLookupError),patch.object(bounds.shutil,'disk_usage',return_value=types.SimpleNamespace(free=8*1024**3)):
            r,out,err=bounds.run(['not-executed'],cwd=td,env={},work=td,deadline=999999999,output_remaining=10000)
        text=json.dumps(r);self.assertEqual(r['exit_code'],77);self.assertEqual(r['failure_class'],'child_exit');self.assertNotIn('::error',text);self.assertNotIn('/Users',text);self.assertEqual(r['stdout_sha256'],hashlib.sha256(payload).hexdigest());self.assertIn('compiler_unusable',r['classifications'])
    def test_output_limit(self):
        reads={10:[b'x'*40],11:[b'']}
        with tempfile.TemporaryDirectory() as td,patch.object(bounds.subprocess,'Popen',return_value=Process(0)),patch.object(bounds.selectors,'DefaultSelector',Selector),patch.object(bounds.os,'read',side_effect=lambda fd,n:reads[fd].pop(0)),patch.object(bounds.os,'killpg',side_effect=ProcessLookupError),patch.object(bounds.shutil,'disk_usage',return_value=types.SimpleNamespace(free=8*1024**3)):
            r,out,err=bounds.run(['not-executed'],cwd=td,env={},work=td,deadline=999999999,output_remaining=10)
        self.assertEqual(r['failure_class'],'output_limit');self.assertEqual(out,b'');self.assertEqual(r['stdout_bytes'],40)
    def test_deadline_before_spawn(self):
        with patch.object(bounds.subprocess,'Popen') as spawn:
            r,_,_=bounds.run([],cwd='.',env={},work='.',deadline=1,output_remaining=20,clock=lambda:2)
        spawn.assert_not_called();self.assertEqual(r['failure_class'],'deadline_exceeded')
    def test_expected_negative_exit(self):
        reads={10:[b''],11:[b'']}
        with tempfile.TemporaryDirectory() as td,patch.object(bounds.subprocess,'Popen',return_value=Process(1)),patch.object(bounds.selectors,'DefaultSelector',Selector),patch.object(bounds.os,'read',side_effect=lambda fd,n:reads[fd].pop(0)),patch.object(bounds.os,'killpg',side_effect=ProcessLookupError),patch.object(bounds.shutil,'disk_usage',return_value=types.SimpleNamespace(free=8*1024**3)):
            r,_,_=bounds.run(['not-executed'],cwd=td,env={},work=td,deadline=999999999,output_remaining=20,expected_codes=(1,))
        self.assertEqual(r['status'],'passed');self.assertEqual(r['exit_code'],1)
    def test_paths_fail_closed(self):
        for value in ('../escape','/absolute','x//z','x/./z','x\\z','x\x00z'):
            with self.assertRaises(archives.ContractError):archives.relative(value)
    def test_redirect_rejects_unknown_and_credentials(self):
        handler=archives.OfficialRedirect(['release-assets.githubusercontent.com'])
        for url in ('http://release-assets.githubusercontent.com/x','https://ghcr.io/token','https://u:p@release-assets.githubusercontent.com/x'):
            with self.assertRaises(archives.ContractError):handler.redirect_request(None,None,302,'',{},url)
    def test_exact_tar_extract(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);tar=p/'x.tar';data=b'plain reviewed fixture'
            with tarfile.open(tar,'w') as t:
                m=tarfile.TarInfo('root/file');m.size=len(data);m.mode=0o644;m.mtime=123;t.addfile(m,io.BytesIO(data))
            digest=archives.digest(tar);record={'path':'root/file','kind':'file','size':len(data),'mode':0o644,'mtime':123,'sha256':hashlib.sha256(data).hexdigest()}
            manifest=p/'members.json';manifest.write_text(json.dumps({'archive_sha256':digest,'expanded_bytes':len(data),'members':[record]}))
            pin={'id':'fixture','format':'tar','root':'root','sha256':digest,'member_manifest_sha256':archives.digest(manifest),'member_count':1,'expanded_bytes':len(data),'max_member_bytes':len(data)}
            root=archives.extract(pin,tar,p/'out',manifest);self.assertEqual((root/'file').read_bytes(),data);self.assertEqual(int((root/'file').stat().st_mtime),123)
    def test_mo_fixture(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'fr/x.mo';stage.write_mo(p);b=p.read_bytes();header=struct.unpack_from('<7I',b);self.assertEqual(header[0],0x950412de);self.assertEqual(header[2],3);self.assertIn('caf\u00e9'.encode(),b);self.assertIn(b'one apple\x00many apples',b)
    def test_profile_write_scope(self):
        text=(HERE/'offline.sb').read_text();self.assertEqual(text.count('(allow file-write*'),1);self.assertIn('(param "PHASE_DIR")',text);self.assertIn('(deny network*)',text);self.assertIn('(param "IMMUTABLE_DIR")',text);self.assertIn('(param "CONTROL_DIR")',text)
    def test_private_diagnostics_no_follow(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td).resolve();target=root/'secret';target.write_text('private bytes');linked=root/'config.log';linked.symlink_to(target)
            record=bounds.private_file_record(linked,'config_log');self.assertTrue(record['invalid_or_unreadable']);self.assertNotIn('sha256',record)
            directory=root/'logs';directory.symlink_to(root,target_is_directory=True)
            record=bounds.private_file_record(directory/'secret','meson_log');self.assertTrue(record['invalid_or_unreadable'])
            record=bounds.private_file_record(target,'known');self.assertEqual(record['sha256'],hashlib.sha256(b'private bytes').hexdigest());self.assertNotIn(str(root),json.dumps(record))
    def test_private_diagnostics_oversize(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td).resolve()/'config.log'
            with p.open('wb') as f:f.truncate(2*1024**2+1)
            record=bounds.private_file_record(p,'config_log');self.assertTrue(record['oversize']);self.assertNotIn('sha256',record)
    def test_api_mentions_fixed_allowlist(self):
        record=stage.required_api_mentions(b"::error:: /Users/private/sdk/ffi/ffi.h undefined ffi_call anything malicious")
        self.assertEqual(record,['header_ffi','symbol_ffi_call']);self.assertNotIn('/Users',json.dumps(record))
    def test_false_gates(self):
        self.assertTrue(stage.FALSE_GATES);self.assertTrue(all(v is False for v in stage.FALSE_GATES.values()));self.assertEqual(len(stage.INPUT_HASHES),6)
    def test_receipt_closed(self):
        receipt=json.loads((HERE/'review-receipt.json').read_text());self.assertFalse(receipt['execution_approved']);self.assertFalse(receipt['independent_review_passed'])
        with self.assertRaises(stage.LaneError):stage.validate_receipt(HERE.parents[1],HERE,receipt,True)
    def test_no_workflow_activation_or_artifact(self):
        text=(HERE/'pdf-foundation-macos.yml.template').read_text();self.assertIn('runs-on: macos-26',text);self.assertIn('timeout-minutes: 12',text);self.assertNotIn('upload-artifact@',text);self.assertNotIn('actions/cache@',text);self.assertIn('      - engine-pdf-foundation-v1-ci',text);self.assertIn("'packaging/pdf-foundation-candidate/**'",text)

if __name__=='__main__':unittest.main()

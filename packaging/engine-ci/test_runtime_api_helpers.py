"""First-party/synthetic helper tests only; no downloaded module execution."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).parent

def load(filename, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

stage = load('runtime_api_stage.py','test_runtime_stage')
bounds = load('bounded_runtime.py','test_runtime_bounds')


class SourceWheelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = b'# synthetic source only\n'
        self.contract = {'fixture.py':{'sha256':hashlib.sha256(self.data).hexdigest()}}
        self.wheel = self.root / 'fixture-1.0-py3-none-any.whl'

    def write(self, payload=None, extra=None):
        with zipfile.ZipFile(self.wheel,'w') as z:
            z.writestr('fixture.py', self.data if payload is None else payload)
            z.writestr('fixture-1.0.dist-info/METADATA','Metadata-Version: 2.1\nName: fixture\nVersion: 1.0\n')
            z.writestr('fixture-1.0.dist-info/WHEEL','Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
            z.writestr('fixture-1.0.dist-info/RECORD','')
            if extra:
                z.writestr(*extra)

    def test_exact_source_payload_accepted(self):
        self.write()
        result = stage.validate_built_wheel(self.wheel,'fixture','1.0',self.contract)
        self.assertTrue(result['source_payload_matches'])
        self.assertEqual(result['source_payload_files'],1)

    def test_changed_payload_refused(self):
        self.write(payload=b'raise RuntimeError("synthetic")\n')
        with self.assertRaisesRegex(RuntimeError,'differs'):
            stage.validate_built_wheel(self.wheel,'fixture','1.0',self.contract)

    def test_new_payload_refused(self):
        self.write(extra=('unexpected.py',b'# synthetic\n'))
        with self.assertRaises(RuntimeError):
            stage.validate_built_wheel(self.wheel,'fixture','1.0',self.contract)

    def test_pth_refused_even_if_source_hash_matches(self):
        self.contract['fixture.pth']={'sha256':hashlib.sha256(b'import synthetic').hexdigest()}
        self.write(extra=('fixture.pth',b'import synthetic'))
        with self.assertRaises(RuntimeError):
            stage.validate_built_wheel(self.wheel,'fixture','1.0',self.contract)

    def test_unsafe_member_refused(self):
        self.write(extra=('../escape',b'synthetic'))
        with self.assertRaises(RuntimeError):
            stage.validate_built_wheel(self.wheel,'fixture','1.0',self.contract)

    def test_console_entrypoint_refused_for_small_sources(self):
        self.write(extra=('fixture-1.0.dist-info/entry_points.txt',b'[console_scripts]\nfixture=fixture:main\n'))
        with self.assertRaises(RuntimeError):
            stage.validate_built_wheel(self.wheel,'fixture','1.0',self.contract)


class ApplicationMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.wheel=self.root/'local_deep_research-1.10.7-py3-none-any.whl'
        self.payload={path:b'# synthetic source/resource\n' for path in (
            'local_deep_research/web/fastapi_app.py',
            'local_deep_research/defaults/settings_deepdesk_ddg.json',
            'local_deep_research/llm/providers/implementations/synthetic.py',
            'local_deep_research/web/templates/index.html','local_deep_research/web/static/base.css')}
        self.license=b'Synthetic fixture license text\n'
        self.contract={'src/'+path:{'sha256':hashlib.sha256(data).hexdigest()} for path,data in self.payload.items()}
        self.contract['LICENSE']={'sha256':hashlib.sha256(self.license).hexdigest()}
        self.contract['NOTICE']={'sha256':hashlib.sha256(b'extra').hexdigest()}
        self.entries='[console_scripts]\nldr-web = local_deep_research.web.app:main\nldr-mcp = local_deep_research.mcp:run_server\n'

    def write(self,entries='default',licenses='default'):
        prefix='local_deep_research-1.10.7.dist-info/'
        if entries=='default': entries=self.entries
        if licenses=='default': licenses={'LICENSE':self.license}
        with zipfile.ZipFile(self.wheel,'w') as z:
            for path,data in self.payload.items():z.writestr(path,data)
            z.writestr(prefix+'METADATA','Metadata-Version: 2.1\nName: local-deep-research\nVersion: 1.10.7\n')
            z.writestr(prefix+'WHEEL','Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
            z.writestr(prefix+'RECORD','')
            if entries is not None:z.writestr(prefix+'entry_points.txt',entries)
            for name,data in licenses.items():z.writestr(prefix+'licenses/'+name,data)

    def validate(self):
        return stage.validate_built_wheel(self.wheel,'local-deep-research','1.10.7',self.contract,app=True)

    def test_exact_declared_scripts_and_license_accepted(self):
        self.write();self.assertTrue(self.validate()['source_payload_matches'])

    def test_added_console_script_refused(self):
        self.write(entries=self.entries+'surprise = subprocess:check_call\n')
        with self.assertRaises(RuntimeError):self.validate()

    def test_changed_script_target_refused(self):
        self.write(entries=self.entries.replace('local_deep_research.mcp:run_server','subprocess:check_call'))
        with self.assertRaises(RuntimeError):self.validate()

    def test_omitted_entry_points_refused(self):
        self.write(entries=None)
        with self.assertRaises(RuntimeError):self.validate()

    def test_omitted_required_license_refused(self):
        self.write(licenses={})
        with self.assertRaises(RuntimeError):self.validate()

    def test_changed_license_refused(self):
        self.write(licenses={'LICENSE':b'changed'})
        with self.assertRaises(RuntimeError):self.validate()

    def test_added_license_refused(self):
        self.write(licenses={'LICENSE':self.license,'NOTICE':b'extra'})
        with self.assertRaises(RuntimeError):self.validate()

    def test_omitted_required_resource_refused(self):
        del self.payload['local_deep_research/web/static/base.css']
        self.write()
        with self.assertRaises(RuntimeError):self.validate()


class SmallSourceLicenseTests(unittest.TestCase):
    inputs=(('google-search-results','2.4.2','serpapi/fixture.py',('LICENSE',)),
            ('langdetect','1.0.9','langdetect/fixture.py',('LICENSE','NOTICE')),
            ('wikipedia','1.4.0','wikipedia/fixture.py',('LICENSE',)),
            ('jstyleson','0.0.2','jstyleson.py',()))

    def check_variant(self,mutation):
        for name,version,payload,licenses in self.inputs:
            if mutation in ('omit','change') and not licenses:continue
            with self.subTest(package=name), tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);wheel=root/'fixture.whl'
                contract={payload:{'sha256':hashlib.sha256(b'# synthetic').hexdigest()}}
                notices={x:('synthetic '+x).encode() for x in licenses}
                for x,b in notices.items():contract[x]={'sha256':hashlib.sha256(b).hexdigest()}
                if mutation=='omit':del notices[licenses[0]]
                elif mutation=='change':notices[licenses[0]]=b'changed'
                elif mutation=='add':
                    notices['COPYING.extra']=b'extra'
                    contract['COPYING.extra']={'sha256':hashlib.sha256(b'extra').hexdigest()}
                prefix=name.replace('-','_')+'-'+version+'.dist-info/'
                with zipfile.ZipFile(wheel,'w') as z:
                    z.writestr(payload,b'# synthetic')
                    z.writestr(prefix+'METADATA','Metadata-Version: 2.1\nName: '+name+'\nVersion: '+version+'\n')
                    z.writestr(prefix+'WHEEL','Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
                    z.writestr(prefix+'RECORD','')
                    for x,b in notices.items():z.writestr(prefix+'licenses/'+x,b)
                if mutation=='none':stage.validate_built_wheel(wheel,name,version,contract)
                else:
                    with self.assertRaises(RuntimeError):stage.validate_built_wheel(wheel,name,version,contract)

    def test_all_four_exact_license_sets(self):self.check_variant('none')
    def test_required_small_source_notices_cannot_be_omitted(self):self.check_variant('omit')
    def test_small_source_license_changes_refused(self):self.check_variant('change')
    def test_small_source_license_additions_refused(self):self.check_variant('add')


class BoundsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.env={'PATH':'/usr/bin:/bin','HOME':str(self.root)}

    def run_code(self,code,**kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return bounds.run_bounded([sys.executable,'-I','-c',code],cwd=self.root,env=self.env,
                                      work=self.root,timeout=kwargs.pop('timeout',5),**kwargs)

    def test_stdout_and_stderr_separate(self):
        result=self.run_code('import sys; print("{}",end="");print("private diagnostic",file=sys.stderr)')
        self.assertEqual(json.loads(result),{})

    def test_synthetic_stdin(self):
        result=self.run_code('import sys;print(sys.stdin.buffer.read().decode(),end="")',input_data=b'synthetic')
        self.assertEqual(result,b'synthetic')

    def test_output_cap(self):
        with self.assertRaisesRegex(RuntimeError,'output limit'):
            self.run_code('print("x"*10000)',output_limit=100)

    def test_timeout(self):
        with self.assertRaisesRegex(RuntimeError,'timed out'):
            self.run_code('import time;time.sleep(5)',timeout=0.1)

    def test_disk_cap(self):
        (self.root/'fixed').write_bytes(b'x'*1000)
        with self.assertRaisesRegex(RuntimeError,'working-set'):
            self.run_code('import time;time.sleep(5)',disk_limit=100)

    def test_closed_streams_do_not_stop_disk_monitor(self):
        code='import os,time\nos.close(1);os.close(2)\nopen("excess","wb").write(b"x"*4096)\ntime.sleep(2.5)'
        with self.assertRaisesRegex(RuntimeError,'working-set'):
            self.run_code(code,disk_limit=128,timeout=5)

    def test_quick_exit_over_limit_fails_final_disk_check(self):
        with self.assertRaisesRegex(RuntimeError,'working-set'):
            self.run_code('open("excess","wb").write(b"x"*4096)',disk_limit=128)

    def test_rejects_oversized_stdin_before_spawn(self):
        with self.assertRaisesRegex(RuntimeError,'stdin'):
            self.run_code('pass',input_data=b'x'*16385)

    @unittest.skipUnless(hasattr(os,'fork'),'POSIX process-group helper test')
    def test_orphaned_descendant_stream_times_out(self):
        with self.assertRaisesRegex(RuntimeError,'timed out'):
            self.run_code('import os,time\nif os.fork(): os._exit(0)\ntime.sleep(10)',timeout=0.2)

    def test_empty_approval_receipt_refuses_before_platform_or_download(self):
        receipt=self.root/'review.json'
        receipt.write_text('{"execution_approved":false}')
        result=subprocess.run([sys.executable,'-I',str(ROOT/'runtime_api_stage.py'),
            '--repository',str(self.root),'--review-receipt',str(receipt)],capture_output=True,timeout=5)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'has not approved execution',result.stderr)
        self.assertFalse((self.root/'immutable').exists())


if __name__=='__main__':
    unittest.main()

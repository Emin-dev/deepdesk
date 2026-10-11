"""First-party synthetic helper tests. No download or third-party execution."""
import ast
import copy
import difflib
import errno
import hashlib
import types
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock
import sys
sys.dont_write_bytecode=True
HERE=Path(__file__).parent
spec=importlib.util.spec_from_file_location('libmagic_stage_under_test',HERE/'stage.py')
stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)

class CandidateTests(unittest.TestCase):
    def test_gate_closed_before_hash_or_deployment(self):
        with self.assertRaisesRegex(RuntimeError,'approval is closed'):
            stage.validate_receipt({'execution_approved':False},Path('/absent'),Path('/absent'))
    def test_scope_cannot_broaden(self):
        with self.assertRaisesRegex(RuntimeError,'scope differs'):
            stage.validate_receipt({'execution_approved':True,'scope':'complete-engine'},HERE,HERE)
    def test_linker_effects_need_explicit_gate(self):
        receipt={'execution_approved':True,'scope':stage.SCOPE,'source_sha256':stage.SOURCE_SHA,
                 'source_changes_allowed':'exact-reviewed-compress-nofork-overlay-only','destination_branch':'engine-libmagic-source-v2-ci',
                 'source_overlay_approved':True,'source_overlay_before_sha256':stage.OVERLAY_BEFORE_SHA,
                 'source_overlay_after_sha256':stage.OVERLAY_AFTER_SHA,'source_overlay_patch_sha256':stage.OVERLAY_PATCH_SHA}
        with self.assertRaisesRegex(RuntimeError,'linker effects'):
            stage.validate_receipt(receipt,HERE,HERE)
    def test_reviewed_bounds_copy_exact(self):
        self.assertEqual(stage.digest(HERE/'bounded_runtime.py'),stage.BOUNDED_SHA)
    def test_pin_exact(self):
        p=json.loads((HERE/'source-pin.json').read_text());stage.validate_pin(p,HERE/'source-members.json')
        for key,value in [('url','https://ghcr.io/alternate'),('size',1),('source_changes_allowed',True),('version','5.49')]:
            q=dict(p);q[key]=value
            with self.assertRaises(RuntimeError):stage.validate_pin(q,HERE/'source-members.json')
    def test_member_paths(self):
        for bad in ['/absolute','../up','a/../x','a//b','a/./b','a\\b','a\x00b','']:
            with self.assertRaises(RuntimeError):stage.safe_relative(bad)
        self.assertEqual(str(stage.safe_relative('file-5.48/src/file.c')),'file-5.48/src/file.c')
    def test_redirect_always_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'redirect'):
            stage.NoRedirect().redirect_request(None,None,302,'Found',{},'https://other.example/file')
    def test_source_hash_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);a=root/'x.tar.gz';a.write_bytes(b'not the source')
            with self.assertRaises(RuntimeError):stage.extract_exact(a,root/'out',{})
            self.assertFalse((root/'out').exists())
    def synthetic_tar(self,root,*,unsafe=False,symlink=False,wrong_member_hash=False):
        target=root/'fixture.tar.gz';rows=[]
        with tarfile.open(target,'w:gz') as archive:
            for index in range(655):
                name='file-5.48' if index==0 else 'file-5.48/d'+str(index)
                m=tarfile.TarInfo(name);m.mode=0o755;m.mtime=100;m.type=tarfile.DIRTYPE
                r={'path':name,'type':'directory','size':0,'mode':m.mode,'mtime':m.mtime}
                content=None
                if index==654:
                    m.name='../escape' if unsafe else 'file-5.48/value';m.type=tarfile.SYMTYPE if symlink else tarfile.REGTYPE
                    m.linkname='/outside' if symlink else '';m.mode=0o644;content=b'text';m.size=0 if symlink else 4
                    r={'path':m.name,'type':'file','size':m.size,'mode':m.mode,'mtime':m.mtime,
                       'sha256':'0'*64 if wrong_member_hash else hashlib.sha256(content).hexdigest()}
                archive.addfile(m,io.BytesIO(content) if content and not symlink else None);rows.append(r)
        sha=stage.digest(target)
        return target,{'archive_sha256':sha,'members':rows,'expanded_bytes':0 if symlink else 4}
    def test_exact_synthetic_extraction_keeps_bytes_mode_mtime(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);a,c=self.synthetic_tar(root)
            with mock.patch.object(stage,'SOURCE_SHA',stage.digest(a)),mock.patch.object(stage,'EXPANDED_SIZE',4):
                result=stage.extract_exact(a,root/'out',c)
            self.assertEqual((result/'value').read_bytes(),b'text')
            self.assertEqual(int((result/'value').stat().st_mtime),100)
            self.assertEqual((result/'value').stat().st_mode&0o777,0o644)
    def test_unsafe_link_or_member_change_rejected(self):
        for option in ['unsafe','symlink','wrong_member_hash']:
            with self.subTest(option=option),tempfile.TemporaryDirectory() as td:
                root=Path(td);a,c=self.synthetic_tar(root,**{option:True})
                with mock.patch.object(stage,'SOURCE_SHA',stage.digest(a)),mock.patch.object(stage,'EXPANDED_SIZE',c['expanded_bytes']):
                    with self.assertRaises(RuntimeError):stage.extract_exact(a,root/'out',c)
                self.assertFalse((root/'escape').exists())
    def test_required_codecs(self):
        text='#define ZLIBSUPPORT 1\n#define BZLIBSUPPORT 1\n#define XZLIBSUPPORT 1\n'
        caps=stage.capabilities(text);self.assertTrue(caps['XZLIBSUPPORT']);self.assertFalse(caps['ZSTDLIBSUPPORT'])
        with self.assertRaises(RuntimeError):stage.capabilities('#define ZLIBSUPPORT 1\n')
    def test_native_paths(self):
        valid='binary:\n\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1.0.0)\n'
        self.assertEqual(stage.parse_otool_loads(valid),['/usr/lib/libSystem.B.dylib'])
        stage.validate_loads(stage.parse_otool_loads(valid),HERE,False)
        for bad in ['@rpath/libevil.dylib','/usr/lib/../homebrew/libevil.dylib']:
            with self.assertRaises(RuntimeError):stage.parse_otool_loads('binary:\n\t'+bad+' (compatibility version 1)\n')
        with self.assertRaises(RuntimeError):stage.validate_loads(['/opt/homebrew/lib/libz.dylib'],HERE,False)
    def test_staged_links_do_not_escape(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'good').write_bytes(b'x');(root/'alias').symlink_to('good')
            self.assertEqual(stage.snapshot(root)['alias'],{'link':'good'})
            (root/'escape').symlink_to('/etc/passwd')
            with self.assertRaises(RuntimeError):stage.snapshot(root)
    def test_smoke_is_strict_and_runtime_images_contained(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);prefix=root/'prefix';prefix.mkdir();library=prefix/'libmagic.1.dylib';library.write_bytes(b'synthetic')
            exe=root/'fixture';exe.write_bytes(b'synthetic')
            text='\n'.join(sorted(stage.EXPECTED_FIXTURES)+['loaded_image='+str(exe),'loaded_image='+str(library),
                'loaded_image=/usr/lib/libSystem.B.dylib','pilot_patched_build_mime_two_codecs_and_external_rejection_passed'])
            self.assertEqual(len(stage.validate_smoke(text,prefix,exe)),3)
            for bad in [text+'\nfixture_pass=extra:success',text+'\nunexpected output',text.replace(str(library),'/opt/homebrew/lib/libmagic.dylib'),
                        text.replace('gzip_text_no_external_helper:text/plain','gzip_text_no_external_helper:application/gzip'),
                        text.replace('bzip2_text_no_external_helper:text/plain','bzip2_text_no_external_helper:application/x-bzip2'),
                        text.replace('application/x-decompression-error-gzip-Fork-is-required-to-uncompress--but-disabled','application/x-decompression-error-gzip-Cannot-posix-spawn')]:
                with self.assertRaises(RuntimeError):stage.validate_smoke(bad,prefix,exe)
    def test_download_exact_synthetic_bytes_no_auth_or_redirect(self):
        payload=b'synthetic archive'
        class Response:
            status=200
            headers={'Content-Length':str(len(payload))}
            def __enter__(self):self.stream=io.BytesIO(payload);return self
            def __exit__(self,*args):return False
            def geturl(self):return stage.SOURCE_URL
            def read(self,size):return self.stream.read(size)
        class Opener:
            def open(self,request,timeout):
                self.request=request;return Response()
        opener=Opener()
        with tempfile.TemporaryDirectory() as td, mock.patch.object(stage,'SOURCE_SIZE',len(payload)), \
             mock.patch.object(stage,'SOURCE_SHA',hashlib.sha256(payload).hexdigest()):
            target=Path(td)/'archive'
            stage.download(target,stage.time.monotonic()+5,opener)
            self.assertEqual(target.read_bytes(),payload)
        self.assertEqual(opener.request.full_url,stage.SOURCE_URL)
        self.assertIsNone(opener.request.get_header('Authorization'))
        self.assertIsNone(opener.request.get_header('Cookie'))
    def test_reused_bounds_output_and_time_limits(self):
        spec=importlib.util.spec_from_file_location('bounds_under_test',HERE/'bounded_runtime.py')
        helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
        with tempfile.TemporaryDirectory() as td:
            work=Path(td);env={'PATH':os.defpath}
            for code,kwargs in [('print("x"*10000)',{'output_limit':100}),
                                ('import time;time.sleep(2)',{'timeout':0.05})]:
                options={'timeout':2,'output_limit':10000};options.update(kwargs)
                with self.assertRaises(RuntimeError):
                    helper.run_bounded([sys.executable,'-I','-c',code],cwd=work,env=env,work=work,
                        disk_limit=1024**2,public_summary=False,**options)
    def test_reused_bounds_workspace_limit(self):
        spec=importlib.util.spec_from_file_location('bounds_disk_under_test',HERE/'bounded_runtime.py')
        helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
        with tempfile.TemporaryDirectory() as td:
            work=Path(td);(work/'large').write_bytes(b'x'*100)
            with self.assertRaisesRegex(RuntimeError,'working-set'):
                helper.run_bounded([sys.executable,'-I','-c','print("bounded")'],cwd=work,
                    env={'PATH':os.defpath},work=work,timeout=2,disk_limit=10,public_summary=False)
    def test_network_canary_accepts_only_creation_or_connect_permission_denial(self):
        tree=ast.parse((HERE/'stage.py').read_text())
        values=[node.value.value for node in ast.walk(tree) if isinstance(node,ast.Assign)
                and any(isinstance(target,ast.Name) and target.id=='net' for target in node.targets)
                and isinstance(node.value,ast.Constant)]
        self.assertEqual(len(values),1)
        for failure in [errno.EPERM,errno.EACCES]:
            with mock.patch.dict(sys.modules,{'socket':types.SimpleNamespace(socket=mock.Mock(side_effect=OSError(failure,'synthetic')))}):
                exec(values[0],{})
            sock=mock.Mock();sock.connect_ex.return_value=failure
            with mock.patch.dict(sys.modules,{'socket':types.SimpleNamespace(socket=mock.Mock(return_value=sock))}):
                exec(values[0],{})
        for failure in [0,errno.ETIMEDOUT,errno.ENETUNREACH,errno.ECONNREFUSED]:
            sock=mock.Mock();sock.connect_ex.return_value=failure
            with mock.patch.dict(sys.modules,{'socket':types.SimpleNamespace(socket=mock.Mock(return_value=sock))}):
                with self.assertRaises(AssertionError):exec(values[0],{})

    def test_source_overlay_gate_separate_from_execution(self):
        receipt={'execution_approved':True,'scope':stage.SCOPE,'source_sha256':stage.SOURCE_SHA,
                 'source_changes_allowed':'exact-reviewed-compress-nofork-overlay-only','source_overlay_approved':False}
        with self.assertRaisesRegex(RuntimeError,'overlay approval is closed'):
            stage.validate_receipt(receipt,HERE,HERE)
    def test_overlay_static_guard_move_preserves_builtin_and_blocks_external(self):
        overlay=json.loads((HERE/'source-overlay.json').read_text())
        before=overlay['before_block'];after=overlay['after_block']
        self.assertIn('if (decompress) {\n\t\tif (nofork)',before)
        self.assertEqual(after.count('if (nofork)'),1)
        self.assertLess(after.index('return (*decompress)'),after.index('if (nofork)'))
        self.assertIn('return (*decompress)(old, newch, bytes_max, n, 1);\n\t}\n\tif (nofork)',after)
        self.assertEqual(before.count('Fork is required to uncompress, but disabled'),1)
        self.assertEqual(after.count('Fork is required to uncompress, but disabled'),1)
        self.assertEqual(stage.digest(HERE/'compress-nofork.patch'),stage.OVERLAY_PATCH_SHA)
        self.assertEqual(stage.digest(HERE/'source-members.json'),json.loads((HERE/'source-pin.json').read_text())['source_members_sha256'])
    def synthetic_overlay(self,root):
        source=root/'file-5.48';(source/'src').mkdir(parents=True)
        pinned=json.loads((HERE/'source-overlay.json').read_text())
        original=('/* synthetic source fixture */\n'+pinned['before_block']+'\n\t(void)fflush(stdout);\n').encode()
        changed=original.replace(pinned['before_block'].encode(),pinned['after_block'].encode())
        target=source/'src/compress.c';target.write_bytes(original)
        for p in [target,source/'src',source]:os.utime(p,(100,100))
        contract={'members':list(stage.overlay_inventory(source).values())}
        patch=''.join(difflib.unified_diff(original.decode().splitlines(keepends=True),changed.decode().splitlines(keepends=True),
            fromfile='a/src/compress.c',tofile='b/src/compress.c')).encode()
        patch_path=root/'patch';patch_path.write_bytes(patch)
        pinned.update(before_sha256=hashlib.sha256(original).hexdigest(),after_sha256=hashlib.sha256(changed).hexdigest(),
            before_size=len(original),after_size=len(changed),patch_sha256=hashlib.sha256(patch).hexdigest())
        return source,contract,pinned,patch_path
    def test_overlay_exact_one_member_and_mtime(self):
        with tempfile.TemporaryDirectory() as td:
            source,contract,overlay,patch=self.synthetic_overlay(Path(td))
            with mock.patch.object(stage,'OVERLAY_BEFORE_SHA',overlay['before_sha256']), \
                 mock.patch.object(stage,'OVERLAY_AFTER_SHA',overlay['after_sha256']), \
                 mock.patch.object(stage,'OVERLAY_PATCH_SHA',overlay['patch_sha256']):
                result=stage.apply_overlay(source,contract,overlay,patch)
                self.assertEqual(result['changed_members'],1)
                self.assertEqual(int((source/'src/compress.c').stat().st_mtime),100)
                with self.assertRaises(RuntimeError):stage.apply_overlay(source,contract,overlay,patch)
    def test_overlay_rejects_changed_input_scope_patch_and_extra_member(self):
        for failure in ['before','after_pin','member','patch','extra','other_metadata']:
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as td:
                source,contract,overlay,patch=self.synthetic_overlay(Path(td))
                pins=dict(overlay)
                if failure=='before':(source/'src/compress.c').write_bytes(b'changed')
                if failure=='after_pin':overlay['after_sha256']='0'*64
                if failure=='member':overlay['relative_path']='src/file.c'
                if failure=='patch':patch.write_bytes(patch.read_bytes()+b'changed')
                if failure=='extra':(source/'extra').write_bytes(b'changed')
                if failure=='other_metadata':os.utime(source/'src',(101,101))
                with mock.patch.object(stage,'OVERLAY_BEFORE_SHA',pins['before_sha256']), \
                     mock.patch.object(stage,'OVERLAY_AFTER_SHA',pins['after_sha256']), \
                     mock.patch.object(stage,'OVERLAY_PATCH_SHA',pins['patch_sha256']):
                    with self.assertRaises(RuntimeError):stage.apply_overlay(source,contract,overlay,patch)
    def test_smoke_exec_denial_is_separate_and_canary_fail_closed(self):
        profile=(HERE/'smoke-no-exec.sb').read_text();base=(HERE/'offline.sb').read_text()
        self.assertEqual(profile,base+'(deny process-exec)\n(allow process-exec (literal (param "FIXTURE_PATH")))\n')
        tree=ast.parse((HERE/'stage.py').read_text())
        values=[n.value.value for n in ast.walk(tree) if isinstance(n,ast.Assign)
                and any(isinstance(t,ast.Name) and t.id=='exec_probe' for t in n.targets) and isinstance(n.value,ast.Constant)]
        self.assertEqual(len(values),1)
        for value in [errno.EPERM,errno.EACCES]:
            with mock.patch.dict(sys.modules,{'subprocess':types.SimpleNamespace(run=mock.Mock(side_effect=OSError(value,'synthetic')))}):
                exec(values[0],{})
        for outcome in [None,OSError(errno.ENOENT,'synthetic'),OSError(errno.ETIMEDOUT,'synthetic')]:
            with mock.patch.dict(sys.modules,{'subprocess':types.SimpleNamespace(run=mock.Mock(side_effect=outcome))}):
                with self.assertRaises((RuntimeError,AssertionError)):exec(values[0],{})
        c=(HERE/'smoke_fixture.c').read_text()
        self.assertIn('MAGIC_COMPRESS_TRANSP | MAGIC_NO_COMPRESS_FORK',c)
        self.assertIn('external_compress_helper_rejected',c)
        self.assertIn('application/x-decompression-error-gzip-Fork-is-required-to-uncompress--but-disabled',c)

    def test_workflow_inert_and_scoped(self):
        s=(HERE/'libmagic-source-macos.yml.template').read_text()
        self.assertIn('runs-on: macos-26',s);self.assertIn('contents: read',s);self.assertIn('private == false',s)
        self.assertIn('persist-credentials: false',s);self.assertNotIn('actions/upload-artifact@',s)
        self.assertNotIn('actions/cache@',s);self.assertIn('\n  push:',s)
        self.assertIn("      - 'packaging/libmagic-source-candidate-v2/**'",s)
        self.assertIn('(deny file-read* (subpath \"/opt/local\"))',(HERE/'offline.sb').read_text())

if __name__=='__main__':unittest.main()

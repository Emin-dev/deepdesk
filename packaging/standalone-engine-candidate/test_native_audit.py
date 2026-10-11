"""Synthetic Mach-O fixtures only; no downloaded native code is executed."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('native_audit',Path(__file__).with_name('native_audit.py'))
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)


def command(cmd,text):
    n=12 if cmd==0x8000001c else 24
    raw=text.encode()+b'\0'
    size=(n+len(raw)+7)//8*8
    data=struct.pack('<III',cmd,size,n)+b'\0'*(n-12)+raw
    return data+b'\0'*(size-len(data))


def binary(*commands,cpu=a.ARM64,filetype=2):
    blob=b''.join(commands)
    return struct.pack('<8I',0xfeedfacf,cpu,0,filetype,len(commands),len(blob),0,0)+blob


class NativeAuditTests(unittest.TestCase):
    def test_arm_header(self):
        self.assertEqual(a.parse_macho(binary())['cpu'],a.ARM64)
    def test_wrong_architecture(self):
        with self.assertRaisesRegex(ValueError,'non-arm64'):
            a.parse_macho(binary(cpu=0x01000007))
    def test_bad_command_length(self):
        data=binary(struct.pack('<II',0xc,4))
        with self.assertRaisesRegex(ValueError,'invalid-load-command'):a.parse_macho(data)
    def test_bad_string_offset(self):
        data=binary(struct.pack('<III',0xc,24,8)+b'\0'*12)
        with self.assertRaisesRegex(ValueError,'offset'):a.parse_macho(data)
    def test_unterminated_string(self):
        data=binary(struct.pack('<III',0xc,32,24)+b'\0'*12+b'abcdefgh')
        with self.assertRaisesRegex(ValueError,'unterminated'):a.parse_macho(data)
    def test_install_id_is_not_dependency(self):
        meta=a.parse_macho(binary(command(0xd,'@rpath/libsample.dylib'),filetype=6))
        self.assertEqual(meta['loads'],[])
        self.assertEqual(meta['install_id'],'@rpath/libsample.dylib')
    def test_universal_arm_slice(self):
        raw=binary(); data=struct.pack('>II5I',0xcafebabe,1,a.ARM64,0,28,len(raw),0)+raw
        self.assertEqual(a.parse_macho(data)['container'],'universal')
    def test_universal_offset_outside(self):
        raw=binary(); data=struct.pack('>II5I',0xcafebabe,1,a.ARM64,0,999,len(raw),0)+raw
        with self.assertRaisesRegex(ValueError,'invalid-fat-slice'):a.parse_macho(data)
    def test_apple_path_components(self):
        self.assertTrue(a.apple_path('/usr/lib/libSystem.B.dylib'))
        for p in ['/usr/lib/../local/x','/usr/lib//x','/usr/library/x','/opt/homebrew/x']:
            self.assertFalse(a.apple_path(p))
    def layout(self,root):
        files={
            'Contents/MacOS/DeepdeskEngine':binary(command(0xc,'/usr/lib/libSystem.B.dylib')),
            'Contents/Resources/Python/bin/python3.12':binary(command(0x8000001c,'@executable_path/../lib'),command(0xc,'@rpath/libpython3.12.dylib')),
            'Contents/Resources/Python/lib/libpython3.12.dylib':binary(command(0xd,'@rpath/libpython3.12.dylib'),filetype=6)}
        for n,data in files.items():
            p=root/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        return {n:[n if n.endswith(('DeepdeskEngine','python3.12')) else 'Contents/Resources/Python/bin/python3.12'] for n in files}
    def test_actual_python_executable_context(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);contexts=self.layout(root);out=a.audit_bundle(root,contexts)
            self.assertEqual(out['native_file_count'],3)
            python=next(x for x in out['records'] if x['path'].endswith('bin/python3.12'))
            self.assertEqual(python['loads'][0]['resolved'],'Contents/Resources/Python/lib/libpython3.12.dylib')
    def test_different_content_name_collision_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);contexts=self.layout(root)
            path=root/'private/libpython3.12.dylib';path.parent.mkdir();path.write_bytes(binary(command(0xd,'@rpath/libpython3.12.dylib'),command(0xc,'/usr/lib/libSystem.B.dylib'),filetype=6))
            contexts['private/libpython3.12.dylib']=['Contents/Resources/Python/bin/python3.12']
            with self.assertRaisesRegex(ValueError,'unreviewed-native-name-collision'):a.audit_bundle(root,contexts)
    def test_duplicate_same_bytes_not_collision(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);contexts=self.layout(root)
            path=root/'private/libpython3.12.dylib';path.parent.mkdir();path.write_bytes((root/'Contents/Resources/Python/lib/libpython3.12.dylib').read_bytes())
            contexts['private/libpython3.12.dylib']=['Contents/Resources/Python/bin/python3.12']
            result=a.audit_bundle(root,contexts)
            self.assertEqual(result['reviewed_name_collisions'],{})
    def test_incomplete_contexts_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);contexts=self.layout(root);contexts.pop('Contents/MacOS/DeepdeskEngine')
            with self.assertRaisesRegex(ValueError,'incomplete-native-context-set'):a.audit_bundle(root,contexts)
    def test_host_rpath_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);contexts=self.layout(root)
            (root/'Contents/MacOS/DeepdeskEngine').write_bytes(binary(command(0x8000001c,'/opt/homebrew/lib')))
            with self.assertRaisesRegex(ValueError,'host-native-path'):a.audit_bundle(root,contexts)
    def test_escaping_symlink_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'app';root.mkdir();contexts=self.layout(root)
            (Path(d)/'outside').write_text('synthetic')
            (root/'escape').symlink_to('../outside')
            with self.assertRaisesRegex(ValueError,'escapes-bundle'):a.audit_bundle(root,contexts)
    def test_unresolved_dependency_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);contexts=self.layout(root)
            (root/'Contents/MacOS/DeepdeskEngine').write_bytes(binary(command(0xc,'@rpath/missing.dylib')))
            with self.assertRaisesRegex(ValueError,'unresolved-or-ambiguous'):a.audit_bundle(root,contexts)
    def test_executable_wrong_context_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);contexts=self.layout(root)
            contexts['Contents/Resources/Python/bin/python3.12']=['Contents/MacOS/DeepdeskEngine']
            with self.assertRaisesRegex(ValueError,'executable-context-mismatch'):a.audit_bundle(root,contexts)

if __name__=='__main__':unittest.main()

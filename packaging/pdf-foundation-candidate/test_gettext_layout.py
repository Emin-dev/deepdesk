"""Inert first-party topology and sandbox-cwd regressions; no make or compiler."""
import ast
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
sys.dont_write_bytecode=True
import tempfile
import types
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
def load(name):
    spec=importlib.util.spec_from_file_location('layout_'+name,HERE/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
stage=load('stage');bounds=load('bounds')
CONTRACT=json.loads((HERE/'gettext-layout-contract.json').read_text())

def gettext_section(module):
    """Compile only the actual first-party orchestration statements with mocked methods."""
    source=ast.parse(Path(module.__file__).read_text())
    lane=next(n for n in source.body if isinstance(n,ast.ClassDef) and n.name=='Lane')
    execute=next(n for n in lane.body if isinstance(n,ast.FunctionDef) and n.name=='execute')
    start=next(i for i,n in enumerate(execute.body) if isinstance(n,ast.Assign) and ast.unparse(n.value)=="self.directory('gettext-build')")
    end=next(i for i,n in enumerate(execute.body) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='self.symbols' and isinstance(n.value.args[0],ast.Constant) and n.value.args[0].value=='libintl')
    function=ast.parse('def section(self,trees,contract):\n    pass\n').body[0]
    function.body=copy.deepcopy(execute.body[start:end+1])
    namespace=dict(module.__dict__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),'<first-party-gettext-section>','exec'),namespace)
    return namespace['section']

class GettextLayoutTests(unittest.TestCase):
    def layout(self,root):
        phase=root/'gettext-build';phase.mkdir();build=phase/'intl';build.mkdir()
        (build/'config.h').write_bytes(b'/* INERT FIRST-PARTY GENERATED HEADER */\n#define TEST_CONFIG 1\n')
        return phase,build

    def test_pinned_parent_prerequisite_is_absent_in_previous_flat_layout(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);phase,build=self.layout(root)
            self.assertEqual(CONTRACT['bare_parent_prerequisites'],['../config.h'])
            self.assertEqual(len(CONTRACT['object_rules']),25)
            self.assertFalse((phase/'../config.h').exists())
            stage.bind_gettext_config_header(phase)
            for rule in CONTRACT['object_rules']:
                with self.subTest(target=rule['target']):
                    for value in rule['parent_prerequisites']:
                        resolved=(build/value).resolve()
                        self.assertTrue(resolved.is_relative_to(phase.resolve()))
                        self.assertEqual(resolved,build/'config.h');self.assertTrue(resolved.is_file())

    def test_generated_header_alias_is_relative_same_bytes_and_hash_bound(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);phase,build=self.layout(root);before=(build/'config.h').read_bytes()
            record=stage.bind_gettext_config_header(phase)
            self.assertTrue((phase/'config.h').is_symlink())
            self.assertEqual((phase/'config.h').readlink(),Path('intl/config.h'))
            self.assertEqual((phase/'config.h').read_bytes(),before)
            self.assertEqual(record['config_header_sha256'],hashlib.sha256(before).hexdigest())
            self.assertEqual(record['config_header_bytes'],len(before))
            self.assertNotIn(str(root),json.dumps(record));self.assertNotIn(before.decode(),json.dumps(record))

    def test_header_updates_remain_one_file_not_a_stale_copy(self):
        with tempfile.TemporaryDirectory() as td:
            phase,build=self.layout(Path(td));stage.bind_gettext_config_header(phase)
            (build/'config.h').write_bytes(b'/* INERT UPDATED HEADER */\n')
            self.assertEqual((phase/'config.h').read_bytes(),(build/'config.h').read_bytes())

    def test_missing_empty_oversized_or_symlink_header_fails_before_alias(self):
        for kind in ('missing','empty','oversized','symlink'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as td:
                root=Path(td);phase,build=self.layout(root);source=build/'config.h';source.unlink()
                if kind=='empty':source.write_bytes(b'')
                if kind=='oversized':source.write_bytes(b'x'*(1024**2+1))
                if kind=='symlink':
                    outside=root/'outside.h';outside.write_bytes(b'INERT');source.symlink_to(outside)
                with self.assertRaises(stage.LaneError):stage.bind_gettext_config_header(phase)
                self.assertFalse((phase/'config.h').exists());self.assertFalse((phase/'config.h').is_symlink())

    def test_existing_file_directory_or_dangling_alias_is_never_overwritten(self):
        for kind in ('file','directory','symlink'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as td:
                phase,build=self.layout(Path(td));alias=phase/'config.h'
                if kind=='file':alias.write_bytes(b'INERT EXISTING')
                elif kind=='directory':alias.mkdir()
                else:alias.symlink_to('missing')
                with self.assertRaises(stage.LaneError):stage.bind_gettext_config_header(phase)
                if kind=='file':self.assertEqual(alias.read_bytes(),b'INERT EXISTING')
                elif kind=='directory':self.assertTrue(alias.is_dir())
                else:self.assertEqual(alias.readlink(),Path('missing'))

    def test_phase_or_build_symlink_is_rejected(self):
        for kind in ('phase','build'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as td:
                root=Path(td);phase,build=self.layout(root)
                if kind=='phase':alias=root/'alias';alias.symlink_to(phase);phase=alias
                else:
                    moved=phase/'moved';build.rename(moved);build.symlink_to('moved')
                with self.assertRaises(stage.LaneError):stage.bind_gettext_config_header(phase)

    def run_lane(self,root):
        work=root/'work';work.mkdir();lane=stage.Lane(root,HERE,work,(None,bounds,None))
        phase=lane.directory('gettext-build');(phase/'intl').mkdir()
        return lane,phase

    def test_child_cwd_retains_original_sandbox_root_home_tmp_and_limits(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);lane,phase=self.run_lane(root)
            record={'status':'passed','stdout_bytes':0,'stderr_bytes':0}
            with patch.object(bounds,'run',return_value=(record,b'',b'')) as run,patch('sys.stdout',io.StringIO()):
                lane.run('gettext-headers',['/usr/bin/make','libintl.h','libgnuintl.h'],directory=phase,subdirectory='intl',timeout=20)
            argv=run.call_args.args[0];options=run.call_args.kwargs
            self.assertIn('PHASE_DIR='+str(phase),argv);self.assertNotIn('PHASE_DIR='+str(phase/'intl'),argv)
            self.assertEqual(options['cwd'],phase/'intl')
            self.assertEqual(options['env']['HOME'],str(phase/'home'));self.assertEqual(options['env']['TMPDIR'],str(phase/'tmp'))
            self.assertEqual(options['output_remaining'],8*1024**2);self.assertEqual(options['expected_codes'],(0,))
            self.assertEqual(argv[-3:],['/usr/bin/make','libintl.h','libgnuintl.h'])

    def test_non_gettext_default_cwd_is_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            lane,phase=self.run_lane(Path(td));record={'status':'passed','stdout_bytes':0,'stderr_bytes':0}
            with patch.object(bounds,'run',return_value=(record,b'',b'')) as run,patch('sys.stdout',io.StringIO()):
                lane.run('unrelated',['mock-not-executed'],directory=phase)
            self.assertEqual(run.call_args.kwargs['cwd'],phase)

    def test_child_cwd_cannot_expand_to_other_phase_name_or_path(self):
        cases=[('gettext-headers','../intl'),('gettext-headers','/tmp'),('gettext-headers','intl/..'),('pcre2-build','intl'),('unreviewed','intl')]
        for name,subdir in cases:
            with self.subTest(name=name,subdir=subdir),tempfile.TemporaryDirectory() as td:
                lane,phase=self.run_lane(Path(td))
                with patch.object(bounds,'run') as run:
                    with self.assertRaises(stage.LaneError):lane.run(name,['mock-not-executed'],directory=phase,subdirectory=subdir)
                run.assert_not_called()
        with tempfile.TemporaryDirectory() as td:
            lane,phase=self.run_lane(Path(td));other=lane.directory('other');(other/'intl').mkdir()
            with patch.object(bounds,'run') as run:
                with self.assertRaises(stage.LaneError):lane.run('gettext-headers',['mock-not-executed'],directory=other,subdirectory='intl')
            run.assert_not_called()

    def test_missing_or_symlink_child_cwd_never_spawns(self):
        for kind in ('missing','symlink'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as td:
                root=Path(td);lane,phase=self.run_lane(root);(phase/'intl').rmdir()
                if kind=='symlink':(phase/'intl').symlink_to(root)
                with patch.object(bounds,'run') as run:
                    with self.assertRaises(stage.LaneError):lane.run('gettext-headers',['mock-not-executed'],directory=phase,subdirectory='intl')
                run.assert_not_called()

    def test_nested_private_config_log_is_hash_only_and_failure_still_raises(self):
        with tempfile.TemporaryDirectory() as td:
            lane,phase=self.run_lane(Path(td));payload=b'INERT_CONFIG_LOG_DO_NOT_PUBLISH'
            (phase/'intl/config.log').write_bytes(payload)
            record={'status':'failed','failure_class':'child_exit','exit_code':2,'stdout_bytes':0,'stderr_bytes':0}
            with patch.object(bounds,'run',return_value=(record,b'',b'')),patch('sys.stdout',io.StringIO()) as output:
                with self.assertRaises(stage.PhaseError) as error:lane.run('gettext-libintl-build',['mock-not-executed'],directory=phase,subdirectory='intl')
            self.assertEqual(error.exception.record['private_diagnostics'][0]['sha256'],hashlib.sha256(payload).hexdigest())
            self.assertNotIn(payload.decode(),output.getvalue())

    def test_actual_gettext_section_preserves_four_commands_and_new_topology(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);phase=root/'gettext-build';provider=root/'provider';trees={'gettext':root/'immutable/gettext-1.0'};calls=[];frozen=[];inspected=[]
            def directory(name):self.assertEqual(name,'gettext-build');phase.mkdir();return phase
            def run(name,command,**kwargs):
                calls.append((name,command,kwargs));self.assertEqual(kwargs['directory'],phase)
                cwd=phase/kwargs.get('subdirectory','')
                if name=='gettext-configure':(cwd/'config.h').write_bytes(b'INERT GENERATED CONFIG\n')
                if name=='gettext-headers':(cwd/'libintl.h').write_bytes(b'INERT GENERATED HEADER\n')
                if name=='gettext-libintl-build':
                    self.assertTrue((cwd/'../config.h').is_file(),'pinned parent config prerequisite must exist')
                    self.assertTrue((cwd/'../config.h').resolve().is_relative_to(phase))
                return b'',b'',{}
            fake=types.SimpleNamespace(directory=directory,provider=provider,run=run,
                inspect=lambda *args:inspected.append(args),freeze=lambda *args:frozen.append(args),alias=lambda *args:None,symbols=lambda *args:None)
            with patch('subprocess.Popen') as spawn,patch('sys.stdout',io.StringIO()):gettext_section(stage)(fake,trees,{'libintl_minimum_exports':[]})
            spawn.assert_not_called()
            self.assertEqual([r[0] for r in calls],['gettext-configure','gettext-headers','gettext-gnulib-build','gettext-libintl-build'])
            self.assertEqual([r[2]['timeout'] for r in calls],[110,20,140,90])
            self.assertTrue(all(r[2]['subdirectory']=='intl' for r in calls))
            self.assertEqual(calls[0][1][1],trees['gettext']/'gettext-runtime/intl/configure')
            self.assertEqual([r[1] for r in calls[1:]],[['/usr/bin/make','libintl.h','libgnuintl.h'],['/usr/bin/make','-C','gnulib-lib','-j2','all'],['/usr/bin/make','-j2','libintl.la']])
            self.assertEqual(inspected,[('libintl',phase/'intl/.libs/libintl.8.dylib')])
            self.assertEqual(frozen[0][0],phase/'intl/.libs/libintl.8.dylib');self.assertEqual(frozen[1][0],phase/'intl/libintl.h')

if __name__=='__main__':unittest.main()

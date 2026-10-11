"""First-party mocks only: preserve xcrun invocation spelling, hash resolved bytes."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
sys.dont_write_bytecode=True
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('pdf_dispatch_stage',HERE/'stage.py')
stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)
TOOLS=('clang','ar','ranlib','nm','ld','strip')
ENV_NAMES=('CC','AR','RANLIB','NM','LD','STRIP')

class StopBeforeCompiler(Exception):pass

class ToolDispatchTests(unittest.TestCase):
    def exercise(self,prefix='/Applications/FirstPartyFixture/usr/bin/',override=None,missing=None):
        """Run real orchestration up to the first SDK compile; all commands are mocked."""
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);work=root/'work';work.mkdir()
            lane=stage.Lane(root,HERE,work,(None,None,None))
            paths={tool:prefix+tool for tool in TOOLS};paths.update(override or {})
            targets={};target_hashes={}
            for tool in TOOLS:
                name={'ranlib':'libtool','clang':'clang-fixture'}.get(tool,tool)
                target=root/name;target.write_bytes(('INERT_FIRST_PARTY_FILE_'+name).encode())
                target_hashes[tool]=hashlib.sha256(target.read_bytes()).hexdigest()
                if tool=='ranlib':
                    alias=root/'ranlib';alias.symlink_to('libtool');targets[paths[tool]]=alias
                    self.assertTrue(alias.is_symlink());self.assertEqual(alias.resolve(),target)
                else:targets[paths[tool]]=target
            # This is data-only. Neither these files nor any source/native tool is executed.
            sdk='/Applications/FirstPartyFixture/SDKs/MacOSX.sdk'
            calls=[];resolutions=[]
            original_resolve=Path.resolve;original_file=Path.is_file;original_dir=Path.is_dir
            def resolve(path,*args,**kwargs):
                if str(path) in targets:
                    resolutions.append(str(path));return original_resolve(targets[str(path)])
                return original_resolve(path,*args,**kwargs)
            def is_file(path):
                if str(path) in targets:return str(path)!=missing
                return original_file(path)
            def run(name,command,**kwargs):
                calls.append((name,list(map(str,command)),kwargs,dict(lane.env)))
                if name.startswith('tool-path-'):return (paths[name[10:]]+'\n').encode(),b'',{}
                if name=='sdk-path':return (sdk+'\n').encode(),b'',{}
                if name=='sdk-version':return b'26.0\n',b'',{}
                if name=='sdk-probe-compile':raise StopBeforeCompiler()
                return b'',b'',{}
            output=io.StringIO()
            with patch.object(lane,'canaries'),patch.object(lane,'run',side_effect=run), \
                 patch.object(Path,'resolve',resolve),patch.object(Path,'is_file',is_file), \
                 patch.object(Path,'is_dir',lambda p:str(p)==sdk or original_dir(p)), \
                 patch('subprocess.Popen') as spawn,patch('sys.stdout',output):
                try:lane.execute({})
                except (StopBeforeCompiler,stage.LaneError) as error:failure=error
                else:self.fail('mock orchestration unexpectedly passed the compiler boundary')
                spawn.assert_not_called()
            records=[json.loads(line) for line in output.getvalue().splitlines()]
            return lane,paths,target_hashes,calls,resolutions,records,failure

    def test_alias_spelling_survives_selection_and_environment_export(self):
        lane,paths,hashes,calls,resolutions,records,failure=self.exercise()
        self.assertIsInstance(failure,StopBeforeCompiler)
        self.assertEqual(lane.tools,paths)
        for tool,key in zip(TOOLS,ENV_NAMES):self.assertEqual(lane.env[key],paths[tool])
        self.assertTrue(lane.env['RANLIB'].endswith('/ranlib'))
        self.assertFalse(lane.env['RANLIB'].endswith('/libtool'))
        self.assertEqual(calls[-1][1][0],paths['clang'])

    def test_resolved_target_bytes_are_still_hashed_for_all_six_roles(self):
        lane,paths,hashes,calls,resolutions,records,failure=self.exercise()
        self.assertIsInstance(failure,StopBeforeCompiler)
        self.assertEqual(resolutions,list(paths.values()))
        self.assertEqual(records,[{'phase':'tool-identity-'+tool,'status':'passed','binary_sha256':hashes[tool]} for tool in TOOLS])
        self.assertNotIn('FirstPartyFixture',json.dumps(records))

    def test_all_existing_allowed_lookup_roots_preserve_aliases(self):
        for prefix in ('/Applications/FirstPartyFixture/usr/bin/','/Library/Developer/FirstPartyFixture/usr/bin/','/usr/bin/'):
            with self.subTest(prefix=prefix):
                lane,paths,*_,failure=self.exercise(prefix)
                self.assertIsInstance(failure,StopBeforeCompiler);self.assertEqual(lane.tools,paths)

    def test_unapproved_lookup_paths_still_fail_before_identity_or_compile(self):
        for value in ('/tmp/ranlib','/opt/homebrew/bin/ranlib','ranlib','./ranlib','/ApplicationsElsewhere/bin/ranlib'):
            with self.subTest(value=value):
                lane,paths,hashes,calls,resolutions,records,failure=self.exercise(override={'ranlib':value})
                self.assertIsInstance(failure,stage.LaneError)
                self.assertNotIn(value,resolutions);self.assertNotIn('ranlib',lane.tools)
                self.assertEqual(calls[-1][0],'tool-path-ranlib')

    def test_whitespace_lookup_paths_still_fail_closed(self):
        for char in (' ','\t','\n','\r'):
            with self.subTest(char=repr(char)):
                value='/Applications/FirstParty'+char+'Fixture/ranlib'
                *_,failure=self.exercise(override={'ranlib':value})
                self.assertIsInstance(failure,stage.LaneError)

    def test_missing_lookup_tool_still_fails_closed(self):
        value='/Applications/FirstPartyFixture/usr/bin/ranlib'
        lane,paths,hashes,calls,resolutions,records,failure=self.exercise(missing=value)
        self.assertIsInstance(failure,stage.LaneError)
        self.assertNotIn(value,resolutions);self.assertNotIn('ranlib',lane.tools)

    def test_lookup_commands_and_precompile_limits_are_unchanged(self):
        lane,paths,hashes,calls,resolutions,records,failure=self.exercise()
        self.assertIsInstance(failure,StopBeforeCompiler)
        for index,tool in enumerate(TOOLS):
            self.assertEqual(calls[index][0],'tool-path-'+tool)
            self.assertEqual(calls[index][1],['/usr/bin/xcrun','--sdk','macosx','--find',tool])
            self.assertEqual(calls[index][2]['timeout'],10)
        self.assertEqual(calls[-1][0],'sdk-probe-compile');self.assertEqual(calls[-1][2]['timeout'],30)
        self.assertEqual(lane.env['PATH'],'/usr/bin:/bin:/usr/sbin:/sbin')
        self.assertNotIn('LIBTOOL',lane.env);self.assertNotIn('LIBTOOL_FORCE_RANLIB',lane.env)

if __name__=='__main__':unittest.main()

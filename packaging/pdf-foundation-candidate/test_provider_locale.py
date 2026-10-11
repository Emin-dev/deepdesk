"""First-party environment mocks, source-policy model and stdlib catalog parser."""
import ast
import copy
import gettext
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
sys.dont_write_bytecode=True
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
def load(name):
    spec=importlib.util.spec_from_file_location('locale_'+name,HERE/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
stage=load('stage');bounds=load('bounds')
CONTRACT=json.loads((HERE/'provider-locale-contract.json').read_text())

def macos_global_locale_selection(environ):
    """Inert model of the three pinned branches; not native libintl execution."""
    locale=next((environ[k] for k in ('LC_ALL','LC_MESSAGES','LANG') if environ.get(k)),None)
    if locale is None:return None  # OS defaults are deliberately outside this model.
    if locale=='C' or locale.startswith('C.'):return locale
    return environ.get('LANGUAGE') or locale

def provider_call(module):
    tree=ast.parse(Path(module.__file__).read_text())
    calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
           and n.func.attr=='run' and n.args and isinstance(n.args[0],ast.Constant) and n.args[0].value=='provider-probe-run']
    assert len(calls)==1
    return compile(ast.fix_missing_locations(ast.Expression(copy.deepcopy(calls[0]))),'<first-party-provider-call>','eval')

class ProviderLocaleTests(unittest.TestCase):
    def capture_provider(self,root):
        work=root/'work';work.mkdir();lane=stage.Lane(root,HERE,work,(None,bounds,None));phase=lane.directory('provider-probe');fixture=phase/'provider-probe'
        initial=dict(lane.env);record={'status':'passed','stdout_bytes':0,'stderr_bytes':0}
        with patch.object(bounds,'run',return_value=(record,b'',b'')) as run,patch('subprocess.Popen') as spawn,patch('sys.stdout',io.StringIO()):
            eval(provider_call(stage),dict(stage.__dict__),{'self':lane,'fixture':fixture,'p':phase})
        spawn.assert_not_called()
        return lane,phase,fixture,initial,run.call_args

    def test_provider_only_effective_locale_matches_explicit_native_locale(self):
        with tempfile.TemporaryDirectory() as td:
            lane,phase,fixture,initial,call=self.capture_provider(Path(td));env=call.kwargs['env']
            self.assertEqual(env['LC_ALL'],'en_US.UTF-8');self.assertEqual(env['LANG'],'C')
            self.assertEqual(lane.env,initial);self.assertEqual(lane.env['LC_ALL'],'C')
            self.assertNotIn('LANGUAGE',env)  # The unchanged native fixture sets it to fr.
            self.assertEqual(call.args[0][-2:],[str(fixture),str(lane.immutable/'catalog')])
            self.assertEqual(call.kwargs['cwd'],phase)

    def test_old_c_environment_suppresses_language_new_effective_env_selects_fr(self):
        with tempfile.TemporaryDirectory() as td:
            lane,phase,fixture,initial,call=self.capture_provider(Path(td))
            old={**initial,'LANGUAGE':'fr'};new={**call.kwargs['env'],'LANGUAGE':'fr'}
            self.assertEqual(macos_global_locale_selection(old),'C')
            self.assertEqual(macos_global_locale_selection(new),'fr')

    def test_build_and_other_probe_steps_retain_c_locale(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);lane,phase,fixture,initial,call=self.capture_provider(root)
            record={'status':'passed','stdout_bytes':0,'stderr_bytes':0}
            for name in ('pkgconf-configure','pkgconf-build','pcre2-build','gettext-configure','gettext-libintl-build','provider-probe-compile','sdk-probe-run'):
                with self.subTest(name=name),patch.object(bounds,'run',return_value=(record,b'',b'')) as run,patch('sys.stdout',io.StringIO()):
                    lane.run(name,['inert-not-executed'],directory=phase)
                self.assertEqual(run.call_args.kwargs['env']['LC_ALL'],'C');self.assertEqual(run.call_args.kwargs['env']['LANG'],'C')
            self.assertEqual(lane.env,initial)

    def test_existing_run_budget_profile_and_failure_expectation_are_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            lane,phase,fixture,initial,call=self.capture_provider(Path(td));argv=call.args[0];options=call.kwargs
            self.assertIn('PHASE_DIR='+str(phase),argv);self.assertIn(str(HERE/'offline.sb'),argv)
            self.assertEqual(options['output_remaining'],8*1024**2);self.assertEqual(options['expected_codes'],(0,))
            self.assertEqual(options['env']['HOME'],str(phase/'home'));self.assertEqual(options['env']['TMPDIR'],str(phase/'tmp'))
            call_ast=ast.parse(Path(stage.__file__).read_text())
            node=next(n for n in ast.walk(call_ast) if isinstance(n,ast.Call) and n.args and isinstance(n.args[0],ast.Constant) and n.args[0].value=='provider-probe-run')
            self.assertEqual(next(k.value.value for k in node.keywords if k.arg=='timeout'),15)

    def test_c_and_c_encoding_overrides_have_precedence_over_language(self):
        for value in ('C','C.UTF-8','C.ISO-8859-1'):
            with self.subTest(value=value):
                self.assertEqual(macos_global_locale_selection({'LC_ALL':value,'LC_MESSAGES':'fr','LANG':'fr','LANGUAGE':'fr'}),value)
        self.assertEqual(macos_global_locale_selection({'LC_ALL':'en_US.UTF-8','LC_MESSAGES':'C','LANG':'C','LANGUAGE':'fr'}),'fr')
        self.assertEqual(macos_global_locale_selection({'LC_ALL':'','LC_MESSAGES':'C','LANG':'en_US.UTF-8','LANGUAGE':'fr'}),'C')
        self.assertEqual(macos_global_locale_selection({'LC_ALL':'','LANG':'en_US.UTF-8','LANGUAGE':'fr'}),'fr')
        self.assertIsNone(macos_global_locale_selection({}))

    def test_mo_catalog_independent_stdlib_singular_plural_utf8_and_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'fr/LC_MESSAGES/deepdesk-proof.mo';stage.write_mo(path)
            catalog=gettext.GNUTranslations(io.BytesIO(path.read_bytes()))
            self.assertEqual(catalog.gettext('coffee'),'café')
            self.assertEqual(catalog.ngettext('one apple','many apples',1),'une pomme')
            self.assertEqual(catalog.ngettext('one apple','many apples',2),'des pommes')
            self.assertEqual(catalog.gettext('missing-key'),'missing-key')
            self.assertEqual(catalog.charset(),'UTF-8');self.assertEqual(catalog.info()['language'],'fr')

    def test_mo_byte_layout_and_identity_are_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'catalog.mo';stage.write_mo(path);data=path.read_bytes()
            self.assertEqual(len(data),230);self.assertEqual(hashlib.sha256(data).hexdigest(),CONTRACT['catalog_sha256'])
            magic,revision,count,originals,translated,hash_size,hash_offset=struct.unpack_from('<7I',data)
            self.assertEqual((magic,revision,count,originals,translated,hash_size,hash_offset),(0x950412de,0,3,28,52,0,0))
            for table in (originals,translated):
                for index in range(count):
                    length,offset=struct.unpack_from('<2I',data,table+8*index)
                    self.assertLess(offset+length,len(data));self.assertEqual(data[offset+length],0);data[offset:offset+length].decode('utf-8')

    def test_native_fixture_assertions_and_order_are_byte_identical(self):
        data=(HERE/'provider_probe.c').read_bytes();self.assertEqual(hashlib.sha256(data).hexdigest(),CONTRACT['provider_probe_sha256'])
        source=data.decode();checks=['int r=regex_test();if(r)return r;','if(!setlocale(LC_ALL,"en_US.UTF-8"))return 32;',
          'if(setenv("LANGUAGE","fr",1))return 33;','if(strcmp(gettext("coffee"),"caf\\xc3\\xa9"))return 36;',
          'if(strcmp(ngettext("one apple","many apples",1),"une pomme"))return 37;',
          'if(strcmp(ngettext("one apple","many apples",2),"des pommes"))return 38;']
        positions=[source.index(item) for item in checks];self.assertEqual(positions,sorted(positions))
        self.assertIn('if(strcmp(dgettext("deepdesk-proof","missing-key"),"missing-key"))return 39;',source)

    def test_source_contract_records_exact_environment_priority_and_early_c_guard(self):
        sources=CONTRACT['source_members']
        environ='\n'.join(r['text'] for r in sources['gnulib-lib/localename-environ.c']['ranges'])
        self.assertLess(environ.index('getenv ("LC_ALL")'),environ.index('getenv (categoryname)'))
        self.assertLess(environ.index('getenv (categoryname)'),environ.index('getenv ("LANG")'))
        guess='\n'.join(r['text'] for r in sources['dcigettext.c']['ranges'])
        self.assertLess(guess.index("if (locale[0] == 'C'"),guess.index('getenv ("LANGUAGE")'))
        posix='\n'.join(r['text'] for r in sources['gnulib-lib/localename-unsafe.c']['ranges'])
        self.assertIn('locname = gl_locale_name_environ (category, categoryname);',posix)
        self.assertIn('macOS',posix);self.assertFalse(CONTRACT['native_source_executed_locally'])

if __name__=='__main__':unittest.main()

"""Inert source/control regressions. No source configure/compiler/native execution."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location('correction_test_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


correction, native, stage = load('iconv_make_stage'), load('glib_native_checks'), load('stage')


def command(kind, value):
    data = value.encode() + b'\0'
    size = (24 + len(data) + 7) // 8 * 8
    return struct.pack('<6I', kind, size, 24, 0, 0, 0) + data + bytes(size - 24 - len(data))


def binary(identity, loads):
    cmds = [struct.pack('<6I', 0x32, 24, 1, 26 << 16, 26 << 16, 0), command(0xd, identity)]
    cmds += [command(0xc, load) for load in loads]
    return struct.pack('<8I', 0xfeedfacf, 0x100000c, 0, 6, len(cmds), sum(map(len, cmds)), 0, 0) + b''.join(cmds)


class CorrectionTests(unittest.TestCase):
    def test_prior_eight_input_pins_unchanged_and_two_official_additions(self):
        lock = json.loads((HERE / 'input-lock.json').read_text())
        inputs = {item['id']: item for item in lock['inputs']}
        self.assertEqual(len(inputs), 10)
        self.assertEqual(inputs['make']['sha256'], 'dd16fb1d67bfab79a72f5e8390735c49e3e8e70b4945a15ab1f81ddb78658fb3')
        self.assertEqual(inputs['libiconv']['sha256'], '88dd96a8c0464eca144fc791ae60cd31cd8ee78321e67397e25fc095c4a19aa6')
        for key in ('make', 'libiconv'):
            self.assertTrue(inputs[key]['url'].startswith('https://ftp.gnu.org/gnu/'))
            self.assertEqual(inputs[key]['redirect_hosts'], ['ftp.gnu.org'])
        self.assertEqual({k: inputs[k]['sha256'] for k in stage.foundation.INPUT_HASHES}, stage.foundation.INPUT_HASHES)

    def test_new_execution_and_staging_gates_are_closed(self):
        receipt = json.loads((HERE / 'review-receipt.json').read_text())
        for key in ('source_make_execution_approved', 'source_libiconv_provider_approved',
                    'phase_libcharset_staging_approved', 'corrected_libintl_provider_approved'):
            self.assertIs(receipt[key], False)
        self.assertIs(stage.FALSE_GATES['gnu_make_guile_embedding'], False)
        self.assertIs(stage.FALSE_GATES['libiconv_cli_install'], False)

    def test_make_catalog_contract_covers_exact_release_linguas_and_members(self):
        contract = json.loads((HERE / 'make-catalog-contract.json').read_text())
        source = (HERE / 'source-review/make/po/LINGUAS').read_text()
        linguas = ' '.join(line.split('#', 1)[0] for line in source.splitlines()).split()
        self.assertEqual(set(linguas), {x['language'] for x in contract['languages']})
        self.assertEqual(len(linguas), 30)
        members = {x['path']: x for x in json.loads((HERE / 'members/make.json').read_text())['members']}
        for catalog in contract['languages']:
            self.assertEqual(catalog['sha256'], members[catalog['source_member']]['sha256'])
            self.assertGreater(catalog['catalog_entries'], 1)

    def test_documented_make_bootstrap_retains_nls_and_avoids_po_build(self):
        readme = (HERE / 'source-review/make/README').read_text()
        source = (HERE / 'source-review/make/build.sh').read_text()
        cfg = (HERE / 'source-review/make/build.cfg.in').read_text()
        code = (HERE / 'iconv_make_stage.py').read_text()
        self.assertIn("type 'sh build.sh'", readme)
        self.assertIn('localedir=$prefix/share/locale', source)
        self.assertIn('@LIBINTL@', cfg)
        self.assertIn("'--enable-nls', '--without-guile'", code)
        self.assertNotIn('--disable-nls', code)
        self.assertNotIn("'-C', 'po'", code)
        self.assertIn("assignments(safe.read(phase / 'build.cfg'", code)

    def test_genuine_libiconv_targets_exclude_src_and_generic_install(self):
        source = (HERE / 'source-review/libiconv/Makefile.in').read_text()
        cli = (HERE / 'source-review/libiconv/src/Makefile.in').read_text()
        code = (HERE / 'iconv_make_stage.py').read_text()
        self.assertIn('lib/localcharset.h :', source)
        self.assertIn('cd libcharset && $(MAKE) all && $(MAKE) install-lib', source)
        self.assertIn('chmod 777', cli)
        self.assertIn("[make, '-j2', 'lib/localcharset.h']", code)
        self.assertIn("[make, '-C', 'lib', '-j2', 'libiconv.la']", code)
        tree = ast.parse(code)
        values = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        self.assertNotIn('install', values)
        self.assertNotIn('install-lib', values)
        self.assertNotIn('chmod', values)

    def metadata(self, provider):
        main = b"# ### BEGIN LIBTOOL CONFIG\npostinstall_cmds=''\nfinish_cmds=''\nfinish_eval=''\nhardcode_automatic=yes\nbuild_old_libs=no\nbuild_libtool_libs=yes\n# ### END LIBTOOL CONFIG\n"
        archive = ("installed=no\nold_library=''\ndependency_libs=''\ndlopen=''\ndlpreopen=''\nlibdir='" + str(provider / 'lib') + "'\n").encode()
        return main, archive

    def test_main_libtool_config_ignores_exact_inactive_tag_blocks(self):
        provider = Path('/work/immutable/providers')
        main, archive = self.metadata(provider)
        source = (HERE / 'source-review/libiconv/libcharset/build-aux/ltmain.sh').read_bytes()
        tail = source[source.index(b'# ### BEGIN LIBTOOL TAG CONFIG: disable-shared'):]
        report = correction.charset_staging_contract(main + tail, archive, provider)
        self.assertTrue(report['shared_only'])
        self.assertIn(b'build_old_libs=yes', tail)

    def test_libtool_main_boundary_must_be_unique_and_ordered(self):
        provider = Path('/work/immutable/providers')
        main, archive = self.metadata(provider)
        for data in (main + main, main.replace(b'BEGIN LIBTOOL CONFIG', b'MISSING CONFIG'),
                     b'# ### END LIBTOOL CONFIG\n# ### BEGIN LIBTOOL CONFIG\n'):
            with self.assertRaises(ValueError): correction.charset_staging_contract(data, archive, provider)

    def test_libtool_nonempty_hook_static_or_relink_is_rejected(self):
        provider = Path('/work/immutable/providers')
        main, archive = self.metadata(provider)
        for key in ('postinstall_cmds', 'finish_cmds', 'finish_eval'):
            with self.assertRaises(ValueError):
                correction.charset_staging_contract(main.replace((key + "=''").encode(), (key + "='INERT_FORBIDDEN_HOOK'").encode()), archive, provider)
        with self.assertRaises(ValueError): correction.charset_staging_contract(main.replace(b'build_old_libs=no', b'build_old_libs=yes'), archive, provider)
        with self.assertRaises(ValueError): correction.charset_staging_contract(main, archive + b'relink_command="INERT_FORBIDDEN_RELINK"\n', provider)

    def test_libtool_duplicate_main_assignments_and_wrong_destinations_fail(self):
        provider = Path('/work/immutable/providers')
        main, archive = self.metadata(provider)
        with self.assertRaises(ValueError): correction.charset_staging_contract(main.replace(b'finish_eval=\'\'', b'finish_eval=\'\'\nfinish_eval=\'\''), archive, provider)
        with self.assertRaises(ValueError): correction.charset_staging_contract(main, archive.replace(str(provider).encode(), b'/outside'), provider)

    def test_exact_upstream_semantic_source_variants_preserved(self):
        contract = json.loads((HERE / 'iconv-semantic-contract.json').read_text())
        source = (HERE / 'source-review/gettext/libtextstyle/configure').read_text()
        start = source.index('#include <iconv.h>\n#include <string.h>', source.index('checking for working iconv'))
        end = source.index('\n_ACEOF\nif ac_fn_c_try_run', start)
        template = source[start:end] + '\n'
        self.assertEqual(hashlib.sha256(template.encode()).hexdigest(), contract['template_sha256'])
        for variant in contract['variants']:
            data = (HERE / variant['path']).read_bytes()
            self.assertEqual(data, template.replace('$ac_iconv_const', variant['substitution']).encode())
            self.assertEqual(hashlib.sha256(data).hexdigest(), variant['sha256'])
        self.assertIsNone(contract['sdk_v2_observed_converted_bytes'])
        self.assertIsNone(contract['sdk_v2_observed_function_origins'])

    def test_semantic_driver_checks_real_function_origins_and_version(self):
        source = (HERE / 'iconv_semantic_driver.c').read_text()
        for value in ('upstream_iconv_semantic_main()', '_LIBICONV_VERSION != 0x0113',
                      '_libiconv_version != 0x0113', 'dladdr', 'iconv_open', 'iconv_close', 'dlsym', '_dyld_image_count'):
            self.assertIn(value, source)

    def test_corrected_intl_has_non_utf8_and_original_behavior_checks(self):
        source = (HERE / 'intl_iconv_probe.c').read_text()
        for value in ('ISO-8859-1', 'caf\\xe9', 'UTF-8', 'caf\\xc3\\xa9', 'ngettext', 'missing-key', 'dladdr'):
            self.assertIn(value, source)
        code = (HERE / 'iconv_make_stage.py').read_text()
        self.assertIn("intl = provider / 'intl-with-iconv'", code)
        self.assertIn('reject_bootstrap_intl=True', code)
        self.assertNotIn("provider / 'lib/libintl.8.dylib', False", code)

    def fixture_paths(self, root):
        provider = root / 'immutable/providers'; provider.mkdir(parents=True)
        executable = root / 'phases/probe'; executable.parent.mkdir(); executable.write_bytes(b'inert')
        library = provider / 'lib/libiconv.2.dylib'; library.parent.mkdir(); library.write_bytes(b'inert')
        return provider, executable, library

    def test_exact_function_and_loaded_image_origin(self):
        with tempfile.TemporaryDirectory() as td:
            provider, executable, library = self.fixture_paths(Path(td).resolve())
            data = f'passed\norigin=iconv|{library}\nimage={executable}\nimage={library}\n'.encode()
            native.origin_fixture_output(data, ['passed'], executable, provider, {'iconv': library}, ['libiconv.2.dylib'])
            with self.assertRaises(native._base.NativeError):
                native.origin_fixture_output(data.replace(str(library).encode(), b'/usr/lib/libiconv.2.dylib', 1), ['passed'], executable, provider, {'iconv': library}, ['libiconv.2.dylib'])

    def test_missing_duplicate_or_unexpected_origins_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            provider, executable, library = self.fixture_paths(Path(td).resolve())
            base = f'passed\nimage={executable}\nimage={library}\n'
            for lines in ('', f'origin=iconv|{library}\norigin=iconv|{library}\n', f'origin=unexpected|{library}\n'):
                with self.assertRaises(native._base.NativeError):
                    native.origin_fixture_output((base + lines).encode(), ['passed'], executable, provider, {'iconv': library}, ['libiconv.2.dylib'])

    def test_old_intl_loaded_alongside_corrected_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            provider, executable, _ = self.fixture_paths(Path(td).resolve())
            old = provider / 'lib/libintl.8.dylib'; old.write_bytes(b'inert')
            data = f'passed\nimage={executable}\nimage={old}\n'.encode()
            with self.assertRaises(native._base.NativeError):
                native.origin_fixture_output(data, ['passed'], executable, provider, {}, ['libintl.8.dylib'], reject_bootstrap_intl=True)

    def test_recursive_closure_uses_exact_corrected_identity(self):
        with tempfile.TemporaryDirectory() as td:
            provider = Path(td).resolve() / 'immutable/providers'
            iconv = provider / 'lib/libiconv.2.dylib'; iconv.parent.mkdir(parents=True)
            iconv.write_bytes(binary(str(iconv), ['/usr/lib/libSystem.B.dylib']))
            intl = provider / 'intl-with-iconv/lib/libintl.8.dylib'; intl.parent.mkdir(parents=True)
            intl.write_bytes(binary(str(intl), [str(iconv), '/usr/lib/libSystem.B.dylib']))
            closure = native.recursive_provider_closure([intl], provider)
            self.assertEqual(len(closure['provider_nodes']), 2)
            self.assertTrue(closure['bootstrap_intl_rejected'])

    def test_recursive_closure_rejects_bootstrap_intl_edge(self):
        with tempfile.TemporaryDirectory() as td:
            provider = Path(td).resolve() / 'immutable/providers'
            old = provider / 'lib/libintl.8.dylib'; old.parent.mkdir(parents=True)
            old.write_bytes(binary(str(old), ['/usr/lib/libSystem.B.dylib']))
            textstyle = provider / 'lib/libtextstyle.0.dylib'
            textstyle.write_bytes(binary(str(textstyle), [str(old)]))
            with self.assertRaises(native._base.NativeError): native.recursive_provider_closure([textstyle], provider)

    def test_no_cache_forcing_or_nls_disabling_or_source_patch(self):
        code = (HERE / 'iconv_make_stage.py').read_text() + (HERE / 'stage.py').read_text()
        for forbidden in ('am_cv_func_iconv_works=yes', 'ac_cv_func_iconv=yes', '--disable-nls', 'install_name_tool', 'chmod 777'):
            self.assertNotIn(forbidden, code)
        self.assertIn("'--with-libiconv-prefix=' + str(self.provider)", code)


if __name__ == '__main__':
    unittest.main()

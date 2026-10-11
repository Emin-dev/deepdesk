"""First-party tests only. Fabricated archives/Mach-O bytes are never executed."""
import ast
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location('test_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stage = load('stage')
archive = load('glib_archive_tools')
native = load('glib_native_checks')
bounds = load('glib_bounds')
diagnostics = load('glib_build_diagnostics')
safe_reads = load('safe_reads')


def command(code, text):
    minimum = 12 if code == 0x8000001c else 24
    data = text.encode() + b'\0'
    size = (minimum + len(data) + 7) // 8 * 8
    return struct.pack('<III', code, size, minimum) + bytes(minimum - 12) + data + bytes(size - minimum - len(data))


def macho_bytes(name, provider, *, rpaths=(), loads=(), minimum=26 << 16, cpu=0x100000c, kind=6):
    chunks = [struct.pack('<6I', 0x32, 24, 1, minimum, minimum, 0)]
    if kind == 6:
        identity = '@rpath/' + name if name in native.GLIB_NAMES else str(provider / 'lib' / name)
        chunks.append(command(0xd, identity))
    chunks += [command(0xc, x) for x in loads]
    chunks += [command(0x8000001c, x) for x in rpaths]
    return struct.pack('<8I', 0xfeedfacf, cpu, 0, kind, len(chunks), sum(map(len, chunks)), 0, 0) + b''.join(chunks)


class CandidateTests(unittest.TestCase):
    def test_exact_ten_input_pins_and_totals(self):
        lock = json.loads((HERE / 'input-lock.json').read_text())
        self.assertEqual(len(lock['inputs']), 10)
        self.assertEqual({x['id']: x['sha256'] for x in lock['inputs']}, stage.INPUT_HASHES)
        self.assertEqual(sum(x['size'] for x in lock['inputs']), 77580242)
        self.assertEqual(sum(x['expanded_bytes'] for x in lock['inputs']), 426518901)
        self.assertFalse(lock['source_changes_allowed'])
        self.assertNotIn('pango', stage.INPUT_HASHES)

    def test_original_foundation_code_and_sandbox_unchanged(self):
        foundation = json.loads((HERE / 'foundation-evidence.json').read_text())['copied_files']
        for name in ('archive_tools.py', 'bounds.py', 'native_checks.py', 'offline.sb', 'meson_entry.py',
                     'canary.py', 'provider_probe.c', 'sdk_probe.c', 'build_diagnostics.py', 'input_diagnostics.py'):
            self.assertEqual(stage.digest(HERE / name), foundation[name])
        self.assertEqual(stage.digest(HERE / 'foundation_stage.py'), foundation['stage.py'])

    def test_receipt_closed_and_hashes_match(self):
        receipt = json.loads((HERE / 'review-receipt.json').read_text())
        stage.validate(HERE.parents[1], receipt, False)
        for flag in ('independent_review_passed', 'execution_approved', 'github_publication_approved',
                     'temporary_linker_adhoc_signing_approved', 'install_name_linker_assignment_approved',
                     'new_libffi_provider_approved', 'runner_free_eligibility_verified'):
            self.assertIs(receipt[flag], False)
        with self.assertRaises(stage.foundation.LaneError):
            stage.validate(HERE.parents[1], receipt, True)

    def test_runtime_scope_and_optional_capabilities_honest(self):
        for flag in ('pango_runtime', 'font_closure', 'pdf_rendering', 'relocation', 'release_ready',
                     'full_glib_install', 'generated_gir_typelibs', 'optional_profiling_instrumentation'):
            self.assertIs(stage.FALSE_GATES[flag], False)
        self.assertIn('-Dnls=enabled', stage.GLIB_OPTIONS)
        self.assertIn('-Dintrospection=disabled', stage.GLIB_OPTIONS)
        self.assertIn('--wrap-mode=nofallback', stage.GLIB_OPTIONS)
        self.assertNotIn('-Dxattr=false', stage.GLIB_OPTIONS)
        self.assertNotIn('-Dglib_checks=false', stage.GLIB_OPTIONS)

    def test_all_production_catalogs_match_archive(self):
        contract = json.loads((HERE / 'catalog-contract.json').read_text())
        members = json.loads((HERE / 'members/glib.json').read_text())['members']
        languages = {Path(x['path']).stem for x in members if x['kind'] == 'file' and
                     x['path'].startswith('glib-2.90.1/po/') and x['path'].endswith('.po') and x['path'].count('/') == 2}
        self.assertEqual(languages, set(contract['languages']))
        self.assertEqual(len(languages), 102)
        self.assertEqual(len(contract['languages']), 102)

    def test_source_review_hashes_are_archive_member_hashes(self):
        lock = json.loads((HERE / 'input-lock.json').read_text())
        manifest = {p['id']: {x['path']: x for x in json.loads((HERE / p['member_manifest']).read_text())['members']} for p in lock['inputs']}
        review = json.loads((HERE / 'source-hook-review.json').read_text())
        for entry in review['files']:
            self.assertEqual(stage.digest(HERE / entry['path']), entry['sha256'])
            self.assertEqual(manifest[entry['input_id']][entry['source_member']]['sha256'], entry['sha256'])
        for generated in review['release_generated_outputs']:
            self.assertGreater(generated['output_mtime'], generated['input_mtime'])

    def test_exact_source_symlink_allowlist(self):
        self.assertEqual(archive.SOURCE_LINKS, {
            'glib-2.90.1/COPYING': 'LICENSES/LGPL-2.1-or-later.txt',
            'glib-2.90.1/gmodule/COPYING': '../LICENSES/LGPL-2.1-or-later.txt'})
        members = json.loads((HERE / 'members/glib.json').read_text())['members']
        self.assertEqual({x['path']: x['target'] for x in members if x['kind'] == 'symlink'}, archive.SOURCE_LINKS)

    def archive_fixture(self, directory, *, link='../LICENSES/LGPL-2.1-or-later.txt', duplicate=False, hardlink=False):
        archive_path = directory / 'input.tar'
        rows = []
        with tarfile.open(archive_path, 'w') as stream:
            for name, payload in [('glib-2.90.1/LICENSES/LGPL-2.1-or-later.txt', b'first-party-license-fixture')]:
                info = tarfile.TarInfo(name); info.mode = 0o644; info.mtime = 1; info.size = len(payload)
                stream.addfile(info, io.BytesIO(payload))
                rows.append({'path': name, 'kind': 'file', 'mode': info.mode, 'mtime': 1, 'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()})
                if duplicate:
                    stream.addfile(info, io.BytesIO(payload))
            info = tarfile.TarInfo('glib-2.90.1/gmodule/COPYING')
            info.type = tarfile.LNKTYPE if hardlink else tarfile.SYMTYPE
            info.mode = 0o777; info.mtime = 1; info.linkname = link
            stream.addfile(info)
            rows.append({'path': info.name, 'kind': 'symlink', 'mode': info.mode, 'mtime': 1, 'size': 0, 'target': link})
        sha = stage.digest(archive_path)
        manifest = directory / 'members.json'
        manifest.write_text(json.dumps({'archive_sha256': sha, 'expanded_bytes': len(b'first-party-license-fixture'), 'members': rows}))
        pin = {'id': 'glib', 'format': 'tar', 'root': 'glib-2.90.1', 'sha256': sha, 'member_manifest_sha256': stage.digest(manifest),
               'member_count': 2, 'expanded_bytes': len(b'first-party-license-fixture'), 'max_member_bytes': 1024}
        return pin, archive_path, manifest

    def test_extracts_only_exact_license_link(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve(); pin, source, manifest = self.archive_fixture(root)
            out = archive.extract(pin, source, root / 'out', manifest)
            self.assertEqual((out / 'gmodule/COPYING').read_bytes(), b'first-party-license-fixture')

    def test_rejects_outside_license_link(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve(); pin, source, manifest = self.archive_fixture(root, link='../../../outside')
            with self.assertRaises(archive.ContractError): archive.extract(pin, source, root / 'out', manifest)

    def test_rejects_archive_hardlink(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve(); pin, source, manifest = self.archive_fixture(root, hardlink=True)
            with self.assertRaises(archive.ContractError): archive.extract(pin, source, root / 'out', manifest)

    def test_rejects_duplicate_archive_member(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve(); pin, source, manifest = self.archive_fixture(root, duplicate=True)
            with self.assertRaises(archive.ContractError): archive.extract(pin, source, root / 'out', manifest)

    def test_rejects_manifest_tampering(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve(); pin, source, manifest = self.archive_fixture(root)
            manifest.write_text('{}')
            with self.assertRaises(archive.ContractError): archive.extract(pin, source, root / 'out', manifest)

    def native_case(self, *, rpaths=(), loads=(), minimum=26 << 16, cpu=0x100000c):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve(); provider = root / 'immutable/providers'
        name = 'libgobject-2.0.0.dylib'; path = root / 'phases/native-test' / name
        path.parent.mkdir(parents=True)
        path.write_bytes(macho_bytes(name, provider, rpaths=rpaths, loads=loads or ['/usr/lib/libSystem.B.dylib'], minimum=minimum, cpu=cpu))
        return path, provider, provider / 'native/gobject' / name

    def test_macho_preserved_relative_layout(self):
        path, provider, final = self.native_case(rpaths=['@loader_path/../glib'], loads=['@rpath/libglib-2.0.0.dylib'])
        record, _ = native.macho(path, provider, promoted_path=final)
        self.assertEqual(record['rpath_count'], 1)

    def test_macho_rejects_mutable_build_rpath(self):
        path, provider, final = self.native_case(rpaths=['/tmp/unreviewed-build/glib'])
        with self.assertRaises(native._base.NativeError): native.macho(path, provider, promoted_path=final)

    def test_macho_rejects_relative_escape(self):
        path, provider, final = self.native_case(rpaths=['@loader_path/../../../../outside'])
        with self.assertRaises(native._base.NativeError): native.macho(path, provider, promoted_path=final)

    def test_macho_rejects_unreviewed_rpath_library(self):
        path, provider, final = self.native_case(loads=['@rpath/libunreviewed.dylib'])
        with self.assertRaises(native._base.NativeError): native.macho(path, provider, promoted_path=final)

    def test_macho_rejects_unreviewed_system_load(self):
        path, provider, final = self.native_case(loads=['/usr/lib/libunreviewed.dylib'])
        with self.assertRaises(native._base.NativeError): native.macho(path, provider, promoted_path=final)

    def test_macho_rejects_wrong_architecture(self):
        path, provider, final = self.native_case(cpu=0x1000007)
        with self.assertRaises(native._base.NativeError): native.macho(path, provider, promoted_path=final)

    def test_macho_rejects_wrong_minimum_os(self):
        path, provider, final = self.native_case(minimum=15 << 16)
        with self.assertRaises(native._base.NativeError): native.macho(path, provider, promoted_path=final)

    def test_new_native_load_set_is_bounded(self):
        self.assertEqual(len(native.GLIB_NAMES), 6)
        self.assertNotIn('/opt/homebrew/lib/libffi.dylib', native.APPLE_LOADS)
        self.assertIn('libffi.8.dylib', native.PROVIDER_NAMES)

    def test_environment_scrub_and_locale_scope(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td).resolve() / 'work'; work.mkdir()
            with mock.patch.dict(os.environ, {'INVALID_TEST_SECRET': 'INERT_DO_NOT_USE', 'DYLD_LIBRARY_PATH': '/forbidden'}):
                lane = stage.Lane(Path(td).resolve(), HERE, work, (archive, bounds, native))
            self.assertNotIn('INVALID_TEST_SECRET', lane.env)
            self.assertNotIn('DYLD_LIBRARY_PATH', lane.env)
            self.assertEqual(lane.env['LC_ALL'], 'C')
            self.assertEqual(lane.env['LANG'], 'C')

    def test_new_run_retains_phase_sandbox_and_budget(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve(); work = root / 'work'; work.mkdir()
            lane = stage.Lane(root, HERE, work, (archive, bounds, native))
            record = {'status': 'passed', 'failure_class': None, 'exit_code': 0, 'stdout_bytes': 0, 'stderr_bytes': 0}
            with mock.patch.object(lane, 'checkpoint'), mock.patch.object(bounds, 'run', return_value=(record, b'', b'')) as run:
                lane.run('first-party-mock', ['/usr/bin/true'])
            args, kwargs = run.call_args
            self.assertEqual(args[0][0], '/usr/bin/sandbox-exec')
            self.assertIn('IMMUTABLE_DIR=' + str(lane.immutable), args[0])
            self.assertEqual(kwargs['output_remaining'], 32 * 1024**2)
            self.assertNotIn('DYLD_LIBRARY_PATH', kwargs['env'])

    def test_rejected_subdirectory_cannot_widen_writes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve(); work = root / 'work'; work.mkdir()
            lane = stage.Lane(root, HERE, work, (archive, bounds, native))
            with self.assertRaises(stage.foundation.LaneError): lane.run('invalid', ['/usr/bin/true'], subdirectory='../../outside')

    def promotion_fixture(self, root):
        work = root / 'work'; work.mkdir()
        lane = stage.Lane(root, HERE, work, (archive, bounds, native))
        phase = lane.directory('first-party-copy-fixture')
        source = phase / 'input'; source.write_bytes(b'first-party-copy')
        target = lane.provider / 'include/fixture.h'
        return lane, source, target

    def test_promotion_reserves_aggregate_workspace_before_copy(self):
        with tempfile.TemporaryDirectory() as td:
            lane, source, target = self.promotion_fixture(Path(td).resolve())
            with mock.patch.object(bounds, 'disk_bytes', return_value=stage.WORKSPACE_LIMIT - 5):
                with self.assertRaises(stage.foundation.LaneError): lane.promote([(source, target, False)])
            self.assertFalse(target.exists())

    def test_promotion_reserves_free_space_before_copy(self):
        with tempfile.TemporaryDirectory() as td:
            lane, source, target = self.promotion_fixture(Path(td).resolve())
            with mock.patch.object(stage.shutil, 'disk_usage', return_value=mock.Mock(free=1024**3 + 5)):
                with self.assertRaises(stage.foundation.LaneError): lane.promote([(source, target, False)])
            self.assertFalse(target.exists())

    def test_promotion_copies_exact_bytes_and_refreezes(self):
        with tempfile.TemporaryDirectory() as td:
            lane, source, target = self.promotion_fixture(Path(td).resolve())
            lane.promote([(source, target, False)])
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertEqual(target.stat().st_mode & 0o777, 0o444)
            self.assertEqual(lane.base, archive.snapshot(lane.immutable))

    def test_promotion_rejects_duplicate_destinations_before_copy(self):
        with tempfile.TemporaryDirectory() as td:
            lane, source, target = self.promotion_fixture(Path(td).resolve())
            with self.assertRaises(stage.foundation.LaneError): lane.promote([(source, target, False), (source, target, False)])
            self.assertFalse(target.exists())

    def test_bounded_read_rejects_oversize_before_allocation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve(); path = root / 'oversized'; path.write_bytes(b'x' * 33)
            with self.assertRaises(safe_reads.ReadContractError): safe_reads.read(path, (root,), 32)

    def test_bounded_read_rejects_symlink_and_parent_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve(); (root / 'real').mkdir(); path = root / 'real/data'; path.write_bytes(b'inert')
            (root / 'file-link').symlink_to('real/data'); (root / 'dir-link').symlink_to('real', target_is_directory=True)
            for path in (root / 'file-link', root / 'dir-link/data'):
                with self.assertRaises(OSError): safe_reads.read(path, (root,), 32)

    def test_bounded_read_rejects_path_outside_explicit_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve(); path = root / 'inert'; path.write_bytes(b'inert')
            with self.assertRaises(safe_reads.ReadContractError): safe_reads.read(path, (root / 'different',), 32)

    def test_bounded_read_accepts_exact_regular_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve(); path = root / 'inert'; path.write_bytes(b'inert')
            self.assertEqual(safe_reads.read(path, (root,), 5), b'inert')

    def test_diagnostic_extension_retains_redaction_and_caps(self):
        text = b'authorization: Bearer INVALID_INERT_TEST_SENTINEL_DO_NOT_USE\npassword=INVALID_INERT_SECRET\nclang: error: public fixture failure\n' * 100
        report = diagnostics.summarize('glib-build', b'', text, HERE / 'build-diagnostic-catalog.json', Path('/immutable'), Path('/phase'), Path('/control'))
        rendered = json.dumps(report)
        self.assertLessEqual(len(rendered.encode()), 16384)
        self.assertNotIn('INVALID_INERT_TEST_SENTINEL_DO_NOT_USE', rendered)
        self.assertNotIn('INVALID_INERT_SECRET', rendered)
        self.assertIn('stderr_excerpt', report)

    def test_diagnostic_phase_extension_only(self):
        old = (HERE / 'build_diagnostics.py').read_text()
        new = (HERE / 'glib_build_diagnostics.py').read_text()
        self.assertEqual(old[old.index('MAX_STREAM_BYTES'):], new[new.index('MAX_STREAM_BYTES'):])
        self.assertEqual(diagnostics.MAX_EXCERPT_BYTES, 6144)
        self.assertEqual(diagnostics.MAX_REPORT_BYTES, 16384)

    def test_bounds_keep_original_helpers_ceilings_and_cleanup_with_diagnostics(self):
        old = ast.parse((HERE / 'bounds.py').read_text())
        code = (HERE / 'glib_bounds.py').read_text()
        new = ast.parse(code)
        for name in ('classify', 'disk_bytes', 'private_file_record'):
            original = next(node for node in old.body if isinstance(node, ast.FunctionDef) and node.name == name)
            current = next(node for node in new.body if isinstance(node, ast.FunctionDef) and node.name == name)
            self.assertEqual(ast.dump(original), ast.dump(current))
        self.assertEqual(bounds.GIB, 1024**3)
        self.assertEqual(bounds.MAX_SUPERVISOR_DIAGNOSTIC_BYTES, 2048)
        for retained in ('>4*GIB', '.free<GIB', 'sum(counts)>output_remaining',
                         'process.wait(timeout=3)', 'cleanup_deadline=time.monotonic()+2',
                         'os.killpg(process.pid,signal.SIGKILL)', 'time.sleep(0.02)'):
            self.assertIn(retained, code)

    def test_meson_python_flags_are_not_put_in_truncating_entry(self):
        source = (HERE / 'source-review/meson/mesonbuild/modules/python.py').read_text()
        self.assertIn('name_or_path = np[0] if np else None', source)
        self.assertIn("PythonExternalProgram('python3', mesonlib.python_command", source)
        code = (HERE / 'stage.py').read_text()
        self.assertNotIn("'python = ' +", code)
        self.assertIn("universal.python_command[:]=[sys.executable,'-I','-S']", (HERE / 'meson_entry.py').read_text())

    def test_fixtures_cover_requested_runtime_paths(self):
        code = (HERE / 'glib_probe.c').read_text()
        for symbol in ('ffi_prep_closure_loc', 'ffi_get_version', 'g_regex_new', 'g_utf8_casefold',
                       'g_cclosure_marshal_generic', 'g_signal_emit', 'g_module_open', 'g_module_symbol',
                       'g_file_replace_contents', 'g_file_load_contents', 'g_file_delete',
                       'g_dpgettext2', 'gi_repository_new', '_dyld_get_image_name'):
            self.assertIn(symbol, code)
        for marker in stage.GLIB_MARKERS:
            self.assertIn(marker, code)

    def test_workflow_public_standard_runner_and_no_upload(self):
        text = (HERE / 'glib-runtime-macos.yml.template').read_text()
        self.assertEqual(text.count('runs-on: macos-26'), 1)
        self.assertIn('github.event.repository.private == false', text)
        self.assertIn('timeout-minutes: 30', text)
        self.assertIn('contents: read', text)
        self.assertIn('persist-credentials: false', text)
        self.assertNotIn('upload-artifact', text)
        self.assertNotIn('actions/cache', text)
        self.assertNotIn('id-token:', text)
        self.assertNotIn('strategy:', text)

    def test_sources_not_modified_or_postlink_resigned(self):
        tree = ast.parse((HERE / 'stage.py').read_text())
        values = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        for forbidden in ('install_name_tool', 'codesign', 'make install', 'pip install', 'brew install'):
            self.assertNotIn(forbidden, values)
        self.assertIn('--disable-builddir', values)
        self.assertIn('--with-included-libxml', values)
        self.assertIn('--with-included-libunistring', values)

    def test_retains_accepted_gettext_layout_guard(self):
        with tempfile.TemporaryDirectory() as td:
            phase = Path(td).resolve(); (phase / 'intl').mkdir(); (phase / 'intl/config.h').write_text('/* first-party */')
            stage.foundation.bind_gettext_config_header(phase)
            self.assertEqual(os.readlink(phase / 'config.h'), 'intl/config.h')

    def test_ninja_visibility_generator_is_isolated(self):
        commands = b'/immutable/python3.12 -I -S /immutable/glib/tools/gen-visibility-macros.py 2.90.1 versions output.h\n'
        result = stage.verify_python_commands(commands, '/immutable/python3.12', '/immutable/glib/tools/gen-visibility-macros.py')
        self.assertEqual(result['visibility_generator_commands'], 1)

    def test_ninja_rejects_direct_executable_shebang_generator(self):
        commands = b'/immutable/glib/tools/gen-visibility-macros.py 2.90.1 versions output.h\n'
        with self.assertRaises(stage.foundation.LaneError):
            stage.verify_python_commands(commands, '/immutable/python3.12', '/immutable/glib/tools/gen-visibility-macros.py')

    def test_ninja_rejects_host_python_and_missing_isolation(self):
        for command in (b'/usr/bin/python3 -I -S /immutable/glib/tools/gen-visibility-macros.py\n',
                        b'/immutable/python3.12 /immutable/glib/tools/gen-visibility-macros.py\n'):
            with self.assertRaises(stage.foundation.LaneError):
                stage.verify_python_commands(command, '/immutable/python3.12', '/immutable/glib/tools/gen-visibility-macros.py')

    def test_visibility_override_is_bound_to_release_shebang(self):
        script = (HERE / 'source-review/glib/tools/gen-visibility-macros.py').read_text()
        tools = (HERE / 'source-review/glib/tools/meson.build').read_text()
        self.assertTrue(script.startswith('#!/usr/bin/env python3'))
        self.assertIn("find_program('gen-visibility-macros.py')", tools)
        members = json.loads((HERE / 'members/glib.json').read_text())['members']
        entry = next(x for x in members if x['path'] == 'glib-2.90.1/tools/gen-visibility-macros.py')
        self.assertNotEqual(entry['mode'] & 0o111, 0)
        self.assertIn("'gen-visibility-macros.py = ' + repr([str(py), '-I', '-S'", (HERE / 'stage.py').read_text())

    def test_configured_mkenums_and_template_are_source_consistent(self):
        meson = (HERE / 'source-review/glib/gobject/meson.build').read_text()
        top = (HERE / 'source-review/glib/meson.build').read_text()
        script = (HERE / 'source-review/glib/gobject/glib-mkenums.in').read_text()
        self.assertIn("python_tools_conf.set('PYTHON', python_shebang)", meson)
        self.assertIn("python_shebang = '/usr/bin/env python3'", top)
        self.assertIn("prod = eprod", script)
        self.assertIn("--eprod=@EnumName@", (HERE / 'stage.py').read_text())

    def test_glib_catalog_probe_does_not_rebind_or_use_native_date_locale(self):
        code = (HERE / 'glib_probe.c').read_text()
        self.assertIn('error->domain != G_REGEX_ERROR', code)
        self.assertIn('G_REGEX_ERROR_UNMATCHED_PARENTHESIS', code)
        self.assertNotIn('bindtextdomain(', code)
        self.assertNotIn('g_date_time_format(', code)
        self.assertIn('g_dpgettext2("glib20", "full month name", "January")', code)


if __name__ == '__main__':
    unittest.main()

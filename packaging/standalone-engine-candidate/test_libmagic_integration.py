"""Portable stdlib/mock/data-only contracts. Never import python-magic or execute downloaded code."""
import ast
import base64
import csv
import ctypes
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE/filename)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


integration = module('magic_integration_test', 'libmagic_integration.py')
loader = module('magic_loader_test', 'bundled_magic_loader.py')
assembly = module('magic_assembly_test', 'assemble.py')
native = module('magic_native_test', 'native_libmagic_stage.py')
runtime = module('magic_runtime_test', 'libmagic_runtime.py')


class FakeFunction:
    def __init__(self): self.calls = []; self.argtypes = None; self.restype = None
    def __call__(self, *args):
        observed = list(args)
        for index, value in enumerate(args):
            if isinstance(value, loader._FilenameParameter):
                # Mock ctypes' lazy argument-2 conversion. Ordering and actual
                # native-pointer freezing are covered by real inert callbacks.
                try:
                    observed[index] = ctypes.c_char_p.from_param(value).value
                except BaseException as error:
                    raise ctypes.ArgumentError('argument 2: ' + type(error).__name__ + ': ' + str(error)) from None
        self.calls.append(tuple(observed)); return 0


class FakeCDLL:
    def __init__(self, path): self.path = path; self.functions = {}
    def __getattr__(self, name):
        if name not in self.functions:
            fn = FakeFunction()
            fn.argtypes = ([ctypes.c_int] if name == 'magic_open' else
                           [ctypes.c_void_p, ctypes.c_int] if name == 'magic_setflags' else
                           [ctypes.c_void_p, ctypes.c_char_p])
            self.functions[name] = fn
        return self.functions[name]


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.root = Path(self.temporary.name).resolve()
        self.prefix = self.root/'Moved engine Ω/DeepdeskEngine.app/Contents/Resources/Python'
        self.native = self.prefix/'lib/deepdesk-native/libmagic'
        self.fake_loader = self.prefix/'lib/python3.12/site-packages/magic/loader.py'
        self.fake_loader.parent.mkdir(parents=True); self.fake_loader.write_text('# first-party inert fixture\n')
        for path in [self.native/'lib/libmagic.1.dylib', self.native/'share/misc/magic.mgc']:
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'inert bytes, never loaded')
        text = self.native/'share/misc/magic'; text.mkdir()
        rows = []
        for i in range(358):
            data = ('# inert text fragment %d\n' % i).encode(); name = 'fragment-%03d' % i
            (text/name).write_bytes(data)
            rows.append({'name': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        (self.native/'share/misc/deepdesk-text-fragments.json').write_text(json.dumps({'count': 358, 'fragments': rows}))
        self.prefix_patch = patch.object(loader.sys, 'prefix', str(self.prefix)); self.prefix_patch.start()
        self.file_patch = patch.object(loader, '__file__', str(self.fake_loader)); self.file_patch.start()
        self.cdll_patch = patch.object(loader.ctypes, 'CDLL', side_effect=FakeCDLL); self.cdll = self.cdll_patch.start()

    def tearDown(self):
        self.cdll_patch.stop(); self.file_patch.stop(); self.prefix_patch.stop(); self.temporary.cleanup()

    def test_exact_bundle_path_no_lookup_and_separate_ctypes_functions(self):
        with patch.dict(os.environ, {'MAGIC': '/host/unapproved.mgc'}):
            modern = loader.load_lib(); compat = loader.load_lib()
        self.assertEqual(self.cdll.call_count, 2)
        self.assertEqual(modern._library.path, str(self.native/'lib/libmagic.1.dylib'))
        self.assertIsNot(modern._library, compat._library)
        modern.magic_load.argtypes = ['modern']; compat.magic_load.argtypes = ['compat']
        self.assertEqual(modern.magic_load.argtypes, ['modern'])
        self.assertEqual(compat.magic_load.argtypes, ['compat'])
        self.assertIs(modern.magic_load, modern.magic_load)

    def test_all_declared_ctypes_null_defaults_in_both_independent_proxies(self):
        class Parameter:
            def __init__(self, value): self._as_parameter_ = value
        char = ctypes.c_char()
        nulls = [None, ctypes.c_char_p(None), ctypes.POINTER(ctypes.c_char)(),
                 Parameter(None), Parameter(Parameter(ctypes.POINTER(ctypes.c_char)())),
                 ctypes.byref(char, -ctypes.addressof(char))]
        modern = loader.load_lib(); compat = loader.load_lib()
        for lib, cookie_type in ((modern, ctypes.c_void_p), (compat, ctypes.POINTER(ctypes.c_char))):
            for name in ('magic_load', 'magic_check', 'magic_list', 'magic_compile'):
                getattr(lib, name).argtypes = [cookie_type, ctypes.c_char_p]
                for null in nulls:
                    getattr(lib, name)('cookie', null)
                    selected = 'magic' if name == 'magic_compile' else 'magic.mgc'
                    self.assertEqual(getattr(lib._library, name).calls[-1],
                                     ('cookie', os.fsencode(self.native/'share/misc'/selected)))
        self.assertIsNot(modern.magic_load._function, compat.magic_load._function)
        self.assertEqual(modern.magic_load.argtypes[0], ctypes.c_void_p)
        self.assertEqual(compat.magic_load.argtypes[0], ctypes.POINTER(ctypes.c_char))

    def test_explicit_nonnull_arguments_and_conversion_failures_preserved(self):
        class Parameter:
            def __init__(self, value): self._as_parameter_ = value
        buffer = ctypes.create_string_buffer(b'/synthetic/compiled.mgc')
        empty = ctypes.c_char(b'\x00')
        explicit = [b'/synthetic/compiled.mgc', b'', ctypes.c_char_p(b'/synthetic/compiled.mgc'),
                    buffer, ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)), ctypes.byref(empty),
                    Parameter(b'/synthetic/compiled.mgc'), Parameter(ctypes.c_char_p(b'/synthetic/compiled.mgc'))]
        for lib in (loader.load_lib(), loader.load_lib()):
            for name in ('magic_load', 'magic_check', 'magic_list', 'magic_compile'):
                fn = getattr(lib, name)
                for value in explicit:
                    fn('cookie', value)
                    actual = getattr(lib._library, name).calls[-1][1]
                    converted = ctypes.c_char_p.from_param(value)
                    owner = getattr(converted, '_obj', None)
                    expected = owner if isinstance(owner, bytes) else ctypes.cast(converted, ctypes.c_char_p).value
                    self.assertEqual(actual, expected)
                for value in (0, ctypes.c_void_p(None), 'unicode filename', object(), ctypes.byref(buffer)):
                    with self.assertRaises(Exception) as original:
                        ctypes.c_char_p.from_param(value)
                    count = len(getattr(lib._library, name).calls)
                    with self.assertRaises(ctypes.ArgumentError) as wrapped:
                        fn('cookie', value)
                    self.assertEqual(str(wrapped.exception), 'argument 2: ' + type(original.exception).__name__ + ': ' + str(original.exception))
                    self.assertEqual(len(getattr(lib._library, name).calls), count)

    def test_real_stdlib_ctypes_conversion_with_inert_python_callbacks(self):
        # This callback is first-party inert test code, not a downloaded/native
        # dependency. It observes the real ctypes boundary without libmagic.
        seen = []
        callback = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_char_p)(
            lambda cookie, filename: seen.append(filename) or 0)
        wrapped = loader._Function(callback, 'magic_load', self.native)
        class Parameter:
            _as_parameter_ = None
        typed = ctypes.c_char_p(None)
        typed._obj = b'/unrelated/attribute/must/not/replace/NULL'
        for value in (None, ctypes.POINTER(ctypes.c_char)(), Parameter(), typed):
            self.assertEqual(wrapped(None, value), 0)
            self.assertEqual(seen[-1], os.fsencode(self.native/'share/misc/magic.mgc'))
        for value in (b'', b'explicit', ctypes.c_char_p(b'explicit'), ctypes.create_string_buffer(b'explicit')):
            self.assertEqual(wrapped(None, value), 0)
            self.assertEqual(seen[-1], b'' if value == b'' else b'explicit')
        for value in (0, ctypes.c_void_p(None), object(), 'unicode'):
            with self.assertRaises(ctypes.ArgumentError) as original:
                callback(None, value)
            with self.assertRaises(ctypes.ArgumentError) as changed:
                wrapped(None, value)
            self.assertEqual(str(changed.exception), str(original.exception))

    def test_real_ctypes_synchronous_order_all_actions_both_signatures(self):
        class MagicSet(ctypes.Structure):
            _fields_ = [('inert', ctypes.c_int)]
        for cookie_type in (ctypes.c_void_p, ctypes.POINTER(MagicSet)):
            for name in ('magic_load', 'magic_check', 'magic_list', 'magic_compile'):
                seen = []
                callback = ctypes.CFUNCTYPE(ctypes.c_int, cookie_type, ctypes.c_char_p)(
                    lambda cookie, filename: seen.append((ctypes.cast(cookie, ctypes.c_void_p).value, filename)) or 0)
                wrapped = getattr(loader._Library(types.SimpleNamespace(**{name: callback}), self.native), name)
                signature = callback.argtypes
                self.assertIs(wrapped.argtypes, signature)
                for initial, final in ((b'initial', None), (None, b'final-explicit')):
                    events = []; filename = ctypes.c_char_p(initial)
                    target = MagicSet(1); other = MagicSet(2)
                    cookie = ctypes.cast(ctypes.pointer(target), cookie_type)
                    expected_cookie = ctypes.cast(cookie, ctypes.c_void_p).value
                    class Cookie:
                        @property
                        def _as_parameter_(self):
                            events.append('cookie')
                            self_signature = wrapped.argtypes
                            if self_signature is not signature: raise AssertionError('shared signature changed')
                            filename.value = final
                            return cookie
                    class Filename:
                        @property
                        def _as_parameter_(self):
                            events.append('filename')
                            # Cookie's native value must already be frozen even
                            # though the earlier typed object remains mutable.
                            if cookie_type is ctypes.c_void_p:
                                cookie.value = ctypes.addressof(other)
                            else:
                                cookie.contents = other
                            return filename
                    self.assertEqual(wrapped(Cookie(), Filename()), 0)
                    expected_filename = (os.fsencode(self.native/'share/misc'/(
                        'magic' if name == 'magic_compile' else 'magic.mgc')) if final is None else final)
                    self.assertEqual(seen[-1], (expected_cookie, expected_filename))
                    self.assertEqual(events, ['cookie', 'filename'])
                    self.assertIs(wrapped.argtypes, signature)
                    self.assertIs(callback.argtypes, signature)
                # The returned snapshot is independent of later mutation of its
                # source typed pointer, with owners retained by the call object.
                typed = ctypes.c_char_p(b'kept-explicit')
                parameter = loader._FilenameParameter(typed, ctypes.c_char_p, name, self.native)
                frozen = parameter._as_parameter_; typed.value = None
                self.assertEqual(frozen.value, b'kept-explicit')
                self.assertIs(parameter._as_parameter_, frozen)
                self.assertIs(parameter._converted, typed)

    def test_real_ctypes_error_order_and_once_conversion_both_signatures(self):
        class MagicSet(ctypes.Structure): pass
        for cookie_type in (ctypes.c_void_p, ctypes.POINTER(MagicSet)):
            for name in ('magic_load', 'magic_check', 'magic_list', 'magic_compile'):
                callback = ctypes.CFUNCTYPE(ctypes.c_int, cookie_type, ctypes.c_char_p)(lambda cookie, filename: 0)
                wrapped = loader._Function(callback, name, self.native)
                for bad_cookie in (False, True):
                    for error_type in (TypeError, ValueError, ImportError, KeyboardInterrupt):
                        observations = []
                        for function in (callback, wrapped):
                            events = []
                            class Cookie:
                                @property
                                def _as_parameter_(self):
                                    events.append('cookie')
                                    return object() if bad_cookie else cookie_type()
                            class Filename:
                                @property
                                def _as_parameter_(self):
                                    events.append('filename')
                                    raise error_type('inert original conversion failure')
                            with self.assertRaises(ctypes.ArgumentError) as error:
                                function(Cookie(), Filename())
                            observations.append((str(error.exception), events))
                        self.assertEqual(observations[0], observations[1])
                        self.assertEqual(observations[1][1], ['cookie'] if bad_cookie else ['cookie', 'filename'])

    def test_real_ctypes_missing_resource_exception_remains_fixed_import_error(self):
        seen = []
        callback = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_char_p)(
            lambda cookie, filename: seen.append(filename) or 0)
        for name, relative, message in (
                ('magic_load', 'share/misc/magic.mgc', 'Bundled magic resource is unavailable'),
                ('magic_compile', 'share/misc/magic', 'Bundled magic text sources are unavailable')):
            original = self.native/relative; held = self.root/'held-resource'; original.rename(held)
            try:
                with self.assertRaisesRegex(ImportError, '^' + message + '$'):
                    loader._Function(callback, name, self.native)(None, None)
                self.assertEqual(seen, [])
            finally:
                held.rename(original)

    def test_as_parameter_is_converted_once_and_cannot_flip_to_host_default(self):
        class Changing:
            def __init__(self): self.calls = 0
            @property
            def _as_parameter_(self):
                self.calls += 1
                return b'/synthetic/explicit.mgc' if self.calls == 1 else None
        for lib in (loader.load_lib(), loader.load_lib()):
            for name in ('magic_load', 'magic_check', 'magic_list', 'magic_compile'):
                value = Changing(); getattr(lib, name)('cookie', value)
                self.assertEqual(value.calls, 1)
                self.assertEqual(getattr(lib._library, name).calls[-1][1], b'/synthetic/explicit.mgc')

    def test_open_setflags_are_unwrapped_and_keep_caller_values_and_conversions(self):
        for lib in (loader.load_lib(), loader.load_lib()):
            self.assertIs(lib.magic_open, lib._library.magic_open)
            self.assertIs(lib.magic_setflags, lib._library.magic_setflags)
            for value in (0, 4, 0x4000000, 0x12345, ctypes.c_int(0), ctypes.c_int(4)):
                ctypes.c_int.from_param(value)  # Original conversion accepts it.
                lib.magic_open(value); lib.magic_setflags('cookie', value)
                self.assertIs(lib._library.magic_open.calls[-1][0], value)
                self.assertIs(lib._library.magic_setflags.calls[-1][1], value)
            lib.magic_setflags('cookie', 0)
            self.assertEqual(lib._library.magic_setflags.calls[-1], ('cookie', 0))

    def test_missing_library_or_database_never_attempts_cdll(self):
        for relative in ('lib/libmagic.1.dylib', 'share/misc/magic.mgc'):
            with self.subTest(relative=relative):
                path = self.native/relative; held = self.root/'held'; path.rename(held)
                try:
                    with self.assertRaisesRegex(ImportError, '^Bundled magic resource is unavailable$'):
                        loader.load_lib()
                    self.cdll.assert_not_called()
                finally: held.rename(path)

    def test_missing_damaged_or_extra_text_refused_without_native_call(self):
        lib = loader.load_lib(); text = self.native/'share/misc/magic'; target = text/'fragment-000'
        original = target.read_bytes()
        for mode in ('missing', 'changed', 'extra', 'linked'):
            if mode == 'missing': target.unlink()
            elif mode == 'changed': target.write_bytes(b'changed')
            elif mode == 'extra': (text/'extra').write_text('unexpected')
            else: target.unlink(); target.symlink_to(self.root/'outside')
            try:
                with self.assertRaises(ImportError): lib.magic_compile('cookie', None)
                self.assertEqual(lib._library.magic_compile.calls, [])
            finally:
                if target.is_symlink(): target.unlink()
                target.write_bytes(original)
                (text/'extra').unlink(missing_ok=True)

    def test_cdll_failure_redacted_no_fallback(self):
        self.cdll.side_effect = OSError('secret host path and native diagnostic')
        with self.assertRaisesRegex(ImportError, '^Bundled libmagic could not be loaded$') as error:
            loader.load_lib()
        self.assertTrue(error.exception.__suppress_context__); self.assertEqual(self.cdll.call_count, 1)

    def test_origin_and_directory_symlink_refused(self):
        with patch.object(loader, '__file__', str(self.root/'other.py')):
            (self.root/'other.py').write_text('# inert')
            with self.assertRaisesRegex(ImportError, 'origin differs'): loader.load_lib()
        actual = self.native.parent/'held'; self.native.rename(actual); self.native.symlink_to(actual, target_is_directory=True)
        with self.assertRaisesRegex(ImportError, 'root is unavailable'): loader.load_lib()
        self.cdll.assert_not_called()


class IntegrationTests(unittest.TestCase):
    def test_combined_cap_accepts_exact_and_rejects_plus_one(self):
        output = json.dumps({'private_native_output_bytes': 4870}).encode()
        summary = {'bounded_step': 'passed', 'stdout_bytes': len(output),
                   'stderr_bytes': integration.CAP-4870-len(output)}
        result = integration.measured_result(output, summary)
        self.assertEqual(result['combined_private_and_outer_output_bytes'], integration.CAP)
        summary['stderr_bytes'] += 1
        with self.assertRaisesRegex(RuntimeError, 'Combined private'): integration.measured_result(output, summary)
        for bad in (None, True, -1, '4870'):
            output = json.dumps({'private_native_output_bytes': bad}).encode()
            with self.assertRaisesRegex(RuntimeError, 'byte count'):
                integration.measured_result(output, {'bounded_step': 'passed', 'stdout_bytes': len(output), 'stderr_bytes': 0})

    def test_measured_outer_summary_is_captured_not_publicly_reprinted(self):
        output = json.dumps({'private_native_output_bytes': 4870}).encode()
        def run():
            print(json.dumps({'bounded_step': 'passed', 'stdout_bytes': len(output), 'stderr_bytes': 37}))
            return output
        from contextlib import redirect_stdout
        public = io.StringIO()
        with redirect_stdout(public): result = integration.run_measured(run)
        self.assertEqual(public.getvalue(), '')
        self.assertEqual(result['combined_private_and_outer_output_bytes'], 4870 + len(output) + 37)

    def test_native_failure_reports_only_fixed_phase_category_and_fails_parent(self):
        from contextlib import redirect_stdout
        def runner(phase='configure', category='nonzero_exit'):
            output = json.dumps({'status': 'failed', 'kind': 'bundled-libmagic-native-build',
                'phase': phase, 'failure_category': category,
                'private_native_output_bytes': None,
                'private_output_measurement': 'unknown-after-failure'}).encode()
            print(json.dumps({'bounded_step': 'passed', 'stdout_bytes': len(output), 'stderr_bytes': 0}))
            return output
        public = io.StringIO()
        with redirect_stdout(public), self.assertRaisesRegex(RuntimeError, 'fixed diagnostics only'):
            integration.run_measured(runner)
        self.assertEqual(json.loads(public.getvalue()), {'native_step': 'configure', 'failure_category': 'nonzero_exit'})
        for phase, category in [('secret-host-path', 'unknown'), ('configure', 'secret-child-output')]:
            public = io.StringIO()
            with redirect_stdout(public), self.assertRaisesRegex(RuntimeError, 'Unreviewed native failure'):
                integration.run_measured(lambda: runner(phase, category))
            self.assertEqual(public.getvalue(), '')

    def test_failed_counts_remain_unknown_and_never_receive_successful_acceptance(self):
        from contextlib import redirect_stdout
        report = native.failure_report(native.NativeStepFailure('make-all', 'output_limit'))
        self.assertIsNone(report['private_native_output_bytes'])
        self.assertEqual(report['private_output_measurement'], 'unknown-after-failure')
        self.assertNotIn('private_output_is_upper_bound', report)
        output = json.dumps(report).encode()
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, 'fixed diagnostics only'):
            integration.measured_result(output, {'bounded_step': 'passed', 'stdout_bytes': len(output), 'stderr_bytes': 0})
        # A historical made-up bound must not be accepted as failure evidence.
        report['private_native_output_bytes'] = integration.CAP-integration.NATIVE_REPORT_RESERVE
        output = json.dumps(report).encode()
        with self.assertRaisesRegex(RuntimeError, 'Unreviewed native failure'):
            integration.measured_result(output, {'bounded_step': 'passed', 'stdout_bytes': len(output), 'stderr_bytes': 0})

    def test_single_profile_native_children_and_no_nested_profile_command(self):
        work = Path('/work'); immutable = work/'immutable'; helpers = Path('/reviewed/pilot')
        for fixture in (None, work/'install/libexec/deepdesk-libmagic-smoke'):
            command = native.sandbox_command(['/reviewed/tool', 'arg'], work=work,
                immutable=immutable, helpers=helpers, fixture=fixture)
            self.assertEqual(command.count('/usr/bin/sandbox-exec'), 1)
            self.assertEqual(command[0], '/usr/bin/sandbox-exec')
            self.assertIn('WORK_DIR=/work', command); self.assertIn('IMMUTABLE_DIR=/work/immutable', command)
            self.assertEqual(command[-2:], ['/reviewed/tool', 'arg'])
            self.assertIn(str(helpers/('smoke-no-exec.sb' if fixture else 'offline.sb')), command)
        with self.assertRaisesRegex(RuntimeError, 'Nested native sandbox'):
            native.sandbox_command(['/usr/bin/sandbox-exec', '/downloaded/payload'], work=work,
                                   immutable=immutable, helpers=helpers)

    def test_only_stdlib_host_orchestrator_is_outside_downloaded_code_profiles(self):
        source = (HERE/'standalone_stage.py').read_text(); tree = ast.parse(source)
        direct = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute) and node.func.attr == 'run_bounded'
                  and node.args and isinstance(node.args[0], ast.List)]
        self.assertEqual(len(direct), 1)
        values = direct[0].args[0].elts
        self.assertEqual([x.value for x in values[:4]], ['/usr/bin/python3', '-I', '-S', '-B'])
        self.assertIn('native_libmagic_stage.py', ast.unparse(values[4]))
        self.assertEqual({x.arg for x in direct[0].keywords}, {'cwd', 'env', 'work', 'timeout', 'own_session'})
        self.assertIs(next(x.value for x in direct[0].keywords if x.arg == 'own_session').value, True)
        self.assertEqual(ast.unparse(next(x.value for x in direct[0].keywords if x.arg == 'timeout')), 'min(540, budget())')
        fixture_calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                         and isinstance(node.func, ast.Name) and node.func.id == 'run'
                         and any(x.arg == 'fixture_executable' for x in node.keywords)]
        self.assertEqual(len(fixture_calls), 2)
        for node in fixture_calls:
            self.assertIsInstance(node.args[0], ast.List)
            self.assertEqual(ast.unparse(node.args[0].elts[0]), 'moved_fixture')
        self.assertNotIn('moved_policy', source)
        self.assertIn('Nested stage sandbox invocation forbidden', source)
        self.assertNotIn('sandbox-exec', (HERE/'libmagic_runtime.py').read_text())
        base = (HERE/'standalone-offline.sb').read_bytes()
        moved = (HERE/'libmagic-moved-no-exec.sb').read_bytes()
        self.assertTrue(moved.startswith(base))
        self.assertEqual(moved[len(base):].count(b'(deny process-exec)'), 1)
        self.assertIn(b'(allow process-exec (literal (param "FIXTURE_PATH")))', moved[len(base):])
        self.assertNotIn(b'(allow network', moved)

    def test_exact_configure_overlay_changes_only_two_install_ids(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); before = b'-install_name \\$rpath/\\$soname'; after = b'-install_name @rpath/\\$soname'
            original = b'# inert configure fixture\n' + before + b'\nother unchanged\n' + before + b'\n'
            modified = original.replace(before, after)
            path = root/'configure'; path.write_bytes(original); path.chmod(0o755)
            row = {'member': 'file-5.48/configure', 'replacements': 2,
                   'before_block': before.decode(), 'after_block': after.decode(),
                   'before_size': len(original), 'after_size': len(modified),
                   'before_sha256': hashlib.sha256(original).hexdigest(), 'after_sha256': hashlib.sha256(modified).hexdigest()}
            mode = path.stat().st_mode; mtime = path.stat().st_mtime_ns
            result = integration.apply_configure_overlay(root, row)
            self.assertEqual(path.read_bytes(), modified); self.assertEqual(path.stat().st_mode, mode)
            self.assertEqual(path.stat().st_mtime_ns, mtime); self.assertEqual(result['install_id'], '@rpath/libmagic.1.dylib')
            with self.assertRaises(RuntimeError): integration.apply_configure_overlay(root, row)

    def test_all_358_text_fragments_copied_as_upstream_flat_compile_input(self):
        contract = json.loads((HERE/'libmagic-text-fragments.json').read_text())
        self.assertEqual(contract['count'], 358)
        self.assertEqual(len(contract['fragments']), 358)
        self.assertEqual(len({x['name'] for x in contract['fragments']}), 358)
        self.assertEqual(contract['fragments'][0]['source'], 'magic/Header')
        self.assertEqual(contract['fragments'][1]['source'], 'magic/Localstuff')
        member_contract = json.loads((HERE/'libmagic-pilot/source-members.json').read_text())
        members = {x['path']: x for x in member_contract['members']}
        for row in contract['fragments']:
            upstream = members['file-5.48/' + row['source']]
            self.assertEqual((row['sha256'], row['size'], row['mode']),
                             (upstream['sha256'], upstream['size'], upstream['mode']))

    def test_relative_native_linkage_strictly_checked(self):
        loads = 'fixture:\n\t@rpath/libmagic.1.dylib (compatibility version 2.0.0)\n\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n'
        commands = 'cmd LC_RPATH\ncmdsize 40\npath @loader_path (offset 12)\ncmd LC_RPATH\ncmdsize 48\npath @loader_path/../lib (offset 12)\nminos 26.0\n'
        self.assertEqual(native.inspect_native(loads, commands)['minimum_os'], '26.0')
        for bad in (loads.replace('@rpath/libmagic.1.dylib', '/temporary/libmagic.1.dylib'),
                    loads.replace('/usr/lib/libSystem.B.dylib', '/opt/homebrew/lib/other.dylib')):
            with self.assertRaises(RuntimeError): native.inspect_native(bad, commands)
        for bad in (commands.replace('@loader_path/../lib', '/temporary/lib'), commands.replace('26.0', '25.0')):
            with self.assertRaises(RuntimeError): native.inspect_native(loads, bad)

    def test_native_and_runtime_modules_import_without_subprocess_or_cdll(self):
        with patch('subprocess.Popen', side_effect=AssertionError('no subprocess')), \
             patch('ctypes.CDLL', side_effect=AssertionError('no native loading')):
            module('magic_native_import', 'native_libmagic_stage.py')
            module('magic_runtime_import', 'libmagic_runtime.py')

    def test_closed_gate_rejects_before_filesystem_or_platform(self):
        with self.assertRaisesRegex(RuntimeError, 'approval is closed'):
            integration.validate_gate({'execution_approved': False}, Path('/absent'))

    def test_each_new_approval_parent_and_exact_pin_is_enforced(self):
        import copy
        root = HERE.parents[1]
        receipt = json.loads((HERE/'review-receipt.json').read_text())
        approvals = ('execution_approved', 'managed_policy_execution_approved',
                     'libmagic_execution_approved', 'libmagic_source_overlays_approved',
                     'libmagic_binding_overlay_approved', 'libmagic_install_id_assignment_approved',
                     'compiler_linker_adhoc_signature_permitted')
        for key in approvals: receipt[key] = True
        integration.validate_gate(receipt, root)
        for key in approvals:
            bad = copy.deepcopy(receipt); bad[key] = False
            with self.assertRaisesRegex(RuntimeError, 'approval is closed'): integration.validate_gate(bad, root)
        bad = copy.deepcopy(receipt); bad['base_commit'] = 'historical-approval'
        with self.assertRaisesRegex(RuntimeError, 'scope differs'): integration.validate_gate(bad, root)
        key = 'packaging/standalone-engine-candidate/bundled_magic_loader.py'
        bad = copy.deepcopy(receipt); bad['sha256'][key] = '0' * 64
        with self.assertRaisesRegex(RuntimeError, 'input changed'): integration.validate_gate(bad, root)
        bad = copy.deepcopy(receipt); del bad['sha256'][key]
        with self.assertRaisesRegex(RuntimeError, 'review set incomplete'): integration.validate_gate(bad, root)

    def test_receipt_is_closed_current_parent_and_all_pins_match(self):
        root = HERE.parents[1]
        receipt = json.loads((HERE/'review-receipt.json').read_text())
        for name in ('execution_approved', 'managed_policy_execution_approved', 'publication_approved',
                     'activation_approved', 'libmagic_execution_approved', 'libmagic_source_overlays_approved',
                     'libmagic_binding_overlay_approved', 'libmagic_install_id_assignment_approved',
                     'compiler_linker_adhoc_signature_permitted'):
            self.assertIs(type(receipt[name]), bool, name)
        self.assertEqual(receipt['base_commit'], '109ce9dc56231f314e5a2fec558514652e20f502')
        for name, sha in receipt['sha256'].items():
            self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(), sha, name)

    def test_dedicated_workflow_branch_and_receipt_are_bound(self):
        root = HERE.parents[1]
        receipt = json.loads((HERE/'review-receipt.json').read_text())
        self.assertEqual(receipt['destination_branch'], 'engine-standalone-libmagic-ci')
        self.assertEqual(receipt['workflow_path'], '.github/workflows/engine-standalone-libmagic-macos.yml')
        text = (HERE/'standalone-libmagic-macos.yml.template').read_text()
        self.assertEqual(text, (root/receipt['workflow_path']).read_text())
        for token in ('engine-standalone-libmagic-ci', 'runs-on: macos-26', 'timeout-minutes: 25',
                      'contents: read', 'persist-credentials: false', 'github.event.repository.private == false'):
            self.assertIn(token, text)
        self.assertNotIn('engine-standalone-core-ci', text)
        for token in ('upload-artifact@', 'cache@', 'secrets.', 'contents: write', 'brew install'):
            self.assertNotIn(token, text)
        self.assertEqual(hashlib.sha256((root/'.github/workflows/engine-standalone-core-macos.yml').read_bytes()).hexdigest(),
                         '7632897d4a31e098c6dedd0f5118cd5a45ef4afe25462810d6a3c71d2a31bc5b')

    def test_pipeline_retains_source_and_binding_runtime_gates(self):
        stage = (HERE/'standalone_stage.py').read_text()
        for token in ('libmagic.validate_gate(receipt, root)', 'libmagic.integrate(', 'native_build = libmagic.run_measured(',
                      "'missing-library'", "'missing-database'", "'missing-text'", 'held.rename(missing)',
                      'Bundle differs after native resource restoration', 'assembly._remove_owned_partial(native_prefix)',
                      'Moved native exec denial canary differs', 'pilot.validate_smoke(moved_smoke.decode()',
                      "'Relocated engine Ω'", "'libmagic_tested':True"):
            self.assertIn(token, stage)
        runtime_source = (HERE/'libmagic_runtime.py').read_text()
        for token in ('magic.magic_compile(modern.cookie, None)', 'legacy.compile(None)', 'magic.magic_check(modern.cookie, None)',
                      'legacy.check(None)', 'legacy.list(None)', 'loaded_images(prefix, library)', 'own_session=False',
                      'magic.MAGIC_MIME_TYPE | magic.MAGIC_COMPRESS | 0x2000000 | 0x4000000'):
            self.assertIn(token, runtime_source)
        native_source = (HERE/'native_libmagic_stage.py').read_text()
        self.assertNotIn('install_name_tool', native_source)
        for token in ('pilot.apply_overlay(', 'integration.apply_configure_overlay(', 'integration.preserve_text_sources(',
                      'pilot.native_canary_observation(', 'pilot.validate_smoke(', "'-verify_arch', 'arm64'", 'own_session=False'):
            self.assertIn(token, native_source)

    def test_controller_identity_is_required_after_cleanup_and_before_copy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); native_root = root/'native'; native_root.mkdir()
            paths = ('lib/libmagic.1.dylib', 'bin/file', 'libexec/deepdesk-libmagic-smoke')
            for name in (*paths, 'share/misc/magic.mgc', 'share/misc/magic/Header'):
                path = native_root/name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(('inert validated bytes ' + name).encode())
            (native_root/'lib/libmagic.dylib').symlink_to('libmagic.1.dylib')
            manifest = assembly.inventory_tree(native_root)
            digest = assembly.manifest_digest(manifest)
            self.assertEqual(integration.inventory_digest(manifest), digest)
            evidence = {'validated_install_manifest_sha256': digest, 'native_records': [
                {'path': name, 'sha256': hashlib.sha256((native_root/name).read_bytes()).hexdigest()} for name in paths]}
            verified = integration.verify_tested_install(native_root, evidence, inventory=assembly.inventory_tree)
            self.assertEqual(verified, manifest)
            for name in (paths[0], 'share/misc/magic/Header'):
                path = native_root/name; original = path.read_bytes(); path.write_bytes(original + b'changed after controller')
                with self.assertRaisesRegex(RuntimeError, 'after controller validation'):
                    integration.verify_tested_install(native_root, evidence, inventory=assembly.inventory_tree)
                prefix = root/'python'; prefix.mkdir(exist_ok=True)
                with self.assertRaisesRegex(RuntimeError, 'before exact copy'):
                    integration.integrate(prefix, native_root, HERE, inventory=assembly.inventory_tree,
                                          expected_native_manifest=manifest)
                self.assertFalse((prefix/integration.NATIVE_RELATIVE).exists())
                path.write_bytes(original)
            target = native_root/'bin/file'; old_mode = target.stat().st_mode & 0o777; target.chmod(old_mode ^ 0o100)
            with self.assertRaisesRegex(RuntimeError, 'after controller validation'):
                integration.verify_tested_install(native_root, evidence, inventory=assembly.inventory_tree)
            target.chmod(old_mode)
            link = native_root/'lib/libmagic.dylib'; link.unlink(); link.symlink_to('../bin/file')
            with self.assertRaisesRegex(RuntimeError, 'after controller validation'):
                integration.verify_tested_install(native_root, evidence, inventory=assembly.inventory_tree)
            link.unlink(); link.symlink_to('libmagic.1.dylib')
            bad = json.loads(json.dumps(evidence)); bad['native_records'][0]['sha256'] = '0' * 64
            with self.assertRaisesRegex(RuntimeError, 'Audited native binary differs'):
                integration.verify_tested_install(native_root, bad, inventory=assembly.inventory_tree)
            for bad in ({}, {**evidence, 'native_records': evidence['native_records'][:2]},
                        {**evidence, 'validated_install_manifest_sha256': '0' * 64}):
                with self.assertRaises(RuntimeError):
                    integration.verify_tested_install(native_root, bad, inventory=assembly.inventory_tree)
        source = (HERE/'standalone_stage.py').read_text()
        self.assertLess(source.index('native_build = libmagic.run_measured('), source.index('tested_native = libmagic.verify_tested_install('))
        self.assertLess(source.index('tested_native = libmagic.verify_tested_install('), source.index('native_overlay = libmagic.integrate('))
        self.assertIn('expected_native_manifest=tested_native', source)
        native_source = (HERE/'native_libmagic_stage.py').read_text()
        self.assertIn('validated_install == before_install', native_source)
        self.assertIn("'validated_install_manifest_sha256': assembly.manifest_digest(validated_install)", native_source)
        self.assertIn("entries[row['path']]['sha256'] == row['sha256']", native_source)

    def test_whole_installed_payload_preserved_with_explicit_record_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); prefix = root/'python'; site = prefix/'lib/python3.12/site-packages'
            package = site/'magic'; dist = site/'python_magic-0.4.27.dist-info'
            package.mkdir(parents=True); dist.mkdir()
            sources = {'magic/loader.py': b'# original inert loader\n', 'magic/compat.py': b'# inert compat\n',
                       'magic/__init__.py': b'# inert init\n', dist.name+'/METADATA': b'Name: python-magic\nVersion: 0.4.27\n'}
            for name, data in sources.items(): (site/name).write_bytes(data)
            (site/'unrelated').mkdir(); (site/'unrelated/native-payload').write_bytes(b'unrelated bytes retained')
            rows = []
            for name, data in sources.items():
                value = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
                rows.append([name, 'sha256='+value, str(len(data))])
            rows.append([dist.name+'/RECORD', '', ''])
            with (dist/'RECORD').open('w', newline='') as f: csv.writer(f).writerows(rows)
            native_root = root/'native'; (native_root/'bin').mkdir(parents=True); (native_root/'lib').mkdir()
            (native_root/'share/misc').mkdir(parents=True)
            (native_root/'bin/file').write_bytes(b'full native helper bytes never run')
            (native_root/'lib/libmagic.1.dylib').write_bytes(b'inert native payload')
            (native_root/'lib/libmagic.dylib').symlink_to('libmagic.1.dylib')
            (native_root/'share/misc/magic.mgc').write_bytes(b'inert database')
            helpers = root/'helpers'; helpers.mkdir()
            (helpers/'bundled_magic_loader.py').write_bytes((HERE/'bundled_magic_loader.py').read_bytes())
            (helpers/'python-magic-original-members.json').write_text(json.dumps({'wheel_sha256': integration.WHEEL_SHA,
                'members': {name: {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)} for name, data in sources.items()}}))
            result = integration.integrate(prefix, native_root, helpers, inventory=assembly.inventory_tree,
                expected_native_manifest=assembly.inventory_tree(native_root))
            self.assertTrue(result['complete_native_install_preserved'])
            self.assertEqual((site/'unrelated/native-payload').read_bytes(), b'unrelated bytes retained')
            self.assertEqual(assembly.inventory_tree(native_root), assembly.inventory_tree(prefix/integration.NATIVE_RELATIVE))
            provenance = json.loads((dist/'deepdesk-overlay.json').read_text())
            self.assertEqual(set(provenance['modified_installed_sources']), {'magic/loader.py'})
            self.assertEqual(provenance['removed_payloads'], [])
            for name, sha, size in csv.reader(io.StringIO((dist/'RECORD').read_text())):
                if name.endswith('/RECORD'): self.assertEqual([sha, size], ['', '']); continue
                data = (site/name).read_bytes()
                self.assertEqual(sha, 'sha256='+base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode())
                self.assertEqual(size, str(len(data)))
            with self.assertRaisesRegex(RuntimeError, 'already exists'):
                integration.integrate(prefix, native_root, helpers, inventory=assembly.inventory_tree,
                expected_native_manifest=assembly.inventory_tree(native_root))


if __name__ == '__main__':
    unittest.main()

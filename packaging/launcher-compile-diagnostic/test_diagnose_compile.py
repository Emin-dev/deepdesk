"""First-party stdlib diagnostic-helper tests; no macOS lane activation."""
from __future__ import annotations

import ast
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPEC = importlib.util.spec_from_file_location('diagnose_compile_candidate', HERE / 'diagnose_compile.py')
assert SPEC and SPEC.loader
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='firstparty-compile-diagnostic-test-')
        self.work = Path(self.temporary.name)
        self.source = Path('/checkout/packaging/standalone-engine-candidate/launcher.c')

    def tearDown(self):
        self.temporary.cleanup()

    def sanitized(self, message):
        return helper.sanitize_diagnostics(message.encode(), self.source, 230)

    def repository(self):
        root = self.work / 'repository'
        for relative in helper.REQUIRED_HASH_PATHS:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        workflow = root / helper.DEPLOYED_WORKFLOW
        workflow.parent.mkdir(parents=True)
        shutil.copyfile(root / helper.TEMPLATE_PATH, workflow)
        receipt = {'schema': helper.SCHEMA, 'approved_to_execute': True,
                   'sha256': {path: helper.digest(root / path) for path in helper.REQUIRED_HASH_PATHS}}
        return root, receipt

    def test_corrected_launcher_differs_only_by_the_reviewed_three_macro_lines(self):
        source = (ROOT / 'packaging/standalone-engine-candidate/launcher.c').read_bytes()
        addition = (b'#if defined(__APPLE__) && !defined(_DARWIN_C_SOURCE)\n'
                    b'#define _DARWIN_C_SOURCE 1\n#endif\n')
        self.assertEqual(hashlib.sha256(source).hexdigest(),
                         '148b2cddcedcc8b1d23daccd29bd834b900baf5e3a4d1dc7e0d534a50cbcbe1b')
        self.assertEqual(helper.LAUNCHER_SHA256, hashlib.sha256(source).hexdigest())
        self.assertEqual(source.count(addition), 1)
        self.assertIn(b'#define _XOPEN_SOURCE 700\n' + addition + b'#include <errno.h>', source)
        original = source.replace(addition, b'', 1)
        self.assertEqual(hashlib.sha256(original).hexdigest(),
                         'b23fc0b7c2d5a3bf0ed88a99521128518d770f2878024da50a867725d499738a')
        self.assertIn(b'open(path, O_RDONLY | O_NOFOLLOW)', source)

    def test_exact_original_command_with_dummy_protected_roots(self):
        profile = Path('/checkout/packaging/engine-ci/runtime-offline.sb')
        self.assertEqual(helper.compile_command(self.source, profile, self.work), [
            '/usr/bin/sandbox-exec', '-D', 'WORK_DIR=' + str(self.work),
            '-D', 'IMMUTABLE_DIR=' + str(self.work / 'immutable'),
            '-D', 'READONLY_ENV=' + str(self.work / 'standalone-prefix/python'),
            '-f', str(profile), '/usr/bin/clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
            str(self.source), '-o', str(self.work / 'DeepdeskEngine')])

    def test_environment_exactly_matches_failed_stage_keys_and_literal_values(self):
        stage = ast.parse((ROOT / 'packaging/standalone-engine-candidate/standalone_stage.py').read_text())
        values = next(node.value for node in ast.walk(stage) if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == 'env' for target in node.targets)
                      and isinstance(node.value, ast.Dict))
        expected_keys = {key.value for key in values.keys}
        environment = helper.compile_environment(self.work)
        self.assertEqual(set(environment), expected_keys)
        for key, value in zip(values.keys, values.values):
            if isinstance(value, ast.Constant):
                self.assertEqual(environment[key.value], value.value)
        self.assertEqual(environment['HOME'], str(self.work / 'home'))
        self.assertEqual(environment['TMPDIR'], str(self.work))
        self.assertEqual(environment['LDR_DATA_DIR'], str(self.work / 'isolated-data'))

    def test_no_ambient_compiler_loader_sdk_or_secret_values_are_inherited(self):
        with mock.patch.dict(os.environ, {'SECRET': 'private-value', 'SDKROOT': '/secret/sdk',
                                         'DYLD_INSERT_LIBRARIES': '/secret/lib', 'CC': '/secret/cc'}):
            environment = helper.compile_environment(self.work)
        self.assertFalse({'SECRET', 'SDKROOT', 'DYLD_INSERT_LIBRARIES', 'CC'} & environment.keys())

    def test_expected_undeclared_nofollow_diagnostic_is_preserved_safely(self):
        result = self.sanitized(f"{self.source}:59:36: error: use of undeclared identifier 'O_NOFOLLOW'\n")
        self.assertEqual(result['records'], [{
            'phase': 'compile', 'severity': 'error', 'code': 'undeclared_identifier',
            'source': 'launcher.c', 'line': 59, 'column': 36, 'message': 'Undeclared identifier: O_NOFOLLOW'}])
        self.assertNotIn('/checkout', json.dumps(result))

    def test_known_function_type_and_header_diagnostics(self):
        examples = [
            ("unknown type name 'uint32_t'", 'unknown_type'),
            ("call to undeclared function '_NSGetExecutablePath'; ISO C99 and later do not support implicit function declarations [-Werror,-Wimplicit-function-declaration]", 'undeclared_function'),
            ("'mach-o/dyld.h' file not found", 'header_missing'),
        ]
        for text, code in examples:
            with self.subTest(code=code):
                result = self.sanitized(f'{self.source}:5:1: error: {text}\n')
                self.assertEqual(result['records'][0]['code'], code)

    def test_driver_linker_and_sandbox_failures_have_no_raw_details(self):
        text = '\n'.join([
            "clang: error: unable to make temporary file: /private/secret: Operation not permitted",
            "error: unable to open output file '/Users/private-user/secret': 'Permission denied'",
            "xcrun: error: active developer path (/Users/private-user/Xcode) does not exist",
            "clang: error: linker command failed with exit code 1 (use -v to see invocation)",
            "ld: library not found for -lSECRET_TOKEN", "sandbox-exec: /private/secret failed",
        ])
        result = self.sanitized(text)
        self.assertEqual({record['phase'] for record in result['records']}, {'driver', 'link', 'sandbox'})
        self.assertEqual(len(result['records']), 6)
        encoded = json.dumps(result)
        for secret in ('private-user', '/private', 'SECRET_TOKEN', '/Users'):
            self.assertNotIn(secret, encoded)

    def test_unknown_message_quotes_and_identifier_never_pass_through(self):
        text = f"{self.source}:5:1: error: use of undeclared identifier 'PRIVATE_TOKEN'\n"
        text += f"{self.source}:6:1: error: file '/Users/private-user/credentials' had value 'secret'\n"
        result = self.sanitized(text)
        self.assertEqual([r['code'] for r in result['records']], ['unclassified', 'unclassified'])
        self.assertNotIn('PRIVATE_TOKEN', json.dumps(result))
        self.assertNotIn('private-user', json.dumps(result))
        self.assertNotIn('credentials', json.dumps(result))

    def test_unapproved_paths_header_traces_source_snippets_and_controls_are_withheld(self):
        result = self.sanitized(
            "/Users/private-user/launcher.c:5:1: error: use of undeclared identifier 'O_NOFOLLOW'\n"
            "In file included from /Users/private-user/header.h:1:\n"
            "  59 | token = secret;\n     | ^\n\x1b[31mPRIVATE_TOKEN\x1b[0m\n")
        self.assertEqual(result['records'], [])
        self.assertGreaterEqual(result['withheld_lines'], 4)
        self.assertNotIn('private-user', json.dumps(result))
        self.assertNotIn('secret', json.dumps(result))

    def test_location_bounds_and_basename_allowlist(self):
        for line, column in ((0, 1), (231, 1), (1, 0), (1, 2049)):
            result = self.sanitized(f"{self.source}:{line}:{column}: error: use of undeclared identifier 'O_NOFOLLOW'\n")
            self.assertEqual(result['records'], [])
        with self.assertRaises(ValueError):
            helper.sanitize_diagnostics(b'', Path('/checkout/secrets.c'), 20)

    def test_public_diagnostic_record_cap(self):
        text = (f"{self.source}:59:1: error: use of undeclared identifier 'O_NOFOLLOW'\n") * 50
        result = self.sanitized(text)
        self.assertEqual(len(result['records']), helper.MAX_RECORDS)
        self.assertEqual(result['withheld_lines'], 50 - helper.MAX_RECORDS)

    def test_nonzero_process_capture_is_private_and_keeps_exit_code(self):
        public = io.StringIO()
        with contextlib.redirect_stdout(public):
            result = helper.capture_bounded([sys.executable, '-I', '-c',
                "import sys; print('private stdout'); print('private stderr', file=sys.stderr); sys.exit(7)"],
                env={}, work=self.work, timeout=3)
        self.assertEqual(result, ('completed', 7, b'private stdout\n', b'private stderr\n'))
        self.assertEqual(public.getvalue(), '')

    def test_output_cap_kills_child_and_bounds_captured_memory(self):
        status, code, out, err = helper.capture_bounded([sys.executable, '-I', '-c',
            "import sys; sys.stdout.write('x' * 10000); sys.stdout.flush()"],
            env={}, work=self.work, timeout=3, output_limit=100)
        self.assertEqual(status, 'output_limit')
        self.assertLessEqual(len(out) + len(err), 100)

    def test_timeout_kills_owned_process_group(self):
        status, _, _, _ = helper.capture_bounded([sys.executable, '-I', '-c',
            "import time; time.sleep(30)"], env={}, work=self.work, timeout=0.1)
        self.assertEqual(status, 'timeout')

    def test_timeout_prevents_descendant_from_writing_later(self):
        child_code = "import time; from pathlib import Path; time.sleep(0.4); Path('orphan-marker').write_text('bad')"
        parent_code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-I','-c'," + repr(child_code) + "]); time.sleep(30)"
        status, _, _, _ = helper.capture_bounded([sys.executable, '-I', '-c', parent_code],
                                                env={}, work=self.work, timeout=0.1)
        self.assertEqual(status, 'timeout')
        time.sleep(0.5)
        self.assertFalse((self.work / 'orphan-marker').exists())

    def test_disk_limit_checked_after_stdout_eof(self):
        status, code, out, err = helper.capture_bounded([sys.executable, '-I', '-c',
            "from pathlib import Path; Path('oversize').write_bytes(b'x' * 1000)"],
            env={}, work=self.work, timeout=3, disk_limit=10)
        self.assertEqual(status, 'work_limit')

    def test_spawn_failure_contains_no_raw_exception(self):
        result = helper.capture_bounded(['/private/secret/nonexistent'], env={}, work=self.work, timeout=1)
        self.assertEqual(result, ('start_failed', None, b'', b''))

    def test_exact_receipt_and_workflow_pass_without_execution(self):
        root, receipt = self.repository()
        helper.validate_receipt(receipt, root)

    def test_unapproved_and_nonboolean_approval_fail(self):
        root, receipt = self.repository()
        for value in (False, 1, 'true', None):
            rejected = copy.deepcopy(receipt)
            rejected['approved_to_execute'] = value
            with self.assertRaisesRegex(ValueError, 'not approved'):
                helper.validate_receipt(rejected, root)

    def test_missing_extra_and_modified_hash_records_fail(self):
        root, receipt = self.repository()
        for mutation in ('missing', 'extra', 'changed'):
            rejected = copy.deepcopy(receipt)
            if mutation == 'missing':
                rejected['sha256'].pop(next(iter(rejected['sha256'])))
            elif mutation == 'extra':
                rejected['sha256']['unknown.py'] = '0' * 64
            else:
                rejected['sha256']['packaging/launcher-compile-diagnostic/README.md'] = '0' * 64
            with self.assertRaises(ValueError):
                helper.validate_receipt(rejected, root)

    def test_deployed_workflow_must_match_reviewed_template(self):
        root, receipt = self.repository()
        (root / helper.DEPLOYED_WORKFLOW).write_text('unreviewed workflow')
        with self.assertRaisesRegex(ValueError, 'workflow differs'):
            helper.validate_receipt(receipt, root)

    def test_receipt_cannot_replace_original_launcher_hash(self):
        root, receipt = self.repository()
        path = 'packaging/standalone-engine-candidate/launcher.c'
        (root / path).write_text('changed source')
        receipt['sha256'][path] = helper.digest(root / path)
        with self.assertRaisesRegex(ValueError, 'reviewed launcher differs'):
            helper.validate_receipt(receipt, root)

    def test_receipt_cannot_replace_original_profile_hash(self):
        root, receipt = self.repository()
        path = 'packaging/engine-ci/runtime-offline.sb'
        (root / path).write_text('(allow default)')
        receipt['sha256'][path] = helper.digest(root / path)
        with self.assertRaisesRegex(ValueError, 'original deny profile differs'):
            helper.validate_receipt(receipt, root)

    def test_reviewed_file_symlinks_are_rejected(self):
        root, receipt = self.repository()
        target = root / 'packaging/launcher-compile-diagnostic/README.md'
        target.unlink()
        target.symlink_to(HERE / 'README.md')
        with self.assertRaises(ValueError):
            helper.validate_receipt(receipt, root)

    def test_mocked_complete_diagnostic_cleans_output_and_never_executes_it(self):
        root, receipt = self.repository()
        receipt_path = root / 'packaging/launcher-compile-diagnostic/review-receipt.json'
        receipt_path.write_text(json.dumps(receipt))
        captured_work = []
        original_is_file = Path.is_file

        def tools_exist(path):
            if str(path) in ('/usr/bin/clang', '/usr/bin/sandbox-exec'):
                return True
            return original_is_file(path)

        def fake_compiler(command, *, env, work, timeout):
            captured_work.append(work)
            self.assertLessEqual(timeout, 90)
            (work / 'DeepdeskEngine').write_text('synthetic unexecuted compiler output')
            source = root / 'packaging/standalone-engine-candidate/launcher.c'
            errors = f"{source}:59:36: error: use of undeclared identifier 'O_NOFOLLOW'\n".encode()
            return 'completed', 1, b'', errors

        with mock.patch.object(helper.sys, 'platform', 'darwin'), \
             mock.patch.object(helper.platform, 'machine', return_value='arm64'), \
             mock.patch.object(helper, 'capture_bounded', side_effect=fake_compiler), \
             mock.patch.object(Path, 'is_file', tools_exist), \
             mock.patch.dict(os.environ, {'RUNNER_TEMP': str(self.work)}), \
             mock.patch.object(helper.subprocess, 'Popen') as process:
            result = helper.diagnose(root, receipt_path)
        self.assertEqual(result['compiler_exit_code'], 1)
        self.assertEqual(result['diagnostics']['records'][0]['code'], 'undeclared_identifier')
        self.assertFalse(result['generated_executable_executed'])
        self.assertFalse(result['runtime_lane_ready'])
        self.assertTrue(result['compiled_output_present'])
        self.assertFalse(captured_work[0].exists())
        process.assert_not_called()
        self.assertNotIn(str(self.work), json.dumps(result))

    def test_non_macos_host_cannot_start_diagnostic(self):
        with mock.patch.object(helper.sys, 'platform', 'linux'), mock.patch.object(helper.subprocess, 'Popen') as process:
            with self.assertRaisesRegex(ValueError, 'arm64 macOS'):
                helper.diagnose(self.work, self.work / 'receipt.json')
            process.assert_not_called()


if __name__ == '__main__':
    unittest.main()

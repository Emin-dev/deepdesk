"""Pure lock mutations and mocked main boundary. No download/native execution."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('lock_test_stage', HERE / 'stage.py')
stage = importlib.util.module_from_spec(spec); spec.loader.exec_module(stage)
LOCK = json.loads((HERE / 'input-lock.json').read_text())
RECEIPT = json.loads((HERE / 'review-receipt.json').read_text())
APPROVALS = ('independent_review_passed', 'execution_approved', 'temporary_linker_adhoc_signing_approved',
             'install_name_linker_assignment_approved', 'new_libffi_provider_approved',
             'runner_free_eligibility_verified', 'source_make_execution_approved',
             'source_libiconv_provider_approved', 'phase_libcharset_staging_approved',
             'corrected_libintl_provider_approved')

class InputBoundaryReached(BaseException):
    pass

class LockContractTests(unittest.TestCase):
    def changed(self, mutate):
        lock = copy.deepcopy(LOCK); mutate(lock); return lock

    def test_exact_scope_count_hashes_and_summed_totals_pass(self):
        self.assertIs(stage.validate_input_lock(LOCK), LOCK)
        self.assertEqual(LOCK['scope'], stage.SCOPE)
        self.assertEqual(RECEIPT['scope'], stage.SCOPE)
        self.assertEqual(len(LOCK['inputs']), 10)
        self.assertEqual(sum(p['size'] for p in LOCK['inputs']), 77580242)
        self.assertEqual(sum(p['expanded_bytes'] for p in LOCK['inputs']), 426518901)

    def test_wrong_or_missing_scope_is_rejected_offline(self):
        for scope in ('glib-runtime-iconv-correction-v3', 'glib-runtime-symbol-parser-v4', '', None, True):
            with self.assertRaises(stage.foundation.LaneError):
                stage.validate_input_lock(self.changed(lambda d: d.update(scope=scope)))
        lock = copy.deepcopy(LOCK); del lock['scope']
        with self.assertRaises(stage.foundation.LaneError): stage.validate_input_lock(lock)

    def test_schema_and_source_permission_types_are_strict(self):
        for field, value in (('schema', True), ('schema', '1'), ('schema', 2),
                             ('source_changes_allowed', True), ('source_changes_allowed', 0),
                             ('source_changes_allowed', None)):
            with self.assertRaises(stage.foundation.LaneError):
                stage.validate_input_lock(self.changed(lambda d: d.update({field: value})))

    def test_input_count_duplicate_unknown_and_changed_hash_rejected(self):
        mutations = [lambda d: d['inputs'].pop(), lambda d: d['inputs'].append(copy.deepcopy(d['inputs'][0])),
            lambda d: d['inputs'].__setitem__(1, copy.deepcopy(d['inputs'][0])),
            lambda d: d['inputs'][0].update(id='unreviewed'),
            lambda d: d['inputs'][0].update(sha256='0' * 64),
            lambda d: d['inputs'][0].update(id=[]), lambda d: d['inputs'][0].update(sha256=None)]
        for mutate in mutations:
            with self.assertRaises(stage.foundation.LaneError): stage.validate_input_lock(self.changed(mutate))

    def test_declared_totals_and_pin_sums_both_enforced(self):
        for field in ('total_compressed_bytes', 'total_expanded_bytes'):
            for value in (0, LOCK[field] + 1, str(LOCK[field]), True):
                with self.assertRaises(stage.foundation.LaneError):
                    stage.validate_input_lock(self.changed(lambda d: d.update({field: value})))
        for field in ('size', 'expanded_bytes'):
            for value in (True, -1, '1', LOCK['inputs'][0][field] + 1):
                with self.assertRaises(stage.foundation.LaneError):
                    stage.validate_input_lock(self.changed(lambda d: d['inputs'][0].update({field: value})))

    def test_invalid_root_input_container_and_pin_types_rejected(self):
        for lock in (None, [], 'invalid'):
            with self.assertRaises(stage.foundation.LaneError): stage.validate_input_lock(lock)
        for value in (None, {}, tuple(LOCK['inputs']), [None] * 10):
            with self.assertRaises(stage.foundation.LaneError):
                stage.validate_input_lock(self.changed(lambda d: d.update(inputs=value)))

    def test_static_validation_uses_same_lock_validator_and_rejects_wrong_scope(self):
        with mock.patch.object(stage, 'validate_input_lock', wraps=stage.validate_input_lock) as shared:
            self.assertEqual(stage.validate(HERE.parents[1], RECEIPT, False), LOCK)
            shared.assert_called_once_with(LOCK)
        for wrong in ('glib-runtime-iconv-correction-v3', 'glib-runtime-symbol-parser-v4'):
            with mock.patch.object(stage, 'bounded_json', return_value=self.changed(lambda d: d.update(scope=wrong))):
                with self.assertRaises(stage.foundation.LaneError): stage.validate(HERE.parents[1], RECEIPT, False)

    def main_until_input(self, lock=LOCK):
        # Real candidate validation and main control flow; only environmental facts,
        # signal effects and the first input operation are replaced with inert doubles.
        original_read = stage.bounded_json
        original_is_file = Path.is_file
        approved = copy.deepcopy(RECEIPT)
        for flag in APPROVALS: approved[flag] = True
        def read(path, *args, **kwargs):
            if path == HERE / 'review-receipt.json': return approved
            if path == HERE / 'input-lock.json': return copy.deepcopy(lock)
            return original_read(path, *args, **kwargs)
        def is_file(path):
            return True if path == Path('/usr/bin/sandbox-exec') else original_is_file(path)
        with tempfile.TemporaryDirectory(prefix='inert-valid-host-') as td, contextlib.ExitStack() as stack:
            temp = Path(td).resolve(); event = temp / 'event.json'
            event.write_text(json.dumps({'repository': {'private': False, 'full_name': 'Emin-dev/deepdesk'}}))
            env = {'GITHUB_REPOSITORY': 'Emin-dev/deepdesk', 'GITHUB_REF': 'refs/heads/' + stage.BRANCH,
                   'GITHUB_EVENT_NAME': 'push', 'RUNNER_ENVIRONMENT': 'github-hosted',
                   'RUNNER_OS': 'macOS', 'RUNNER_ARCH': 'ARM64', 'GITHUB_EVENT_PATH': str(event),
                   'RUNNER_TEMP': str(temp)}
            for patcher in (mock.patch.object(stage.sys, 'argv', ['stage.py', '--repository', str(HERE.parents[1])]),
                    mock.patch.object(stage.sys, 'executable', '/usr/bin/python3'),
                    mock.patch.object(stage.platform, 'system', return_value='Darwin'),
                    mock.patch.object(stage.platform, 'machine', return_value='arm64'),
                    mock.patch.dict(stage.os.environ, env, clear=True), mock.patch.object(Path, 'is_file', is_file),
                    mock.patch.object(stage, 'bounded_json', side_effect=read),
                    mock.patch.object(stage.shutil, 'disk_usage', return_value=types.SimpleNamespace(free=8 * 1024**3)),
                    mock.patch.object(stage.signal, 'signal'), mock.patch.object(stage.signal, 'setitimer')):
                stack.enter_context(patcher)
            shared = stack.enter_context(mock.patch.object(stage, 'validate_input_lock', wraps=stage.validate_input_lock))
            boundary = stack.enter_context(mock.patch.object(stage.foundation, 'read_input', side_effect=InputBoundaryReached))
            execution = stack.enter_context(mock.patch.object(stage.Lane, 'execute', side_effect=AssertionError('unexpected_payload_execution')))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                try: result = stage.main()
                except InputBoundaryReached: result = 'input_boundary_reached'
            execution.assert_not_called()
            return result, boundary.call_args_list, shared.call_count, output.getvalue()

    def test_mocked_valid_host_main_reaches_first_input_without_downloading(self):
        result, calls, validations, output = self.main_until_input()
        self.assertEqual(result, 'input_boundary_reached')
        self.assertEqual(validations, 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args[2], LOCK['inputs'][0])
        self.assertEqual(output, '')

    def test_mocked_valid_host_main_wrong_scope_stops_before_input(self):
        wrong = self.changed(lambda d: d.update(scope='glib-runtime-symbol-parser-v4'))
        result, calls, validations, output = self.main_until_input(wrong)
        self.assertEqual(result, 1)
        self.assertEqual(validations, 1)
        self.assertEqual(calls, [])
        self.assertEqual(json.loads(output)['phase'], 'receipt-validation')
        self.assertEqual(json.loads(output)['status'], 'failed')

if __name__ == '__main__':
    unittest.main()

"""Portable stdlib/stub tests. No upstream package or downloaded dependency runs."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('managed_policy_contract', HERE / 'managed_policy_checks.py')
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)


def passed():
    return {'schema': 3, 'kind': contract.KIND, 'status': 'passed', 'checks': list(contract.CHECKS),
            'failed_check': 'none', 'error_class': 'none', 'forbidden_operation_attempted': True,
            'expected_blocked_probe_count': 1, 'unexpected_operation_attempted': False,
            'blocked_operations': [dict(contract.EXPECTED_BLOCKED_PROBE)],
            **dict.fromkeys(contract.FALSE_FIELDS, False)}


class SchemaTests(unittest.TestCase):
    def test_success_requires_exact_complete_contract(self):
        self.assertEqual(contract.validate(passed()), passed())
        for key, value in [('schema', True), ('schema', 2), ('kind', 'not-policy'), ('status', []),
                           ('error_class', 'private-error-message'), ('checks', list(reversed(contract.CHECKS))),
                           ('checks', list(contract.CHECKS[:-1])), ('model_loaded', True),
                           ('forbidden_operation_attempted', False), ('failed_check', 'arbitrary'),
                           ('expected_blocked_probe_count', True), ('expected_blocked_probe_count', -1),
                           ('expected_blocked_probe_count', 0), ('expected_blocked_probe_count', 2),
                           ('expected_blocked_probe_count', 3), ('unexpected_operation_attempted', True),
                           ('unexpected_operation_attempted', 0), ('blocked_operations', [])]:
            with self.subTest(key=key, value=value), self.assertRaises(RuntimeError):
                contract.validate({**passed(), key: value})
        with self.assertRaises(RuntimeError):
            contract.validate({**passed(), 'raw_exception': 'must never escape'})

    def test_raw_report_bounds_duplicate_keys_and_invalid_json(self):
        self.assertEqual(contract.parse_report(json.dumps(passed()).encode()), passed())
        for raw in (b' ' * 2049, b'private raw text', b'{"schema":1,"schema":1}', b'\xff'):
            with self.subTest(raw=raw[:20]), self.assertRaises(RuntimeError):
                contract.parse_report(raw)

    def test_native_and_python_stdout_are_private_from_final_json(self):
        # First-party helper and stub exercise only. No upstream/dependency import.
        script = """
import importlib.util,os,sys
spec=importlib.util.spec_from_file_location('fixture',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
def exercise(*args):
    print('synthetic-private-python-output')
    os.write(1,b'synthetic-private-native-output\\n')
    os.write(2,b'synthetic-private-error-output\\n')
    return {'schema':3,'kind':module.KIND,'status':'passed','checks':list(module.CHECKS),
            'failed_check':'none','error_class':'none','forbidden_operation_attempted':True,
            'expected_blocked_probe_count':1,'unexpected_operation_attempted':False,
            'blocked_operations':[dict(module.EXPECTED_BLOCKED_PROBE)],
            **dict.fromkeys(module.FALSE_FIELDS,False)}
module.exercise=exercise
sys.argv=['fixture','--wrapper','/synthetic','--wrapper-sha256','0'*64,
          '--runtime-prefix','/synthetic','--fixture-root','/synthetic']
module.main()
os.write(1,b'synthetic-private-late-output\\n')
"""
        process = subprocess.run([sys.executable, '-I', '-B', '-c', script,
                                  str(HERE / 'managed_policy_checks.py')],
                                 capture_output=True, timeout=10, check=True)
        self.assertEqual(contract.parse_report(process.stdout), passed())
        for token in (b'python', b'native', b'error', b'late'):
            self.assertIn(b'synthetic-private-' + token + b'-output', process.stderr)
        self.assertNotIn(b'synthetic-private', process.stdout)

    def test_installed_policy_pin_matches_reviewed_source_manifest(self):
        manifest = json.loads((ROOT / 'research/engine-ci/source-build-manifest.json').read_text())
        policy = next(item for item in manifest['files'] if item['path'] == 'src/local_deep_research/security/egress/policy.py')
        self.assertEqual(contract.POLICY_SHA256, policy['sha256'])

    def test_diagnostic_wrapper_inventory_matches_current_files(self):
        inventory = json.loads((HERE / 'asgi-diagnostic-source-allowlist.json').read_text())
        for relative, expected in inventory['managed_wrapper_sha256'].items():
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected)

    def test_failure_only_accepts_next_fixed_checkpoint_and_error_enum(self):
        for index, checkpoint in enumerate(contract.CHECKS):
            result = {**passed(), 'status': 'failed', 'checks': list(contract.CHECKS[:index]),
                      'failed_check': checkpoint, 'error_class': 'AssertionError'}
            self.assertEqual(contract.validate(result), result)
            with self.assertRaises(RuntimeError):
                contract.validate({**result, 'failed_check': 'private-path-or-endpoint'})

    def test_audit_guard_blocks_operations_without_performing_them(self):
        for event in ('socket.__new__', 'socket.bind', 'socket.connect', 'socket.getaddrinfo',
                      'subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.exec', 'os.fork', 'os.forkpty'):
            state = {'forbidden': False}
            with self.subTest(event=event), self.assertRaises(RuntimeError):
                contract.operation_guard(state)(event, ('not-transmitted',))
            self.assertTrue(state['forbidden'])
        state = {'forbidden': False}
        contract.operation_guard(state)('import', ('standard-import',))
        self.assertFalse(state['forbidden'])

    def test_operation_diagnostics_are_fixed_bounded_and_secret_free(self):
        state = {'forbidden': False, 'completed': [contract.CHECKS[0]]}
        guard = contract.operation_guard(state)
        for event in ('socket.__new__', 'socket.gethostname', 'socket.private-secret-event',
                      'subprocess.Popen', 'socket.connect'):
            with self.assertRaises(RuntimeError):
                guard(event, ('private-secret-host-and-credential',))
        operations = state['blocked_operations']
        self.assertEqual(len(operations), 4)
        self.assertEqual([item['event'] for item in operations],
                         ['socket-create', 'hostname-read', 'socket-other', 'process-spawn'])
        self.assertTrue(all(item['check'] == 'installed-wrapper-identity' for item in operations))
        self.assertTrue(all(item['source'] == 'unknown' and item['line'] == 0 for item in operations))
        result = {**passed(), 'status': 'failed', 'checks': list(contract.CHECKS[:-1]),
                  'failed_check': contract.CHECKS[-1], 'error_class': 'AssertionError',
                  'forbidden_operation_attempted': True, 'blocked_operations': operations,
                  'expected_blocked_probe_count': 0, 'unexpected_operation_attempted': True}
        raw = json.dumps(result).encode()
        self.assertLessEqual(len(raw), 2048)
        self.assertNotIn(b'private-secret', raw)
        self.assertEqual(contract.parse_report(raw), result)
        for mutation in ({'event': 'private-secret'}, {'check': 'private-secret'},
                         {'source': '/private/secret.py'}, {'line': True}, {'line': 1}):
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                contract.validate({**result, 'blocked_operations': [{**operations[0], **mutation}]})
        for invalid in ([], operations + [operations[0]], 'private-secret'):
            with self.subTest(invalid=invalid), self.assertRaises(RuntimeError):
                contract.validate({**result, 'blocked_operations': invalid})

    def test_origin_requires_exact_filename_and_hash_not_basename(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = "def probe(callback, prefix):\n    return callback(prefix)\n"
            path = root / 'lib/python3.12/probe.py'
            path.parent.mkdir(parents=True)
            path.write_text(source)
            namespace = {}
            exec(compile(source, str(path), 'exec'), namespace)
            mapping = {'stdlib-platform': ('lib/python3.12/probe.py', hashlib.sha256(source.encode()).hexdigest())}
            with patch.dict(contract.SOURCE_IDS, mapping, clear=True):
                self.assertEqual(namespace['probe'](contract.blocked_origin, root), ('stdlib-platform', 2))
                path.write_text(source + '# changed\n')
                self.assertEqual(namespace['probe'](contract.blocked_origin, root), ('unknown', 0))
                exec(compile(source, '/private/credential/probe.py', 'exec'), namespace)
                self.assertEqual(namespace['probe'](contract.blocked_origin, root), ('unknown', 0))

    def test_diagnostic_source_hashes_match_pinned_inventory_and_policy(self):
        sources = contract.SOURCE_IDS
        inventory = json.loads((HERE / 'asgi-diagnostic-source-allowlist.json').read_text())
        for label in ('stdlib-platform', 'stdlib-subprocess'):
            relative, expected = sources[label]
            self.assertEqual(inventory['files']['stdlib'][relative.removeprefix('lib/python3.12/')], expected)
        self.assertEqual(sources['upstream-egress-policy'][1], contract.POLICY_SHA256)


class ProbeAccountingTests(unittest.TestCase):
    def new_state(self):
        return {'forbidden': False, 'expected_blocked_probe_count': 0,
                'unexpected_operation_attempted': False, 'blocked_operations': [],
                'completed': [contract.CHECKS[0]], 'prefix': None}

    def attempt(self, state, event='socket.__new__', origin=('urllib3-ipv6-probe', 126)):
        with patch.object(contract, 'blocked_origin', return_value=origin), \
             self.assertRaisesRegex(RuntimeError, '^Forbidden managed policy fixture operation$'):
            contract.operation_guard(state)(event, ('private-not-retained',))

    def failed(self, state):
        return {**passed(), 'status': 'failed', 'checks': list(contract.CHECKS[:-1]),
                'failed_check': contract.CHECKS[-1], 'error_class': 'AssertionError',
                'forbidden_operation_attempted': state['forbidden'],
                'expected_blocked_probe_count': state['expected_blocked_probe_count'],
                'unexpected_operation_attempted': state['unexpected_operation_attempted'],
                'blocked_operations': state['blocked_operations']}

    def test_expected_record_is_exact_and_every_attempt_is_still_denied(self):
        exact = {'event': 'socket-create', 'check': 'installed-wrapper-identity',
                 'source': 'urllib3-ipv6-probe', 'line': 126}
        self.assertEqual(contract.EXPECTED_BLOCKED_PROBE, exact)
        self.assertEqual(contract.CHECKS[-1], 'only-reviewed-denied-import-probe')
        state = self.new_state()
        self.attempt(state)
        self.assertEqual(state['blocked_operations'], [exact])
        self.assertIs(state['forbidden'], True)
        self.assertEqual(state['expected_blocked_probe_count'], 1)
        self.assertIs(state['unexpected_operation_attempted'], False)
        for _ in range(10):
            self.attempt(state)
        self.assertEqual(state['expected_blocked_probe_count'], 2)
        self.assertIs(state['unexpected_operation_attempted'], True)
        self.assertEqual(state['blocked_operations'], [exact] * 4)
        self.assertEqual(contract.validate(self.failed(state)), self.failed(state))

    def test_all_other_socket_dns_and_process_events_latch_unexpected(self):
        for event in (*contract.EVENTS, 'socket.unrecognized'):
            if event == 'socket.__new__':
                continue
            with self.subTest(event=event):
                state = self.new_state()
                self.attempt(state, event)
                self.assertIs(state['unexpected_operation_attempted'], True)
                self.assertEqual(state['expected_blocked_probe_count'], 0)
                self.attempt(state)
                self.assertIs(state['unexpected_operation_attempted'], True)
                self.assertEqual(state['expected_blocked_probe_count'], 1)
                self.assertEqual(contract.validate(self.failed(state)), self.failed(state))

    def test_unknown_source_wrong_line_phase_and_provider_are_fatal(self):
        for origin in (('unknown', 0), ('urllib3-ipv6-probe', 125),
                       ('urllib3-ipv6-probe', 127), ('langchain-socket-options', 126)):
            with self.subTest(origin=origin):
                state = self.new_state()
                self.attempt(state, origin=origin)
                self.assertEqual(state['expected_blocked_probe_count'], 0)
                self.assertIs(state['unexpected_operation_attempted'], True)
                self.assertEqual(contract.validate(self.failed(state)), self.failed(state))
        for completed in ([], list(contract.CHECKS[:2]), list(contract.CHECKS[:-1])):
            with self.subTest(completed=completed):
                state = self.new_state()
                state['completed'] = completed
                self.attempt(state)
                self.assertEqual(state['expected_blocked_probe_count'], 0)
                self.assertIs(state['unexpected_operation_attempted'], True)
        state = self.new_state()
        contract.record_blocked(state, 'provider-factory')
        self.assertEqual(state['blocked_operations'][0]['source'], 'fixture')
        self.assertEqual(state['expected_blocked_probe_count'], 0)
        self.assertIs(state['unexpected_operation_attempted'], True)

    def test_accounting_continues_after_four_display_records(self):
        state = self.new_state()
        for _ in range(4):
            self.attempt(state, 'socket.getaddrinfo', ('unknown', 0))
        visible = list(state['blocked_operations'])
        self.assertEqual(state['expected_blocked_probe_count'], 0)
        self.attempt(state)
        self.assertEqual(state['expected_blocked_probe_count'], 1)
        self.attempt(state)
        self.assertEqual(state['expected_blocked_probe_count'], 2)
        for _ in range(10):
            self.attempt(state)
        self.assertEqual(state['expected_blocked_probe_count'], 2)
        self.assertIs(state['unexpected_operation_attempted'], True)
        self.assertEqual(state['blocked_operations'], visible)
        self.assertEqual(contract.parse_report(json.dumps(self.failed(state)).encode()), self.failed(state))
        # Exercise the latch independently of earlier display records.
        state['unexpected_operation_attempted'] = False
        self.attempt(state, 'socket.connect', ('unknown', 0))
        self.assertIs(state['unexpected_operation_attempted'], True)
        self.assertEqual(state['blocked_operations'], visible)

    def test_malformed_accounting_receipts_are_rejected(self):
        empty = self.new_state()
        zero = self.failed(empty)
        self.assertEqual(contract.validate(zero), zero)
        for key in ('expected_blocked_probe_count', 'unexpected_operation_attempted'):
            report = dict(passed())
            del report[key]
            with self.subTest(missing=key), self.assertRaises(RuntimeError):
                contract.validate(report)
        for count in (True, False, -1, 3, 1.0, '1', None, [], {}):
            with self.subTest(count=count), self.assertRaises(RuntimeError):
                contract.validate({**passed(), 'expected_blocked_probe_count': count})
        for value in (0, 1, 'false', None, [], {}):
            with self.subTest(unexpected=value), self.assertRaises(RuntimeError):
                contract.validate({**passed(), 'unexpected_operation_attempted': value})
        state = self.new_state()
        self.attempt(state)
        self.attempt(state)
        repeated = self.failed(state)
        for report in ({**zero, 'expected_blocked_probe_count': 1},
                       {**zero, 'unexpected_operation_attempted': True},
                       {**repeated, 'expected_blocked_probe_count': 1},
                       {**repeated, 'unexpected_operation_attempted': False},
                       {**passed(), 'status': 'failed'},
                       {**passed(), 'blocked_operations': [dict(contract.EXPECTED_BLOCKED_PROBE),
                                                          dict(contract.EXPECTED_BLOCKED_PROBE)]}):
            with self.subTest(report=report), self.assertRaises(RuntimeError):
                contract.validate(report)
        for field in ('expected_blocked_probe_count', 'unexpected_operation_attempted'):
            raw = json.dumps(passed()).replace('"' + field + '":', '"' + field + '": 0, "' + field + '":', 1)
            with self.subTest(duplicate=field), self.assertRaises(RuntimeError):
                contract.parse_report(raw.encode())


@contextmanager
def stub_runtime(prefix, mutation=None):
    package = prefix / 'lib/python3.12/site-packages/local_deep_research'
    for relative in ('llm/providers/implementations', 'web/templates', 'web/static', 'defaults', 'security/egress'):
        (package / relative).mkdir(parents=True, exist_ok=True)
    (package / '__init__.py').write_text('# Inert first-party fixture, never imported from disk.\n')
    (package / 'llm/providers/implementations/stub.py').write_text('# Inert fixture.\n')
    (package / 'web/fastapi_app.py').write_text('# DEEPDESK_MANAGED_RUNTIME\n')
    (package / 'defaults/settings_deepdesk_ddg.json').write_text(json.dumps({
        'search.engine.web.ddg.requires_api_key': {'value': False}}))
    policy_file = package / 'security/egress/policy.py'
    policy_file.write_text('# Inert policy fixture; no upstream source executes.\n')
    calls = []
    cloud = object()
    registry = {'openai': cloud}
    class Provider:
        @classmethod
        def create_llm(cls, *args, **kwargs):
            raise AssertionError('Never call a provider factory')
    def setting(key, default=None, settings_snapshot=None):
        return (settings_snapshot or {}).get(key, default)
    def register(name, function):
        registry[name] = function
    def get(name):
        if mutation == 'registry-bypass' and name == 'openai_endpoint':
            return lambda *args, **kwargs: None
        return registry.get(name)
    def context(snapshot, primary_engine, *, allow_dns):
        calls.append(('context', dict(snapshot), primary_engine, allow_dns))
        return types.SimpleNamespace(scope=types.SimpleNamespace(value='public_only'), primary_engine=primary_engine,
            require_local_llm=mutation != 'context-local-false', require_local_embeddings=True)
    def llm(provider, ctx, *, settings_snapshot):
        calls.append(('llm', provider, dict(settings_snapshot)))
        if provider == 'openai':
            return types.SimpleNamespace(allowed=mutation == 'cloud-llm-allowed', reason='provider_cloud_only')
        unset = not settings_snapshot.get('llm.openai_endpoint.url')
        return types.SimpleNamespace(allowed=not unset, reason='provider_url_unset' if unset else 'provider_local')
    def embeddings(provider, ctx, *, settings_snapshot):
        calls.append(('embeddings', provider, dict(settings_snapshot)))
        if provider == 'sentence_transformers':
            return types.SimpleNamespace(allowed=True, reason='provider_local')
        if provider == 'synthetic_unknown':
            return types.SimpleNamespace(allowed=False, reason='provider_unknown')
        local = settings_snapshot.get('embeddings.openai.base_url') == contract.ENDPOINT
        return types.SimpleNamespace(allowed=local or mutation == 'cloud-embeddings-allowed',
                                     reason='provider_local_endpoint' if local else 'provider_cloud')
    exports = {
        'local_deep_research': {'__file__': str(package / '__init__.py')},
        'local_deep_research.config.thread_settings': {'get_setting_from_snapshot': setting},
        'local_deep_research.llm.providers.implementations.custom_openai_endpoint': {'CustomOpenAIEndpointProvider': Provider},
        'local_deep_research.llm.llm_registry': {'register_llm': register, 'get_llm_from_registry': get},
        'local_deep_research.security.egress.policy': {'__file__': str(policy_file), 'context_from_snapshot': context,
                                                     'evaluate_llm_endpoint': llm, 'evaluate_embeddings': embeddings},
    }
    modules = {}
    for name, values in exports.items():
        parts = name.split('.')
        for length in range(1, len(parts) + 1):
            key = '.'.join(parts[:length])
            if key not in modules:
                modules[key] = types.ModuleType(key)
                modules[key].__path__ = []
        modules[name].__dict__.update(values)
    modules['local_deep_research.security.egress'].policy = modules['local_deep_research.security.egress.policy']
    with patch.dict(sys.modules, modules), patch.object(contract, 'POLICY_SHA256', hashlib.sha256(policy_file.read_bytes()).hexdigest()):
        yield calls


class ExerciseTests(unittest.TestCase):
    def run_fixture(self, mutation=None, bad_hash=False, *, probe_count=1,
                    probe_event='socket.__new__', probe_line=126,
                    probe_source='exact', probe_phase='installed-wrapper-identity'):
        with tempfile.TemporaryDirectory(prefix='firstparty-policy-stub-') as temporary:
            root = Path(temporary)
            resources = root / 'DeepdeskEngine.app/Contents/Resources'
            prefix = resources / 'Python'
            prefix.mkdir(parents=True)
            wrapper = resources / 'engine_entry.py'
            shutil.copyfile(ROOT / 'packaging/standalone-engine-candidate/engine_entry.py', wrapper)
            if mutation == 'wrapper-model-guard-missing':
                text = wrapper.read_text()
                text = text.replace('        if model_name != model:\n            raise RuntimeError("Research requested a model that is not loaded")\n', '')
                wrapper.write_text(text)
            expected = hashlib.sha256(wrapper.read_bytes()).hexdigest() if not bad_hash else '0' * 64
            # Synthetic first-party source only: call the captured deny hook, never
            # construct a socket or import/execute the installed urllib3 payload.
            relative = contract.SOURCE_IDS['urllib3-ipv6-probe'][0]
            probe_path = prefix / relative
            probe_path.parent.mkdir(parents=True, exist_ok=True)
            source = '\n' * (probe_line - 2) + 'def probe(guard, event):\n    guard(event, ())\n'
            probe_path.write_text(source)
            probe_hash = hashlib.sha256(source.encode()).hexdigest()
            namespace = {}
            filename = str(probe_path) if probe_source != 'wrong-path' else '/unverified/connection.py'
            exec(compile(source, filename, 'exec'), namespace)
            if probe_source == 'wrong-hash':
                probe_hash = '0' * 64
            original_run_path = contract.runpy.run_path
            def probe():
                for _ in range(probe_count):
                    with self.assertRaisesRegex(RuntimeError, '^Forbidden managed policy fixture operation$'):
                        namespace['probe'](add_hook.call_args.args[0], probe_event)
            def run_wrapper(*args, **kwargs):
                module = original_run_path(*args, **kwargs)
                if probe_phase == 'installed-wrapper-identity':
                    probe()
                else:
                    install = module['install_managed_inference_provider']
                    def install_with_probe():
                        probe()
                        return install()
                    module['install_managed_inference_provider'] = install_with_probe
                return module
            scope = root / 'policy-scope'
            scope.mkdir()
            old_cwd = Path.cwd()
            try:
                os.chdir(scope)
                with patch.dict(os.environ, {}, clear=True), patch.object(sys, 'prefix', str(prefix)), \
                     patch.object(sys, 'addaudithook') as add_hook, stub_runtime(prefix, mutation) as calls, \
                     patch.dict(contract.SOURCE_IDS, {'urllib3-ipv6-probe': (relative, probe_hash)}), \
                     patch.object(contract.runpy, 'run_path', side_effect=run_wrapper):
                    result = contract.exercise(wrapper, expected, prefix, scope / 'fixture')
                    self.assertEqual(add_hook.call_count, 1)
                    return result, calls
            finally:
                os.chdir(old_cwd)

    def test_full_firstparty_flow_with_inert_upstream_stubs(self):
        result, calls = self.run_fixture()
        self.assertEqual(result, passed())
        context = calls[0]
        self.assertEqual(context[0], 'context')
        self.assertEqual(context[2:], ('ddg', False))
        self.assertEqual(context[1]['policy.egress_scope'], 'public_only')
        self.assertIs(context[1]['llm.require_local_endpoint'], False)
        self.assertIs(context[1]['embeddings.require_local'], False)
        self.assertEqual(len([entry for entry in calls if entry[0] == 'llm']), 3)
        self.assertEqual(len([entry for entry in calls if entry[0] == 'embeddings']), 4)


    def test_zero_or_repeated_probe_fails_final_acceptance(self):
        for count in (0, 2, 5, 20):
            with self.subTest(count=count):
                result, _ = self.run_fixture(probe_count=count)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['failed_check'], 'only-reviewed-denied-import-probe')
                self.assertEqual(result['expected_blocked_probe_count'], min(2, count))
                self.assertIs(result['forbidden_operation_attempted'], bool(count))
                self.assertIs(result['unexpected_operation_attempted'], count > 1)
                self.assertEqual(len(result['blocked_operations']), min(4, count))

    def test_unknown_wrong_phase_line_or_operation_fails_final_acceptance(self):
        for options in ({'probe_source': 'wrong-path'}, {'probe_source': 'wrong-hash'},
                        {'probe_line': 125}, {'probe_line': 127},
                        {'probe_phase': 'managed-flags-restored'},
                        {'probe_event': 'socket.getaddrinfo'}, {'probe_event': 'socket.connect'},
                        {'probe_event': 'socket.bind'}, {'probe_event': 'subprocess.Popen'}):
            with self.subTest(options=options):
                result, _ = self.run_fixture(**options)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['failed_check'], 'only-reviewed-denied-import-probe')
                self.assertEqual(result['expected_blocked_probe_count'], 0)
                self.assertIs(result['forbidden_operation_attempted'], True)
                self.assertIs(result['unexpected_operation_attempted'], True)

    def test_mismatched_wrapper_fails_before_upstream_access(self):
        result, calls = self.run_fixture(bad_hash=True)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['failed_check'], 'installed-wrapper-identity')
        self.assertEqual(calls, [])

    def test_policy_and_registry_regressions_fail_at_specific_check(self):
        for mutation, check in (
            ('context-local-false', 'public-context-overrides-false-snapshot'),
            ('cloud-llm-allowed', 'cloud-llm-denied'),
            ('cloud-embeddings-allowed', 'cloud-embeddings-denied'),
            ('registry-bypass', 'managed-registry-bound'),
        ):
            with self.subTest(mutation=mutation):
                result, _ = self.run_fixture(mutation)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['failed_check'], check)
                self.assertNotIn('raw_exception', result)
                self.assertNotIn(contract.SYNTHETIC_KEY, json.dumps(result))

    def test_factory_sentinel_prevents_construction_when_guard_regresses(self):
        result, _ = self.run_fixture('wrapper-model-guard-missing')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['failed_check'], 'wrong-model-rejected')
        self.assertTrue(result['forbidden_operation_attempted'])
        self.assertTrue(result['unexpected_operation_attempted'])
        self.assertEqual(result['expected_blocked_probe_count'], 1)
        self.assertEqual(result['blocked_operations'][-1], {
            'event': 'provider-factory', 'check': 'wrong-model-rejected', 'source': 'fixture', 'line': 0})

    def test_fixture_must_be_new_child_of_current_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            result = contract.exercise(path / 'missing', '0' * 64, path, path)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['failed_check'], 'fixture-isolation')


if __name__ == '__main__':
    unittest.main()

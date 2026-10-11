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
    return {'schema': 1, 'kind': contract.KIND, 'status': 'passed', 'checks': list(contract.CHECKS),
            'failed_check': 'none', 'error_class': 'none', 'forbidden_operation_attempted': False,
            **dict.fromkeys(contract.FALSE_FIELDS, False)}


class SchemaTests(unittest.TestCase):
    def test_success_requires_exact_complete_contract(self):
        self.assertEqual(contract.validate(passed()), passed())
        for key, value in [('schema', True), ('kind', 'not-policy'), ('status', []),
                           ('error_class', 'private-error-message'), ('checks', list(reversed(contract.CHECKS))),
                           ('checks', list(contract.CHECKS[:-1])), ('model_loaded', True),
                           ('forbidden_operation_attempted', True), ('failed_check', 'arbitrary')]:
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
    return {'schema':1,'kind':module.KIND,'status':'passed','checks':list(module.CHECKS),
            'failed_check':'none','error_class':'none','forbidden_operation_attempted':False,
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
    def run_fixture(self, mutation=None, bad_hash=False):
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
            scope = root / 'policy-scope'
            scope.mkdir()
            old_cwd = Path.cwd()
            try:
                os.chdir(scope)
                with patch.dict(os.environ, {}, clear=True), patch.object(sys, 'prefix', str(prefix)), \
                     patch.object(sys, 'addaudithook') as add_hook, stub_runtime(prefix, mutation) as calls:
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

    def test_fixture_must_be_new_child_of_current_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            result = contract.exercise(path / 'missing', '0' * 64, path, path)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['failed_check'], 'fixture-isolation')


if __name__ == '__main__':
    unittest.main()

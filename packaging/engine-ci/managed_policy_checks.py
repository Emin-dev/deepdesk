"""Installed managed-policy contract only. Never instantiate or query inference.

Run only in the separately reviewed relocated-runtime lane, under the existing
network-deny profile and a new fixture-only write root. Module import is stdlib
only so local first-party contract tests need not execute upstream dependencies.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys

KIND = 'installed-managed-policy-contract'
CHECKS = (
    'fixture-isolation', 'installed-wrapper-identity', 'managed-flags-restored',
    'ephemeral-key-contained', 'public-context-overrides-false-snapshot',
    'cloud-llm-denied', 'unset-compatible-llm-denied', 'exact-local-llm-permitted',
    'cloud-embeddings-denied', 'unknown-embeddings-denied', 'exact-local-embeddings-permitted',
    'inprocess-embeddings-permitted', 'managed-registry-bound',
    'unmanaged-endpoint-rejected', 'wrong-model-rejected', 'no-inference-or-network-attempt',
)
ERRORS = {'none', 'AssertionError', 'RuntimeError', 'ValueError', 'TypeError', 'KeyError',
          'AttributeError', 'ImportError', 'ModuleNotFoundError', 'PermissionError',
          'FileNotFoundError', 'OSError', 'OtherException'}
FALSE_FIELDS = ('model_loaded', 'provider_queried', 'research_execution_tested',
                'real_http_tested', 'tcp_listener_tested', 'native_transport_tested')
POLICY_SHA256 = 'b2046d1402a2ceab865fc1457b199ca7894a37bf7090c05d95cdcde44542b085'
MODEL = 'mlx-community/Qwen3.8-27B-4bit'
ENDPOINT = 'http://127.0.0.1:18544/v1'
SYNTHETIC_KEY = 'a' * 64
FLAGS = ('LDR_LLM_REQUIRE_LOCAL_ENDPOINT', 'LDR_EMBEDDINGS_REQUIRE_LOCAL')


def require(value):
    if not value:
        raise AssertionError('Managed policy contract mismatch')


def validate(report):
    keys = {'schema', 'kind', 'status', 'checks', 'failed_check', 'error_class',
            'forbidden_operation_attempted', 'blocked_operations', *FALSE_FIELDS}
    if not isinstance(report, dict) or set(report) != keys:
        raise RuntimeError('Invalid managed policy schema')
    if type(report['schema']) is not int or report['schema'] != 2 or report['kind'] != KIND:
        raise RuntimeError('Invalid managed policy identity')
    if (type(report['status']) is not str or type(report['error_class']) is not str
            or report['status'] not in {'passed', 'failed'} or report['error_class'] not in ERRORS):
        raise RuntimeError('Invalid managed policy result enum')
    checks = report['checks']
    if not isinstance(checks, list) or checks != list(CHECKS[:len(checks)]) or len(checks) > len(CHECKS):
        raise RuntimeError('Invalid managed policy check sequence')
    if any(report[key] is not False for key in FALSE_FIELDS):
        raise RuntimeError('Unexpected inference or transport claim')
    if type(report['forbidden_operation_attempted']) is not bool:
        raise RuntimeError('Invalid managed policy operation flag')
    operations = report['blocked_operations']
    if not isinstance(operations, list) or len(operations) > 4:
        raise RuntimeError('Invalid managed policy operation bound')
    if bool(operations) is not report['forbidden_operation_attempted']:
        raise RuntimeError('Inconsistent managed policy operation flag')
    for operation in operations:
        if not isinstance(operation, dict) or set(operation) != {'event', 'check', 'source', 'line'}:
            raise RuntimeError('Invalid blocked operation schema')
        for key, values in (('event', set(EVENTS.values()) | {'socket-other', 'provider-factory'}),
                            ('check', set(CHECKS)), ('source', set(SOURCE_IDS) | {'unknown', 'fixture'})):
            if type(operation[key]) is not str or operation[key] not in values:
                raise RuntimeError('Invalid blocked operation enum')
        if type(operation['line']) is not int or not 0 <= operation['line'] <= 100000:
            raise RuntimeError('Invalid blocked operation line')
        if operation['source'] in {'unknown', 'fixture'} and operation['line'] != 0:
            raise RuntimeError('Unexpected unverified source line')
    if report['status'] == 'passed':
        if checks != list(CHECKS) or report['failed_check'] != 'none' or report['error_class'] != 'none' or report['forbidden_operation_attempted']:
            raise RuntimeError('Incomplete managed policy success')
    elif (len(checks) == len(CHECKS) or report['failed_check'] != CHECKS[len(checks)]
          or report['error_class'] == 'none'):
        raise RuntimeError('Invalid managed policy failure checkpoint')
    if len(json.dumps(report)) > 2048:
        raise RuntimeError('Oversized managed policy report')
    return report


def parse_report(raw):
    if not isinstance(raw, bytes) or len(raw) > 2048:
        raise RuntimeError('Invalid managed policy output bound')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise RuntimeError('Duplicate managed policy field')
            result[key] = value
        return result
    try:
        report = json.loads(raw.decode('utf-8'), object_pairs_hook=unique)
    except (UnicodeError, json.JSONDecodeError):
        raise RuntimeError('Invalid managed policy JSON') from None
    return validate(report)


# Diagnostic-only public labels. No audit arguments, paths, messages or locals
# are retained. These exact immutable source hashes identify likely call sites;
# all other frames map to unknown. A label never permits an operation.
EVENTS = {
    'socket.__new__': 'socket-create', 'socket.bind': 'socket-bind',
    'socket.connect': 'socket-connect', 'socket.getaddrinfo': 'socket-resolve',
    'socket.gethostbyname': 'socket-resolve', 'socket.gethostbyaddr': 'socket-resolve',
    'socket.getnameinfo': 'socket-resolve', 'socket.gethostname': 'hostname-read',
    'subprocess.Popen': 'process-spawn', 'os.system': 'process-system',
    'os.posix_spawn': 'process-spawn', 'os.exec': 'process-exec',
    'os.fork': 'process-fork', 'os.forkpty': 'process-fork',
}
SOURCE_IDS = {
    'urllib3-ipv6-probe': ('lib/python3.12/site-packages/urllib3/util/connection.py',
        '2633bbdb69731e5ccb5cf4e4afd65605d86c7979cc5633126f50c92d5ad74a74'),
    'langchain-socket-options': ('lib/python3.12/site-packages/langchain_openai/chat_models/_client_utils.py',
        '1486a89c1ac2609fcfb52a9070d9a3379aae2cc225bb83f8186b2015a4ec3483'),
    'upstream-egress-policy': ('lib/python3.12/site-packages/local_deep_research/security/egress/policy.py', POLICY_SHA256),
    'stdlib-platform': ('lib/python3.12/platform.py',
        'f5ff83f15c841792be42709a6710dc8d7a9f72791c1ae4cad719b1fb0abe0a05'),
    'stdlib-subprocess': ('lib/python3.12/subprocess.py',
        '85d29b2bf0249f5436838298c9a60ee93508b1102e9ac43b001f8a7e7ae8f375'),
}


def blocked_origin(prefix):
    """Only exact pinned filenames and bytes can become public source IDs."""
    if prefix is None:
        return 'unknown', 0
    frame = sys._getframe(1)
    try:
        for _ in range(32):
            if frame is None:
                break
            for label, (relative, expected) in SOURCE_IDS.items():
                path = prefix / relative
                if frame.f_code.co_filename != str(path):
                    continue
                try:
                    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
                        continue
                    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                        continue
                except OSError:
                    continue
                return label, min(max(frame.f_lineno, 0), 100000)
            frame = frame.f_back
    finally:
        del frame
    return 'unknown', 0


def record_blocked(state, event):
    state['forbidden'] = True
    operations = state.setdefault('blocked_operations', [])
    if len(operations) < 4:
        completed = state.get('completed', [])
        check = CHECKS[min(len(completed), len(CHECKS) - 1)]
        source, line = ('fixture', 0) if event == 'provider-factory' else blocked_origin(state.get('prefix'))
        operations.append({'event': event, 'check': check, 'source': source, 'line': line})


def operation_guard(state):
    """Fail before socket/DNS/process actions, even if an import regresses.

    The kernel deny profile is the primary containment. This audit hook adds a
    no-attempt assertion; it is not a replacement or a sandbox escape defense.
    """
    def guard(event, args):
        if (event.startswith('socket.') or event in {
            'subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.exec', 'os.fork', 'os.forkpty'
        }):
            record_blocked(state, EVENTS.get(event, 'socket-other'))
            raise RuntimeError('Forbidden managed policy fixture operation')
    return guard


def exercise(wrapper, wrapper_sha256, runtime_prefix, fixture_root):
    completed = []
    state = {'forbidden': False, 'factory_calls': 0, 'blocked_operations': [],
             'completed': completed, 'prefix': None}
    try:
        # A fresh child-only directory; never open real account/model data.
        require(fixture_root.is_absolute() and fixture_root.parent.resolve() == Path.cwd().resolve()
                and fixture_root.name == 'fixture' and not fixture_root.exists() and not fixture_root.is_symlink())
        fixture_root.mkdir(mode=0o700)
        for key in tuple(os.environ):
            if key.startswith(('LDR_', 'DEEPDESK_')):
                os.environ.pop(key)
        os.environ.update({
            'HOME': str(fixture_root), 'TMPDIR': str(fixture_root),
            'XDG_CACHE_HOME': str(fixture_root / 'cache'), 'HF_HOME': str(fixture_root / 'hf'),
            'LDR_DATA_DIR': str(fixture_root / 'data'), 'LDR_BOOTSTRAP_ALLOW_UNENCRYPTED': 'false',
            'LDR_APP_DEBUG': 'false', 'LDR_ENABLE_FILE_LOGGING': 'false', 'LDR_LOGURU_DIAGNOSE': 'false',
            'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'HF_HUB_DISABLE_TELEMETRY': '1',
            'DEEPDESK_MANAGED_RUNTIME': '1', 'DEEPDESK_INFERENCE_API_KEY': SYNTHETIC_KEY,
            'DEEPDESK_INFERENCE_URL': ENDPOINT, 'DEEPDESK_INFERENCE_MODEL': MODEL,
            # Start hostile: the valid managed tuple must reassert both locks.
            'LDR_LLM_REQUIRE_LOCAL_ENDPOINT': 'false', 'LDR_EMBEDDINGS_REQUIRE_LOCAL': 'false',
        })
        os.chdir(fixture_root)
        sys.dont_write_bytecode = True
        sys.addaudithook(operation_guard(state))
        completed.append(CHECKS[len(completed)])

        require(wrapper.is_file() and not wrapper.is_symlink())
        require(hashlib.sha256(wrapper.read_bytes()).hexdigest() == wrapper_sha256)
        prefix = runtime_prefix.resolve(strict=True)
        require(prefix == Path(sys.prefix).resolve() and wrapper.parent / 'Python' == prefix)
        state['prefix'] = prefix
        module = runpy.run_path(str(wrapper), run_name='managed_policy_installed_wrapper')
        installed = module['runtime_resources']()
        require(installed.resolve().is_relative_to(prefix / 'lib/python3.12/site-packages'))
        # Real pinned modules are imported only here, in the bounded CI child.
        from local_deep_research.llm.providers.implementations.custom_openai_endpoint import CustomOpenAIEndpointProvider
        from local_deep_research.llm.llm_registry import get_llm_from_registry
        from local_deep_research.security.egress import policy
        require(Path(policy.__file__).resolve().is_relative_to(installed.resolve()))
        require(hashlib.sha256(Path(policy.__file__).read_bytes()).hexdigest() == POLICY_SHA256)
        cloud_factory = get_llm_from_registry('openai')
        # Do not risk invoking original inference even if a wrapper guard is
        # accidentally removed. This sentinel is captured by the real wrapper.
        def forbidden_factory(cls, *args, **kwargs):
            state['factory_calls'] += 1
            record_blocked(state, 'provider-factory')
            raise RuntimeError('Provider creation forbidden in policy fixture')
        CustomOpenAIEndpointProvider.create_llm = classmethod(forbidden_factory)
        completed.append(CHECKS[len(completed)])

        module['install_managed_inference_provider']()
        require(all(os.environ.get(flag) == 'true' for flag in FLAGS))
        require(os.environ.get('LDR_LLM_PROVIDER') == 'openai_endpoint'
                and os.environ.get('LDR_LLM_MODEL') == MODEL
                and os.environ.get('LDR_LLM_OPENAI_ENDPOINT_URL') == ENDPOINT)
        completed.append(CHECKS[len(completed)])
        require('DEEPDESK_INFERENCE_API_KEY' not in os.environ
                and 'LDR_LLM_OPENAI_ENDPOINT_API_KEY' not in os.environ
                and SYNTHETIC_KEY not in os.environ.values())
        snapshot = {'policy.egress_scope': 'public_only', 'llm.require_local_endpoint': False,
                    'embeddings.require_local': False, 'llm.openai_endpoint.url': ENDPOINT}
        require(CustomOpenAIEndpointProvider.resolve_api_key(snapshot) == SYNTHETIC_KEY)
        require(SYNTHETIC_KEY not in json.dumps(snapshot))
        completed.append(CHECKS[len(completed)])

        ctx = policy.context_from_snapshot(snapshot, primary_engine='ddg', allow_dns=False)
        require(ctx.scope.value == 'public_only' and ctx.primary_engine == 'ddg'
                and ctx.require_local_llm is True and ctx.require_local_embeddings is True)
        require(snapshot['llm.require_local_endpoint'] is False and snapshot['embeddings.require_local'] is False)
        completed.append(CHECKS[len(completed)])
        decision = policy.evaluate_llm_endpoint('openai', ctx, settings_snapshot=snapshot)
        require(decision.allowed is False and decision.reason == 'provider_cloud_only')
        completed.append(CHECKS[len(completed)])
        unset = {key: value for key, value in snapshot.items() if key != 'llm.openai_endpoint.url'}
        decision = policy.evaluate_llm_endpoint('openai_endpoint', ctx, settings_snapshot=unset)
        require(decision.allowed is False and decision.reason == 'provider_url_unset')
        completed.append(CHECKS[len(completed)])
        decision = policy.evaluate_llm_endpoint('openai_endpoint', ctx, settings_snapshot=snapshot)
        require(decision.allowed is True and decision.reason == 'provider_local')
        completed.append(CHECKS[len(completed)])
        decision = policy.evaluate_embeddings('openai', ctx, settings_snapshot=snapshot)
        require(decision.allowed is False and decision.reason == 'provider_cloud')
        completed.append(CHECKS[len(completed)])
        decision = policy.evaluate_embeddings('synthetic_unknown', ctx, settings_snapshot=snapshot)
        require(decision.allowed is False and decision.reason == 'provider_unknown')
        completed.append(CHECKS[len(completed)])
        decision = policy.evaluate_embeddings('openai', ctx, settings_snapshot={
            **snapshot, 'embeddings.openai.base_url': ENDPOINT})
        require(decision.allowed is True and decision.reason == 'provider_local_endpoint')
        completed.append(CHECKS[len(completed)])
        decision = policy.evaluate_embeddings('sentence_transformers', ctx, settings_snapshot=snapshot)
        require(decision.allowed is True and decision.reason == 'provider_local')
        completed.append(CHECKS[len(completed)])

        factory = get_llm_from_registry('openai_endpoint')
        require(factory.__self__ is CustomOpenAIEndpointProvider
                and factory.__func__ is CustomOpenAIEndpointProvider.create_llm.__func__
                and get_llm_from_registry('openai') is cloud_factory)
        completed.append(CHECKS[len(completed)])
        remote = {**snapshot, 'llm.openai_endpoint.url': 'https://8.8.8.8/v1'}
        for call in (
            lambda: CustomOpenAIEndpointProvider.resolve_api_key(remote),
            lambda: factory(MODEL, settings_snapshot=remote),
        ):
            try:
                call()
            except RuntimeError as exc:
                require(str(exc) == 'Research requested an unmanaged inference endpoint')
            else:
                require(False)
        require(state['factory_calls'] == 0)
        completed.append(CHECKS[len(completed)])
        try:
            factory('synthetic-wrong-model', settings_snapshot=snapshot)
        except RuntimeError as exc:
            require(str(exc) == 'Research requested a model that is not loaded')
        else:
            require(False)
        require(state['factory_calls'] == 0)
        completed.append(CHECKS[len(completed)])
        require(state['forbidden'] is False and state['factory_calls'] == 0)
        completed.append(CHECKS[len(completed)])
        status, checkpoint, error = 'passed', 'none', 'none'
    except Exception as exc:
        status = 'failed'
        checkpoint = CHECKS[len(completed)]
        name = type(exc).__name__
        error = name if name in ERRORS else 'OtherException'
    return validate({'schema': 2, 'kind': KIND, 'status': status, 'checks': completed,
                     'failed_check': checkpoint, 'error_class': error,
                     'forbidden_operation_attempted': state['forbidden'],
                     'blocked_operations': state['blocked_operations'],
                     **dict.fromkeys(FALSE_FIELDS, False)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--wrapper', type=Path, required=True)
    parser.add_argument('--wrapper-sha256', required=True)
    parser.add_argument('--runtime-prefix', type=Path, required=True)
    parser.add_argument('--fixture-root', type=Path, required=True)
    args = parser.parse_args()
    # Keep even native writes/late stdio flushes off the public JSON pipe.
    # Raw stderr remains private and capped by the unchanged outer runner.
    public_fd = os.dup(sys.stdout.fileno())
    try:
        sys.stdout.flush()
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        with redirect_stdout(sys.stderr):
            result = exercise(args.wrapper, args.wrapper_sha256, args.runtime_prefix, args.fixture_root)
        payload = (json.dumps(validate(result), sort_keys=True) + '\n').encode('ascii')
        require(len(payload) <= 2048)
        # Do not restore descriptor 1: late dependency output stays private.
        offset = 0
        while offset < len(payload):
            offset += os.write(public_fd, payload[offset:])
    finally:
        os.close(public_fd)


if __name__ == '__main__':
    main()

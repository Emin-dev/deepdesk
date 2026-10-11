"""Offline first-party mocks and inert data only; never executes archive payloads."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import socket
import ssl
import sys
import tarfile
import tempfile
import time
import types
import unittest
import urllib.error
import urllib.parse
import zipfile
from unittest import mock
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SECRET = 'INVALID_TEST_EXCEPTION token=INVALID_TEST_VALUE ::warning:: /invalid-test/private/location'
URL = 'https://ftp.gnu.org/gnu/gettext/gettext-1.0.tar.gz'

def load(name):
    spec = importlib.util.spec_from_file_location('input_test_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

a = load('archive_tools')
d = load('input_diagnostics')
s = load('stage')
b = load('bounds')
n = load('native_checks')

class Response:
    def __init__(self, data=b'abc', status=200, url=URL, length='3', error=None):
        self.data, self.status, self.url, self.error = data, status, url, error
        self.headers = {} if length is None else {'Content-Length': length}
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def geturl(self): return self.url
    def read(self, size):
        if self.error: raise self.error
        result, self.data = self.data[:size], self.data[size:]
        return result

class InputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.block = mock.patch.object(socket, 'create_connection', side_effect=AssertionError('network_forbidden'))
        self.block.start()
        self.block_connect = mock.patch.object(socket.socket, 'connect', side_effect=AssertionError('network_forbidden'))
        self.block_connect.start()
        self.pin = {'id': 'gettext', 'url': URL, 'redirect_hosts': ['ftp.gnu.org'], 'size': 3,
                    'sha256': hashlib.sha256(b'abc').hexdigest()}
    def tearDown(self):
        self.block_connect.stop()
        self.block.stop()
        self.temp.cleanup()
    def safe(self, result):
        encoded = json.dumps(result)
        self.assertLess(len(encoded.encode()), 2048)
        for forbidden in (SECRET, str(self.root), 'https://', 'Content-Length', 'Traceback'):
            self.assertNotIn(forbidden, encoded)
        return result
    def download(self, response=None, error=None, redirects=(), pin=None, deadline=None):
        pin = pin or self.pin
        observer = d.Observer(a, pin)
        followed = []
        def build(*handlers):
            self.assertEqual(handlers[0].proxies, {})
            self.assertEqual(handlers[1].hosts, set(pin['redirect_hosts']))
            def open_(request, timeout):
                self.assertEqual(request.full_url, pin['url'])
                self.assertGreater(timeout, 0)
                self.assertLessEqual(timeout, 10)
                for url in redirects:
                    request = handlers[1].redirect_request(request, None, 302, SECRET, {}, url)
                    followed.append(True)
                if error: raise error
                return response or Response(url=pin['url'])
            return mock.Mock(open=open_)
        target = self.root / 'download'
        target.unlink(missing_ok=True)
        result = {'status': 'passed'}
        previous = sys.gettrace()
        with mock.patch.object(a.urllib.request, 'build_opener', side_effect=build):
            sys.settrace(observer.trace)
            try: a.download(pin, target, deadline if deadline is not None else time.monotonic() + 20)
            except Exception as caught: result = observer.failure_record(caught, 'download')
            finally: sys.settrace(previous)
        if result['status'] == 'passed':
            result.update(http_status=observer.status, response_host=observer.host,
                          redirects=observer.redirects, downloaded_bytes=observer.total)
        return self.safe(result), followed
    def fixture(self):
        data = b'first-party inert fixture\n'
        archive = self.root / 'fixture.tar'
        with tarfile.open(archive, 'w') as out:
            member = tarfile.TarInfo('gettext-1.0/data.txt')
            member.size, member.mode, member.mtime = len(data), 0o644, 0
            out.addfile(member, io.BytesIO(data))
        sha = a.digest(archive)
        row = {'path': member.name, 'kind': 'file', 'size': len(data), 'mode': 0o644,
               'mtime': 0, 'sha256': hashlib.sha256(data).hexdigest()}
        contract = {'members': [row], 'archive_sha256': sha, 'expanded_bytes': len(data)}
        manifest = self.root / 'fixture.json'
        manifest.write_text(json.dumps(contract))
        pin = dict(self.pin, format='tar', root='gettext-1.0', sha256=sha,
                   member_manifest_sha256=a.digest(manifest), expanded_bytes=len(data),
                   member_count=1, max_member_bytes=len(data), size=archive.stat().st_size,
                   member_manifest='members/gettext.json', filename='input.tar')
        return archive, manifest, pin, contract
    def read_input(self, pin, manifest, response, checks=None):
        checks = checks or mock.Mock()
        out = io.StringIO()
        previous = sys.gettrace()
        with mock.patch.object(a.urllib.request, 'build_opener', return_value=mock.Mock(open=lambda *args, **kwargs: response)), contextlib.redirect_stdout(out):
            try:
                tree = s.read_input(a, d, pin, self.root / 'input.tar', self.root / 'tree', manifest, time.monotonic() + 20, checks)
                result = {'status': 'passed', 'tree': tree}
            except s.PhaseError as error:
                result = self.safe(error.record)
        self.assertIs(sys.gettrace(), previous)
        return result, out.getvalue(), checks

    def test_same_host_redirect_accepted(self):
        result, followed = self.download(redirects=['https://ftp.gnu.org/gnu/gettext/another'])
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(followed, [True])
        self.assertEqual(result['redirects'], [{'status': 302, 'host': 'origin', 'decision': 'allowed'}])
    def test_external_redirect_denied_before_follow_or_bytes(self):
        result, followed = self.download(redirects=['https://external.invalid/' + SECRET])
        self.assertEqual((result['failure_class'], result['downloaded_bytes']), ('redirect_host_denied', 0))
        self.assertEqual((result['archive_source_line'], followed), (33, []))
        self.assertEqual(result['redirects'], [{'status': 302, 'host': 'other', 'decision': 'redirect_host_denied'}])
    def test_six_pins_derive_own_origin_and_host_policy(self):
        for original in json.loads((HERE / 'input-lock.json').read_text())['inputs']:
            with self.subTest(input=original['id']):
                pin = dict(original, size=3, sha256=hashlib.sha256(b'abc').hexdigest())
                result, _ = self.download(pin=pin)
                self.assertEqual((result['status'], result['response_host']), ('passed', 'origin'))
                result, followed = self.download(pin=pin, redirects=['https://external.invalid/' + SECRET])
                self.assertEqual(result['failure_class'], 'redirect_host_denied')
                self.assertEqual(result['phase'], 'input-' + original['id'])
                self.assertEqual(followed, [])
                if len(pin['redirect_hosts']) > 1:
                    url = 'https://' + pin['redirect_hosts'][1] + '/first-party-fixture'
                    result, followed = self.download(pin=pin, response=Response(url=url), redirects=[url])
                    self.assertEqual((result['status'], result['response_host'], followed), ('passed', 'allowed_redirect', [True]))
    def test_all_redirect_rules_remain_enforced(self):
        cases = [('http://ftp.gnu.org/a', 'redirect_scheme_denied'),
                 ('https://ftp.gnu.org:444/a', 'redirect_port_denied'),
                 ('https://INVALID_TEST_USER:INVALID_TEST_PASSWORD@ftp.gnu.org/a', 'redirect_userinfo_denied'),
                 ('https://ftp.gnu.org/a#' + SECRET, 'redirect_fragment_denied'),
                 ('https://[bad', 'redirect_url_malformed'),
                 ('https://ftp.gnu.org:bad/a', 'redirect_url_malformed'),
                 ('https://ftp.gnu.org:70000/a', 'redirect_url_malformed')]
        for url, expected in cases:
            with self.subTest(failure=expected):
                result, followed = self.download(redirects=[url])
                self.assertEqual(result['failure_class'], expected)
                self.assertEqual(followed, [])
        result, followed = self.download(redirects=[URL] * 4)
        self.assertEqual((result['failure_class'], len(followed), len(result['redirects'])), ('redirect_count_denied', 3, 4))
        result, followed = self.download(redirects=[URL] * 3 + ['https://[bad'])
        self.assertEqual((result['failure_class'], len(followed)), ('redirect_url_malformed', 3))
    def test_status_host_scheme_length_size_and_hash_fail_separately(self):
        cases = [(dict(status=204), 'response_status_mismatch', 42),
                 (dict(url='http://ftp.gnu.org/a'), 'response_scheme_mismatch', 42),
                 (dict(url='https://external.invalid/' + SECRET), 'response_host_mismatch', 42),
                 (dict(length='03'), 'response_length_mismatch', 43),
                 (dict(length=SECRET), 'response_length_mismatch', 43),
                 (dict(data=b'ab'), 'download_size_mismatch', 49),
                 (dict(data=b'abcd'), 'download_size_mismatch', 48),
                 (dict(data=b'xyz'), 'download_hash_mismatch', 49)]
        for settings, failure, line in cases:
            with self.subTest(failure=failure):
                result, _ = self.download(response=Response(**settings))
                self.assertEqual((result['failure_class'], result['archive_source_line']), (failure, line))
    def test_missing_content_length_remains_accepted(self):
        result, _ = self.download(response=Response(length=None))
        self.assertEqual(result['status'], 'passed')
    def test_network_errors_and_secret_messages_remain_fixed(self):
        cases = [(socket.gaierror(-3, SECRET), 'network_dns_error'),
                 (ssl.SSLCertVerificationError(1, SECRET), 'network_tls_certificate_error'),
                 (ssl.SSLError(1, SECRET), 'network_tls_error'),
                 (TimeoutError(SECRET), 'network_timeout'),
                 (ConnectionResetError(SECRET), 'network_transport_error'),
                 (OSError(d.errno.ENETUNREACH, SECRET), 'network_transport_error'),
                 (OSError(d.errno.EACCES, SECRET), 'io_error'),
                 (urllib.error.URLError(SECRET), 'network_url_error'),
                 (ValueError(SECRET), 'network_url_or_value_error'),
                 (RuntimeError(SECRET), 'unexpected_failure'),
                 (urllib.error.HTTPError(URL, 404, SECRET, {}, None), 'http_error'),
                 (urllib.error.HTTPError(URL, 302, SECRET, {'Location': 'javascript:' + SECRET}, None), 'redirect_scheme_denied'),
                 (urllib.error.HTTPError(URL, 302, SECRET, {'Location': 'https://[bad'}, None), 'redirect_url_malformed'),
                 (urllib.error.HTTPError(URL, 302, SECRET, {}, None), 'http_redirect_error')]
        for error, failure in cases:
            with self.subTest(failure=failure):
                wrapped = urllib.error.URLError(error) if isinstance(error, (socket.gaierror, ssl.SSLError, TimeoutError)) else error
                result, _ = self.download(error=wrapped)
                self.assertEqual((result['failure_class'], result['archive_source_line']), (failure, 41))
    def test_nested_network_and_malformed_http_error(self):
        result, _ = self.download(error=urllib.error.URLError(urllib.error.URLError(socket.gaierror(-3, SECRET))))
        self.assertEqual(result['failure_class'], 'network_dns_error')
        result, _ = self.download(error=urllib.error.HTTPError('https://[bad', 503, SECRET, {}, None))
        self.assertEqual((result['failure_class'], result['http_status'], result['response_host']), ('http_error', 503, 'malformed'))
    def test_no_exception_stringification(self):
        class PoisonError(OSError):
            def __str__(self): raise AssertionError(SECRET)
        result, _ = self.download(error=PoisonError(SECRET))
        self.assertEqual(result['failure_class'], 'io_error')
    def test_download_deadline_and_read_timeout(self):
        result, _ = self.download(deadline=time.monotonic() - 1)
        self.assertEqual((result['failure_class'], result['archive_source_line']), ('deadline_exceeded', 38))
        result, _ = self.download(response=Response(error=TimeoutError(SECRET)))
        self.assertEqual((result['failure_class'], result['archive_source_line']), ('network_timeout', 46))
    def test_real_inert_extraction_and_checkpoint_order(self):
        archive, manifest, pin, _ = self.fixture()
        result, output, checks = self.read_input(pin, manifest, Response(archive.read_bytes(), length=str(pin['size'])))
        self.assertEqual(result['status'], 'passed')
        self.assertEqual((result['tree'] / 'data.txt').read_bytes(), b'first-party inert fixture\n')
        self.assertEqual(output, '')
        self.assertEqual(checks.call_args_list, [mock.call(force=True), mock.call(force=True), mock.call(), mock.call(), mock.call(force=True)])
    def test_extraction_contract_hash_and_members(self):
        for mutation, line in [('member_count', 54), ('mode', 59), ('mtime', 60), ('file_hash', 68), ('member_name', 79)]:
            with self.subTest(mutation=mutation):
                archive, manifest, pin, contract = self.fixture()
                if mutation == 'member_count': pin['member_count'] = 2
                elif mutation == 'mode': contract['members'][0]['mode'] = 0o600
                elif mutation == 'mtime': contract['members'][0]['mtime'] = 1
                elif mutation == 'file_hash': contract['members'][0]['sha256'] = '0' * 64
                else: contract['members'][0]['path'] = SECRET
                manifest.write_text(json.dumps(contract)); pin['member_manifest_sha256'] = a.digest(manifest)
                (self.root / 'input.tar').unlink(missing_ok=True)
                import shutil
                if (self.root / 'tree').exists(): shutil.rmtree(self.root / 'tree')
                result, output, _ = self.read_input(pin, manifest, Response(archive.read_bytes(), length=str(pin['size'])))
                self.assertEqual((result['failure_class'], result['input_phase'], result['archive_source_line']), ('extraction_contract_failure', 'extract', line))
                self.assertEqual(json.loads(output), result)
    def test_actual_bad_archive_and_manifest_are_extraction_failures(self):
        archive, manifest, pin, contract = self.fixture()
        archive.write_bytes(b'inert invalid tar ' + SECRET.encode())
        pin['sha256'] = a.digest(archive); pin['size'] = archive.stat().st_size
        contract['archive_sha256'] = pin['sha256']; manifest.write_text(json.dumps(contract)); pin['member_manifest_sha256'] = a.digest(manifest)
        result, _, _ = self.read_input(pin, manifest, Response(archive.read_bytes(), length=str(pin['size'])))
        self.assertEqual((result['failure_class'], result['archive_source_line']), ('extraction_archive_error', 74))
        (self.root / 'input.tar').unlink()
        manifest.write_text(SECRET); pin['member_manifest_sha256'] = a.digest(manifest)
        result, _, _ = self.read_input(pin, manifest, Response(archive.read_bytes(), length=str(pin['size'])))
        self.assertEqual((result['failure_class'], result['archive_source_line']), ('extraction_error', 53))
    def test_extraction_errors_are_distinct_from_network(self):
        observer = d.Observer(a, self.pin)
        for error, expected in [(zipfile.BadZipFile(SECRET), 'extraction_archive_error'), (EOFError(SECRET), 'extraction_archive_error'), (OSError(SECRET), 'extraction_io_error'), (ValueError(SECRET), 'extraction_error')]:
            self.assertEqual(observer.classify(error, 'extract'), expected)
    def test_trace_restored_on_success_failure_and_baseexception(self):
        archive, manifest, pin, _ = self.fixture()
        old = sys.gettrace()
        def previous(frame, event, arg): return previous
        sys.settrace(previous)
        try:
            self.read_input(pin, manifest, Response(archive.read_bytes(), length=str(pin['size'])))
            self.assertIs(sys.gettrace(), previous)
            (self.root / 'input.tar').unlink()
            self.read_input(pin, manifest, Response(b'x', length=None))
            self.assertIs(sys.gettrace(), previous)
            (self.root / 'input.tar').unlink()
            with self.assertRaises(KeyboardInterrupt):
                self.read_input(pin, manifest, Response(length=None, error=KeyboardInterrupt(SECRET)))
            self.assertIs(sys.gettrace(), previous)
        finally: sys.settrace(old)
    def test_boundary_failure_retains_checkpoint_phase(self):
        archive, manifest, pin, _ = self.fixture()
        for count, phase in [(1, 'input_checkpoint'), (2, 'download_checkpoint'), (3, 'extract'), (5, 'extraction_checkpoint')]:
            with self.subTest(phase=phase):
                (self.root / 'input.tar').unlink(missing_ok=True)
                import shutil
                if (self.root / 'tree').exists(): shutil.rmtree(self.root / 'tree')
                calls = [0]
                def check(*args, **kwargs):
                    calls[0] += 1
                    if calls[0] == count: raise s.LaneError(SECRET)
                result, _, _ = self.read_input(pin, manifest, Response(archive.read_bytes(), length=str(pin['size'])), check)
                self.assertEqual((result['failure_class'], result['input_phase']), ('input_boundary_failure', phase))
    def test_stage_failure_is_fatal_cleans_workspace_and_restores_alarm(self):
        event = self.root / 'event.json'
        event.write_text(json.dumps({'repository': {'private': False, 'full_name': 'Emin-dev/deepdesk'}}))
        created, executed = [], []
        class FakeLane:
            def __init__(self, root, helpers, work, modules):
                self.work = work; self.immutable = work / 'immutable'; self.immutable.mkdir(); created.append(work)
            def checkpoint(self): pass
            def execute(self, trees): executed.append(True); raise AssertionError('must_not_execute')
        real_is_file = Path.is_file
        def is_file(path): return True if str(path) == '/usr/bin/sandbox-exec' else real_is_file(path)
        previous_trace = sys.gettrace(); previous_alarm = signal.getsignal(signal.SIGALRM)
        out = io.StringIO()
        env = {'GITHUB_REPOSITORY': 'Emin-dev/deepdesk', 'GITHUB_REF': 'refs/heads/' + s.BRANCH,
               'GITHUB_EVENT_NAME': 'push', 'GITHUB_EVENT_PATH': str(event), 'RUNNER_TEMP': str(self.root)}
        def modules(name, path): return {'pdf_archive_tools': a, 'pdf_bounds': b, 'pdf_native_checks': n, 'pdf_input_diagnostics': d}[name]
        with mock.patch.object(s, 'validate_receipt'), mock.patch.object(s, 'Lane', FakeLane), \
             mock.patch.object(s, 'load_module', side_effect=modules), \
             mock.patch.object(s.platform, 'system', return_value='Darwin'), mock.patch.object(s.platform, 'machine', return_value='arm64'), \
             mock.patch.object(Path, 'is_file', is_file), mock.patch.object(s.sys, 'executable', '/usr/bin/python3'), \
             mock.patch.object(s.sys, 'argv', ['stage.py', '--repository', str(ROOT)]), \
             mock.patch.dict(os.environ, env), mock.patch.object(s.shutil, 'disk_usage', return_value=types.SimpleNamespace(free=8 * 1024**3)), \
             mock.patch.object(a.urllib.request, 'build_opener', return_value=mock.Mock(open=mock.Mock(side_effect=urllib.error.HTTPError(URL, 503, SECRET, {}, None)))), \
             contextlib.redirect_stdout(out):
            code = s.main()
        self.assertEqual(code, 1); self.assertEqual(executed, []); self.assertEqual(len(created), 1)
        self.assertFalse(created[0].exists()); self.assertIs(sys.gettrace(), previous_trace)
        self.assertEqual(signal.getsignal(signal.SIGALRM), previous_alarm)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)
        records = [self.safe(json.loads(line)) for line in out.getvalue().splitlines()]
        self.assertEqual(len(records), 2)
        self.assertEqual((records[0]['input_phase'], records[0]['failure_class']), ('download', 'http_error'))
        self.assertEqual(records[1]['failure_class'], 'http_error')
        for gate in s.FALSE_GATES: self.assertIs(records[1][gate], False)
    def test_revision_closed_receipt_and_hash_validation(self):
        receipt = json.loads((HERE / 'review-receipt.json').read_text())
        self.assertEqual((s.CANDIDATE_REVISION, receipt['candidate_revision']), (10, 10))
        for gate in ('execution_approved', 'independent_review_passed', 'temporary_linker_adhoc_signing_approved', 'install_name_linker_assignment_approved'):
            self.assertIs(receipt[gate], False)
        s.validate_receipt(ROOT, HERE, receipt, False)
        with self.assertRaises(s.LaneError): s.validate_receipt(ROOT, HERE, receipt, True)
        flags = ('execution_approved', 'independent_review_passed', 'temporary_linker_adhoc_signing_approved', 'install_name_linker_assignment_approved')
        for blocked in flags:
            isolated = copy.deepcopy(receipt)
            for flag in flags: isolated[flag] = flag != blocked
            with self.assertRaises(s.LaneError): s.validate_receipt(ROOT, HERE, isolated, True)
        self.assertEqual(receipt['base_commit'], 'eeee4308a79e5d0b7fc95d1eac4fdb1bea60671a')
        changed = copy.deepcopy(receipt); changed['sha256']['input_diagnostics.py'] = '0' * 64
        with self.assertRaises(s.LaneError): s.validate_receipt(ROOT, HERE, changed, False)
    def test_receipt_pins_unchanged_helper_and_canonical_source(self):
        self.assertEqual(a.digest(HERE / 'archive_tools.py'), 'd5273a166c7e3f3485cf8d0fd5f63551dee1b38a1cda3548f75e19553814a146')
        pin = json.loads((HERE / 'input-lock.json').read_text())['inputs'][0]
        self.assertEqual((pin['id'], pin['url'], pin['redirect_hosts']), ('gettext', URL, ['ftp.gnu.org']))
        self.assertEqual((pin['size'], pin['sha256']), (32694085, s.INPUT_HASHES['gettext']))
    def test_malformed_safe_categories_and_status(self):
        for status in (SECRET, True, 999, None): self.assertIsNone(d.status_number(status))
        self.assertEqual(d.host_category(None, 'ftp.gnu.org', ('ftp.gnu.org',)), 'malformed')
        self.assertEqual(d.host_category(urllib.parse.urlsplit('/relative'), 'ftp.gnu.org', ('ftp.gnu.org',)), 'missing')

if __name__ == '__main__': unittest.main(verbosity=2)

"""Offline first-party fixtures only. Invocation: python3 -I -B test_diagnostic.py SOURCE_ROOT."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import socket
import ssl
import sys
import tarfile
import tempfile
import time
import unittest
import urllib.error
from unittest import mock

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
SOURCE = Path(sys.argv.pop(1)).resolve()
spec = importlib.util.spec_from_file_location('diagnostic', HERE / 'diagnose.py')
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)
for name, sha in d.REUSED.items():
    if d.digest(SOURCE / d.ORIGINAL / name) != sha: raise SystemExit('fixed_source_integrity_failed')
a = d.load_archive(SOURCE)
SECRET = 'DO_NOT_LOG_TOKEN_secret?credential=xyz:/private/user/secret.txt'

class Response:
    def __init__(self, data=b'abc', *, status=200, url=d.URL, length='3', error=None):
        self.stream = io.BytesIO(data)
        self.status, self.url, self.error = status, url, error
        self.headers = {'Content-Length': length}
    def geturl(self): return self.url
    def read(self, count):
        if self.error is not None: raise self.error
        return self.stream.read(count)
    def __enter__(self): return self
    def __exit__(self, *args): self.stream.close()

class Suite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.offline-test-', dir=HERE.parent.parent)
        self.root = Path(self.tmp.name)
        self.no_network = mock.patch.object(socket, 'create_connection', side_effect=AssertionError('network_forbidden'))
        self.no_network.start()
        self.pin = {'url': d.URL, 'redirect_hosts': list(d.HOSTS), 'size': 3,
                    'sha256': hashlib.sha256(b'abc').hexdigest()}
    def tearDown(self):
        self.no_network.stop()
        self.tmp.cleanup()

    def run_download(self, response=None, error=None, redirects=(), pin=None, deadline=None):
        observer = d.Observer(a)
        followed = []
        def build(*handlers):
            self.assertEqual(handlers[0].proxies, {})
            self.assertEqual(handlers[1].hosts, set(d.HOSTS))
            def open_(request, timeout):
                self.assertEqual(request.full_url, d.URL)
                self.assertGreater(timeout, 0)
                self.assertLessEqual(timeout, 10)
                for url in redirects:
                    request = handlers[1].redirect_request(request, None, 302, SECRET, {}, url)
                    followed.append(True)
                if error is not None: raise error
                return response or Response()
            return mock.Mock(open=open_)
        raised = None
        with mock.patch.object(a.urllib.request, 'build_opener', side_effect=build):
            sys.settrace(observer.trace)
            try: a.download(pin or self.pin, self.root / 'archive', deadline if deadline is not None else time.monotonic() + 20)
            except BaseException as caught: raised = caught
            finally: sys.settrace(None)
        result = d.record()
        result.update(phase='download', status='failed' if raised else 'passed',
                      failure_class=observer.classify(raised, 'download') if raised else None,
                      archive_source_line=observer.source_line(raised) if raised else 0,
                      downloaded_bytes=observer.total, redirects=observer.redirects,
                      response_host=observer.host, http_status=observer.status)
        encoded = json.dumps(result)
        self.assertLess(len(encoded.encode()), 4096)
        self.assertNotIn(SECRET, encoded)
        self.assertNotIn(str(self.root), encoded)
        return result, followed

    def test_download_success_exact_original_policy(self):
        result, _ = self.run_download()
        self.assertEqual((result['status'], result['downloaded_bytes'], result['http_status'], result['response_host']),
                         ('passed', 3, 200, 'origin'))
    def test_allowed_redirects(self):
        result, followed = self.run_download(response=Response(url='https://mirrors.ocf.berkeley.edu/a'),
            redirects=['https://mirrors.ocf.berkeley.edu/a', 'https://ftpmirror.gnu.org/a'])
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(len(followed), 2)
        self.assertTrue(all(r['decision'] == 'allowed' for r in result['redirects']))
        self.assertEqual(result['response_host'], 'allowed_mirror')
    def test_redirect_rejections_never_followed(self):
        cases = [('http://ftpmirror.gnu.org/a', 'redirect_scheme_denied'),
                 ('https://secret.example.invalid/' + SECRET, 'redirect_host_denied'),
                 ('https://ftpmirror.gnu.org:444/a', 'redirect_port_denied'),
                 ('https://user:password@ftpmirror.gnu.org/a', 'redirect_userinfo_denied'),
                 ('https://ftpmirror.gnu.org/a#' + SECRET, 'redirect_fragment_denied'),
                 ('https://[bad', 'redirect_url_malformed'),
                 ('https://ftpmirror.gnu.org:bad/a', 'redirect_url_malformed')]
        for url, expected in cases:
            with self.subTest(expected=expected, url_kind=cases.index((url, expected))):
                result, followed = self.run_download(redirects=[url])
                self.assertEqual(result['failure_class'], expected)
                self.assertEqual(followed, [])
                self.assertIn(result['archive_source_line'], (32, 33))
    def test_redirect_count_bound(self):
        result, followed = self.run_download(redirects=[d.URL] * 4)
        self.assertEqual(result['failure_class'], 'redirect_count_denied')
        self.assertEqual(len(followed), 3)
        self.assertEqual(len(result['redirects']), 4)
    def test_network_classifications(self):
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
                 (d.Deadline(), 'deadline_exceeded'), (d.Interrupted(), 'interrupted'),
                 (d.DiskBound(), 'disk_bound'),
                 (urllib.error.HTTPError(d.URL, 404, SECRET, {}, None), 'http_error'),
                 (urllib.error.HTTPError(d.URL, 302, SECRET, {'Location': 'javascript:' + SECRET}, None), 'redirect_scheme_denied'),
                 (urllib.error.HTTPError(d.URL, 302, SECRET, {'Location': 'https://[bad'}, None), 'redirect_url_malformed'),
                 (urllib.error.HTTPError(d.URL, 302, SECRET, {}, None), 'http_redirect_error')]
        for error, expected in cases:
            with self.subTest(classification=expected):
                wrapped = urllib.error.URLError(error) if isinstance(error, (socket.gaierror, ssl.SSLError, TimeoutError)) else error
                result, _ = self.run_download(error=wrapped)
                self.assertEqual(result['failure_class'], expected)
                self.assertEqual(result['archive_source_line'], 41)
    def test_response_and_download_contract_classifications(self):
        cases = [(dict(status=204), 'response_status_mismatch', 42),
                 (dict(url='http://ftpmirror.gnu.org/a'), 'response_scheme_mismatch', 42),
                 (dict(url='https://secret.invalid/' + SECRET), 'response_host_mismatch', 42),
                 (dict(length='03'), 'response_length_mismatch', 43),
                 (dict(length=SECRET), 'response_length_mismatch', 43),
                 (dict(data=b'ab'), 'download_size_mismatch', 49),
                 (dict(data=b'abcd'), 'download_size_mismatch', 48),
                 (dict(data=b'xyz'), 'download_hash_mismatch', 49)]
        for settings, expected, line in cases:
            with self.subTest(classification=expected):
                (self.root / 'archive').unlink(missing_ok=True)
                result, _ = self.run_download(response=Response(**settings))
                self.assertEqual((result['failure_class'], result['archive_source_line']), (expected, line))
    def test_no_content_length_is_accepted(self):
        result, _ = self.run_download(response=Response(length=None))
        self.assertEqual(result['status'], 'passed')
    def test_expired_deadline_and_read_timeout(self):
        result, _ = self.run_download(deadline=time.monotonic() - 1)
        self.assertEqual((result['failure_class'], result['archive_source_line']), ('deadline_exceeded', 38))
        result, _ = self.run_download(response=Response(error=TimeoutError(SECRET)))
        self.assertEqual((result['failure_class'], result['archive_source_line']), ('network_timeout', 46))
    def test_no_exception_stringification(self):
        class PoisonError(OSError):
            def __str__(self): raise AssertionError(SECRET)
        result, _ = self.run_download(error=PoisonError(SECRET))
        self.assertEqual(result['failure_class'], 'io_error')

    def fixture(self):
        data = b'first-party inert fixture\n'
        archive = self.root / 'fixture.tar'
        with tarfile.open(archive, 'w') as out:
            member = tarfile.TarInfo('gettext-1.0/data.txt')
            member.size, member.mode, member.mtime = len(data), 0o644, 0
            out.addfile(member, io.BytesIO(data))
        sha = d.digest(archive)
        row = {'path': member.name, 'kind': 'file', 'size': len(data), 'mode': 0o644,
               'mtime': 0, 'sha256': hashlib.sha256(data).hexdigest()}
        contract = {'members': [row], 'archive_sha256': sha, 'expanded_bytes': len(data)}
        manifest = self.root / 'fixture.json'
        manifest.write_text(json.dumps(contract))
        pin = {'id': 'gettext', 'format': 'tar', 'root': 'gettext-1.0', 'sha256': sha,
               'member_manifest_sha256': d.digest(manifest), 'expanded_bytes': len(data),
               'member_count': 1, 'max_member_bytes': len(data), 'size': archive.stat().st_size,
               'url': d.URL, 'redirect_hosts': list(d.HOSTS)}
        return archive, manifest, pin, contract

    def test_original_extraction_success_as_data(self):
        archive, manifest, pin, _ = self.fixture()
        path = a.extract(pin, archive, self.root / 'tree', manifest)
        self.assertEqual((path / 'data.txt').read_bytes(), b'first-party inert fixture\n')
    def test_extraction_stage_source_line_failures(self):
        mutations = [('archive_hash', 52), ('member_count', 54), ('mode', 59), ('mtime', 60), ('file_hash', 68), ('member_name', 79)]
        for mutation, line in mutations:
            with self.subTest(mutation=mutation):
                archive, manifest, pin, contract = self.fixture()
                if mutation == 'archive_hash': pin['sha256'] = '0' * 64
                elif mutation == 'member_count': pin['member_count'] = 2
                elif mutation == 'mode': contract['members'][0]['mode'] = 0o600
                elif mutation == 'mtime': contract['members'][0]['mtime'] = 1
                elif mutation == 'file_hash': contract['members'][0]['sha256'] = '0' * 64
                else: contract['members'][0]['path'] = SECRET
                manifest.write_text(json.dumps(contract))
                pin['member_manifest_sha256'] = d.digest(manifest)
                observer = d.Observer(a)
                with self.assertRaises(a.ContractError) as raised:
                    a.extract(pin, archive, self.root / ('tree-' + mutation), manifest)
                # unittest clears tracebacks: retain an independent direct caught exception.
                try: a.extract(pin, archive, self.root / ('again-' + mutation), manifest)
                except a.ContractError as error:
                    self.assertEqual(observer.classify(error, 'extract'), 'extraction_contract_failure')
                    self.assertEqual(observer.source_line(error), line)
    def test_extraction_other_errors_are_fixed(self):
        observer = d.Observer(a)
        self.assertEqual(observer.classify(tarfile.ReadError(SECRET), 'extract'), 'extraction_archive_error')
        self.assertEqual(observer.classify(ValueError(SECRET), 'extract'), 'extraction_error')
        self.assertEqual(observer.classify(a.ContractError(SECRET), 'preflight'), 'input_contract_failure')
    def test_checkpoint_bounds(self):
        checkpoint = d.Checkpoint(self.root, time.monotonic() - 1)
        with self.assertRaises(d.Deadline): checkpoint()
        checkpoint = d.Checkpoint(self.root, time.monotonic() + 20)
        with mock.patch.object(d.shutil, 'disk_usage', return_value=mock.Mock(free=0)):
            with self.assertRaises(d.DiskBound): checkpoint(force=True)
        huge = self.root / 'sparse'
        with huge.open('wb') as stream: stream.truncate(2 * d.GIB + 1)
        with self.assertRaises(d.DiskBound): checkpoint(force=True)
        huge.unlink()
    def test_complete_input_lifecycle_cleans_temp_and_has_false_gates(self):
        archive, manifest, pin, _ = self.fixture()
        data = archive.read_bytes()
        with mock.patch.object(a.urllib.request, 'build_opener', return_value=mock.Mock(open=lambda *args, **kwargs: Response(data, length=str(len(data))))), \
             mock.patch.object(d.shutil, 'disk_usage', return_value=mock.Mock(free=8 * d.GIB)):
            result = d.diagnose(a, pin, manifest, self.root, d.record())
        self.assertEqual(result['status'], 'passed')
        self.assertTrue(result['download_verified'] and result['extraction_verified'])
        self.assertEqual(result['cleanup'], 'removed')
        self.assertEqual(list(self.root.glob('gettext-input-*')), [])
        for key in ('downloaded_code_executed', 'build_started', 'native_checks_started', 'pdf_runtime_proven', 'artifact_uploaded', 'cache_used'):
            self.assertIs(result[key], False)
        self.assertIsNone(sys.gettrace())
    def test_failed_lifecycle_cleans_partial_download(self):
        _, manifest, pin, _ = self.fixture()
        with mock.patch.object(a.urllib.request, 'build_opener', return_value=mock.Mock(open=lambda *args, **kwargs: Response(b'bad', length=None))), \
             mock.patch.object(d.shutil, 'disk_usage', return_value=mock.Mock(free=8 * d.GIB)):
            result = d.diagnose(a, pin, manifest, self.root, d.record())
        self.assertEqual((result['failure_class'], result['cleanup']), ('download_size_mismatch', 'removed'))
        self.assertEqual(list(self.root.glob('gettext-input-*')), [])

    def test_initial_disk_floor_is_classified(self):
        with mock.patch.object(d.shutil, 'disk_usage', return_value=mock.Mock(free=0)):
            result = d.diagnose(a, self.pin, self.root / 'unused', self.root, d.record())
        self.assertEqual((result['status'], result['phase'], result['failure_class'], result['cleanup']),
                         ('failed', 'input_preflight', 'disk_bound', 'not_created'))
    def test_cleanup_failure_is_fail_closed(self):
        archive, manifest, pin, _ = self.fixture()
        data = archive.read_bytes()
        with mock.patch.object(a.urllib.request, 'build_opener', return_value=mock.Mock(open=lambda *args, **kwargs: Response(data, length=str(len(data))))), \
             mock.patch.object(d.shutil, 'disk_usage', return_value=mock.Mock(free=8 * d.GIB)), \
             mock.patch.object(d.shutil, 'rmtree', side_effect=OSError(SECRET)):
            result = d.diagnose(a, pin, manifest, self.root, d.record())
        self.assertEqual((result['status'], result['failure_class'], result['cleanup']), ('failed', 'cleanup_failure', 'failed'))
        self.assertNotIn(SECRET, json.dumps(result))
    def test_actual_extraction_parser_failures(self):
        archive, manifest, pin, contract = self.fixture()
        archive.write_bytes(b'inert invalid tar ' + SECRET.encode())
        pin['sha256'] = d.digest(archive)
        contract['archive_sha256'] = pin['sha256']
        manifest.write_text(json.dumps(contract))
        pin['member_manifest_sha256'] = d.digest(manifest)
        observer = d.Observer(a)
        try: a.extract(pin, archive, self.root / 'malformed-tree', manifest)
        except tarfile.ReadError as error:
            self.assertEqual((observer.classify(error, 'extract'), observer.source_line(error)), ('extraction_archive_error', 74))
        else: self.fail('malformed archive accepted')
        manifest.write_text(SECRET)
        pin['member_manifest_sha256'] = d.digest(manifest)
        try: a.extract(pin, archive, self.root / 'malformed-manifest', manifest)
        except ValueError as error:
            self.assertEqual((observer.classify(error, 'extract'), observer.source_line(error)), ('extraction_error', 53))
        else: self.fail('malformed manifest accepted')
    def test_malformed_fourth_redirect_reports_parse_failure_first(self):
        result, followed = self.run_download(redirects=[d.URL] * 3 + ['https://[bad'])
        self.assertEqual(result['failure_class'], 'redirect_url_malformed')
        self.assertEqual(len(followed), 3)
    def test_safe_categories_reject_malformed_status_and_hosts(self):
        self.assertIsNone(d.status_number(SECRET))
        self.assertIsNone(d.status_number(True))
        self.assertIsNone(d.status_number(999))
        self.assertEqual(d.host_category(d.urllib.parse.urlsplit('/relative')), 'missing')
        self.assertEqual(d.host_category(None), 'malformed')
        self.assertEqual(d.redirect_decision(d.urllib.parse.urlsplit('https://ftpmirror.gnu.org:70000/a'), 1), 'redirect_url_malformed')
    def test_nested_and_malformed_network_errors_remain_fixed(self):
        error = urllib.error.URLError(urllib.error.URLError(socket.gaierror(-3, SECRET)))
        result, _ = self.run_download(error=error)
        self.assertEqual(result['failure_class'], 'network_dns_error')
        error = urllib.error.HTTPError('https://[bad', 503, SECRET, {}, None)
        result, _ = self.run_download(error=error)
        self.assertEqual((result['failure_class'], result['http_status'], result['response_host']), ('http_error', 503, 'malformed'))

    def validation_root(self):
        root = self.root / 'review-root'
        for name in d.OWN_FILES | {'review-receipt.json'}:
            target = root / d.PACKAGE / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(HERE / name, target)
        for name in d.REUSED:
            target = root / d.ORIGINAL / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / d.ORIGINAL / name, target)
        workflow = root / d.WORKFLOW
        workflow.parent.mkdir(parents=True)
        shutil.copyfile(HERE / 'pdf-input-diagnostic-macos.yml.template', workflow)
        return root
    def test_receipt_is_closed_and_execution_unapproved(self):
        root = self.validation_root()
        self.assertEqual(d.validate(root)['sha256'], d.ARCHIVE_SHA)
        with self.assertRaises(d.GuardError): d.validate(root, execute=True)
        (root / d.PACKAGE / 'extra').write_text(SECRET)
        with self.assertRaises(d.GuardError): d.validate(root)
    def test_modified_original_or_workflow_rejected(self):
        root = self.validation_root()
        path = root / d.ORIGINAL / 'archive_tools.py'
        path.write_text(path.read_text() + '\n')
        with self.assertRaises(d.GuardError): d.validate(root)
        shutil.copyfile(SOURCE / d.ORIGINAL / 'archive_tools.py', path)
        (root / d.WORKFLOW).write_text(SECRET)
        with self.assertRaises(d.GuardError): d.validate(root)
    def test_unknown_receipt_keys_and_symlinks_are_rejected(self):
        root = self.validation_root()
        path = root / d.PACKAGE / 'review-receipt.json'
        receipt = json.loads(path.read_text())
        receipt['unreviewed'] = SECRET
        path.write_text(json.dumps(receipt))
        with self.assertRaises(d.GuardError): d.validate(root)
        del receipt['unreviewed']
        path.write_text(json.dumps(receipt))
        target = root / d.PACKAGE / 'README.md'
        saved = self.root / 'readme-copy'
        target.rename(saved)
        target.symlink_to(saved)
        with self.assertRaises(d.GuardError): d.validate(root)
    def test_secret_bearing_cli_arguments_are_not_echoed(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output): code = d.main([SECRET])
        self.assertEqual(code, 1)
        self.assertNotIn(SECRET, output.getvalue())
        self.assertLess(len(output.getvalue()), 4096)
        self.assertEqual(json.loads(output.getvalue())['failure_class'], 'preflight_or_host_guard_failed')

if __name__ == '__main__': unittest.main(verbosity=2)

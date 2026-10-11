"""Input-only gettext diagnostic. Never imports, builds, or runs archive payloads."""
from __future__ import annotations
import errno
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import socket
import ssl
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse

sys.dont_write_bytecode = True
BASE = 'f52e37049b7d280e53e07013ccd14da3c3ac53d3'
BRANCH = 'engine-pdf-input-diagnostic-ci'
PACKAGE = 'packaging/pdf-input-diagnostic-candidate'
ORIGINAL = 'packaging/pdf-foundation-candidate'
WORKFLOW = '.github/workflows/engine-pdf-input-diagnostic-macos.yml'
HOSTS = ('ftpmirror.gnu.org', 'mirrors.ocf.berkeley.edu')
URL = 'https://ftpmirror.gnu.org/gettext/gettext-1.0.tar.gz'
ARCHIVE_SHA = '85d99b79c981a404874c02e0342176cf75c7698e2b51fe41031cf6526d974f1a'
ARCHIVE_SIZE = 32694085
REUSED = {
    'archive_tools.py': 'd5273a166c7e3f3485cf8d0fd5f63551dee1b38a1cda3548f75e19553814a146',
    'input-lock.json': 'e8220aeba8dfd36a0ddd93b6f48b17b4f1aef451fed248393f0293cc13236f2a',
    'members/gettext.json': 'ffaf3c8ff6702d9fff652114204d251c1bd76a762018533619d7e449b0a77c6f',
}
OWN_FILES = {'diagnose.py', 'test_diagnostic.py', 'README.md', 'pdf-input-diagnostic-macos.yml.template'}
GIB = 1024 ** 3

class GuardError(Exception): pass
class Deadline(BaseException): pass
class Interrupted(BaseException): pass
class DiskBound(Exception): pass

def need(value):
    if not value: raise GuardError()

def digest(path):
    need(path.is_file() and not path.is_symlink())
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 ** 2), b''): h.update(chunk)
    return h.hexdigest()

def validate(root, execute=False):
    package = root / PACKAGE
    receipt = json.loads((package / 'review-receipt.json').read_text())
    need(set(receipt) == {'schema', 'scope', 'base_commit', 'destination_branch', 'execution_approved',
                         'independent_review_passed', 'source_changes_allowed', 'sha256', 'reused_sha256', 'workflow_sha256'})
    need(receipt['schema'] == 1 and receipt['scope'] == 'gettext-input-only-diagnostic-v1')
    need(receipt['base_commit'] == BASE and receipt['destination_branch'] == BRANCH)
    need(receipt['source_changes_allowed'] is False)
    need(type(receipt['execution_approved']) is bool and type(receipt['independent_review_passed']) is bool)
    need(receipt['reused_sha256'] == REUSED and set(receipt['sha256']) == OWN_FILES)
    observed = {p.relative_to(package).as_posix() for p in package.rglob('*') if p.is_file()}
    need(observed == OWN_FILES | {'review-receipt.json'})
    need(not any(p.is_symlink() for p in package.rglob('*')))
    for name, sha in receipt['sha256'].items(): need(digest(package / name) == sha)
    for name, sha in REUSED.items(): need(digest(root / ORIGINAL / name) == sha)
    need(digest(root / WORKFLOW) == receipt['workflow_sha256'] == digest(package / 'pdf-input-diagnostic-macos.yml.template'))
    if execute: need(receipt['execution_approved'] is True and receipt['independent_review_passed'] is True)
    lock = json.loads((root / ORIGINAL / 'input-lock.json').read_text())
    pins = [pin for pin in lock['inputs'] if pin['id'] == 'gettext']
    need(len(pins) == 1)
    pin = pins[0]
    need(pin['url'] == URL and tuple(pin['redirect_hosts']) == HOSTS)
    need(pin['sha256'] == ARCHIVE_SHA and pin['size'] == ARCHIVE_SIZE)
    return pin

def load_archive(root):
    # validate() must have verified the unchanged first-party helper before import.
    spec = importlib.util.spec_from_file_location('reviewed_archive', root / ORIGINAL / 'archive_tools.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def status_number(value):
    return value if type(value) is int and 100 <= value <= 599 else None

def host_category(parts):
    try:
        host = parts.hostname
        return 'origin' if host == HOSTS[0] else 'allowed_mirror' if host == HOSTS[1] else 'other' if host else 'missing'
    except (ValueError, AttributeError): return 'malformed'

def redirect_decision(parts, count):
    # Match the original short-circuit policy in its original order; never follow here.
    if parts is None: return 'redirect_url_malformed'
    if count > 3: return 'redirect_count_denied'
    try:
        if parts.scheme != 'https': return 'redirect_scheme_denied'
        if parts.hostname not in HOSTS: return 'redirect_host_denied'
        if parts.port not in (None, 443): return 'redirect_port_denied'
        if parts.username or parts.password: return 'redirect_userinfo_denied'
        if parts.fragment: return 'redirect_fragment_denied'
    except ValueError: return 'redirect_url_malformed'
    return 'allowed'

class Observer:
    """Read trusted frame locals only. Does not patch the helper, urllib, or policy."""
    def __init__(self, archive):
        self.archive = archive
        self.download_code = archive.download.__code__
        self.redirect_code = archive.OfficialRedirect.redirect_request.__code__
        self.total = 0
        self.expected_size = ARCHIVE_SIZE
        self.status = None
        self.host = 'unobserved'
        self.response_scheme_ok = None
        self.redirects = []

    def trace(self, frame, event, arg):
        if frame.f_code not in (self.download_code, self.redirect_code): return None
        if event == 'return':
            values = frame.f_locals
            if frame.f_code is self.download_code:
                self.expected_size = values['pin']['size']
                self.total = min(max(values.get('total', 0), 0), self.expected_size + 65536)
                response = values.get('response')
                if response is not None: self.status = status_number(response.status)
                parts = values.get('u')
                if parts is not None:
                    self.host = host_category(parts)
                    self.response_scheme_ok = parts.scheme == 'https'
            elif len(self.redirects) < 4:
                parts = values.get('p')
                self.redirects.append({'status': status_number(values.get('code')),
                    'host': host_category(parts) if parts is not None else 'malformed',
                    'decision': redirect_decision(parts, values['self'].count)})
        return self.trace

    def source_line(self, error):
        result = 0
        tb = error.__traceback__
        while tb is not None:
            if tb.tb_frame.f_globals is self.archive.__dict__ and tb.tb_frame.f_code.co_name != 'need':
                result = tb.tb_lineno if 1 <= tb.tb_lineno <= 103 else 0
            tb = tb.tb_next
        return result

    def classify(self, error, phase):
        if isinstance(error, Deadline): return 'deadline_exceeded'
        if isinstance(error, Interrupted): return 'interrupted'
        if isinstance(error, DiskBound): return 'disk_bound'
        line = self.source_line(error)
        if self.redirects and self.redirects[-1]['decision'] != 'allowed':
            return self.redirects[-1]['decision']
        cause = error
        for _ in range(8):
            if not isinstance(cause, urllib.error.URLError) or isinstance(cause, urllib.error.HTTPError): break
            if not isinstance(cause.reason, BaseException): return 'network_url_error'
            cause = cause.reason
        if isinstance(cause, urllib.error.HTTPError):
            self.status = status_number(cause.code)
            try: self.host = host_category(urllib.parse.urlsplit(cause.geturl()))
            except (ValueError, TypeError): self.host = 'malformed'
            if self.status is not None and 300 <= self.status < 400:
                # urllib can reject a Location scheme before calling OfficialRedirect.
                location = cause.headers.get('Location') if cause.headers is not None else None
                if isinstance(location, str):
                    try:
                        parts = urllib.parse.urlsplit(location)
                        if parts.scheme and parts.scheme != 'https': return 'redirect_scheme_denied'
                    except ValueError: return 'redirect_url_malformed'
                return 'http_redirect_error'
            return 'http_error'
        if isinstance(cause, socket.gaierror): return 'network_dns_error'
        if isinstance(cause, ssl.SSLCertVerificationError): return 'network_tls_certificate_error'
        if isinstance(cause, ssl.SSLError): return 'network_tls_error'
        if isinstance(cause, TimeoutError): return 'network_timeout'
        if isinstance(cause, (http.client.HTTPException, ConnectionError)): return 'network_transport_error'
        if isinstance(cause, OSError):
            if cause.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ECONNREFUSED, errno.ECONNRESET): return 'network_transport_error'
            return 'io_error'
        if isinstance(error, self.archive.ContractError):
            if phase == 'download':
                if line in (38, 45): return 'deadline_exceeded'
                if line == 42:
                    if self.status != 200: return 'response_status_mismatch'
                    if self.response_scheme_ok is False: return 'response_scheme_mismatch'
                    return 'response_host_mismatch'
                if line == 43: return 'response_length_mismatch'
                if line == 48 or (line == 49 and self.total != self.expected_size): return 'download_size_mismatch'
                if line == 49: return 'download_hash_mismatch'
            if phase == 'extract': return 'extraction_contract_failure'
            return 'input_contract_failure'
        if phase == 'extract':
            return 'extraction_archive_error' if isinstance(error, (tarfile.TarError, EOFError)) else 'extraction_error'
        if isinstance(error, ValueError): return 'network_url_or_value_error'
        return 'unexpected_failure'

class Checkpoint:
    def __init__(self, work, deadline):
        self.work, self.deadline, self.next_scan = work, deadline, 0
    def __call__(self, force=False):
        now = time.monotonic()
        if now >= self.deadline: raise Deadline()
        if force or now >= self.next_scan:
            total = 0
            for base, dirs, names in os.walk(self.work, followlinks=False):
                dirs[:] = [name for name in dirs if not (Path(base) / name).is_symlink()]
                for name in names:
                    path = Path(base) / name
                    if not path.is_symlink(): total += path.stat().st_size
            if total > 2 * GIB or shutil.disk_usage(self.work).free < GIB: raise DiskBound()
            self.next_scan = time.monotonic() + 2
        if time.monotonic() >= self.deadline: raise Deadline()

def record():
    return {'schema': 1, 'input': 'gettext', 'phase': 'preflight', 'status': 'failed',
            'failure_class': None, 'archive_source_line': 0, 'http_status': None, 'response_host': 'unobserved',
            'redirects': [], 'downloaded_bytes': 0, 'download_verified': False, 'extraction_verified': False,
            'cleanup': 'not_created', 'downloaded_code_executed': False, 'build_started': False,
            'native_checks_started': False, 'pdf_runtime_proven': False, 'artifact_uploaded': False, 'cache_used': False}

def diagnose(archive, pin, manifest, temp, result):
    observer = Observer(archive)
    work = None
    previous_trace = sys.gettrace()
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGALRM, signal.SIGTERM, signal.SIGINT)}
    def alarm(signum, frame): raise Deadline()
    def interrupted(signum, frame): raise Interrupted()
    try:
        signal.signal(signal.SIGALRM, alarm)
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        signal.setitimer(signal.ITIMER_REAL, 120)
        deadline = time.monotonic() + 120
        result['phase'] = 'input_preflight'
        if shutil.disk_usage(temp).free < 4 * GIB: raise DiskBound()
        work = Path(tempfile.mkdtemp(prefix='gettext-input-', dir=temp))
        checkpoint = Checkpoint(work, deadline)
        checkpoint(force=True)
        sys.settrace(observer.trace)
        result['phase'] = 'download'
        archive.download(pin, work / 'input.tar.gz', deadline)
        result['download_verified'] = True
        checkpoint(force=True)
        result['phase'] = 'extract'
        archive.extract(pin, work / 'input.tar.gz', work / 'tree', manifest, checkpoint)
        checkpoint(force=True)
        result['extraction_verified'] = True
        result['status'] = 'passed'
    except BaseException as error:
        result['status'] = 'failed'
        result['failure_class'] = observer.classify(error, result['phase'])
        result['archive_source_line'] = observer.source_line(error)
    finally:
        sys.settrace(previous_trace)
        signal.setitimer(signal.ITIMER_REAL, 0)
        if work is not None:
            try:
                signal.setitimer(signal.ITIMER_REAL, 10)
                shutil.rmtree(work)
                need(not work.exists())
                result['cleanup'] = 'removed'
            except BaseException:
                result['cleanup'] = 'failed'
                result['status'] = 'failed'
                if result['failure_class'] is None: result['failure_class'] = 'cleanup_failure'
        signal.setitimer(signal.ITIMER_REAL, 0)
        for sig, handler in handlers.items(): signal.signal(sig, handler)
    result.update(http_status=observer.status, response_host=observer.host,
                  redirects=observer.redirects, downloaded_bytes=observer.total)
    return result

def main(argv):
    result = record()
    try:
        need(len(argv) in (2, 3) and argv[0] == '--repository')
        execute = len(argv) == 3
        need(not execute or argv[2] == '--execute')
        root = Path(argv[1]).resolve()
        need(Path(__file__).resolve().parent == root / PACKAGE)
        pin = validate(root, execute)
        if not execute:
            result['status'] = 'passed'
        else:
            result['phase'] = 'host_guards'
            need(platform.system() == 'Darwin' and platform.mac_ver()[0].split('.')[0] == '26')
            need(platform.machine() == 'arm64' and sys.version_info >= (3, 9))
            need(os.environ.get('GITHUB_REPOSITORY') == 'Emin-dev/deepdesk')
            need(os.environ.get('GITHUB_REF') == 'refs/heads/' + BRANCH)
            need(os.environ.get('GITHUB_EVENT_NAME') in ('push', 'workflow_dispatch'))
            event_path = Path(os.environ.get('GITHUB_EVENT_PATH', ''))
            need(event_path.is_file() and event_path.stat().st_size < 2 * 1024 ** 2)
            event = json.loads(event_path.read_text())
            need(event.get('repository', {}).get('private') is False)
            need(event.get('repository', {}).get('full_name') == 'Emin-dev/deepdesk')
            temp = Path(os.environ.get('RUNNER_TEMP', '')).resolve()
            need(temp.is_dir() and temp != root and not temp.is_relative_to(root))
            result = diagnose(load_archive(root), pin, root / ORIGINAL / pin['member_manifest'], temp, result)
    except BaseException:
        result['status'] = 'failed'
        result['failure_class'] = 'preflight_or_host_guard_failed'
    encoded = json.dumps(result, sort_keys=True, separators=(',', ':'))
    if len(encoded.encode('utf-8')) > 4096:
        encoded = '{"schema":1,"status":"failed","failure_class":"output_bound"}'
    print(encoded, flush=True)
    return 0 if result['status'] == 'passed' else 1

if __name__ == '__main__': raise SystemExit(main(sys.argv[1:]))

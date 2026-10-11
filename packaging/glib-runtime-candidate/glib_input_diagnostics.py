"""Fixed, bounded input failure metadata; does not change retrieval/extraction policy.

Derived from the independently reviewed input-only diagnostic observer. Frame
observations are restricted to the receipt-hashed archive helper's two functions.
No request, redirect, header, response, archive, exception or frame is modified.
Line classifications intentionally match the unchanged archive_tools.py SHA-256
 d5273a166c7e3f3485cf8d0fd5f63551dee1b38a1cda3548f75e19553814a146.
"""
from __future__ import annotations
import errno
import http.client
import socket
import ssl
import tarfile
import urllib.error
import urllib.parse
import zipfile

INPUT_IDS = ('gettext', 'pcre2', 'pkgconf', 'meson', 'ninja', 'python', 'glib', 'libffi')

def status_number(value):
    return value if type(value) is int and 100 <= value <= 599 else None

def host_category(parts, origin, hosts):
    try:
        host = parts.hostname
        return 'origin' if host == origin else 'allowed_redirect' if host in hosts else 'other' if host else 'missing'
    except (ValueError, AttributeError): return 'malformed'

def redirect_decision(parts, count, hosts):
    # Match the original short-circuit policy in its original order; never follow here.
    if parts is None: return 'redirect_url_malformed'
    if count > 3: return 'redirect_count_denied'
    try:
        if parts.scheme != 'https': return 'redirect_scheme_denied'
        if parts.hostname not in hosts: return 'redirect_host_denied'
        if parts.port not in (None, 443): return 'redirect_port_denied'
        if parts.username or parts.password: return 'redirect_userinfo_denied'
        if parts.fragment: return 'redirect_fragment_denied'
    except ValueError: return 'redirect_url_malformed'
    return 'allowed'

class Observer:
    """Read trusted frame locals only. Does not patch the helper, urllib, or policy."""
    def __init__(self, archive, pin, boundary_errors=()):
        self.archive = archive
        self.input_id = pin['id'] if pin['id'] in INPUT_IDS else 'unknown'
        self.origin = urllib.parse.urlsplit(pin['url']).hostname
        self.hosts = tuple(pin['redirect_hosts'])
        self.boundary_errors = boundary_errors
        self.download_code = archive.download.__code__
        self.redirect_code = archive.OfficialRedirect.redirect_request.__code__
        self.total = 0
        self.expected_size = pin['size']
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
                    self.host = host_category(parts, self.origin, self.hosts)
                    self.response_scheme_ok = parts.scheme == 'https'
            elif len(self.redirects) < 4:
                parts = values.get('p')
                self.redirects.append({'status': status_number(values.get('code')),
                    'host': host_category(parts, self.origin, self.hosts) if parts is not None else 'malformed',
                    'decision': redirect_decision(parts, values['self'].count, self.hosts)})
        return self.trace

    def source_line(self, error):
        result = 0
        tb = error.__traceback__
        while tb is not None:
            if tb.tb_frame.f_globals is self.archive._base.__dict__ and tb.tb_frame.f_code.co_name != 'need':
                result = tb.tb_lineno if 1 <= tb.tb_lineno <= 103 else 0
            tb = tb.tb_next
        return result

    def classify(self, error, phase):
        if isinstance(error, self.boundary_errors): return 'input_boundary_failure'
        if phase != 'download':
            if phase != 'extract': return 'input_boundary_failure'
            if isinstance(error, self.archive.ContractError): return 'extraction_contract_failure'
            if isinstance(error, (tarfile.TarError, zipfile.BadZipFile, EOFError)): return 'extraction_archive_error'
            if isinstance(error, OSError): return 'extraction_io_error'
            return 'extraction_error'
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
            try: self.host = host_category(urllib.parse.urlsplit(cause.geturl()), self.origin, self.hosts)
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
            return 'input_contract_failure'
        if isinstance(error, ValueError): return 'network_url_or_value_error'
        return 'unexpected_failure'

    def failure_record(self, error, phase):
        return {'phase': 'input-' + self.input_id, 'input_phase': phase,
                'status': 'failed', 'failure_class': self.classify(error, phase), 'exit_code': None,
                'archive_source_line': self.source_line(error), 'http_status': self.status,
                'response_host': self.host, 'redirects': self.redirects, 'downloaded_bytes': self.total}

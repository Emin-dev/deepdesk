"""Synthetic transport checks only. No socket, backend, or dependency imports."""
import importlib.util
import json
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.parse

sys.dont_write_bytecode = True

spec = importlib.util.spec_from_file_location("fixture_api", Path(__file__).with_name("smoke_authenticated.py"))
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


class Process:
    def poll(self):
        return None


class Response:
    def __init__(self, status=200, data=None, headers=None):
        self.status, self.data = status, json.dumps(data or {}).encode()
        self.headers = [("X-Deepdesk-Instance", "fixture-nonce"), *(headers or [])]

    def getheader(self, name):
        return next((value for key, value in self.headers if key.lower() == name.lower()), None)

    def getheaders(self):
        return self.headers

    def read(self, limit):
        return self.data[:limit]


class Connection:
    response = None
    calls = []
    closed = 0

    def __init__(self, host, port, timeout):
        assert host == "127.0.0.1" and port == 54321 and timeout == 15

    def request(self, method, path, body, headers):
        self.calls.append((method, path, body, headers))

    def getresponse(self):
        return self.response

    def close(self):
        type(self).closed += 1


class FixtureClientTests(unittest.TestCase):
    def setUp(self):
        Connection.calls, Connection.closed = [], 0
        self.client = api.Client(Process(), 54321, "fixture-nonce")
        self.client.verified = True
        self.patcher = patch.object(api.http.client, "HTTPConnection", Connection)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_initial_handshake_has_no_token_or_cookies(self):
        self.client.verified = False
        self.client.cookies = {"session":"must-not-send"}
        Connection.response = Response()
        self.client.request("GET", "/api/v1/health", bootstrap=True)
        headers = Connection.calls[0][3]
        self.assertNotIn("Cookie", headers)
        self.assertNotIn("X-Deepdesk-Request", headers)
        self.assertTrue(self.client.verified)

    def test_nonbootstrap_refused_before_identity(self):
        self.client.verified = False
        with self.assertRaises(RuntimeError):
            self.client.request("GET", "/auth/check")
        self.assertEqual(Connection.calls, [])

    def test_collision_never_receives_nonce(self):
        self.client.verified = False
        Connection.response = Response()
        Connection.response.headers = [("X-Deepdesk-Instance", "other-listener")]
        with self.assertRaises(RuntimeError):
            self.client.request("GET", "/api/v1/health", bootstrap=True)
        self.assertNotIn("X-Deepdesk-Request", Connection.calls[0][3])
        self.assertFalse(self.client.verified)

    def test_synthetic_cookie_retained(self):
        Connection.response = Response(data={"csrf_token": "synthetic-token", "auth_context": None},
                                       headers=[("Set-Cookie", "session=synthetic; HttpOnly; Path=/; SameSite=lax")])
        self.client.refresh_csrf(False)
        self.client.request("GET", "/auth/check")
        self.assertEqual(Connection.calls[-1][3]["Cookie"], "session=synthetic")
        self.assertEqual(Connection.closed, 2)

    def test_cookie_deletion(self):
        self.client.cookies = {"session": "synthetic"}
        Connection.response = Response(headers=[("Set-Cookie", 'session=""; Max-Age=0; Path=/')])
        self.client.request("GET", "/auth/check")
        self.assertEqual(self.client.cookies, {})

    def test_domain_cookie_refused(self):
        Connection.response = Response(headers=[("Set-Cookie", "session=x; Domain=example.invalid")])
        with self.assertRaises(RuntimeError):
            self.client.request("GET", "/auth/check")

    def test_form_encoding_and_auth_context(self):
        self.client.csrf, self.client.context = "csrf-fixture", "context-fixture"
        Connection.response = Response(status=302, headers=[("Location", "/")])
        self.client.form("/auth/login", {"username": "synthetic", "password": "fixture1-&+=%"})
        method, path, body, headers = Connection.calls[0]
        self.assertEqual(urllib.parse.parse_qs(body.decode())["password"], ["fixture1-&+=%"])
        self.assertEqual(headers["X-CSRF-Token"], "csrf-fixture")
        self.assertEqual(headers["X-LDR-Auth-Context"], "context-fixture")
        self.assertEqual(len(Connection.calls), 1)  # No redirect follow.

    def test_spoofed_identity_refused(self):
        Connection.response = Response()
        Connection.response.headers = [("X-Deepdesk-Instance", "other-process")]
        with self.assertRaises(RuntimeError):
            self.client.request("GET", "/auth/check")

    def test_mutation_without_csrf_refused(self):
        Connection.response = Response()
        with self.assertRaises(RuntimeError):
            self.client.request("POST", "/auth/logout")
        self.assertEqual(Connection.calls, [])

    def test_wrong_context_shape_refused(self):
        Connection.response = Response(data={"csrf_token": "fixture", "auth_context": None})
        with self.assertRaises(RuntimeError):
            self.client.refresh_csrf(True)

    def test_oversized_body_refused(self):
        Connection.response = Response()
        Connection.response.data = b"x" * (2 * 1024 * 1024 + 1)
        with self.assertRaises(RuntimeError):
            self.client.request("GET", "/api/report/synthetic")


if __name__ == "__main__":
    unittest.main()

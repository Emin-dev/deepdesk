"""Actual installed-engine auth/report API smoke, with an explicitly synthetic DB.

No inference, search/provider enumeration, real research job, or external URL is
requested. Engine and seed subprocesses must run behind reviewed macOS sandbox
profiles. This client never follows redirects or connects to a different host.
"""
from __future__ import annotations
import argparse
import http.client
import importlib.util
import threading
import hashlib
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import platform
import secrets
import signal
import socket
import subprocess
import tempfile
import time
import urllib.parse
import uuid


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


class OwnedEngine:
    """Private bounded server output; nested process stays in outer owned group."""
    def __init__(self, command, **kwargs):
        self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        start_new_session=False, **kwargs)
        self.output_bytes, self.output_limit = 0, 2 * 1024 * 1024
        self.failure, self.lock = None, threading.Lock()
        self.digests = [hashlib.sha256(), hashlib.sha256()]
        self.threads = []
        for stream, digest in zip((self.process.stdout,self.process.stderr),self.digests):
            thread = threading.Thread(target=self.drain,args=(stream,digest),daemon=True)
            thread.start()
            self.threads.append(thread)

    def drain(self, stream, digest):
        try:
            while data := stream.read(65536):
                with self.lock:
                    self.output_bytes += len(data)
                    if self.output_bytes > self.output_limit:
                        self.failure = "Engine private-output limit exceeded"
                        if self.process.poll() is None:
                            self.process.kill()
                        return
                    digest.update(data)
        finally:
            stream.close()

    def poll(self):
        require(self.failure is None, self.failure or "Engine capture failed")
        return self.process.poll()

    def terminate(self):
        self.process.terminate()

    def kill(self):
        self.process.kill()

    def wait(self, timeout):
        result = self.process.wait(timeout=timeout)
        for thread in self.threads:
            thread.join(timeout=1)
        require(not any(thread.is_alive() for thread in self.threads), "Engine descendant kept a stream open")
        require(self.failure is None, self.failure or "Engine capture failed")
        return result

    @property
    def returncode(self):
        return self.process.returncode


class Client:
    def __init__(self, process, port, nonce):
        self.process, self.port, self.nonce = process, port, nonce
        self.cookies = {}
        self.csrf, self.context = None, None
        self.verified = False

    def request(self, method, path, body=None, content_type=None, auth=True, extra_headers=None, bootstrap=False):
        require(self.process.poll() is None, "Owned engine exited before request")
        require(self.verified or (bootstrap and method == "GET" and path == "/api/v1/health"),
                "Listener identity must be verified before authenticated requests")
        require(not bootstrap or (body is None and extra_headers is None), "Unsafe bootstrap request")
        headers = {"Accept": "application/json"}
        if not bootstrap:
            headers["X-Deepdesk-Request"] = self.nonce
        if self.cookies and not bootstrap:
            headers["Cookie"] = "; ".join(key + "=" + value for key, value in self.cookies.items())
        if content_type:
            headers["Content-Type"] = content_type
        if method != "GET" and auth:
            require(self.csrf, "Missing current CSRF token")
            headers["X-CSRF-Token"] = self.csrf
            if self.context:
                headers["X-LDR-Auth-Context"] = self.context
        headers.update(extra_headers or {})
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read(2 * 1024 * 1024 + 1)
            require(len(raw) <= 2 * 1024 * 1024, "Oversized fixture response")
            require(response.getheader("X-Deepdesk-Instance") == self.nonce, "Unexpected listener identity")
            require(self.process.poll() is None, "Owned engine exited during response")
            if bootstrap:
                require(response.status == 200, "Unexpected initial health status")
                self.verified = True
            for name, value in response.getheaders():
                if name.lower() == "set-cookie":
                    cookie = SimpleCookie(value)
                    for key, morsel in cookie.items():
                        require(not morsel["domain"], "Unexpected cookie domain")
                        if morsel["max-age"] == "0":
                            self.cookies.pop(key, None)
                        else:
                            self.cookies[key] = morsel.coded_value
            try:
                data = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                data = None
            return response.status, {key.lower(): value for key, value in response.getheaders()}, data
        finally:
            connection.close()

    def refresh_csrf(self, authenticated):
        status, _, data = self.request("GET", "/auth/csrf-token")
        require(status == 200 and isinstance(data, dict) and data.get("csrf_token"), "CSRF refresh failed")
        self.csrf, self.context = data["csrf_token"], data.get("auth_context")
        require(bool(self.context) == authenticated, "Unexpected auth context")

    def form(self, path, values):
        return self.request("POST", path, urllib.parse.urlencode(values).encode(), "application/x-www-form-urlencoded")

    def logout(self):
        status, _, _ = self.request("POST", "/auth/logout")
        require(status in (200, 302, 303), "Logout failed")
        status, _, data = self.request("GET", "/auth/check")
        require(status == 401 and data.get("authenticated") is False, "Logout retained authentication")
        self.cookies.clear()
        self.refresh_csrf(False)


def stop(process):
    require(process.poll() is None, "Owned process exited prematurely")
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        raise RuntimeError("Owned engine needed forced termination")
    require(process.returncode in (0, -signal.SIGTERM, 128 + signal.SIGTERM), "Unexpected engine exit")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--runtime-python", type=Path, required=True)
    parser.add_argument("--offline-profile", type=Path, required=True)
    parser.add_argument("--loopback-profile", type=Path, required=True)
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--immutable-root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    require(platform.system() == "Darwin" and platform.machine() == "arm64", "macOS arm64 runtime test only")
    engine = args.engine.resolve(strict=True)
    runtime_env = args.runtime_python.parent.parent.resolve(strict=True)
    runtime_python = runtime_env / "bin/python"  # Preserve venv symlink spelling.
    require(runtime_python.exists(), "Installed environment interpreter absent")
    require(1024 <= args.port < 65535, "Unexpected fixture port")
    immutable = args.immutable_root.resolve(strict=True)
    spec = importlib.util.spec_from_file_location("deepdesk_fixture_bounds", Path(__file__).with_name("bounded_runtime.py"))
    bounds = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bounds)
    seed = Path(__file__).with_name("seed_fixture.py").resolve(strict=True)
    sandbox = "/usr/bin/sandbox-exec"
    require(Path(sandbox).is_file(), "Required subprocess network sandbox unavailable")
    require(not args.fixture_root.exists() and args.fixture_root.parent.is_dir(), "Fixture root must be new")
    with tempfile.TemporaryDirectory(prefix=args.fixture_root.name + "-", dir=args.fixture_root.parent) as temporary:
        root = Path(temporary)
        marker = secrets.token_hex(32)
        (root / "deepdesk-ci-fixture-only").write_text(marker)
        env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": temporary, "TMPDIR": temporary,
               "LDR_DATA_DIR": str(root / "engine-data"), "LDR_WEB_HOST": "127.0.0.1",
               "LDR_BOOTSTRAP_ALLOW_UNENCRYPTED": "false", "LDR_ENABLE_FILE_LOGGING": "false",
               "LDR_APP_DEBUG": "false", "LDR_LOGURU_DIAGNOSE": "false",
               "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
               "ANONYMIZED_TELEMETRY": "false", "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1",
               "TOKENIZERS_PARALLELISM": "false", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
               "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
        username = "deepdesk_fixture_" + secrets.token_hex(6)
        password = "fixture1-&+=%" + secrets.token_hex(32)
        research_id = str(uuid.uuid4())
        process = None

        def start():
            port = args.port
            nonce = secrets.token_hex(32)
            launch_env = dict(env, LDR_WEB_PORT=str(port), DEEPDESK_INSTANCE_NONCE=nonce)
            proc = OwnedEngine([sandbox, "-D", "WORK_DIR=" + str(root.resolve()),
                "-D", "IMMUTABLE_DIR=" + str(immutable), "-D", "READONLY_ENV=" + str(runtime_env),
                "-D", "SERVER_ADDRESS=127.0.0.1:" + str(port), "-f", str(args.loopback_profile.resolve()),
                str(runtime_python), "-I", str(engine)], env=launch_env, cwd=temporary, stdin=subprocess.DEVNULL)
            client = Client(proc, port, nonce)
            deadline = time.monotonic() + 90
            try:
                while time.monotonic() < deadline:
                    require(proc.poll() is None, "Engine failed during startup")
                    try:
                        status, _, _ = client.request("GET", "/api/v1/health", bootstrap=True)
                        require(status == 200, "Unexpected health response")
                        return proc, client
                    except (OSError, TimeoutError):
                        time.sleep(0.25)
                raise RuntimeError("Engine health startup timed out")
            except BaseException:
                if proc.poll() is None:
                    stop(proc)
                raise

        try:
            process, client = start()
            status, _, _ = client.request("GET", "/history/api?limit=5&offset=0")
            require(status == 401, "History accepted unauthenticated caller")
            client.refresh_csrf(False)
            status, headers, _ = client.form("/auth/register", {"username": username, "password": password,
                "confirm_password": password, "acknowledge": "true"})
            require(status == 302 and headers.get("location") == "/", "Synthetic registration failed; do not retry")
            status, _, data = client.request("GET", "/auth/check")
            require(status == 200 and data.get("authenticated") is True and data.get("username") == username, "Registration session failed")
            client.refresh_csrf(True)
            status, _, data = client.request("GET", "/history/api?limit=5&offset=0")
            require(status == 200 and data.get("items") == [], "Synthetic account not empty")
            invalid = json.dumps({"query": "", "mode": "quick"}).encode()
            status, headers, _ = client.request("POST", "/api/start_research", invalid, "application/json",
                                                extra_headers={"X-CSRF-Token": "incorrect"})
            require(status == 403 and headers.get("x-ldr-csrf-rejected") == "1", "CSRF rejection failed")
            status, _, _ = client.request("POST", "/api/start_research", invalid, "application/json",
                                          extra_headers={"X-LDR-Auth-Context": "incorrect"})
            require(status == 409, "Account-context rejection failed")
            status, _, _ = client.request("POST", "/api/start_research", invalid, "application/json")
            require(status == 400, "Invalid start did not fail before research")
            status, _, data = client.request("GET", "/history/api?limit=5&offset=0")
            require(status == 200 and data.get("items") == [], "Rejected start created research state")
            client.logout()
            stop(process)
            process = None
            fixture = {"fixture_marker": marker, "username": username, "password": password, "research_id": research_id}
            seeded = bounds.run_bounded([sandbox, "-D", "WORK_DIR=" + str(root.resolve()),
                "-D", "IMMUTABLE_DIR=" + str(immutable), "-D", "READONLY_ENV=" + str(runtime_env),
                "-f", str(args.offline_profile.resolve()), str(runtime_python), "-I", str(seed)],
                input_data=json.dumps(fixture).encode(), env=env, cwd=temporary, work=root,
                disk_limit=128 * 1024**2, timeout=90, own_session=False, public_summary=False)
            require(json.loads(seeded) == {"status":"seeded","synthetic":True,
                    "model_executed":False,"provider_queried":False}, "Fixture persistence failed")
            process, client = start()
            status, _, _ = client.request("GET", "/api/report/" + research_id)
            require(status == 401, "Persisted report accepted unauthenticated caller")
            client.refresh_csrf(False)
            status, _, _ = client.form("/auth/login", {"username": username, "password": password + "wrong", "remember": "false"})
            require(status == 401, "Wrong password accepted")
            client.refresh_csrf(False)
            status, headers, _ = client.form("/auth/login", {"username": username, "password": password, "remember": "false"})
            require(status == 302 and headers.get("location") == "/", "Correct-key login after restart failed")
            status, _, data = client.request("GET", "/auth/check")
            require(status == 200 and data.get("authenticated") is True and data.get("username") == username,
                    "Restarted login account identity differs")
            client.refresh_csrf(True)
            status, _, data = client.request("GET", "/api/research/" + research_id + "/status")
            require(status == 200 and data.get("status") == "completed" and data.get("progress") == 100, "Fixture status mismatch")
            status, _, data = client.request("GET", "/api/report/" + research_id)
            require(status == 200 and data.get("summary") == data.get("content") and "Synthetic CI evidence" in data["content"], "Fixture report mismatch")
            require(any(source.get("url") == "https://fixture.invalid/evidence" for source in data.get("sources", [])), "Fixture citation missing")
            status, _, data = client.request("GET", "/history/api?limit=5&offset=0")
            require(status == 200 and any(item.get("id") == research_id for item in data.get("items", [])), "Fixture history missing")
            status, _, data = client.request("GET", "/settings/api")
            require(status == 200 and data.get("status") == "success" and isinstance(data.get("settings"), dict), "Authenticated settings failed")
            status, _, data = client.request("POST", "/api/terminate/" + research_id)
            require(status == 200 and data.get("status") == "success", "Already-terminal stop failed")
            client.logout()
        finally:
            if process is not None:
                stop(process)
    print(json.dumps({"status": "passed", "kind": "installed-authenticated-synthetic-api",
                      "checks": ["token-free-identity-handshake", "registration", "cookie-session", "csrf", "auth-context", "invalid-start",
                                 "rejected-start-no-history", "logout", "restart", "unauthenticated-report-rejected",
                                 "wrong-password", "correct-password", "restarted-account-identity", "fixture-status",
                                 "fixture-report-citation", "fixture-history", "settings", "already-terminal-stop"],
                      "research_execution_tested": False, "model_loaded": False, "provider_queried": False}))


if __name__ == "__main__":
    main()

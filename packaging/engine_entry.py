"""Deepdesk's frozen local engine entry point. Not executed in cloud preparation.

The upstream authenticated HTTP API and lifecycle are retained. This wrapper only
validates managed-launch settings, adds instance identity, and checks packaging.
"""
from __future__ import annotations

import importlib
import importlib.metadata
import hmac
import json
import multiprocessing
import os
from pathlib import Path
import re
import sys
import tempfile


class InstanceHeaderMiddleware:
    def __init__(self, app, nonce: str, port: int):
        self.app = app
        self.nonce = nonce.encode("ascii")
        self.host = f"127.0.0.1:{port}".encode("ascii")
        self.origin = b"http://" + self.host

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            # The native client uses authenticated non-overlapping HTTP polling.
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = scope.get("headers", [])
        hosts = [v for k, v in headers if k.lower() == b"host"]
        browser_signals = [v for k, v in headers if k.lower() in (b"origin", b"sec-fetch-site")]
        tokens = [v for k, v in headers if k.lower() == b"x-deepdesk-request"]
        handshake = scope.get("method") == "GET" and scope.get("path") == "/api/v1/health"
        valid = (
            hosts == [self.host]
            and not browser_signals
            and (handshake or (len(tokens) == 1 and hmac.compare_digest(tokens[0], self.nonce)))
        )
        if not valid:
            body = b'{"detail":"Managed engine request rejected"}'
            await send({"type": "http.response.start", "status": 403, "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"cache-control", b"no-store"),
            ]})
            await send({"type": "http.response.body", "body": body})
            return

        async def send_with_identity(message):
            if message["type"] == "http.response.start":
                message = dict(message)
                headers = [
                    (key, value) for key, value in message.get("headers", [])
                    if key.lower() != b"x-deepdesk-instance"
                ]
                headers.append((b"x-deepdesk-instance", self.nonce))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_identity)


def runtime_resources() -> Path:
    import local_deep_research
    root = Path(local_deep_research.__file__).resolve().parent
    providers = root / "llm" / "providers" / "implementations"
    if not providers.is_dir() or not list(providers.glob("*.py")):
        raise RuntimeError("Bundled provider source discovery files are missing")
    for resource in (root / "web" / "templates", root / "web" / "static"):
        if not resource.is_dir():
            raise RuntimeError(f"Required bundled resource directory missing: {resource.name}")
    app_source = root / "web" / "fastapi_app.py"
    if not app_source.is_file() or "DEEPDESK_MANAGED_RUNTIME" not in app_source.read_text():
        raise RuntimeError("Reviewed read-only bundle adaptation is missing")
    ddg_defaults = root / "defaults" / "settings_deepdesk_ddg.json"
    if not ddg_defaults.is_file():
        raise RuntimeError("Managed DuckDuckGo defaults are missing")
    ddg = json.loads(ddg_defaults.read_text())
    if ddg.get("search.engine.web.ddg.requires_api_key", {}).get("value") is not False:
        raise RuntimeError("Managed DuckDuckGo configuration is invalid")
    return root


def install_managed_inference_provider():
    """Keep the per-launch inference key out of persisted settings snapshots.

    Only this provider receives the key, only for the exact managed URL/model.
    No upstream session/CSRF/account behavior is replaced.
    """
    key = os.environ.pop("DEEPDESK_INFERENCE_API_KEY", "")
    endpoint = os.environ.get("DEEPDESK_INFERENCE_URL", "")
    model = os.environ.get("DEEPDESK_INFERENCE_MODEL", "")
    # Registered LDR_* API-key overrides are copied into research metadata;
    # deliberately never use that channel for the ephemeral managed bearer key.
    os.environ.pop("LDR_LLM_OPENAI_ENDPOINT_API_KEY", None)
    configured = bool(key or endpoint or model)
    match = re.fullmatch(r"http://127\.0\.0\.1:([0-9]{4,5})/v1", endpoint)
    if configured and not (
        re.fullmatch(r"[0-9a-f]{64}", key) and match
        and 1024 <= int(match.group(1)) <= 65535
        and model in {"mlx-community/Qwen3.8-27B-4bit", "orcarouter/Qwen3.8-27B-Uncensored-MLX"}
    ):
        raise RuntimeError("Invalid managed inference configuration")
    if configured:
        os.environ["LDR_LLM_PROVIDER"] = "openai_endpoint"
        os.environ["LDR_LLM_MODEL"] = model
        os.environ["LDR_LLM_OPENAI_ENDPOINT_URL"] = endpoint
    from local_deep_research.config.thread_settings import get_setting_from_snapshot
    from local_deep_research.llm.providers.implementations.custom_openai_endpoint import CustomOpenAIEndpointProvider

    def require_managed_endpoint(settings_snapshot):
        if not configured:
            raise RuntimeError("Managed inference is not running")
        actual = get_setting_from_snapshot("llm.openai_endpoint.url", default=endpoint,
                                           settings_snapshot=settings_snapshot)
        if actual != endpoint:
            raise RuntimeError("Research requested an unmanaged inference endpoint")

    def resolve_api_key(cls, settings_snapshot=None):
        require_managed_endpoint(settings_snapshot)
        return key

    original_create = CustomOpenAIEndpointProvider.create_llm

    def create_llm(cls, model_name=None, temperature=0.7, **kwargs):
        require_managed_endpoint(kwargs.get("settings_snapshot"))
        if model_name != model:
            raise RuntimeError("Research requested a model that is not loaded")
        return original_create(model_name, temperature, **kwargs)

    CustomOpenAIEndpointProvider.resolve_api_key = classmethod(resolve_api_key)
    CustomOpenAIEndpointProvider.create_llm = classmethod(create_llm)
    # Discovery stores a bound factory before these replacements. Deliberately
    # replace that registry callable too; otherwise model validation is bypassed.
    from local_deep_research.llm.llm_registry import register_llm
    register_llm("openai_endpoint", CustomOpenAIEndpointProvider.create_llm)


def self_test() -> None:
    # Isolate any package initialization. Never read the user's real LDR data.
    with tempfile.TemporaryDirectory(prefix="deepdesk-engine-self-test-") as temporary:
        os.environ["LDR_DATA_DIR"] = temporary
        os.environ["LDR_BOOTSTRAP_ALLOW_UNENCRYPTED"] = "false"
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        root = runtime_resources()
        imported = []
        for module in (
            "fastapi", "starlette", "uvicorn", "pydantic", "sqlalchemy",
            "sqlcipher3", "lxml.etree", "cryptography", "numpy", "pandas",
            "pyarrow", "torch", "faiss", "sentence_transformers", "weasyprint",
        ):
            importlib.import_module(module)
            imported.append(module)
        from sqlcipher3 import dbapi2 as sqlite
        database = Path(temporary) / "test.db"
        connection = sqlite.connect(str(database))
        connection.execute("PRAGMA key='deepdesk-build-self-test-only'")
        cipher_version = connection.execute("PRAGMA cipher_version").fetchone()
        if not cipher_version or not cipher_version[0]:
            raise RuntimeError("SQLCipher is unavailable; refusing plaintext fallback")
        connection.execute("CREATE TABLE proof (value TEXT NOT NULL)")
        connection.execute("INSERT INTO proof VALUES ('encrypted')")
        connection.commit()
        connection.close()
        if database.read_bytes().startswith(b"SQLite format 3"):
            raise RuntimeError("SQLCipher self-test produced a plaintext database")
        connection = sqlite.connect(str(database))
        connection.execute("PRAGMA key='deepdesk-build-self-test-only'")
        if connection.execute("SELECT value FROM proof").fetchone() != ("encrypted",):
            raise RuntimeError("Encrypted database round-trip failed")
        connection.close()
        print(json.dumps({
            "status": "passed", "kind": "packaging-self-test",
            "python": sys.version.split()[0],
            "sqlcipher": cipher_version[0], "imported": imported,
            "provider_sources": len(list((root / "llm/providers/implementations").glob("*.py"))),
            "network_research_tested": False,
            "authenticated_api_tested": False,
        }, sort_keys=True))


def serve() -> None:
    if os.environ.get("LDR_WEB_HOST") != "127.0.0.1":
        raise RuntimeError("Managed engine requires IPv4 loopback binding")
    try:
        port = int(os.environ["LDR_WEB_PORT"])
    except (KeyError, ValueError):
        raise RuntimeError("Missing or invalid managed engine port") from None
    if not 1024 <= port <= 65535:
        raise RuntimeError("Managed engine port must be unprivileged")
    nonce = os.environ.get("DEEPDESK_INSTANCE_NONCE", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", nonce):
        raise RuntimeError("Missing or invalid managed instance identity")
    data = Path(os.environ.get("LDR_DATA_DIR", ""))
    if not data.is_absolute():
        raise RuntimeError("Managed engine requires an absolute per-user data path")
    data.mkdir(parents=True, exist_ok=True)
    os.environ["LDR_BOOTSTRAP_ALLOW_UNENCRYPTED"] = "false"
    os.environ["LDR_APP_DEBUG"] = "false"
    os.environ["LDR_EXPOSE_DOCS"] = "false"
    os.environ["LDR_LOGURU_DIAGNOSE"] = "false"
    os.environ["LDR_ENABLE_FILE_LOGGING"] = "false"
    os.environ["LDR_WEB_USE_HTTPS"] = "false"
    os.environ.pop("PYTEST_CURRENT_TEST", None)
    os.environ.pop("LDR_TEST_MODE", None)
    os.environ["TRUST_PROXY_HEADERS"] = "false"
    os.environ["DEEPDESK_MANAGED_RUNTIME"] = "1"
    # Exact built-in generic search; its EXPOSING privacy classification and
    # upstream policy enforcement remain unchanged.
    os.environ["LDR_SEARCH_TOOL"] = "ddg"
    runtime_resources()
    install_managed_inference_provider()
    # Import the module-level ASGI app first; web.app.main's uvicorn string then
    # resolves this same cached object. Existing auth and lifespan remain intact.
    from local_deep_research.web.fastapi_app import app
    # Managed native mode has no interactive web/API documentation surface.
    docs_paths = {"/docs", "/api/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}
    app.router.routes[:] = [route for route in app.router.routes if getattr(route, "path", None) not in docs_paths]
    app.add_middleware(InstanceHeaderMiddleware, nonce=nonce, port=port)
    from local_deep_research.web.app import main
    main()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    if sys.argv[1:] == ["--self-test"]:
        self_test()
    elif sys.argv[1:]:
        raise SystemExit("Unsupported engine arguments")
    else:
        serve()

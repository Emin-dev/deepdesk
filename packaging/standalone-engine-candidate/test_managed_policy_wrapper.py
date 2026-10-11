"""First-party synthetic regressions; never import or execute upstream code.

Uses only stdlib, reviewed first-party wrappers, and the system C
compiler to run the reviewed launcher with a first-party inert interpreter.
This is not an inference, provider-policy implementation, or macOS runtime test.
"""
from __future__ import annotations

import ast
import builtins
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import runpy
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
CANDIDATE = HERE.parents[1]
ACCEPTED = CANDIDATE  # Current reviewed checkout; no local audit dependency.
WRAPPERS = ("packaging/engine_entry.py", "packaging/standalone-engine-candidate/engine_entry.py")
POLICY_FLAGS = ("LDR_LLM_REQUIRE_LOCAL_ENDPOINT", "LDR_EMBEDDINGS_REQUIRE_LOCAL")
MODELS = ("mlx-community/Qwen3.8-27B-4bit", "orcarouter/Qwen3.8-27B-Uncensored-MLX")
MANAGED = {
    "DEEPDESK_INFERENCE_API_KEY": "a" * 64,  # Synthetic fixture, never a user key.
    "DEEPDESK_INFERENCE_URL": "http://127.0.0.1:18544/v1",
    "DEEPDESK_INFERENCE_MODEL": MODELS[0],
}
ALLOWED = {
    "HOME", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "TZ",
    "LDR_WEB_HOST", "LDR_WEB_PORT", "LDR_DATA_DIR", "DEEPDESK_INSTANCE_NONCE",
    "DEEPDESK_INFERENCE_API_KEY", "DEEPDESK_INFERENCE_URL", "DEEPDESK_INFERENCE_MODEL",
}


@contextmanager
def synthetic_upstream():
    """Only in-memory stubs; unexpected upstream imports fail rather than run."""
    imported = []
    calls = []
    cloud_sentinel = object()
    registry = {"synthetic_cloud": cloud_sentinel}

    class Provider:
        @classmethod
        def create_llm(cls, model_name=None, temperature=0.7, **kwargs):
            calls.append((model_name, temperature, kwargs))
            return "synthetic-llm"

    def get_setting(key, default=None, settings_snapshot=None):
        value = (settings_snapshot or {}).get(key, default)
        return value["value"] if isinstance(value, dict) and "value" in value else value

    def register(name, function):
        registry[name] = function

    exports = {
        "local_deep_research.config.thread_settings": {"get_setting_from_snapshot": get_setting},
        "local_deep_research.llm.providers.implementations.custom_openai_endpoint": {
            "CustomOpenAIEndpointProvider": Provider,
        },
        "local_deep_research.llm.llm_registry": {"register_llm": register},
    }
    modules = {}
    for name, values in exports.items():
        parts = name.split(".")
        for length in range(1, len(parts) + 1):
            prefix = ".".join(parts[:length])
            if prefix not in modules:
                module = types.ModuleType(prefix)
                module.__path__ = []
                modules[prefix] = module
        modules[name].__dict__.update(values)
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.startswith("local_deep_research"):
            if name not in exports:
                raise AssertionError("Unexpected upstream import: " + name)
            imported.append((name, {flag: os.environ.get(flag) for flag in POLICY_FLAGS}))
        return real_import(name, *args, **kwargs)

    with patch.dict(sys.modules, modules), patch("builtins.__import__", side_effect=guarded_import):
        yield types.SimpleNamespace(provider=Provider, imports=imported, calls=calls,
                                    registry=registry, cloud=cloud_sentinel)


def wrapper(path):
    return runpy.run_path(str(path), run_name="synthetic_wrapper_contract")




class PortableSourceTests(unittest.TestCase):
    def test_exact_reviewed_wrapper_hashes(self):
        expected = {
            "packaging/engine_entry.py": "7e4fdbe84458f1e8aed760d44852ff3a9823c729f56d161f3dd163120f118f65",
            "packaging/standalone-engine-candidate/engine_entry.py": "ad8fc34f04809ad9b6a43922d47709a112e6aaedf04ddc427cae968edc5264d2",
        }
        for relative, digest in expected.items():
            self.assertEqual(hashlib.sha256((CANDIDATE / relative).read_bytes()).hexdigest(), digest)

    def test_only_validated_managed_branch_sets_both_flags(self):
        for relative in WRAPPERS:
            tree = ast.parse((CANDIDATE / relative).read_text())
            function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                            and node.name == "install_managed_inference_provider")
            conditional = next(node for node in function.body if isinstance(node, ast.If)
                               and isinstance(node.test, ast.Name) and node.test.id == "configured")
            expected = ast.parse("\n".join(f'os.environ["{flag}"] = "true"' for flag in POLICY_FLAGS)).body
            self.assertEqual([ast.dump(node) for node in conditional.body[:2]], [ast.dump(node) for node in expected])
            position = function.body.index(conditional)
            self.assertIsInstance(function.body[position - 1], ast.If)
            self.assertTrue(any(isinstance(node, ast.Raise) for node in function.body[position - 1].body))


class WrapperPolicyTests(unittest.TestCase):
    def test_configured_flags_true_before_any_upstream_provider_import(self):
        for relative in WRAPPERS:
            for model in MODELS:
                with self.subTest(wrapper=relative, model=model):
                    module = wrapper(CANDIDATE / relative)
                    with patch.dict(os.environ, {**MANAGED, "DEEPDESK_INFERENCE_MODEL": model}, clear=True), synthetic_upstream() as fake:
                        module["install_managed_inference_provider"]()
                        self.assertEqual(len(fake.imports), 3)
                        self.assertTrue(all(values == dict.fromkeys(POLICY_FLAGS, "true")
                                            for _, values in fake.imports))
                        self.assertEqual(os.environ["LDR_LLM_PROVIDER"], "openai_endpoint")
                        self.assertEqual(os.environ["LDR_LLM_MODEL"], model)
                        self.assertEqual(os.environ["LDR_LLM_OPENAI_ENDPOINT_URL"], MANAGED["DEEPDESK_INFERENCE_URL"])

    def test_configured_overrides_false_empty_or_malformed_flags(self):
        for relative in WRAPPERS:
            for supplied in ("false", "", "enabled", "0"):
                with self.subTest(wrapper=relative, supplied=supplied):
                    module = wrapper(CANDIDATE / relative)
                    with patch.dict(os.environ, {**MANAGED, **dict.fromkeys(POLICY_FLAGS, supplied)}, clear=True), synthetic_upstream():
                        module["install_managed_inference_provider"]()
                        self.assertEqual({flag: os.environ[flag] for flag in POLICY_FLAGS}, dict.fromkeys(POLICY_FLAGS, "true"))

    def test_unconfigured_does_not_introduce_local_policy(self):
        for relative in WRAPPERS:
            for empty_tuple in ({}, dict.fromkeys(MANAGED, "")):
                with self.subTest(wrapper=relative, empty_tuple=bool(empty_tuple)):
                    module = wrapper(CANDIDATE / relative)
                    with patch.dict(os.environ, empty_tuple, clear=True), synthetic_upstream() as fake:
                        module["install_managed_inference_provider"]()
                        self.assertTrue(all(flag not in os.environ for flag in POLICY_FLAGS))
                        self.assertTrue(all(values == dict.fromkeys(POLICY_FLAGS, None) for _, values in fake.imports))
                        self.assertNotIn("LDR_LLM_PROVIDER", os.environ)
                        with self.assertRaisesRegex(RuntimeError, "Managed inference is not running"):
                            fake.provider.resolve_api_key()

    def test_unrelated_explicit_cloud_settings_are_not_changed(self):
        selected = {"LDR_LLM_PROVIDER": "synthetic_cloud", "LDR_LLM_MODEL": "synthetic-cloud-model",
                    "LDR_EMBEDDINGS_PROVIDER": "synthetic_cloud", "LDR_POLICY_EGRESS_SCOPE": "public_only"}
        for relative in WRAPPERS:
            for policy in ({}, dict.fromkeys(POLICY_FLAGS, "false"), dict.fromkeys(POLICY_FLAGS, "true")):
                with self.subTest(wrapper=relative, policy=policy):
                    module = wrapper(CANDIDATE / relative)
                    environment = {**selected, **policy}
                    with patch.dict(os.environ, environment, clear=True), synthetic_upstream() as fake:
                        module["install_managed_inference_provider"]()
                        self.assertEqual(dict(os.environ), environment)
                        self.assertIs(fake.registry["synthetic_cloud"], fake.cloud)

    def test_invalid_or_partial_managed_tuple_fails_before_policy_and_imports(self):
        invalid = [
            {name: value for name, value in MANAGED.items() if name != omitted} for omitted in MANAGED
        ] + [
            {**MANAGED, "DEEPDESK_INFERENCE_API_KEY": "not-a-key"},
            {**MANAGED, "DEEPDESK_INFERENCE_MODEL": "unapproved-model"},
        ] + [
            {**MANAGED, "DEEPDESK_INFERENCE_URL": endpoint} for endpoint in (
                "http://localhost:18544/v1", "https://127.0.0.1:18544/v1",
                "http://192.168.1.1:18544/v1", "http://example.invalid:18544/v1",
                "http://127.0.0.1:1023/v1", "http://127.0.0.1:65536/v1",
                "http://127.0.0.1:18544/v1/", "http://127.0.0.1:18544/v1?target=cloud",
            )
        ]
        for relative in WRAPPERS:
            for index, environment in enumerate(invalid):
                with self.subTest(wrapper=relative, case=index):
                    module = wrapper(CANDIDATE / relative)
                    with patch.dict(os.environ, {**environment, **dict.fromkeys(POLICY_FLAGS, "false")}, clear=True), synthetic_upstream() as fake:
                        with self.assertRaisesRegex(RuntimeError, "^Invalid managed inference configuration$"):
                            module["install_managed_inference_provider"]()
                        self.assertEqual(fake.imports, [])
                        self.assertEqual({flag: os.environ[flag] for flag in POLICY_FLAGS}, dict.fromkeys(POLICY_FLAGS, "false"))
                        self.assertNotIn("LDR_LLM_PROVIDER", os.environ)

    def test_ephemeral_key_stays_out_of_environment_and_snapshot(self):
        for relative in WRAPPERS:
            with self.subTest(wrapper=relative):
                module = wrapper(CANDIDATE / relative)
                snapshot = {"llm.openai_endpoint.url": MANAGED["DEEPDESK_INFERENCE_URL"]}
                with patch.dict(os.environ, {**MANAGED, "LDR_LLM_OPENAI_ENDPOINT_API_KEY": "synthetic-legacy"}, clear=True), synthetic_upstream() as fake:
                    module["install_managed_inference_provider"]()
                    self.assertNotIn("DEEPDESK_INFERENCE_API_KEY", os.environ)
                    self.assertNotIn("LDR_LLM_OPENAI_ENDPOINT_API_KEY", os.environ)
                    self.assertNotIn(MANAGED["DEEPDESK_INFERENCE_API_KEY"], os.environ.values())
                    self.assertEqual(fake.provider.resolve_api_key(snapshot), MANAGED["DEEPDESK_INFERENCE_API_KEY"])
                    self.assertEqual(snapshot, {"llm.openai_endpoint.url": MANAGED["DEEPDESK_INFERENCE_URL"]})

    def test_model_endpoint_and_registry_guards_still_apply(self):
        for relative in WRAPPERS:
            with self.subTest(wrapper=relative):
                module = wrapper(CANDIDATE / relative)
                with patch.dict(os.environ, MANAGED, clear=True), synthetic_upstream() as fake:
                    module["install_managed_inference_provider"]()
                    factory = fake.registry["openai_endpoint"]
                    snapshot = {"llm.openai_endpoint.url": MANAGED["DEEPDESK_INFERENCE_URL"],
                                "llm.require_local_endpoint": False, "embeddings.require_local": False}
                    self.assertEqual(factory(MODELS[0], 0.3, settings_snapshot=snapshot), "synthetic-llm")
                    self.assertEqual(len(fake.calls), 1)
                    with self.assertRaisesRegex(RuntimeError, "model that is not loaded"):
                        factory("other-model", settings_snapshot=snapshot)
                    wrong = {"llm.openai_endpoint.url": "http://127.0.0.1:18545/v1"}
                    with self.assertRaisesRegex(RuntimeError, "unmanaged inference endpoint"):
                        fake.provider.resolve_api_key(wrong)
                    with self.assertRaisesRegex(RuntimeError, "unmanaged inference endpoint"):
                        factory(MODELS[0], settings_snapshot=wrong)
                    self.assertEqual(len(fake.calls), 1)
                    self.assertIs(fake.registry["synthetic_cloud"], fake.cloud)
                    self.assertEqual({flag: os.environ[flag] for flag in POLICY_FLAGS}, dict.fromkeys(POLICY_FLAGS, "true"))


STUB = r'''
#include <stdio.h>
extern char **environ;
int main(void) {
    for (char **entry = environ; *entry; entry++) puts(*entry);
    return 0;
}
'''


@unittest.skipUnless(sys.platform == "linux" or (sys.platform == "darwin" and platform.machine() == "arm64"),
                     "Linux synthetic host or arm64 macOS required")
class LauncherIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = next((path for path in ("/usr/bin/clang", "/usr/bin/cc") if Path(path).is_file()), None)
        if compiler is None:
            raise unittest.SkipTest("System C compiler unavailable; no downloaded compiler permitted")
        cls.temporary = tempfile.TemporaryDirectory(prefix="deepdesk-policy-firstparty-")
        cls.addClassCleanup(cls.temporary.cleanup)
        root = Path(cls.temporary.name)
        resources = root / "DeepdeskEngine.app/Contents/Resources"
        cls.launcher = root / "DeepdeskEngine.app/Contents/MacOS/DeepdeskEngine"
        interpreter = resources / "Python/bin/python3.12"
        interpreter.parent.mkdir(parents=True)
        cls.launcher.parent.mkdir(parents=True)
        stub = root / "synthetic-interpreter.c"
        stub.write_text(STUB)
        (resources / "engine_entry.py").write_text("# Inert fixture; never interpreted.\n")
        for source, target in ((stub, interpreter),
                               (ACCEPTED / "packaging/standalone-engine-candidate/launcher.c", cls.launcher)):
            result = subprocess.run([compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                                     str(source), "-o", str(target)], capture_output=True, text=True,
                                    timeout=30, check=False)
            if result.returncode:
                raise AssertionError("First-party C compilation failed: " + result.stderr)

    def filtered_environment(self, extra=None):
        native = {**MANAGED, "HOME": "/synthetic", "LDR_WEB_HOST": "127.0.0.1", "LDR_WEB_PORT": "5001",
                  "LDR_DATA_DIR": "/synthetic-data", "DEEPDESK_INSTANCE_NONCE": "b" * 64,
                  **dict.fromkeys(POLICY_FLAGS, "true"),
                  "LDR_LLM_PROVIDER": "untrusted-parent-provider", "PYTHONPATH": "/not-used",
                  "ARBITRARY_PARENT_VARIABLE": "not-forwarded", **(extra or {})}
        process = subprocess.run([str(self.launcher)], env=native, cwd="/", capture_output=True,
                                 text=True, timeout=10, check=False)
        self.assertEqual((process.returncode, process.stderr), (0, ""))
        actual = dict(line.split("=", 1) for line in process.stdout.splitlines())
        self.assertEqual(actual, {name: value for name, value in native.items() if name in ALLOWED})
        return actual

    def test_actual_launcher_drops_both_flags_and_keeps_exact_whitelist(self):
        actual = self.filtered_environment()
        self.assertTrue(all(flag not in actual for flag in POLICY_FLAGS))
        self.assertEqual({key: actual[key] for key in MANAGED}, MANAGED)


    def test_proposed_wrapper_restores_policy_after_same_unchanged_launcher(self):
        environment = self.filtered_environment()
        for relative in WRAPPERS:
            with self.subTest(wrapper=relative):
                module = wrapper(CANDIDATE / relative)
                with patch.dict(os.environ, environment, clear=True), synthetic_upstream() as fake:
                    module["install_managed_inference_provider"]()
                    self.assertEqual({flag: os.environ[flag] for flag in POLICY_FLAGS}, dict.fromkeys(POLICY_FLAGS, "true"))
                    self.assertTrue(all(values == dict.fromkeys(POLICY_FLAGS, "true") for _, values in fake.imports))
                    self.assertEqual(fake.provider.resolve_api_key(), MANAGED["DEEPDESK_INFERENCE_API_KEY"])


if __name__ == "__main__":
    unittest.main()

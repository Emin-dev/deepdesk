"""Compile only first-party C and run synthetic interpreter fixtures.

These tests do not execute CPython archives, wheels or the production wrapper.
macOS-specific dyld behavior remains unproved on a Linux test host.
"""
from __future__ import annotations

import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
STUB_SOURCE = r'''
#define _XOPEN_SOURCE 700
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
extern char **environ;
static void string(const char *value) {
    putchar('"');
    for (const unsigned char *p = (const unsigned char *)value; *p; p++) {
        if (*p == '"' || *p == '\\') { putchar('\\'); putchar(*p); }
        else if (*p < 32) printf("\\u%04x", *p);
        else putchar(*p);
    }
    putchar('"');
}
int main(int argc, char **argv) {
    printf("{\"pid\":%ld,\"args\":[", (long)getpid());
    for (int i = 0; i < argc; i++) { if(i) putchar(','); string(argv[i]); }
    printf("],\"environment\":[");
    for (int i = 0; environ[i]; i++) { if(i) putchar(','); string(environ[i]); }
    puts("]}");
    return 0;
}
'''


@unittest.skipUnless(sys.platform == "linux" or (sys.platform == "darwin" and platform.machine() == "arm64"),
                     "Linux synthetic host or arm64 macOS required")
class LauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = next((Path(p) for p in ("/usr/bin/clang", "/usr/bin/cc")
                             if Path(p).is_file()), None)
        if cls.compiler is None:
            raise unittest.SkipTest("No system C compiler; no downloaded compiler is used")
        cls.build = tempfile.TemporaryDirectory(prefix="deepdesk-firstparty-c-")
        build = Path(cls.build.name)
        stub_source = build / "synthetic_interpreter.c"
        stub_source.write_text(STUB_SOURCE)
        cls.stub = build / "synthetic_interpreter"
        cls.launcher = build / "DeepdeskEngine"
        cls.header_probe = build / "header-probe"
        header_source = build / "header-probe.c"
        header_source.write_text(
            "#define main launcher_main\n#include " + json.dumps(str(HERE / "launcher.c")) +
            "\n#undef main\n" + r"""
int main(void) {
    unsigned char arm[20] = {0xcf, 0xfa, 0xed, 0xfe, 12, 0, 0, 1, 0, 0, 0, 0, 2};
    unsigned char elf[20] = {0x7f, 'E', 'L', 'F', 2, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2};
    unsigned char script[20] = {'#', '!', '/', 'b', 'i', 'n', '/', 's', 'h'};
    if (!native_header(arm, 1) || native_header(arm, 0)) return 1;
    if (!native_header(elf, 0) || native_header(elf, 1)) return 2;
    if (native_header(script, 0) || native_header(script, 1)) return 3;
    arm[4] = 7; if (native_header(arm, 1)) return 4; /* x86_64 */
    arm[4] = 12; arm[7] = 0; if (native_header(arm, 1)) return 5; /* arm32 */
    arm[7] = 1; arm[12] = 6; if (native_header(arm, 1)) return 6; /* dylib */
    arm[12] = 2; arm[0] = 0xca; if (native_header(arm, 1)) return 7; /* not thin */
    return 0;
}
""")
        for source, output in ((stub_source, cls.stub), (HERE / "launcher.c", cls.launcher),
                               (header_source, cls.header_probe)):
            subprocess.run([str(cls.compiler), "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                            str(source), "-o", str(output)], check=True, capture_output=True, text=True,
                           timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="deepdesk-launcher-test-")
        self.root = Path(self.temporary.name)
        self.app = self.root / "DeepdeskEngine.app"
        self.resources = self.app / "Contents/Resources"
        self.python = self.resources / "Python"
        self.image = self.python / "bin/python3.12"
        self.executable = self.app / "Contents/MacOS/DeepdeskEngine"
        self.image.parent.mkdir(parents=True)
        self.executable.parent.mkdir(parents=True)
        shutil.copy2(self.stub, self.image)
        shutil.copy2(self.launcher, self.executable)
        (self.resources / "engine_entry.py").write_text("# Synthetic fixture, not executed.\n")
        self.unrelated = self.root / "unrelated cwd"
        self.unrelated.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def run_launcher(self, arguments=(), environment=None):
        process = subprocess.Popen([str(self.executable), *arguments], cwd=self.unrelated,
                                   env=environment or {}, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        out, error = process.communicate(timeout=10)
        return process, out, error

    def assert_refused(self, arguments=()):
        process, out, error = self.run_launcher(arguments)
        self.assertEqual(process.returncode, 78, (out, error))
        self.assertEqual(out, "")
        self.assertTrue(error.startswith("DeepdeskEngine: "), error)
        self.assertNotIn(str(self.root), error)

    def test_production_arm64_native_header_and_linux_fixture_headers(self):
        result = subprocess.run([str(self.header_probe)], check=False, capture_output=True, timeout=10)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))

    def test_exact_no_argument_contract_and_exec_pid(self):
        process, out, error = self.run_launcher()
        self.assertEqual((process.returncode, error), (0, ""))
        receipt = json.loads(out)
        self.assertEqual(receipt["pid"], process.pid)
        self.assertEqual(receipt["args"], [str(self.image), "-I", "-B", str(self.resources / "engine_entry.py")])
        self.assertEqual(receipt["environment"], [])

    def test_self_test_contract(self):
        process, out, error = self.run_launcher(["--self-test"])
        self.assertEqual((process.returncode, error), (0, ""))
        self.assertEqual(json.loads(out)["args"][-1], "--self-test")
        self.assertEqual(len(json.loads(out)["args"]), 5)

    def test_core_self_test_is_a_distinct_explicit_flag(self):
        process, out, error = self.run_launcher(["--core-self-test"])
        self.assertEqual((process.returncode, error), (0, ""))
        self.assertEqual(json.loads(out)["args"][-1], "--core-self-test")
        self.assertEqual(len(json.loads(out)["args"]), 5)

    def test_all_other_arguments_refused(self):
        for arguments in (["-c", "malicious"], ["--help"], [""], ["--self-test", "extra"],
                          ["--self-test=1"], ["--core-self-test", "extra"], ["--core-self-test=1"],
                          ["--self-test", "--core-self-test"]):
            with self.subTest(arguments=arguments):
                self.assert_refused(arguments)

    def test_injection_environment_removed_managed_inputs_retained(self):
        managed = {
            "HOME": str(self.root / "fixture home"), "TMPDIR": str(self.root),
            "LANG": "C", "LC_ALL": "C", "LC_CTYPE": "C", "TZ": "UTC",
            "LDR_WEB_HOST": "127.0.0.1", "LDR_WEB_PORT": "18543",
            "LDR_DATA_DIR": str(self.root / "synthetic data"),
            "DEEPDESK_INSTANCE_NONCE": "n" * 32,
            "DEEPDESK_INFERENCE_API_KEY": "a" * 64,
            "DEEPDESK_INFERENCE_URL": "http://127.0.0.1:18544/v1",
            "DEEPDESK_INFERENCE_MODEL": "synthetic-model",
        }
        hostile = {
            "PATH": "/untrusted", "PYTHONHOME": "/untrusted", "PYTHONPATH": "/untrusted",
            "PYTHONSTARTUP": "/untrusted.py", "PYTHONINSPECT": "1", "PYTHONEXECUTABLE": "/untrusted",
            "__PYVENV_LAUNCHER__": "/untrusted", "VIRTUAL_ENV": "/untrusted", "CONDA_PREFIX": "/untrusted",
            "DYLD_LIBRARY_PATH": "/untrusted", "DYLD_FRAMEWORK_PATH": "/untrusted",
            "DYLD_FALLBACK_LIBRARY_PATH": "/untrusted", "DYLD_PRINT_LIBRARIES": "1",
            "DYLD_INSERT_LIBRARIES": "", "LD_PRELOAD": "",
            "LD_LIBRARY_PATH": "/untrusted", "PIP_CONFIG_FILE": "/untrusted",
            "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
            "LDR_TEST_MODE": "1", "LDR_BOOTSTRAP_ALLOW_UNENCRYPTED": "true",
            "DEEPDESK_PYTHON": "/untrusted", "DEEPDESK_ENGINE_ENTRY": "/untrusted.py",
            "WEASYPRINT_DLL_DIRECTORIES": "/untrusted", "MAGIC": "/untrusted",
            "FONTCONFIG_FILE": "/untrusted", "PYPANDOC_PANDOC": "/untrusted",
        }
        # These empty injection values do not name or load any library. Supplying
        # valid DYLD_INSERT_LIBRARIES/LD_PRELOAD payloads would run them before main().
        process, out, error = self.run_launcher(environment={**managed, **hostile})
        self.assertEqual(process.returncode, 0, error)
        actual = dict(entry.split("=", 1) for entry in json.loads(out)["environment"])
        self.assertEqual(actual, managed)

    def test_relocation_spaces_unicode_no_original_and_no_cwd_dependency(self):
        old = self.app
        destination = self.root / "other place \u00e9 \u6771\u4eac"
        destination.mkdir()
        new = destination / "DeepdeskEngine.app"
        self.app.rename(new)
        self.assertFalse(old.exists())
        self.executable = new / "Contents/MacOS/DeepdeskEngine"
        process, out, error = self.run_launcher(["--self-test"])
        self.assertEqual((process.returncode, error), (0, ""))
        result = json.loads(out)
        self.assertEqual(result["pid"], process.pid)
        self.assertEqual(result["args"][0], str(new / "Contents/Resources/Python/bin/python3.12"))
        self.assertEqual(result["args"][3], str(new / "Contents/Resources/engine_entry.py"))
        self.assertNotIn(str(old), out)

    def test_missing_and_nonexecutable_interpreter_refused(self):
        self.image.unlink()
        self.assert_refused()
        self.image.write_text("not executable")
        self.image.chmod(0o644)
        self.assert_refused()

    def test_shebang_interpreter_refused_without_shell_execution(self):
        marker = self.root / "shell-must-not-run"
        self.image.write_text(f"#!/bin/sh\n/usr/bin/touch '{marker}'\n")
        self.image.chmod(0o755)
        self.assert_refused()
        self.assertFalse(marker.exists())

    def test_interpreter_relative_link_stays_in_bin(self):
        actual = self.image.with_name("python3.12-real")
        self.image.rename(actual)
        self.image.symlink_to(actual.name)
        process, out, error = self.run_launcher()
        self.assertEqual((process.returncode, error), (0, ""))
        self.assertEqual(json.loads(out)["args"][0], str(actual))

    def test_absolute_escape_loop_and_dangling_interpreter_links_refused(self):
        self.image.unlink()
        for target in (str(self.stub), "../../../../../missing", "missing", "python3.12"):
            with self.subTest(target=target):
                self.image.symlink_to(target)
                self.assert_refused()
                self.image.unlink()

    def test_absolute_interpreter_link_rejected_even_if_inside_bundle(self):
        actual = self.image.with_name("python3.12-real")
        self.image.rename(actual)
        self.image.symlink_to(actual)
        self.assert_refused()

    def test_outside_bin_image_rejected_even_if_inside_python(self):
        actual = self.python / "python-other"
        self.image.rename(actual)
        self.image.symlink_to("../python-other")
        self.assert_refused()

    def test_relative_link_can_not_escape_and_return(self):
        actual = self.image.with_name("python3.12-real")
        self.image.rename(actual)
        # Target exists inside the bundle after resolution, but crossing out of
        # the Python prefix and returning through an alias is still rejected.
        (self.resources / "return-to-python").symlink_to("Python", target_is_directory=True)
        self.image.symlink_to("../../return-to-python/bin/python3.12-real")
        self.assert_refused()

    def test_escape_after_directory_link_is_refused(self):
        actual = self.image.with_name("python3.12-real")
        self.image.rename(actual)
        (self.python / "nested").mkdir()
        (self.python / "nested/up").symlink_to("..", target_is_directory=True)
        (self.resources / "return-to-python").symlink_to("Python", target_is_directory=True)
        self.image.symlink_to("../nested/up/../return-to-python/bin/python3.12-real")
        self.assertEqual(self.image.resolve(strict=True), actual)
        self.assert_refused()

    def test_file_used_as_directory_in_link_is_refused(self):
        actual = self.image.with_name("python3.12-real")
        self.image.rename(actual)
        self.image.symlink_to("python3.12-real/../python3.12-real")
        self.assert_refused()

    def test_missing_linked_and_directory_wrapper_refused(self):
        wrapper = self.resources / "engine_entry.py"
        wrapper.unlink()
        self.assert_refused()
        wrapper.symlink_to(self.root / "outside.py")
        self.assert_refused()
        wrapper.unlink()
        (self.resources / "alias.py").write_text("# synthetic")
        wrapper.symlink_to("alias.py")
        self.assert_refused()
        wrapper.unlink()
        wrapper.mkdir()
        self.assert_refused()

    def test_venv_marker_refused(self):
        for relative in ("pyvenv.cfg", "bin/pyvenv.cfg"):
            with self.subTest(relative=relative):
                marker = self.python / relative
                marker.write_text("home = /untrusted\n")
                self.assert_refused()
                marker.unlink()

    def test_linked_structural_directory_refused(self):
        target = self.resources / "OtherPython"
        self.python.rename(target)
        self.python.symlink_to("OtherPython", target_is_directory=True)
        self.assert_refused()

    def test_launcher_outside_fixed_app_layout_refused(self):
        self.executable = self.root / "DeepdeskEngine"
        shutil.copy2(self.launcher, self.executable)
        self.assert_refused()


if __name__ == "__main__":
    unittest.main()

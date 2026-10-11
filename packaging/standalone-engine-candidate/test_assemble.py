"""Host-stdlib tests; synthetic payload only, no installed dependency imports."""
from __future__ import annotations

import copy
import importlib.util
import os
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("candidate_assemble", HERE / "assemble.py")
assert SPEC and SPEC.loader
assemble = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assemble)
WRAPPER = HERE.parent / "engine_entry.py"


def synthetic_prefix(path: Path) -> Path:
    for relative in ("bin", "lib/python3.12/site-packages", "lib/python3.12/encodings",
                     "lib/python3.12/importlib", "share/licenses", "include/python3.12"):
        (path / relative).mkdir(parents=True, exist_ok=True)
    payloads = {
        "bin/python3.12": b"synthetic interpreter bytes; never executed by assembly tests\n",
        "lib/python3.12/os.py": b"# synthetic stdlib\n",
        "lib/python3.12/encodings/__init__.py": b"# synthetic encodings\n",
        "lib/python3.12/importlib/__init__.py": b"# synthetic importlib\n",
        "lib/python3.12/site-packages/provider.py": b"# every provider must remain\n",
        "lib/python3.12/site-packages/dummy-1.dist-info/RECORD": b"provider.py,,\n",
        "lib/python3.12/site-packages/driver/package/cli.js": b"/* retained browser driver */\n",
        "lib/python3.12/site-packages/web/static/na\u00efve asset.css": b"body{}\n",
        "lib/python3.12/site-packages/.hidden-resource": b"retained hidden payload\n",
        "share/licenses/LICENSE": b"retained license\n",
        "include/python3.12/pyconfig.h": b"/* synthetic header */\n",
    }
    for relative, content in payloads.items():
        target = path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        target.chmod(0o755 if relative == "bin/python3.12" else 0o640)
    (path / "bin/python3").symlink_to("python3.12")
    (path / "include/current").symlink_to("python3.12", target_is_directory=True)
    (path / "share/licenses").chmod(0o750)
    path.chmod(0o750)
    return path


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="deepdesk-assembly-test-")
        self.root = Path(self.temporary.name)
        self.prefix = synthetic_prefix(self.root / "prefix")
        self.launcher = self.root / "first-party-launcher"
        self.launcher.write_bytes(b"synthetic first-party launcher bytes\n")
        self.launcher.chmod(0o751)
        self.launcher_hash = assemble.sha256_file(self.launcher)
        self.manifest = assemble.inventory_tree(self.prefix)
        self.output = self.root / "DeepdeskEngine.app"

    def tearDown(self):
        self.temporary.cleanup()

    def run_assembly(self, **overrides):
        values = dict(prefix=self.prefix, wrapper=WRAPPER, launcher=self.launcher,
                      destination=self.output, expected_prefix_manifest=self.manifest,
                      expected_launcher_sha256=self.launcher_hash)
        values.update(overrides)
        return assemble.assemble_bundle(**values)

    def test_preserves_every_member_mode_link_and_hash(self):
        receipt = self.run_assembly()
        copied = self.output / "Contents/Resources/Python"
        self.assertEqual(assemble.inventory_tree(copied), self.manifest)
        self.assertEqual(assemble.inventory_tree(self.prefix), self.manifest)
        self.assertEqual(os.readlink(copied / "bin/python3"), "python3.12")
        self.assertEqual(stat.S_IMODE((self.output / "Contents/MacOS/DeepdeskEngine").stat().st_mode), 0o751)
        self.assertEqual((self.output / "Contents/Resources/engine_entry.py").read_bytes(), WRAPPER.read_bytes())
        self.assertEqual(receipt["bundle_manifest"], assemble.inventory_tree(self.output))
        self.assertFalse(receipt["native_features_complete"])
        self.assertFalse(receipt["ready_for_execution"])
        self.assertFalse(receipt["payload_execution_performed"])

    def test_full_content_manifest_is_independent_of_relocation(self):
        receipt = self.run_assembly()
        relocated_parent = self.root / "different place \u00e9 \u6771\u4eac"
        relocated_parent.mkdir()
        relocated = relocated_parent / self.output.name
        self.output.rename(relocated)
        self.assertFalse(self.output.exists())
        actual = assemble.inventory_tree(relocated)
        self.assertEqual(actual, receipt["bundle_manifest"])
        self.assertEqual(assemble.manifest_digest(actual), receipt["bundle_manifest_sha256"])

    def test_wrapper_mismatch_rejected_before_output_exists(self):
        wrapper = self.root / "engine_entry.py"
        wrapper.write_bytes(WRAPPER.read_bytes() + b"\n# unreviewed\n")
        with self.assertRaisesRegex(assemble.AssemblyError, "wrapper SHA-256"):
            self.run_assembly(wrapper=wrapper)
        self.assertFalse(self.output.exists())

    def test_candidate_wrapper_requires_explicit_exact_hash(self):
        candidate = self.root / "candidate-wrapper.py"
        candidate.write_bytes(WRAPPER.read_bytes() + b"\n# synthetic candidate change; never executed\n")
        with self.assertRaisesRegex(assemble.AssemblyError, "wrapper SHA-256"):
            self.run_assembly(wrapper=candidate)
        expected = assemble.sha256_file(candidate)
        receipt = self.run_assembly(wrapper=candidate, expected_wrapper_sha256=expected)
        self.assertEqual(receipt["wrapper_sha256"], expected)
        self.assertEqual((self.output / "Contents/Resources/engine_entry.py").read_bytes(), candidate.read_bytes())
        self.assertFalse(receipt["ready_for_execution"])
        self.assertFalse(receipt["native_features_complete"])

    def test_invalid_explicit_wrapper_hash_is_rejected(self):
        for value in ("auto", "", "0" * 63, assemble.WRAPPER_SHA256.upper()):
            with self.subTest(value=value):
                with self.assertRaisesRegex(assemble.AssemblyError, "wrapper SHA-256"):
                    self.run_assembly(expected_wrapper_sha256=value)
        self.assertFalse(self.output.exists())

    def test_launcher_hash_mismatch_rejected(self):
        with self.assertRaisesRegex(assemble.AssemblyError, "launcher SHA-256"):
            self.run_assembly(expected_launcher_sha256="0" * 64)
        self.assertFalse(self.output.exists())

    def test_rejects_unreviewed_content_addition_deletion_and_mode(self):
        for change in ("addition", "deletion", "mode", "bytes", "link"):
            with self.subTest(change=change):
                expected = copy.deepcopy(self.manifest)
                if change == "addition":
                    expected["entries"].pop()
                elif change == "deletion":
                    expected["entries"].append({"path": "missing", "kind": "file", "mode": 0o644, "size": 0, "sha256": "0" * 64})
                elif change == "mode":
                    expected["entries"][0]["mode"] = 0o755
                elif change == "bytes":
                    next(e for e in expected["entries"] if e["kind"] == "file")["sha256"] = "0" * 64
                else:
                    next(e for e in expected["entries"] if e["kind"] == "symlink")["target"] = "different"
                with self.assertRaisesRegex(assemble.AssemblyError, "manifest mismatch"):
                    self.run_assembly(expected_prefix_manifest=expected)
                self.assertFalse(self.output.exists())

    def test_venv_markers_rejected_even_with_matching_manifest(self):
        for relative in ("pyvenv.cfg", "bin/pyvenv.cfg"):
            with self.subTest(relative=relative):
                marker = self.prefix / relative
                marker.write_text("home = /outside/python\n")
                with self.assertRaisesRegex(assemble.AssemblyError, "venv"):
                    self.run_assembly(expected_prefix_manifest=assemble.inventory_tree(self.prefix))
                marker.unlink()
        self.assertFalse(self.output.exists())

    def test_rejects_absolute_escaping_dangling_and_cyclic_links(self):
        external = self.root / "external"
        external.write_text("not payload")
        for target in (str(external), "../external", "missing", "bad"):
            with self.subTest(target=target):
                link = self.prefix / "bad"
                link.symlink_to(target)
                with self.assertRaises(assemble.AssemblyError):
                    assemble.inventory_tree(self.prefix)
                link.unlink()

    def test_rejects_escaping_link_that_returns_inside(self):
        (self.root / "return-to-prefix").symlink_to(self.prefix, target_is_directory=True)
        (self.prefix / "bad").symlink_to("../return-to-prefix/bin/python3.12")
        with self.assertRaisesRegex(assemble.AssemblyError, "Escaping"):
            assemble.inventory_tree(self.prefix)

    def test_rejects_escape_after_traversing_directory_link(self):
        (self.root / "return-to-prefix").symlink_to(self.prefix, target_is_directory=True)
        (self.prefix / "nested").mkdir()
        (self.prefix / "nested/up").symlink_to("..", target_is_directory=True)
        link = self.prefix / "bad"
        link.symlink_to("nested/up/../return-to-prefix/bin/python3.12")
        self.assertEqual(link.resolve(strict=True), self.prefix / "bin/python3.12")
        with self.assertRaisesRegex(assemble.AssemblyError, "Escaping"):
            assemble.inventory_tree(self.prefix)

    def test_rejects_file_used_as_directory_in_link(self):
        (self.prefix / "bad").symlink_to("bin/python3.12/../python3.12")
        with self.assertRaisesRegex(assemble.AssemblyError, "Non-directory"):
            assemble.inventory_tree(self.prefix)

    def test_rejects_root_and_wrapper_symlinks(self):
        link = self.root / "prefix-alias"
        link.symlink_to(self.prefix, target_is_directory=True)
        with self.assertRaisesRegex(assemble.AssemblyError, "real directory"):
            self.run_assembly(prefix=link)
        wrapper = self.root / "wrapper-alias"
        wrapper.symlink_to(WRAPPER)
        with self.assertRaisesRegex(assemble.AssemblyError, "regular file"):
            self.run_assembly(wrapper=wrapper)

    def test_rejects_interpreter_outside_bin_even_if_inside_prefix(self):
        executable = self.prefix / "bin/python3.12"
        executable.rename(self.prefix / "alternate-python")
        executable.symlink_to("../alternate-python")
        with self.assertRaisesRegex(assemble.AssemblyError, "Python/bin"):
            self.run_assembly(expected_prefix_manifest=assemble.inventory_tree(self.prefix))

    def test_rejects_missing_stdlib(self):
        (self.prefix / "lib/python3.12/os.py").unlink()
        with self.assertRaises(FileNotFoundError):
            self.run_assembly(expected_prefix_manifest=assemble.inventory_tree(self.prefix))
        self.assertFalse(self.output.exists())

    def test_rejects_nonexecutable_interpreter(self):
        (self.prefix / "bin/python3.12").chmod(0o644)
        with self.assertRaisesRegex(assemble.AssemblyError, "executable"):
            self.run_assembly(expected_prefix_manifest=assemble.inventory_tree(self.prefix))

    def test_rejects_privileged_mode_and_special_file(self):
        target = self.prefix / "bin/python3.12"
        target.chmod(0o4755)
        with self.assertRaisesRegex(assemble.AssemblyError, "Privileged"):
            assemble.inventory_tree(self.prefix)
        target.chmod(0o755)
        os.mkfifo(self.prefix / "pipe")
        with self.assertRaisesRegex(assemble.AssemblyError, "special file"):
            assemble.inventory_tree(self.prefix)

    def test_never_overwrites_existing_destination_or_symlink(self):
        self.output.mkdir()
        (self.output / "keep").write_text("existing")
        with self.assertRaises(FileExistsError):
            self.run_assembly()
        self.assertEqual((self.output / "keep").read_text(), "existing")
        shutil.rmtree(self.output)
        self.output.symlink_to(self.prefix, target_is_directory=True)
        with self.assertRaises(FileExistsError):
            self.run_assembly()
        self.assertEqual(assemble.inventory_tree(self.prefix), self.manifest)

    def test_rejects_output_inside_source(self):
        with self.assertRaisesRegex(assemble.AssemblyError, "disjoint"):
            self.run_assembly(destination=self.prefix / "DeepdeskEngine.app")

    def test_copy_corruption_fails_and_removes_only_new_output(self):
        original_copytree = shutil.copytree

        def corrupt(source, destination, *args, **kwargs):
            result = original_copytree(source, destination, *args, **kwargs)
            if Path(source) == self.prefix:
                (Path(destination) / "share/licenses/LICENSE").write_text("damaged")
            return result

        with mock.patch.object(assemble.shutil, "copytree", side_effect=corrupt):
            with self.assertRaisesRegex(assemble.AssemblyError, "Staged prefix"):
                self.run_assembly()
        self.assertFalse(self.output.exists())
        self.assertEqual(assemble.inventory_tree(self.prefix), self.manifest)

    def test_failure_cleans_copied_readonly_tree_and_keeps_source(self):
        (self.prefix / "share/licenses").chmod(0o555)
        self.prefix.chmod(0o555)
        manifest = assemble.inventory_tree(self.prefix)
        original_copy2 = shutil.copy2

        def fail_on_wrapper(source, destination, *args, **kwargs):
            if Path(source) == WRAPPER:
                raise OSError("synthetic wrapper copy failure")
            return original_copy2(source, destination, *args, **kwargs)

        with mock.patch.object(assemble.shutil, "copy2", side_effect=fail_on_wrapper):
            with self.assertRaisesRegex(OSError, "synthetic wrapper"):
                self.run_assembly(expected_prefix_manifest=manifest)
        self.assertFalse(self.output.exists())
        self.assertEqual(assemble.inventory_tree(self.prefix), manifest)

    def test_input_mutation_during_copy_fails(self):
        original_copytree = shutil.copytree

        def mutate(source, destination, *args, **kwargs):
            result = original_copytree(source, destination, *args, **kwargs)
            if Path(source) == self.prefix:
                (self.prefix / "new-payload").write_text("changed concurrently")
            return result

        with mock.patch.object(assemble.shutil, "copytree", side_effect=mutate):
            with self.assertRaisesRegex(assemble.AssemblyError, "Original prefix"):
                self.run_assembly()
        self.assertFalse(self.output.exists())
        self.assertTrue((self.prefix / "new-payload").is_file())


if __name__ == "__main__":
    unittest.main()

"""Non-executing local assembly candidate; Python standard library only.

No downloads, installs, imports from the payload, signing or CI activation.
An input manifest must be independently reviewed/pinned by the caller. Computing
one with inventory_tree does not establish archive or wheel provenance.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import stat
from typing import Any

MANIFEST_SCHEMA = "deepdesk-content-v1"
WRAPPER_SHA256 = "c150823f009f0a9f004923413444894e95f3681d81f0fb94537be75cf7f778b9"
INTERPRETER_RELATIVE = "bin/python3.12"


class AssemblyError(ValueError):
    """An input or preservation check failed; no feature readiness is implied."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest_digest(manifest: dict[str, Any]) -> str:
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _root(path: Path) -> Path:
    path = Path(path)
    if not stat.S_ISDIR(path.lstat().st_mode):
        raise AssemblyError("Tree root must be a real directory")
    return path.resolve(strict=True)


def _within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _link_target(root: Path, path: Path) -> str:
    target = os.readlink(path)
    # Resolve component by component. Lexical normalization plus realpath alone
    # misses an escape-and-return reached via ".." after a directory symlink.
    pending = list(path.relative_to(root).parts)
    current = root
    traversed_links = 0
    while pending:
        component, *pending = pending
        if component == ".":
            continue
        if component == "..":
            if current == root:
                raise AssemblyError(f"Escaping symlink: {path.relative_to(root)}")
            current = current.parent
            continue
        candidate = current / component
        try:
            information = candidate.lstat()
        except OSError as error:
            raise AssemblyError(f"Missing symlink target: {path.relative_to(root)}") from error
        if stat.S_ISLNK(information.st_mode):
            traversed_links += 1
            if traversed_links > 40:
                raise AssemblyError(f"Cyclic or excessive symlink chain: {path.relative_to(root)}")
            value = os.readlink(candidate)
            if not value or os.path.isabs(value):
                raise AssemblyError(f"Absolute or empty symlink: {path.relative_to(root)}")
            pending = list(Path(value).parts) + pending
        else:
            if pending and not stat.S_ISDIR(information.st_mode):
                raise AssemblyError(f"Non-directory in symlink target: {path.relative_to(root)}")
            current = candidate
    return target


def inventory_tree(root: Path) -> dict[str, Any]:
    """Inventory every directory, regular file and link, never follow links.

    Records exact bytes, POSIX mode bits (including executable bits), and literal
    symlink targets. Special files and privileged mode bits are refused. Runtime
    code-signing/xattrs/ACLs/hardlink identity are separate unproved macOS gates.
    """
    root = _root(root)
    entries: list[dict[str, Any]] = []

    def walk(path: Path) -> None:
        information = path.lstat()
        mode = stat.S_IMODE(information.st_mode)
        relative = path.relative_to(root).as_posix()
        if mode & (stat.S_ISUID | stat.S_ISGID):
            raise AssemblyError(f"Privileged mode bits: {relative}")
        entry: dict[str, Any] = {"path": relative, "mode": mode}
        if stat.S_ISLNK(information.st_mode):
            entry.update(kind="symlink", target=_link_target(root, path))
        elif stat.S_ISDIR(information.st_mode):
            entry.update(kind="directory")
        elif stat.S_ISREG(information.st_mode):
            entry.update(kind="file", size=information.st_size, sha256=sha256_file(path))
        else:
            raise AssemblyError(f"Unsupported special file: {relative}")
        entries.append(entry)
        if entry["kind"] == "directory":
            for child in sorted(path.iterdir(), key=lambda item: item.name):
                walk(child)

    walk(root)
    return {"schema": MANIFEST_SCHEMA, "entries": sorted(entries, key=lambda e: e["path"])}


def _assert_manifest(actual: dict[str, Any], expected: dict[str, Any], label: str) -> None:
    # Exact structure equality rejects omitted files, extra files, changed kinds,
    # hashes, bytes, sizes, mode bits and link targets, including root mode.
    if actual != expected:
        raise AssemblyError(f"{label} content manifest mismatch")


def _regular_input(path: Path, label: str, executable: bool = False) -> Path:
    path = Path(path)
    information = path.lstat()
    if not stat.S_ISREG(information.st_mode) or information.st_mode & (stat.S_ISUID | stat.S_ISGID):
        raise AssemblyError(f"{label} must be a non-privileged regular file")
    if executable and (not information.st_mode & 0o111 or not os.access(path, os.X_OK)):
        raise AssemblyError(f"{label} must be executable")
    return path.resolve(strict=True)


def _standalone_shape(prefix: Path) -> None:
    # These structural checks reject ordinary copied venvs. They do not replace
    # provenance or prove that unexecuted file bytes are the approved CPython.
    for marker in (prefix / "pyvenv.cfg", prefix / "bin/pyvenv.cfg"):
        if os.path.lexists(marker):
            raise AssemblyError("A venv is not a standalone Python prefix")
    for relative in ("bin", "lib", "lib/python3.12", "lib/python3.12/site-packages"):
        path = prefix / relative
        if not stat.S_ISDIR(path.lstat().st_mode):
            raise AssemblyError(f"Required standalone directory missing or linked: {relative}")
    for relative in ("lib/python3.12/os.py", "lib/python3.12/encodings/__init__.py",
                     "lib/python3.12/importlib/__init__.py"):
        _regular_input(prefix / relative, "Standalone standard-library file")
    interpreter = (prefix / INTERPRETER_RELATIVE).resolve(strict=True)
    if interpreter.parent != prefix / "bin":
        raise AssemblyError("Interpreter image must remain directly in Python/bin")
    _regular_input(interpreter, "Standalone interpreter", executable=True)


def _remove_owned_partial(root: Path) -> None:
    # Only used for the fresh, exclusively created output if assembly fails.
    # Never follows payload symlinks. Read-only payload directories can occur.
    for directory, child_directories, _ in os.walk(root, topdown=True, followlinks=False):
        os.chmod(directory, stat.S_IMODE(os.lstat(directory).st_mode) | 0o700)
        child_directories[:] = [name for name in child_directories
                                if not (Path(directory) / name).is_symlink()]
    shutil.rmtree(root)


def assemble_bundle(prefix: Path, wrapper: Path, launcher: Path, destination: Path, *,
                    expected_prefix_manifest: dict[str, Any],
                    expected_launcher_sha256: str,
                    expected_wrapper_sha256: str = WRAPPER_SHA256) -> dict[str, Any]:
    """Copy exact approved local inputs without pruning or executing payloads.

    The default wrapper hash pins the frozen original. A separately reviewed
    candidate wrapper requires its exact explicit expected_wrapper_sha256.
    The destination must not exist and its parent must already exist. Do not run
    with concurrently mutable/adversarial inputs or output directories: this is
    a local build helper, not a privilege boundary or race-resistant installer.
    On an assembly exception it removes only its newly created partial output.
    A success receipt deliberately keeps native_features_complete and
    ready_for_execution false, regardless of caller metadata.
    """
    prefix = _root(prefix)
    wrapper = _regular_input(wrapper, "Wrapper")
    launcher = _regular_input(launcher, "Launcher", executable=True)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_launcher_sha256):
        raise AssemblyError("Expected launcher SHA-256 must be lowercase hexadecimal")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_wrapper_sha256):
        raise AssemblyError("Expected wrapper SHA-256 must be lowercase hexadecimal")
    if sha256_file(wrapper) != expected_wrapper_sha256:
        raise AssemblyError("Reviewed wrapper SHA-256 mismatch")
    if sha256_file(launcher) != expected_launcher_sha256:
        raise AssemblyError("Reviewed launcher SHA-256 mismatch")
    before = inventory_tree(prefix)
    _assert_manifest(before, expected_prefix_manifest, "Input prefix")
    _standalone_shape(prefix)
    destination = Path(destination)
    if destination.name != "DeepdeskEngine.app":
        raise AssemblyError("Output must be named DeepdeskEngine.app")
    parent = _root(destination.parent)
    destination = parent / destination.name
    if _within(destination, prefix) or _within(prefix, destination):
        raise AssemblyError("Output must be disjoint from input prefix")
    # mkdir is exclusive: never merge into, overwrite, or remove prior output.
    destination.mkdir(mode=0o755)
    try:
        os.chmod(destination, 0o755)
        contents = destination / "Contents"
        resources = contents / "Resources"
        macos = contents / "MacOS"
        for directory in (contents, resources, macos):
            directory.mkdir(mode=0o755)
            os.chmod(directory, 0o755)
        staged_prefix = resources / "Python"
        shutil.copytree(prefix, staged_prefix, symlinks=True, copy_function=shutil.copy2)
        shutil.copy2(wrapper, resources / "engine_entry.py", follow_symlinks=False)
        shutil.copy2(launcher, macos / "DeepdeskEngine", follow_symlinks=False)
        plist = {
            "CFBundleExecutable": "DeepdeskEngine",
            "CFBundleIdentifier": "app.deepdesk.engine",
            "CFBundleName": "DeepdeskEngine",
            "CFBundlePackageType": "APPL",
            "CFBundleVersion": "0",
        }
        (contents / "Info.plist").write_bytes(plistlib.dumps(plist, sort_keys=True))
        os.chmod(contents / "Info.plist", 0o644)
        _assert_manifest(inventory_tree(prefix), before, "Original prefix after copy")
        _assert_manifest(inventory_tree(staged_prefix), before, "Staged prefix")
        if sha256_file(wrapper) != expected_wrapper_sha256 or sha256_file(resources / "engine_entry.py") != expected_wrapper_sha256:
            raise AssemblyError("Wrapper changed during assembly")
        if sha256_file(launcher) != expected_launcher_sha256 or sha256_file(macos / "DeepdeskEngine") != expected_launcher_sha256:
            raise AssemblyError("Launcher changed during assembly")
        for source, copied in ((wrapper, resources / "engine_entry.py"),
                               (launcher, macos / "DeepdeskEngine")):
            if stat.S_IMODE(source.stat().st_mode) != stat.S_IMODE(copied.stat().st_mode):
                raise AssemblyError("Wrapper or launcher mode preservation failed")
        bundle_manifest = inventory_tree(destination)
        return {
            "schema": "deepdesk-standalone-assembly-candidate-v1",
            "prefix_manifest_sha256": manifest_digest(before),
            "wrapper_sha256": expected_wrapper_sha256,
            "launcher_sha256": expected_launcher_sha256,
            "bundle_manifest_sha256": manifest_digest(bundle_manifest),
            "bundle_manifest": bundle_manifest,
            "native_features_complete": False,
            "ready_for_execution": False,
            "payload_execution_performed": False,
            "preservation_scope": "all file bytes, POSIX modes and relative symlink targets",
        }
    except BaseException:
        _remove_owned_partial(destination)
        raise

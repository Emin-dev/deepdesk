"""Reviewed macOS-only source-wheel and SQLCipher validation, no full runtime.

No installation/execution until a separate review receipt approves exact files.
Downloads occur before isolated execution, only from pinned official sources.
No credentials, cache, model, publication, or artifact-upload operation exists.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import selectors
import shutil
import signal
import subprocess
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def digest(path):
    require(path.is_file() and not path.is_symlink(), "Missing/linked input")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def extract_regular_tar(archive_path, output, allow_internal_links=False):
    """No tarfile.extract/extractall; reject special files, traversal and links.

    The pinned CPython distribution has ten same-directory filename aliases.
    Only those may be created, after every regular file has been written.
    """
    require(not output.exists(), "Extraction target must be new")
    output.mkdir(mode=0o700)
    seen, links, expanded = set(), [], 0
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            require(not path.is_absolute() and ".." not in path.parts and "\\" not in member.name,
                    "Unsafe tar member")
            require(member.name not in seen, "Duplicate tar member")
            seen.add(member.name)
            expanded += member.size
            require(len(seen) <= 5000 and expanded <= 256 * 1024**2 and member.size <= 32 * 1024**2,
                    "Tar extraction exceeds budget")
            destination = output.joinpath(*path.parts)
            if member.issym():
                require(allow_internal_links and PurePosixPath(member.linkname).name == member.linkname
                        and member.linkname not in ("", ".", ".."), "Unapproved tar symlink")
                links.append((destination, member.linkname))
            elif member.isdir():
                destination.mkdir(mode=0o700, parents=True, exist_ok=True)
            else:
                require(member.isfile(), "Tar contains special file")
                destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with archive.extractfile(member) as source, destination.open("xb") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
                destination.chmod(0o700 if member.mode & 0o111 else 0o600)
    for destination, target in links:
        require((destination.parent / target).is_file(), "Tar alias target absent")
        destination.symlink_to(target)
    return expanded


class OfficialPythonRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        require(parsed.scheme == "https" and parsed.hostname in ("github.com", "release-assets.githubusercontent.com"),
                "Unapproved Python download redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_python(candidate, destination):
    expected = "https://github.com/astral-sh/python-build-standalone/releases/download/20261009/"
    require(candidate["url"].startswith(expected) and candidate["version"] == "3.12.15", "Unexpected Python origin/version")
    require(candidate["size"] == 25165569 and candidate["sha256"] == "83dcb04777c798bd95f3687acf9ae84b09860272ee6bdfb05be8bcf9447f75b8",
            "Unexpected Python bytes")
    opener = urllib.request.build_opener(OfficialPythonRedirect())
    total = 0
    with opener.open(candidate["url"], timeout=30) as response, destination.open("xb") as target:
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            require(total <= candidate["size"], "Python download exceeds pin")
            target.write(chunk)
    require(total == candidate["size"] and digest(destination) == candidate["sha256"], "Python archive integrity failed")


def run_bounded(command, *, cwd, env, work, timeout, output_limit=2 * 1024**2):
    """Drain into bounded private memory; never forward subprocess text to CI.

    Workflow control markers, absolute paths and unknown logs cannot escape.
    The only public output is a first-party status and SHA-256 of captured bytes.
    """
    process = subprocess.Popen(list(map(str, command)), env=env, cwd=cwd,
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    output, errors = bytearray(), bytearray()
    deadline, next_disk_check = time.monotonic() + timeout, 0
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, output)
    selector.register(process.stderr, selectors.EVENT_READ, errors)
    try:
        while selector.get_map():
            require(time.monotonic() < deadline, "Isolated subprocess timed out")
            if time.monotonic() >= next_disk_check:
                used = 0
                for path in work.rglob("*"):
                    try:
                        if path.is_file() and not path.is_symlink():
                            used += path.stat().st_size
                    except FileNotFoundError:
                        pass  # A build can remove its temporary file during a scan.
                require(used < 2 * 1024**3, "Stage A exceeds 2 GiB working-set budget")
                next_disk_check = time.monotonic() + 2
            for key, _ in selector.select(timeout=0.2):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                else:
                    key.data.extend(chunk)
                    require(len(output) + len(errors) <= output_limit, "Isolated subprocess output exceeded 2 MiB cap")
        process.wait(timeout=max(0.1, deadline - time.monotonic()))
        require(process.returncode == 0, "Isolated subprocess failed; raw output withheld")
        print(json.dumps({"isolated_step": "passed", "output_bytes": len(output),
                          "output_sha256": hashlib.sha256(output).hexdigest(),
                          "stderr_bytes": len(errors), "stderr_sha256": hashlib.sha256(errors).hexdigest()}))
        return bytes(output)
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()
        # Fresh, stage-owned session: remove descendants even when their direct
        # parent exited. Never carry this group identifier into a later step.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=3)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--review-receipt", required=True, type=Path)
    args = parser.parse_args()
    root = args.repository.resolve(strict=True)
    require(platform.system() == "Darwin" and platform.machine() == "arm64", "macOS arm64 only")
    receipt = json.loads(args.review_receipt.read_text())
    require(receipt.get("execution_approved") is True and receipt.get("scope") == "source-wheels-and-sqlcipher-only",
            "Exact-input independent review is not approved")
    require(receipt.get("source_import_commit") == "1ae0aba0da096f88db4a44ef76f7ba7e1d3fd33b", "Wrong source import")
    for filename, expected in receipt["sha256"].items():
        path = PurePosixPath(filename)
        require(not path.is_absolute() and ".." not in path.parts, "Invalid review input path")
        require(digest(root / filename) == expected, "Reviewed file changed: " + filename)
    required_review = {"packaging/engine-ci/stage_a.py", "packaging/engine-ci/audit_archives.py",
        "packaging/engine-ci/check_sqlcipher.py", "packaging/engine-ci/offline.sb",
        "research/engine-ci/input-proposal.json", "research/engine-ci/python-candidate.json",
        "research/engine-ci/source-build-manifest.json", "research/engine-ci/build-requirements.lock",
        "packaging/engine-ci/source-wheels-macos.yml.template",
        ".github/workflows/engine-source-wheels-macos.yml",
        "packaging/patches/readonly-themes.patch", "packaging/patches/managed-ddg-defaults.patch"}
    require(required_review <= receipt["sha256"].keys(), "Incomplete exact-input review")
    require(digest(root / ".github/workflows/engine-source-wheels-macos.yml") ==
            digest(root / "packaging/engine-ci/source-wheels-macos.yml.template"),
            "Executing workflow differs from reviewed template")
    spec = importlib.util.spec_from_file_location("deepdesk_archive_audit", root / "packaging/engine-ci/audit_archives.py")
    archive_audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(archive_audit)
    proposal = json.loads((root / "research/engine-ci/input-proposal.json").read_text())
    candidate = json.loads((root / "research/engine-ci/python-candidate.json").read_text())
    selected = proposal["build"] + [item for item in proposal["runtime"]
                                    if item["kind"] == "reviewed-sdist-candidate" or item["name"] == "sqlcipher3"]
    require(len(selected) == 15 and all("resolution_error" not in item for item in selected), "Unexpected stage-A distributions")
    require(sum(item["file"]["size"] for item in selected) < 16 * 1024**2, "Stage-A download exceeds 16 MiB")
    sandbox = "/usr/bin/sandbox-exec"
    require(Path(sandbox).is_file(), "Required sandbox executable absent")
    source_manifest = json.loads((root / "research/engine-ci/source-build-manifest.json").read_text())
    require(source_manifest["upstream_commit"] == "b0ac4dea5a407c51e465e802b9928d34569a8db1", "Wrong upstream")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="deepdesk-wheel-ci-", dir=os.environ.get("RUNNER_TEMP")) as temporary, \
         tempfile.TemporaryDirectory(prefix="deepdesk-control-ci-", dir=os.environ.get("RUNNER_TEMP")) as control:
        work = Path(temporary).resolve()
        home, downloads, wheels = work / "home", work / "downloads", work / "wheels"
        for path in (home, downloads, wheels):
            path.mkdir(mode=0o700)
        require(shutil.disk_usage(work).free >= 4 * 1024**3, "Need 4 GiB free before stage A")
        env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(home), "TMPDIR": temporary,
               "PIP_CONFIG_FILE": "/dev/null", "PIP_NO_INDEX": "1", "PIP_NO_CACHE_DIR": "1",
               "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
               "SOURCE_DATE_EPOCH": "1791670628", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
        profile = root / "packaging/engine-ci/offline.sb"
        trusted_files = {}
        readonly_env = work / "not-yet-created-readonly-environment"

        def run(command, *, cwd=work, timeout=180):
            remaining = 600 - (time.monotonic() - started)
            require(remaining > 0, "Stage A exceeds ten-minute inner budget")
            used = sum(path.stat().st_size for path in work.rglob("*") if path.is_file() and not path.is_symlink())
            require(used < 2 * 1024**3, "Stage A exceeds 2 GiB working-set budget")
            for filename, expected in trusted_files.items():
                require(digest(filename) == expected, "Trusted interpreter changed after verification")
            return run_bounded([sandbox, "-D", "WORK_DIR=" + str(work),
                               "-D", "READONLY_PYTHON=" + str(work / "python-root"),
                               "-D", "READONLY_DOWNLOADS=" + str(downloads),
                               "-D", "READONLY_ENV=" + str(readonly_env),
                               "-f", str(profile), *map(str, command)], env=env,
                               cwd=cwd, work=work, timeout=min(timeout, remaining))

        pyarchive = downloads / candidate["filename"]
        download_python(candidate, pyarchive)
        for item in selected:
            archive_audit.download(item["file"], downloads)
            inspection = archive_audit.inspect_archive(downloads / item["file"]["filename"])
            for pth in inspection["pth"]:
                require(item["name"] == "setuptools" and pth["path"] == "distutils-precedence.pth"
                        and pth["sha256"] == "2638ce9e2500e572a5e0de7faed6661eb569d1b696fcba07b0dd223da5f5d224",
                        "Unreviewed executable .pth")
        extract_regular_tar(pyarchive, work / "python-root", allow_internal_links=True)
        python = work / "python-root/python/bin/python3.12"
        require(digest(python) == "6e4dac0c7c1761a63c5a603ef56397c8d3d8fa00cf8dd65fb3e6a4476b63af4b", "Python executable changed")
        require(digest(work / "python-root/python/lib/libpython3.12.dylib") == "4bb987cf2aaef22cbfb0db73bedda798a106f20832955850d5823ad8928c2358", "Python shared library changed")
        trusted_files[python] = digest(python)
        trusted_files[work / "python-root/python/lib/libpython3.12.dylib"] = digest(work / "python-root/python/lib/libpython3.12.dylib")
        # No request payload: require the kernel sandbox to reject a connect to
        # the documentation-only TEST-NET address with EPERM/EACCES, not timeout.
        run([python, "-I", "-c", "import errno,socket; s=socket.socket(); s.settimeout(1); r=s.connect_ex(('192.0.2.1',9)); s.close(); assert r in (errno.EPERM,errno.EACCES), r"], timeout=10)
        outside = Path(control) / "must-not-create"
        probe = "import errno,sys\ntry:\n open(sys.argv[1],'xb').close()\nexcept OSError as e:\n assert e.errno in (errno.EPERM,errno.EACCES)\nelse:\n raise RuntimeError('Outside-tree write permitted')\n"
        run([python, "-I", "-c", probe, outside], timeout=10)
        require(not outside.exists(), "Filesystem sandbox probe created an outside-tree file")
        for protected in (work / "python-root", downloads):
            probe_path = protected / "must-not-create"
            run([python, "-I", "-c", probe, probe_path], timeout=10)
            require(not probe_path.exists(), "Sandbox permitted a write to a protected input tree")
        run([python, "-I", "-m", "venv", work / "build-env"])
        build_python = work / "build-env/bin/python"
        run([build_python, "-I", "-m", "pip", "--isolated", "install", "--no-index", "--no-cache-dir",
             "--find-links", downloads, "--require-hashes", "--only-binary=:all:",
             "-r", root / "research/engine-ci/build-requirements.lock"])
        readonly_env = work / "build-env"
        run([python, "-I", "-c", probe, work / "build-env/must-not-create"], timeout=10)
        require(not (work / "build-env/must-not-create").exists(), "Sandbox failed to seal the build environment")
        for item in selected:
            if item["kind"] != "reviewed-sdist-candidate":
                continue
            source_root = work / (item["name"] + "-source")
            extract_regular_tar(downloads / item["file"]["filename"], source_root)
            children = list(source_root.iterdir())
            require(len(children) == 1 and children[0].is_dir(), "Unexpected source archive layout")
            run([build_python, "-I", "-m", "build", "--wheel", "--no-isolation", "--outdir", wheels, children[0]])
        staged = work / "upstream-source"
        staged.mkdir()
        for item in source_manifest["files"]:
            relative = PurePosixPath(item["path"])
            require(not relative.is_absolute() and ".." not in relative.parts, "Invalid source path")
            # The standalone import brands its root README and preserves the
            # exact upstream build README at this fixed documentation path.
            source_relative = "docs/upstream/README.md" if item["path"] == "README.md" else item["path"]
            source = root / source_relative
            require(digest(source) == item["sha256"] and source.stat().st_size == item["size"], "Pinned source changed: " + item["path"])
            destination = staged / item["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        for patch in ("readonly-themes.patch", "managed-ddg-defaults.patch"):
            run(["/usr/bin/patch", "--batch", "--forward", "-p1", "-i", root / "packaging/patches" / patch], cwd=staged)
        run([build_python, "-I", "-m", "build", "--wheel", "--no-isolation", "--outdir", wheels, staged])
        built, identities = [], set()
        for wheel in sorted(wheels.glob("*.whl")):
            inspection = archive_audit.inspect_archive(wheel)
            require(not inspection["pth"], "Built wheel has executable .pth")
            require(len(inspection["metadata"]) == 1, "Ambiguous built-wheel metadata")
            metadata = inspection["metadata"][0]
            name = re.sub(r"[-_.]+", "-", metadata["name"]).lower()
            identities.add((name, metadata["version"]))
            built.append({"filename": wheel.name, "size": wheel.stat().st_size, "sha256": digest(wheel)})
        require(len(built) == 5 and identities == {("google-search-results", "2.4.2"), ("jstyleson", "0.0.2"),
            ("langdetect", "1.0.9"), ("wikipedia", "1.4.0"), ("local-deep-research", "1.10.7")},
            "Built wheel identity/version set differs from the exact five reviewed packages")
        sqlcipher = next(item for item in selected if item["name"] == "sqlcipher3")
        lock = work / "sqlcipher.lock"
        lock.write_text("sqlcipher3==0.6.2 --hash=sha256:" + sqlcipher["file"]["sha256"] + "\n")
        readonly_env = work / "not-yet-created-readonly-environment"
        run([build_python, "-I", "-m", "pip", "--isolated", "install", "--no-index", "--no-cache-dir",
             "--find-links", downloads, "--require-hashes", "--only-binary=:all:", "-r", lock])
        readonly_env = work / "build-env"
        sqlcipher_result = json.loads(run([build_python, "-I", root / "packaging/engine-ci/check_sqlcipher.py"]))
        require(sqlcipher_result.get("status") == "passed" and sqlcipher_result.get("checks") == [
            "encrypted-header", "correct-key-reopen", "wrong-key-refused", "ordinary-sqlite-refused"],
            "SQLCipher result schema mismatch")
        print(json.dumps({"status": "passed", "scope": "source-wheels-and-sqlcipher-only", "built_wheels": built,
                          "sqlcipher_checks": sqlcipher_result["checks"],
                          "python": "3.12.15", "model_loaded": False, "full_engine_imported": False,
                          "frozen_app_created": False, "authenticated_api_tested": False}, sort_keys=True))


if __name__ == "__main__":
    main()

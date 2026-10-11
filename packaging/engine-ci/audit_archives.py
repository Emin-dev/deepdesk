"""Bounded archive inspection with no extraction, imports, or build hooks.

Download phase uses the reviewed proposal's exact PyPI URL, size, SHA-256.
Neither this tool nor --download installs or executes any distribution.
"""
from __future__ import annotations
import argparse
import email.parser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import urllib.parse
import urllib.request
import zipfile

# Torch's pinned libtorch_cpu.dylib is 386,016,976 bytes. Binary members are
# inventoried from ZIP headers, never decompressed by this metadata inspector.
MAX_MEMBER = 512 * 1024 * 1024
MAX_EXPANDED = 6 * 1024 * 1024 * 1024
MAX_MEMBERS = 100000


def require(ok, message):
    if not ok:
        raise ValueError(message)


def safe_name(name):
    path = PurePosixPath(name)
    require(name and not path.is_absolute() and ".." not in path.parts and "\\" not in name and "\0" not in name,
            "Unsafe archive member")
    return path


def checked_bytes(path, expected, size):
    require(path.is_file() and not path.is_symlink(), "Missing/linked archive")
    require(path.stat().st_size == size, "Archive size mismatch")
    with path.open("rb") as stream:
        require(hashlib.file_digest(stream, "sha256").hexdigest() == expected, "Archive hash mismatch")


class PyPIRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        require(parsed.scheme == "https" and parsed.hostname == "files.pythonhosted.org", "Unapproved file redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(file, destination):
    parsed = urllib.parse.urlsplit(file["url"])
    require(parsed.scheme == "https" and parsed.hostname == "files.pythonhosted.org", "Unapproved file origin")
    require(Path(file["filename"]).name == file["filename"], "Invalid archive filename")
    require(re.fullmatch("[0-9a-f]{64}", file["sha256"]) and 0 < file["size"] <= 1024**3, "Invalid archive bounds")
    target = destination / file["filename"]
    if target.exists():
        checked_bytes(target, file["sha256"], file["size"])
        return target
    partial = target.with_suffix(target.suffix + ".partial")
    opener = urllib.request.build_opener(PyPIRedirect())
    digest, total = hashlib.sha256(), 0
    with opener.open(file["url"], timeout=30) as response, partial.open("xb") as output:
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            require(total <= file["size"], "Archive download exceeded pinned size")
            digest.update(chunk)
            output.write(chunk)
    require(total == file["size"] and digest.hexdigest() == file["sha256"], "Downloaded archive failed integrity")
    os.replace(partial, target)
    return target


def inspect_archive(path):
    records, notices, executable_pth, entry_points, metadata = [], [], [], [], []
    seen, total = set(), 0

    def record(name, size, mode, read):
        nonlocal total
        safe_name(name)
        require(name not in seen, "Duplicate archive member")
        seen.add(name)
        total += size
        require(size <= MAX_MEMBER and total <= MAX_EXPANDED and len(seen) <= MAX_MEMBERS, "Archive exceeds audit bounds")
        if read is None:
            return
        require(not stat.S_ISLNK(mode), "Archive contains symlink")
        lower = name.lower()
        interesting = lower.endswith((".pth", "entry_points.txt", "/metadata", "/pkg-info", "/setup.py", "/setup.cfg", "/pyproject.toml", "/manifest.in"))
        is_license = any(word in PurePosixPath(name).name.lower() for word in ("license", "copying", "notice"))
        if interesting or is_license:
            require(size <= 4 * 1024 * 1024, "Oversized metadata/license")
            data = read()
            digest = hashlib.sha256(data).hexdigest()
            records.append({"path": name, "size": size, "sha256": digest})
            if is_license:
                notices.append({"path": name, "sha256": digest, "text": data.decode("utf-8", errors="replace")})
            if lower.endswith(".pth"):
                executable_pth.append({"path": name, "sha256": digest, "text": data.decode("utf-8", errors="replace")})
            if lower.endswith("entry_points.txt"):
                entry_points.append({"path": name, "text": data.decode("utf-8", errors="replace")})
            if lower.endswith(("/metadata", "/pkg-info")):
                msg = email.parser.BytesParser().parsebytes(data)
                metadata.append({"name": msg.get("Name"), "version": msg.get("Version"),
                                 "requires_dist": msg.get_all("Requires-Dist", []),
                                 "license": msg.get("License"), "license_expression": msg.get("License-Expression")})

    if path.name.endswith(".whl"):
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                require(not member.flag_bits & 1, "Encrypted ZIP entry")
                mode = member.external_attr >> 16
                record(member.filename, member.file_size, mode,
                       None if member.is_dir() else lambda member=member: archive.read(member))
    else:
        with tarfile.open(path, mode="r:gz") as archive:
            for member in archive:
                require(member.isfile() or member.isdir(), "Source archive contains link/device/special member")
                record(member.name, member.size, member.mode,
                       (lambda member=member: archive.extractfile(member).read()) if member.isfile() else None)
    return {"filename": path.name, "members": len(seen), "expanded_bytes": total,
            "reviewed_metadata": records, "notices": notices, "pth": executable_pth,
            "entry_points": entry_points, "metadata": metadata}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--proposal", type=Path, required=True)
    parser.add_argument("--proposal-sha256", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--sources-only", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    args = parser.parse_args()
    raw = args.proposal.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == args.proposal_sha256, "Proposal changed after review")
    proposal = json.loads(raw)
    require(not (args.sources_only and args.build_only), "Choose one audit group")
    items = proposal["build"] if args.build_only else proposal["runtime"] + proposal["build"]
    files = {item["file"]["filename"]: item["file"] for item in items
             if not args.sources_only or item["kind"] == "reviewed-sdist-candidate"}
    require(sum(file["size"] for file in files.values()) <= 2 * 1024**3, "Download budget exceeds 2 GiB")
    args.directory.mkdir(parents=True, exist_ok=True)
    require(not args.directory.is_symlink(), "Linked archive directory")
    results = []
    for file in sorted(files.values(), key=lambda value: value["filename"]):
        path = download(file, args.directory) if args.download else args.directory / file["filename"]
        checked_bytes(path, file["sha256"], file["size"])
        results.append(inspect_archive(path))
    args.output.write_text(json.dumps({"status": "inspect-only-not-install-approval", "archives": results}, indent=2) + "\n")
    print(json.dumps({"archives": len(results), "report_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
                      "pth_files_require_review": sum(len(item["pth"]) for item in results),
                      "without_embedded_notice": [item["filename"] for item in results if not item["notices"]]}))


if __name__ == "__main__":
    main()

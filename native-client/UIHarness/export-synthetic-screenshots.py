#!/usr/bin/env python3
"""Export bounded, explicitly named synthetic-window images to public CI logs for review.

No screenshots are saved to Actions artifacts or Library. A failure here never masks the UI test result.
"""
import base64
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

NAMES = (
    "synthetic-first-use-light",
    "synthetic-model-download-paused",
    "synthetic-research-progress",
    "synthetic-report-citations",
    "synthetic-download-error-dark",
    "synthetic-model-chooser-dark",
)
MAX_SOURCE_BYTES = 25 * 1024 * 1024
MAX_JPEG_BYTES = 120 * 1024
MAX_LOG_BYTES = 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024


def candidates(value):
    """Read only documented exporter attachment metadata; unknown layouts are skipped."""
    if isinstance(value, dict):
        name = value.get("suggestedHumanReadableName")
        filename = value.get("exportedFileName")
        if isinstance(name, str) and isinstance(filename, str):
            normalized = name.removesuffix(".png").removesuffix(".jpeg").removesuffix(".jpg")
            if normalized in NAMES and filename == Path(filename).name:
                yield normalized, filename
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from candidates(child)
    elif isinstance(value, list):
        for child in value:
            yield from candidates(child)


def regular_bounded(path, maximum):
    info = path.lstat()
    return stat.S_ISREG(info.st_mode) and 0 < info.st_size <= maximum


def main():
    if len(sys.argv) != 2:
        raise ValueError("Expected one xcresult path")
    result = Path(sys.argv[1])
    if not result.is_dir() or result.is_symlink():
        print("Synthetic screenshot review unavailable: no result bundle.")
        return
    with tempfile.TemporaryDirectory(prefix="deepdesk-ui-screenshots-", dir=result.parent) as temporary:
        root = Path(temporary)
        exported = root / "exported"
        subprocess.run(["/usr/bin/xcrun", "xcresulttool", "export", "attachments", "--path", str(result),
                        "--output-path", str(exported)], check=True, timeout=90, stdout=subprocess.DEVNULL)
        manifest = exported / "manifest.json"
        if not regular_bounded(manifest, MAX_MANIFEST_BYTES):
            raise ValueError("Attachment metadata unavailable or exceeds bounds")
        metadata = json.loads(manifest.read_bytes())
        selected = {}
        for name, filename in candidates(metadata):
            source = exported / filename
            if name not in selected and source.suffix.lower() in {".png", ".jpg", ".jpeg"} and regular_bounded(source, MAX_SOURCE_BYTES):
                selected[name] = source
        output_bytes = 0
        for name in NAMES:
            source = selected.get(name)
            if source is None:
                continue
            jpeg = root / (name + ".jpg")
            subprocess.run(["/usr/bin/sips", "-s", "format", "jpeg", "-s", "formatOptions", "55", "-Z", "1000",
                            str(source), "--out", str(jpeg)], check=True, timeout=30, stdout=subprocess.DEVNULL)
            if not regular_bounded(jpeg, MAX_JPEG_BYTES):
                print("Synthetic screenshot skipped: resized image exceeds byte bound.")
                continue
            data = jpeg.read_bytes()
            receipt = {"name": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "mime": "image/jpeg"}
            encoded = base64.b64encode(data).decode("ascii")
            lines = ["DEEPDESK_SYNTHETIC_IMAGE_BEGIN " + json.dumps(receipt, sort_keys=True)]
            lines += ["DEEPDESK_SYNTHETIC_IMAGE_DATA " + encoded[offset:offset + 4000] for offset in range(0, len(encoded), 4000)]
            lines += ["DEEPDESK_SYNTHETIC_IMAGE_END " + name]
            block = "\n".join(lines) + "\n"
            size = len(block.encode("ascii"))
            if output_bytes + size > MAX_LOG_BYTES:
                break
            sys.stdout.write(block)
            output_bytes += size
        if not selected:
            print("Synthetic screenshot review unavailable: no allowlisted named attachments were exported.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError):
        print("Synthetic screenshot review unavailable: export failed or metadata was unsupported.")
        # Test execution is a separate CI step; optional pixel export does not alter its outcome.

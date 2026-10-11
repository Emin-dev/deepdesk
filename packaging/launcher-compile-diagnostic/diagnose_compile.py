"""Candidate v2: compile one reviewed corrected launcher; never execute the result.

No downloads or runtime dependencies. Raw compiler bytes stay bounded in memory.
A separately reviewed receipt must explicitly authorize this diagnostic lane.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time

SCHEMA = "deepdesk-launcher-compile-diagnostic-v1"
LAUNCHER_SHA256 = "148b2cddcedcc8b1d23daccd29bd834b900baf5e3a4d1dc7e0d534a50cbcbe1b"
PROFILE_SHA256 = "9d4f464140e5bb35efb2f937e820349b6f7a47482d4fcb2a618cc489b9bf4710"
TOTAL_SECONDS = 120
TIMEOUT_SECONDS = 90
OUTPUT_LIMIT = 64 * 1024
WORK_LIMIT = 64 * 1024 * 1024
MAX_RECORDS = 20
REQUIRED_HASH_PATHS = frozenset({
    'packaging/launcher-compile-diagnostic/diagnose_compile.py',
    'packaging/launcher-compile-diagnostic/test_diagnose_compile.py',
    'packaging/launcher-compile-diagnostic/README.md',
    'packaging/launcher-compile-diagnostic/launcher-compile-diagnostic-macos.yml.template',
    'packaging/standalone-engine-candidate/launcher.c',
    'packaging/engine-ci/runtime-offline.sb',
})
DEPLOYED_WORKFLOW = '.github/workflows/engine-launcher-compile-diagnostic-macos.yml'
TEMPLATE_PATH = 'packaging/launcher-compile-diagnostic/launcher-compile-diagnostic-macos.yml.template' 
ALLOWED_SOURCE_BASENAMES = frozenset({"launcher.c"})
ALLOWED_SYMBOLS = frozenset({
    "O_NOFOLLOW", "O_RDONLY", "PATH_MAX", "S_ISUID", "S_ISGID", "uint32_t",
    "_NSGetExecutablePath", "realpath", "strtok_r", "readlink", "lstat", "execve",
})
ALLOWED_HEADERS = frozenset({"mach-o/dyld.h", "fcntl.h", "limits.h", "sys/stat.h", "unistd.h"})


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, fixed_message: str) -> None:
    if not condition:
        raise ValueError(fixed_message)


def compile_environment(work: Path) -> dict[str, str]:
    """Exact environment values from the failed stage, with fresh dummy paths."""
    return {
        'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'HOME': str(work / 'home'), 'TMPDIR': str(work),
        'PIP_CONFIG_FILE': '/dev/null', 'PIP_NO_INDEX': '1', 'PIP_NO_CACHE_DIR': '1',
        'PIP_DISABLE_PIP_VERSION_CHECK': '1', 'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1',
        'SOURCE_DATE_EPOCH': '1791670628', 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
        'HF_HUB_DISABLE_TELEMETRY': '1', 'ANONYMIZED_TELEMETRY': 'false',
        'TOKENIZERS_PARALLELISM': 'false', 'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1',
        'PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD': '1', 'LDR_DATA_DIR': str(work / 'isolated-data'),
    }


def compile_command(source: Path, profile: Path, work: Path) -> list[str]:
    """No added diagnostic flags: retain the original compiler arguments."""
    return [
        '/usr/bin/sandbox-exec', '-D', 'WORK_DIR=' + str(work),
        '-D', 'IMMUTABLE_DIR=' + str(work / 'immutable'),
        '-D', 'READONLY_ENV=' + str(work / 'standalone-prefix/python'),
        '-f', str(profile),
        '/usr/bin/clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
        str(source), '-o', str(work / 'DeepdeskEngine'),
    ]


def _classification(message: str) -> tuple[str, str]:
    """Return only reviewed fixed text, never free-form compiler substrings."""
    for pattern, code, prefix in (
        (r"use of undeclared identifier '([A-Za-z_][A-Za-z_0-9]*)'", "undeclared_identifier", "Undeclared identifier"),
        (r"unknown type name '([A-Za-z_][A-Za-z_0-9]*)'", "unknown_type", "Unknown type"),
        (r"call to undeclared function '([A-Za-z_][A-Za-z_0-9]*)'; ISO C99 and later do not support implicit function declarations(?: \[-W(?:error,)?-?W?implicit-function-declaration\])?", "undeclared_function", "Undeclared function"),
    ):
        match = re.fullmatch(pattern, message)
        if match and match.group(1) in ALLOWED_SYMBOLS:
            return code, prefix + ": " + match.group(1)
    missing = re.fullmatch(r"'([^']+)' file not found", message)
    if missing and missing.group(1) in ALLOWED_HEADERS:
        return "header_missing", "Required compiler header is unavailable: " + missing.group(1)
    for prefix, code, description in (
        ("incompatible pointer types", "incompatible_pointer_types", "Compiler reports incompatible pointer types"),
        ("format specifies type", "format_type_mismatch", "Compiler reports a format argument type mismatch"),
        ("format string is not a string literal", "nonliteral_format", "Compiler reports a nonliteral format string"),
        ("too many arguments", "too_many_arguments", "Compiler reports too many arguments"),
        ("too few arguments", "too_few_arguments", "Compiler reports too few arguments"),
    ):
        if message.startswith(prefix):
            return code, description
    return "unclassified", "Unclassified compiler diagnostic withheld"


def sanitize_diagnostics(raw: bytes, source: Path, source_lines: int) -> dict:
    """Only the exact pinned source path may produce a public location record.

    Header traces, source excerpts, carets, arbitrary quoted values, paths,
    ANSI/control bytes and unknown diagnostics are never forwarded verbatim.
    """
    require(source.name in ALLOWED_SOURCE_BASENAMES, "Unexpected diagnostic source basename")
    require(1 <= source_lines <= 10000, "Unexpected source length")
    records, withheld = [], 0
    source_pattern = re.compile(re.escape(str(source)) + r":([0-9]+):([0-9]+): (fatal error|error|warning|note): (.*)")
    for line in raw.decode('utf-8', errors='replace').splitlines():
        if len(records) >= MAX_RECORDS:
            withheld += 1
            continue
        match = source_pattern.fullmatch(line)
        if match:
            number, column = int(match.group(1)), int(match.group(2))
            if not (1 <= number <= source_lines and 1 <= column <= 2048):
                withheld += 1
                continue
            code, message = _classification(match.group(4))
            records.append({"phase": "compile", "severity": match.group(3), "code": code,
                            "source": source.name, "line": number, "column": column, "message": message})
            continue
        # Driver/linker/sandbox diagnostics have no exposed path or source line.
        record = None
        if line.startswith(('clang: error:', 'clang: warning:', 'error:')):
            if 'unable to make temporary file' in line:
                record = ('driver', 'temporary_file_failed', 'Compiler could not create a temporary file')
            elif 'unable to open output file' in line:
                record = ('driver', 'output_file_failed', 'Compiler could not open its output file')
            elif 'linker command failed' in line:
                record = ('link', 'linker_failed', 'Compiler linker phase failed')
            elif 'no such file or directory' in line:
                record = ('driver', 'compiler_input_missing', 'Compiler input or tool was unavailable')
            else:
                record = ('driver', 'unclassified', 'Unclassified compiler driver diagnostic withheld')
        elif line.startswith('xcrun: error:'):
            record = ('driver', 'developer_tool_failed', 'Apple developer tool selection failed')
        elif line.startswith('sandbox-exec:'):
            record = ('sandbox', 'sandbox_launch_failed', 'Sandbox launcher reported a failure')
        elif line.startswith('ld:'):
            record = ('link', 'linker_diagnostic', 'Linker diagnostic details withheld')
        if record:
            phase, code, message = record
            records.append({"phase": phase, "severity": "error", "code": code,
                            "source": None, "line": None, "column": None, "message": message})
        elif line:
            withheld += 1
    return {"records": records, "withheld_lines": withheld}


def _disk_bytes(work: Path) -> int:
    result = 0
    for base, directories, names in os.walk(work, followlinks=False):
        directories[:] = [name for name in directories if not (Path(base) / name).is_symlink()]
        for name in names:
            try:
                information = (Path(base) / name).lstat()
                if stat.S_ISREG(information.st_mode):
                    result += information.st_size
            except FileNotFoundError:
                pass
    return result


def capture_bounded(command: list[str], *, env: dict[str, str], work: Path,
                    timeout: float = TIMEOUT_SECONDS, output_limit: int = OUTPUT_LIMIT,
                    disk_limit: int = WORK_LIMIT) -> tuple[str, int | None, bytes, bytes]:
    """Private capture, including nonzero exits. Never executes generated output."""
    require(timeout > 0 and output_limit > 0 and disk_limit > 0, "Invalid process bounds")
    try:
        process = subprocess.Popen(command, cwd=work, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    except OSError:
        return "start_failed", None, b"", b""
    output, errors = bytearray(), bytearray()
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, output)
    selector.register(process.stderr, selectors.EVENT_READ, errors)
    deadline, next_scan, status = time.monotonic() + timeout, 0.0, "completed"
    try:
        while selector.get_map() or process.poll() is None:
            if time.monotonic() >= deadline:
                status = "timeout"
                break
            if time.monotonic() >= next_scan:
                if _disk_bytes(work) > disk_limit:
                    status = "work_limit"
                    break
                next_scan = time.monotonic() + 0.2
            for key, _ in selector.select(timeout=0.05):
                block = os.read(key.fileobj.fileno(), min(65536, output_limit + 1))
                if not block:
                    selector.unregister(key.fileobj)
                    continue
                remaining = output_limit - len(output) - len(errors)
                key.data.extend(block[:remaining])
                if len(block) > remaining:
                    status = "output_limit"
                    break
            if status != "completed":
                break
        if status == "completed":
            process.wait(timeout=max(0.05, deadline - time.monotonic()))
            if _disk_bytes(work) > disk_limit:
                status = "work_limit"
        code = process.returncode
    finally:
        selector.close()
        # Kill the owned process group even after driver exit; descendants may
        # otherwise keep pipes open. No claim of preventing session escape.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=3)
        for stream in (process.stdout, process.stderr):
            stream.close()
    return status, code, bytes(output), bytes(errors)


def validate_receipt(receipt: dict, repository: Path) -> None:
    require(receipt.get('schema') == SCHEMA, "Unexpected diagnostic receipt schema")
    require(receipt.get('approved_to_execute') is True, "Compile diagnostic execution is not approved")
    hashes = receipt.get('sha256')
    require(isinstance(hashes, dict) and set(hashes) == REQUIRED_HASH_PATHS, "Diagnostic hash allowlist differs")
    for relative, expected in hashes.items():
        path = repository / relative
        require(isinstance(expected, str) and re.fullmatch(r'[0-9a-f]{64}', expected) is not None,
                "Invalid reviewed hash")
        require(stat.S_ISREG(path.lstat().st_mode) and path.stat().st_size <= 2 * 1024 * 1024,
                "Invalid reviewed file")
        require(path.resolve().is_relative_to(repository), "Reviewed file escaped repository")
        require(digest(path) == expected, "Reviewed file differs")
    require(hashes['packaging/standalone-engine-candidate/launcher.c'] == LAUNCHER_SHA256,
            "Pinned reviewed launcher differs")
    require(hashes['packaging/engine-ci/runtime-offline.sb'] == PROFILE_SHA256,
            "Pinned original deny profile differs")
    require(hashes['packaging/launcher-compile-diagnostic/diagnose_compile.py'] == digest(Path(__file__)),
            "Executing helper differs from reviewed receipt")
    deployed = repository / DEPLOYED_WORKFLOW
    require(stat.S_ISREG(deployed.lstat().st_mode) and deployed.resolve().is_relative_to(repository)
            and deployed.stat().st_size <= 2 * 1024 * 1024, "Invalid deployed diagnostic workflow")
    require(deployed.read_bytes() == (repository / TEMPLATE_PATH).read_bytes(),
            "Deployed diagnostic workflow differs from reviewed template")


def diagnose(repository: Path, receipt_path: Path) -> dict:
    started = time.monotonic()
    require(sys.platform == 'darwin' and platform.machine() == 'arm64', "An arm64 macOS host is required")
    repository = repository.resolve(strict=True)
    source = repository / 'packaging/standalone-engine-candidate/launcher.c'
    profile = repository / 'packaging/engine-ci/runtime-offline.sb'
    for path in (source, profile, receipt_path):
        require(stat.S_ISREG(path.lstat().st_mode), "Diagnostic inputs must be regular files")
        require(path.resolve().is_relative_to(repository), "Diagnostic input lies outside repository")
    require(receipt_path.stat().st_size <= 64 * 1024, "Diagnostic receipt is oversized")
    receipt = json.loads(receipt_path.read_text())
    validate_receipt(receipt, repository)
    require(Path('/usr/bin/clang').is_file() and Path('/usr/bin/sandbox-exec').is_file(), "Required Apple tools are missing")
    with tempfile.TemporaryDirectory(prefix='deepdesk-launcher-compile-', dir=os.environ.get('RUNNER_TEMP')) as temporary:
        work = Path(temporary).resolve()
        for relative in ('home', 'immutable', 'standalone-prefix/python'):
            (work / relative).mkdir(mode=0o700, parents=True)
        status, returncode, output, errors = capture_bounded(
            compile_command(source, profile, work), env=compile_environment(work), work=work,
            timeout=min(TIMEOUT_SECONDS, TOTAL_SECONDS - (time.monotonic() - started)))
        validate_receipt(receipt, repository)
        require(time.monotonic() - started < TOTAL_SECONDS, "Diagnostic total deadline exceeded")
        result = {
            'schema': SCHEMA, 'capture_status': status, 'compiler_exit_code': returncode,
            'launcher_sha256': LAUNCHER_SHA256, 'profile_sha256': PROFILE_SHA256,
            'stdout_bytes': len(output), 'stdout_sha256': hashlib.sha256(output).hexdigest(),
            'stderr_bytes': len(errors), 'stderr_sha256': hashlib.sha256(errors).hexdigest(),
            'diagnostics': sanitize_diagnostics(errors, source, len(source.read_text().splitlines())),
            'generated_executable_executed': False, 'runtime_dependencies_downloaded': False,
            'native_features_complete': False, 'runtime_lane_ready': False,
        }
        compiled = work / 'DeepdeskEngine'
        result['compiled_output_present'] = compiled.is_file()
        if compiled.is_file():
            require(compiled.stat().st_size <= WORK_LIMIT, "Compiled output exceeds cap")
            result['compiled_output_sha256'] = digest(compiled)
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description='Reviewed first-party compile diagnostic only')
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--review-receipt', type=Path, required=True)
    arguments = parser.parse_args()
    try:
        result = diagnose(arguments.repository, arguments.review_receipt)
    except Exception:
        # No exception string or traceback may expose paths or inherited values.
        print(json.dumps({'schema': SCHEMA, 'capture_status': 'setup_failed',
                          'message': 'Diagnostic prerequisites or integrity checks failed',
                          'generated_executable_executed': False, 'runtime_lane_ready': False}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    # A nonzero compiler result is a successfully captured diagnostic, not a
    # runtime pass. Bounds/start failures remain a failed diagnostic job.
    return 0 if result['capture_status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())

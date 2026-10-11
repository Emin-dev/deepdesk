"""First-party private-output subprocess bounds for the proposed API lane."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def disk_bytes(root):
    total = 0
    for base, directories, names in os.walk(root, followlinks=False):
        directories[:] = [name for name in directories if not (Path(base) / name).is_symlink()]
        for name in names:
            path = Path(base) / name
            try:
                if not path.is_symlink():
                    total += path.stat().st_size
            except FileNotFoundError:
                pass
    return total


def run_bounded(command, *, cwd, env, work, timeout, disk_limit=12 * 1024**3,
                output_limit=2 * 1024**2, input_data=None, own_session=True, public_summary=True):
    """Never forward child bytes. The caller must validate any parsed JSON.

    Nested fixture children share the outer owned process group, so the outer
    runner can remove every descendant on timeout, including detached parents.
    Session escape is not claimed to be prevented by this helper.
    """
    require(timeout > 0, "No subprocess time budget remains")
    require(input_data is None or len(input_data) <= 16384, "Oversized synthetic stdin")
    process = subprocess.Popen(list(map(str, command)), env=env, cwd=cwd,
        stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=own_session)
    output, errors = bytearray(), bytearray()
    deadline, next_scan = time.monotonic() + timeout, 0
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, output)
    selector.register(process.stderr, selectors.EVENT_READ, errors)
    pending = memoryview(input_data) if input_data is not None else None
    if pending is not None:
        os.set_blocking(process.stdin.fileno(), False)
        selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
    try:
        while selector.get_map() or process.poll() is None:
            require(time.monotonic() < deadline, "Bounded subprocess timed out")
            if time.monotonic() >= next_scan:
                require(disk_bytes(work) <= disk_limit, "Bounded working-set limit exceeded")
                next_scan = time.monotonic() + 2
            for key, _ in selector.select(timeout=0.1):
                if key.data == "stdin":
                    if len(pending):
                        count = os.write(key.fileobj.fileno(), pending)
                        pending = pending[count:]
                    if not len(pending):
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                    continue
                data = os.read(key.fileobj.fileno(), 65536)
                if not data:
                    selector.unregister(key.fileobj)
                else:
                    key.data.extend(data)
                    require(len(output) + len(errors) <= output_limit, "Private output limit exceeded")
        process.wait(timeout=max(0.1, deadline - time.monotonic()))
        require(disk_bytes(work) <= disk_limit, "Bounded working-set limit exceeded at completion")
        require(process.returncode == 0, "Bounded subprocess failed; raw output withheld")
        if public_summary:
            print(json.dumps({"bounded_step": "passed", "stdout_bytes": len(output),
            "stdout_sha256": hashlib.sha256(output).hexdigest(), "stderr_bytes": len(errors),
            "stderr_sha256": hashlib.sha256(errors).hexdigest()}))
        return bytes(output)
    finally:
        selector.close()
        for stream in (process.stdout, process.stderr, process.stdin):
            if stream is not None and not stream.closed:
                stream.close()
        try:
            if own_session:
                os.killpg(process.pid, signal.SIGKILL)
            elif process.poll() is None:
                process.kill()
        except ProcessLookupError:
            pass
        process.wait(timeout=3)

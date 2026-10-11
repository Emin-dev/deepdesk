"""First-party diagnostic: compile the unchanged rejected profile, run /usr/bin/true.

No downloads, package execution, credentials, socket creation, or raw child logs.
This is diagnostic evidence only, never an installed-runtime/API success result.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import selectors
import signal
import subprocess
import tempfile
import time

PROFILE_HASH = '8895066a9bce3f8e7aa4500aed8978b4a652f8c89e1677d2d37fd9d3c7e6f2e8'
WORKFLOW = '.github/workflows/engine-sandbox-diagnostic-macos.yml'
TEMPLATE = 'packaging/engine-ci/sandbox-diagnostic-macos.yml.template'


def require(value, message):
    if not value:
        raise RuntimeError(message)


def digest(path):
    require(path.is_file() and not path.is_symlink(), 'Missing or linked diagnostic input')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classify(returncode, stdout, stderr):
    """Never return any child-origin text, including a potentially hostile suffix."""
    if returncode != 0 and b'host must be * or localhost' in stderr:
        return 'numeric-network-host-rejected-by-profile-parser'
    if returncode == 0 and not stdout and not stderr:
        return 'profile-compiled-and-system-true-succeeded'
    return 'unclassified-failure-or-unexpected-output'


def capture(command, *, work, timeout=5, output_limit=8192):
    process = subprocess.Popen(command, cwd=work,
        env={'PATH':'/usr/bin:/bin','HOME':str(work),'TMPDIR':str(work)},
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True)
    stdout, stderr = bytearray(), bytearray()
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, stdout)
    selector.register(process.stderr, selectors.EVENT_READ, stderr)
    deadline = time.monotonic() + timeout
    try:
        while selector.get_map() or process.poll() is None:
            require(time.monotonic() < deadline, 'Diagnostic process deadline exceeded')
            for key, _ in selector.select(timeout=0.05):
                data = os.read(key.fileobj.fileno(), 4096)
                if data:
                    key.data.extend(data)
                    require(len(stdout)+len(stderr) <= output_limit, 'Diagnostic output bound exceeded')
                else:
                    selector.unregister(key.fileobj)
        process.wait(timeout=max(0.1,deadline-time.monotonic()))
        return process.returncode, bytes(stdout), bytes(stderr)
    finally:
        selector.close()
        for stream in (process.stdout,process.stderr):
            stream.close()
        try:
            os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=3)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository',type=Path,required=True)
    parser.add_argument('--review-receipt',type=Path,required=True)
    args = parser.parse_args()
    root = args.repository.resolve(strict=True)
    receipt = json.loads(args.review_receipt.read_text())
    require(receipt.get('execution_approved') is True and receipt.get('scope') == 'unchanged-seatbelt-profile-diagnostic-only',
            'Exact diagnostic execution review is not approved')
    required = {'packaging/engine-ci/diagnose_seatbelt.py','packaging/engine-ci/runtime-loopback.sb',TEMPLATE,WORKFLOW}
    require(required <= receipt.get('sha256',{}).keys(), 'Incomplete diagnostic review hash set')
    for filename,expected in receipt['sha256'].items():
        relative=PurePosixPath(filename)
        require(not relative.is_absolute() and '..' not in relative.parts,'Unsafe diagnostic input path')
        require(digest(root/filename)==expected,'Reviewed diagnostic input changed')
    require(digest(root/WORKFLOW)==digest(root/TEMPLATE),'Deployed diagnostic workflow differs')
    profile=root/'packaging/engine-ci/runtime-loopback.sb'
    require(digest(profile)==PROFILE_HASH,'The previously failing profile changed')
    require(platform.system()=='Darwin' and platform.machine()=='arm64','macOS arm64 only')
    require(Path('/usr/bin/sandbox-exec').is_file() and Path('/usr/bin/true').is_file(),'Required system tools absent')
    with tempfile.TemporaryDirectory(prefix='deepdesk-seatbelt-diagnostic-',dir=os.environ.get('RUNNER_TEMP')) as temporary:
        work=Path(temporary).resolve()
        for name in ('immutable','readonly'):
            (work/name).mkdir(mode=0o700)
        code,out,err=capture(['/usr/bin/sandbox-exec','-D','WORK_DIR='+str(work),
            '-D','IMMUTABLE_DIR='+str(work/'immutable'),'-D','READONLY_ENV='+str(work/'readonly'),
            '-D','SERVER_ADDRESS=127.0.0.1:54321','-f',str(profile),'/usr/bin/true'],work=work)
        result=classify(code,out,err)
        print(json.dumps({'scope':'unchanged-seatbelt-profile-diagnostic-only','classification':result,
            'returncode':code,'stdout_bytes':len(out),'stdout_sha256':hashlib.sha256(out).hexdigest(),
            'stderr_bytes':len(err),'stderr_sha256':hashlib.sha256(err).hexdigest(),
            'profile_sha256':PROFILE_HASH,'profile_changed':False,'dependency_downloaded':False,
            'dependency_executed':False,'socket_created':False,'raw_output_published':False},sort_keys=True))
        require(result!='unclassified-failure-or-unexpected-output','Diagnostic could not classify the system-tool result')


if __name__=='__main__':
    main()

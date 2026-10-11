"""Classify single versus nested application of the exact existing offline profile.

Only /usr/bin/sandbox-exec and /usr/bin/true execute. No dependency, socket,
network-policy change, fixture credentials or raw subprocess output.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path,PurePosixPath
import platform
import tempfile

PROFILE_HASH='9d4f464140e5bb35efb2f937e820349b6f7a47482d4fcb2a618cc489b9bf4710'
WORKFLOW='.github/workflows/engine-sandbox-diagnostic-macos.yml'
TEMPLATE='packaging/engine-ci/sandbox-diagnostic-macos.yml.template'


def require(value,message):
    if not value: raise RuntimeError(message)


def digest(path):
    require(path.is_file() and not path.is_symlink(),'Missing or linked diagnostic input')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classify(case,code,out,err):
    if code==0 and not out and not err: return 'system-true-succeeded'
    if case=='nested' and code==71 and not out and err.strip()==b'sandbox-exec: sandbox_apply: Operation not permitted':
        return 'nested-sandbox-application-denied'
    return 'unclassified-system-tool-result'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--repository',type=Path,required=True)
    parser.add_argument('--review-receipt',type=Path,required=True);args=parser.parse_args()
    root=args.repository.resolve(strict=True);receipt=json.loads(args.review_receipt.read_text())
    require(receipt.get('execution_approved') is True and receipt.get('scope')=='single-versus-nested-offline-profile-diagnostic',
            'Exact nested-profile diagnostic review not approved')
    required={'packaging/engine-ci/diagnose_nested_sandbox.py','packaging/engine-ci/diagnose_seatbelt.py',
              'packaging/engine-ci/runtime-offline.sb',TEMPLATE,WORKFLOW}
    require(required<=receipt.get('sha256',{}).keys(),'Incomplete diagnostic hash set')
    for filename,expected in receipt['sha256'].items():
        relative=PurePosixPath(filename);require(not relative.is_absolute() and '..' not in relative.parts,'Unsafe diagnostic path')
        require(digest(root/filename)==expected,'Reviewed diagnostic input changed')
    require(digest(root/WORKFLOW)==digest(root/TEMPLATE),'Deployed diagnostic workflow differs')
    profile=root/'packaging/engine-ci/runtime-offline.sb';require(digest(profile)==PROFILE_HASH,'Offline profile changed')
    require(platform.system()=='Darwin' and platform.machine()=='arm64','macOS arm64 only')
    for path in ('/usr/bin/sandbox-exec','/usr/bin/true'):require(Path(path).is_file(),'Required system binary absent')
    spec=importlib.util.spec_from_file_location('reviewed_private_capture',root/'packaging/engine-ci/diagnose_seatbelt.py')
    capture=importlib.util.module_from_spec(spec);spec.loader.exec_module(capture)
    with tempfile.TemporaryDirectory(prefix='deepdesk-nested-profile-',dir=os.environ.get('RUNNER_TEMP')) as temporary:
        work=Path(temporary).resolve()
        for name in ('fixture','immutable','readonly'):(work/name).mkdir(mode=0o700)
        def sandbox(writable):
            return ['/usr/bin/sandbox-exec','-D','WORK_DIR='+str(writable),'-D','IMMUTABLE_DIR='+str(work/'immutable'),
                    '-D','READONLY_ENV='+str(work/'readonly'),'-f',str(profile)]
        commands={'single':sandbox(work)+['/usr/bin/true'],
                  'nested':sandbox(work)+sandbox(work/'fixture')+['/usr/bin/true']}
        for case,command in commands.items():
            code,out,err=capture.capture(command,work=work,timeout=5,output_limit=8192)
            category=classify(case,code,out,err)
            print(json.dumps({'scope':'single-versus-nested-offline-profile-diagnostic','case':case,
                'classification':category,'returncode':code,'stdout_bytes':len(out),'stderr_bytes':len(err),
                'stdout_sha256':hashlib.sha256(out).hexdigest(),'stderr_sha256':hashlib.sha256(err).hexdigest(),
                'profile_sha256':PROFILE_HASH,'profile_changed':False,'dependency_downloaded':False,
                'dependency_executed':False,'socket_created':False,'raw_output_published':False},sort_keys=True))
            require(category!='unclassified-system-tool-result','Unclassified system-tool result; no fallback permitted')


if __name__=='__main__':main()

"""Approval-closed, source-free diagnosis of the exact Python exec canary."""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import sys
import tempfile
import time
sys.dont_write_bytecode = True

SCOPE = 'libmagic-python-exec-canary-diagnostic-only'
BRANCH = 'engine-libmagic-exec-diagnostic-ci'
BASE = '827c358df7a5956515a60e9fe1e75184791a2e28'
NAMES = {'stage.py','probe.py','control.py','test_helpers.py','README.md','bounded_runtime.py',
         'offline.sb','smoke-no-exec.sb','libmagic-exec-diagnostic-macos.yml.template'}
BOUNDS_SHA = 'a94a58ba7e45f203fafd4d4d7a0d60ec91cd8366ac7ae8d55909c7d8b1d128f4'
OFFLINE_SHA = 'b1ef4e080f63c8b50de664fe217ebd9887684454cdc7b94290aa2998cfd9802d'
SMOKE_SHA = '981b85c11f138be1f44192791fd1ebe2896096c976d9741f9e4207a677aef3a4'
PHASES = ('sdk-path','compiler-path','control-entry','restrictive-exec-probe')
FAILURES = {'Bounded subprocess failed; raw output withheld':'nonzero_exit',
    'Bounded subprocess timed out':'timeout','No subprocess time budget remains':'timeout',
    'Private output limit exceeded':'output_limit','Bounded working-set limit exceeded':'work_limit',
    'Bounded working-set limit exceeded at completion':'work_limit'}
CHILD_STATES = {'zero','nonzero_exit','timeout','output_limit','work_limit','unknown'}
OUTCOMES = {'permission_denied':'entered_permission_denied','other_oserror':'entered_unexpected_oserror',
    'child_nonzero':'entered_child_nonzero','other_exception':'entered_other_exception',
    'setup_exception':'entered_setup_exception','exec_succeeded':'entered_exec_was_allowed'}
MARKER_CAP = 128
WORK_CAP = 64*1024**2
STEP_OUTPUT_CAP = 16*1024


def require(ok, message):
    if not ok: raise RuntimeError(message)


def sha(path):
    p=Path(path); require(p.is_file() and not p.is_symlink(), 'Input missing or linked')
    return hashlib.sha256(p.read_bytes()).hexdigest()


def failure_category(error):
    return (FAILURES.get(error.args[0],'unknown') if type(error) is RuntimeError
            and len(error.args)==1 and type(error.args[0]) is str else 'unknown')


def validate_receipt(receipt, helpers, root, *, deployed=True):
    require(receipt.get('execution_approved') is True and receipt.get('scope')==SCOPE, 'Diagnostic approval is closed or scope differs')
    require(receipt.get('destination_branch')==BRANCH and receipt.get('base_commit')==BASE, 'Diagnostic destination differs')
    require(receipt.get('source_downloads_allowed') is False and receipt.get('compiler_execution_allowed') is False
            and receipt.get('native_payload_execution_allowed') is False and receipt.get('profile_changes_allowed') is False,
            'Diagnostic scope broadened')
    require(receipt.get('host_image_observation')=='read-only-_NSGetExecutablePath-no-executable-selection', 'Host identity observation scope differs')
    require(set(receipt.get('sha256',{}))==NAMES, 'Diagnostic review set differs')
    for name,digest in receipt['sha256'].items():
        require(type(digest) is str and re.fullmatch(r'[0-9a-f]{64}',digest) and sha(helpers/name)==digest, 'Reviewed diagnostic bytes differ')
    for name,digest in [('bounded_runtime.py',BOUNDS_SHA),('offline.sb',OFFLINE_SHA),('smoke-no-exec.sb',SMOKE_SHA)]:
        require(sha(helpers/name)==digest, 'Frozen diagnostic helper or profile differs')
    if deployed:
        require(sha(root/'.github/workflows/engine-libmagic-exec-diagnostic-macos.yml')==
                sha(helpers/'libmagic-exec-diagnostic-macos.yml.template'),'Deployed diagnostic workflow differs')


def read_marker(path):
    path=Path(path)
    before=path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink==1 and before.st_size<=MARKER_CAP, 'Invalid diagnostic marker')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        current=os.fstat(fd)
        require((before.st_dev,before.st_ino)==(current.st_dev,current.st_ino)
                and stat.S_ISREG(current.st_mode) and current.st_nlink==1, 'Diagnostic marker changed')
        data=os.read(fd,MARKER_CAP+1)
        require(len(data)<=MARKER_CAP and os.read(fd,1)==b'' and os.fstat(fd).st_size==len(data), 'Oversized or changing diagnostic marker')
        return data
    finally: os.close(fd)


def parse_probe_marker(data, child_status):
    require(type(data) is bytes and len(data)<=MARKER_CAP and child_status in CHILD_STATES, 'Invalid diagnostic marker contract')
    if data==b'': progress='python_entry_not_observed'
    elif data==b'entered\n': progress='entered_before_imports_incomplete'
    elif data==b'entered\nimports_ready\n': progress='entered_probe_incomplete'
    elif data==b'entered\nsetup_exception\n': progress='entered_setup_exception'
    else:
        prefix=b'entered\nimports_ready\n'
        require(data.startswith(prefix) and data.endswith(b'\n'), 'Invalid diagnostic token order')
        token=data[len(prefix):-1]
        require(token in {x.encode() for x in OUTCOMES}, 'Unreviewed diagnostic token')
        progress=OUTCOMES[token.decode('ascii')]
    if child_status not in {'zero','nonzero_exit'}:
        return {'progress':progress,'classification':'child_inconclusive','canary_passed':False}
    passed=progress=='entered_permission_denied' and child_status=='zero'
    mismatch=(progress=='entered_permission_denied') != (child_status=='zero')
    return {'progress':progress,'classification':'exit_marker_mismatch' if mismatch else progress,'canary_passed':passed}



def evaluate_probe_marker(path, child_status):
    try: return parse_probe_marker(read_marker(path),child_status)
    except Exception:
        return {'progress':'marker_unavailable','classification':'invalid_marker','canary_passed':False}


def path_class(value):
    if value.startswith('/usr/bin/'): return 'usr_bin'
    if value.startswith('/Applications/'): return 'apple_applications'
    if value.startswith('/Library/Developer/'): return 'apple_developer'
    return 'other'



def read_host_image_path():
    # Read the current process image only. No new binary or library path is selected.
    import ctypes
    process=ctypes.CDLL(None)
    function=process._NSGetExecutablePath
    function.argtypes=[ctypes.POINTER(ctypes.c_char),ctypes.POINTER(ctypes.c_uint32)]
    function.restype=ctypes.c_int
    buffer=ctypes.create_string_buffer(16384);size=ctypes.c_uint32(len(buffer))
    require(function(buffer,ctypes.byref(size))==0 and buffer.value and len(buffer.value)<16384,
            'Host image observation unavailable')
    return os.fsdecode(buffer.value)


def host_image_observation(py):
    try:
        value=read_host_image_path()
        require(type(value) is str and value.startswith('/') and len(os.fsencode(value))<16384,
                'Invalid host image observation')
        canonical=Path(value).resolve()
        basename=canonical.name
        if basename in {'Python','python','python3'}: name_class=basename
        elif re.fullmatch(r'python3\.[0-9]+',basename): name_class='python3_versioned'
        else: name_class='other'
        return {'host_image_observation':'available','host_image_matches_resolved_interpreter':canonical==py,
                'host_image_path_class':path_class(str(canonical)),'host_image_basename_class':name_class,
                'host_image_path_sha256':hashlib.sha256(os.fsencode(str(canonical))).hexdigest()}
    except Exception:
        return {'host_image_observation':'unavailable','host_image_matches_resolved_interpreter':None,
                'host_image_path_class':'unknown','host_image_basename_class':'unknown','host_image_path_sha256':None}


def private_child(bounded, command, *, phase, **kwargs):
    require(phase in PHASES, 'Unreviewed diagnostic phase')
    capture=io.StringIO()
    try:
        with contextlib.redirect_stdout(capture): output=bounded.run_bounded(command,**kwargs)
    except Exception as error:
        return {'phase':phase,'child_status':failure_category(error),'output_metadata_available':False},None
    try:
        summary=json.loads(capture.getvalue())
        require(set(summary)=={'bounded_step','stdout_bytes','stdout_sha256','stderr_bytes','stderr_sha256'}
                and summary['bounded_step']=='passed' and summary['stdout_bytes']==len(output)
                and type(summary['stderr_bytes']) is int and 0<=summary['stderr_bytes']<=STEP_OUTPUT_CAP
                and summary['stdout_bytes']+summary['stderr_bytes']<=STEP_OUTPUT_CAP
                and all(type(summary[k]) is str and re.fullmatch(r'[0-9a-f]{64}',summary[k]) for k in ['stdout_sha256','stderr_sha256'])
                and summary['stdout_sha256']==hashlib.sha256(output).hexdigest(), 'Invalid private summary')
    except Exception:
        return {'phase':phase,'child_status':'unknown','output_metadata_available':False},None
    return {'phase':phase,'child_status':'zero','output_metadata_available':True,
            **{k:summary[k] for k in ['stdout_bytes','stdout_sha256','stderr_bytes','stderr_sha256']}},output


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--repository',type=Path,required=True)
    parser.add_argument('--review-receipt',type=Path,required=True);args=parser.parse_args()
    root=args.repository.resolve(strict=True);helpers=root/'packaging/libmagic-exec-diagnostic'
    receipt_path=args.review_receipt if args.review_receipt.is_absolute() else root/args.review_receipt
    require(receipt_path.resolve()==helpers/'review-receipt.json' and not receipt_path.is_symlink(), 'Diagnostic receipt location differs')
    validate_receipt(json.loads(receipt_path.read_text()),helpers,root)
    require(platform.system()=='Darwin' and platform.machine()=='arm64', 'Native macOS arm64 required')
    require(os.environ.get('GITHUB_REPOSITORY')=='Emin-dev/deepdesk' and
            os.environ.get('GITHUB_REF')=='refs/heads/'+BRANCH,'Diagnostic destination guard failed')
    event=Path(os.environ.get('GITHUB_EVENT_PATH',''))
    require(event.is_file() and event.stat().st_size<2*1024**2,'Missing diagnostic event')
    repository=json.loads(event.read_text()).get('repository',{})
    require(repository.get('private') is False and repository.get('full_name')=='Emin-dev/deepdesk','Public repository guard failed')
    require(Path('/usr/bin/sandbox-exec').is_file(),'Sandbox unavailable')
    py=Path(sys.executable).resolve()
    require(sys.version_info>=(3,9) and not str(py).startswith(('/opt/homebrew/','/opt/local/','/usr/local/','/Library/Frameworks/Python.framework/')),
            'Unreviewed host interpreter')
    spec=importlib.util.spec_from_file_location('exact_diagnostic_bounds',helpers/'bounded_runtime.py')
    bounded=importlib.util.module_from_spec(spec);spec.loader.exec_module(bounded)
    started=time.monotonic();deadline=started+120;steps=[];reserved_output=0
    identity=host_image_observation(py)
    print(json.dumps(identity,sort_keys=True),flush=True)
    with tempfile.TemporaryDirectory(prefix='deepdesk-exec-diagnostic-',dir=os.environ.get('RUNNER_TEMP')) as td:
        work=Path(td).resolve();require(not re.search(r'\s',str(work)) and shutil.disk_usage(work).free>=128*1024**2,'Diagnostic work preflight failed')
        immutable=work/'immutable';immutable.mkdir(mode=0o700)
        home=work/'home';home.mkdir(mode=0o700);tmp=work/'tmp';tmp.mkdir(mode=0o700)
        env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','HOME':str(home),'TMPDIR':str(tmp),
             'LC_ALL':'C','LANG':'C','TZ':'UTC','SOURCE_DATE_EPOCH':'0',
             'PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1','MACOSX_DEPLOYMENT_TARGET':'26.0'}
        def run(command,phase,*,restrictive=False):
            nonlocal reserved_output
            remaining=deadline-time.monotonic();require(remaining>0,'Diagnostic total timeout')
            reserved_output+=STEP_OUTPUT_CAP;require(reserved_output<=64*1024,'Diagnostic private-output budget exceeded')
            wrapped=['/usr/bin/sandbox-exec','-D','WORK_DIR='+str(work),'-D','IMMUTABLE_DIR='+str(immutable),
                     *(['-D','FIXTURE_PATH='+str(py)] if restrictive else []),
                     '-f',str(helpers/('smoke-no-exec.sb' if restrictive else 'offline.sb')),*map(str,command)]
            row,output=private_child(bounded,wrapped,phase=phase,cwd=work,env=env,work=work,
                timeout=min(10,remaining),disk_limit=WORK_CAP,output_limit=STEP_OUTPUT_CAP,public_summary=True)
            steps.append(row);print(json.dumps(row,sort_keys=True),flush=True)
            return row,output
        values={}
        for phase,command in [('sdk-path',['/usr/bin/xcrun','--sdk','macosx','--show-sdk-path']),
                              ('compiler-path',['/usr/bin/xcrun','--sdk','macosx','--find','clang'])]:
            row,output=run(command,phase)
            require(row['child_status']=='zero' and output is not None,'Diagnostic tool path query failed')
            value=output.decode('utf-8').strip()
            require(value.startswith(('/Applications/','/Library/Developer/','/usr/bin/')) and not re.search(r'\s',value)
                    and Path(value).exists(),'Unexpected Apple toolchain path')
            values[phase]=value
        sdk=values['sdk-path'];clang=values['compiler-path']
        env.update({'CC':clang,'CFLAGS':'-arch arm64 -isysroot '+sdk+' -O2','CPPFLAGS':'-isysroot '+sdk,
                    'LDFLAGS':'-arch arm64 -isysroot '+sdk,'SDKROOT':sdk})
        control=work/'control.marker';control.write_bytes(b'')
        row,output=run([py,'-I','-c',(helpers/'control.py').read_text(),control],'control-entry')
        require(row['child_status']=='zero' and output==b'' and read_marker(control)==b'entered\n','Diagnostic control entry failed')
        marker=work/'probe.marker';marker.write_bytes(b'')
        row,output=run([py,'-I','-c',(helpers/'probe.py').read_text(),marker],'restrictive-exec-probe',restrictive=True)
        require(output in (None,b''),'Unexpected diagnostic probe stdout')
        parsed=evaluate_probe_marker(marker,row['child_status'])
        result={'scope':SCOPE,**parsed,**identity,'child_status':row['child_status'],
                'interpreter_path_class':path_class(sys.executable),'resolved_interpreter_path_class':path_class(str(py)),
                'interpreter_path_sha256':hashlib.sha256(sys.executable.encode()).hexdigest(),
                'resolved_interpreter_path_sha256':hashlib.sha256(str(py).encode()).hexdigest(),
                'declared_and_resolved_interpreter_equal':sys.executable==str(py),
                'sdk_path_sha256':hashlib.sha256(sdk.encode()).hexdigest(),'compiler_path_sha256':hashlib.sha256(clang.encode()).hexdigest(),
                'source_downloaded':False,'compiler_executed':False,'native_payload_executed':False,
                'mime_fixture_executed':False,'exec_allowance_broadened':False,'artifact_uploaded':False,
                'elapsed_seconds':round(time.monotonic()-started,3),'working_set_bytes':bounded.disk_bytes(work)}
        require(result['working_set_bytes']<=WORK_CAP and time.monotonic()<deadline,'Diagnostic final bounds exceeded')
        print(json.dumps(result,sort_keys=True),flush=True)
        require(parsed['canary_passed'],'Diagnostic canary did not pass; details withheld')


if __name__=='__main__':
    try: main()
    except Exception:
        print(json.dumps({'diagnostic_status':'failed','detail':'withheld'}),flush=True)
        raise SystemExit(1) from None

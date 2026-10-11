"""First-party bounded process supervisor; reviewed new 4 GiB workspace ceiling. Never forwards child strings to CI.
Adapted conceptually from libmagic-source-candidate-v2/bounded_runtime.py;
independent receipt hashes and review are required. No downloaded imports.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import shutil
import signal
import stat
import errno
import subprocess
import time

GIB=1024**3
MAX_SUPERVISOR_DIAGNOSTIC_BYTES=2048
FLAGS={
 'meson_isolation_required':(b'deepdesk_meson_isolation_required',),
 'meson_command_contract_failed':(b'deepdesk_meson_command_contract_failed',),
 'meson_launcher_contract_failed':(b'deepdesk_meson_launcher_contract_failed',),
 'sandbox_initialization_denied':(b'sandbox-exec: sandbox_apply',b'failed to initialize sandbox'),
 'permission_denied':(b'operation not permitted',b'permission denied'),
 'compiler_unusable':(b'c compiler cannot create executables',b'compiler cannot compile programs'),
 'missing_header':(b'file not found',b'no such file or directory'),
 'missing_make_target':(b'no rule to make target',),
 'linker_failure':(b'undefined symbols for architecture',b'linker command failed',b'library not found for'),
 'source_regeneration_attempt':(b'autoreconf',b'automake-',b'autoconf-',b'bison: command not found'),
 'dependency_not_found':(b'dependency "',b'dependency lookup',b'not found: pkg-config'),
 'unexpected_network_attempt':(b'could not resolve host',b'network is unreachable',b'failed to download'),
 'catalog_tool_missing':(b'translation (po) targets will be ignored',b'xgettext not found',b'msgfmt not found'),
}

def classify(data):
    low=data.lower()
    return sorted(k for k,needles in FLAGS.items() if any(x in low for x in needles))


def disk_bytes(root):
    total=0
    for base,dirs,names in os.walk(root,followlinks=False):
        dirs[:]=[x for x in dirs if not (Path(base)/x).is_symlink()]
        for name in names:
            p=Path(base)/name
            try:
                if not p.is_symlink():total+=p.stat().st_size
            except FileNotFoundError:pass
    return total


def private_file_record(path,tag):
    """No-follow openat chain plus stable bounded regular-file read; no path/content output."""
    p=Path(path);limit=2*1024**2;fds=[];file_fd=None
    try:
        if not p.is_absolute() or '..' in p.parts:return {'tag':tag,'invalid_type':True}
        directory_flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
        parent=os.open('/',directory_flags);fds.append(parent)
        for part in p.parts[1:-1]:
            parent=os.open(part,directory_flags,dir_fd=parent);fds.append(parent)
        file_fd=os.open(p.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
        before=os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode):return {'tag':tag,'present':True,'invalid_type':True}
        if before.st_size>limit:return {'tag':tag,'present':True,'oversize':True,'bytes':before.st_size}
        parts=[];count=0
        while count<=limit:
            chunk=os.read(file_fd,min(65536,limit+1-count))
            if not chunk:break
            parts.append(chunk);count+=len(chunk)
        after=os.fstat(file_fd)
        identity=lambda st:(st.st_dev,st.st_ino,st.st_mode,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
        if count>limit:return {'tag':tag,'present':True,'oversize':True,'bytes':count}
        if identity(before)!=identity(after) or count!=after.st_size:return {'tag':tag,'present':True,'unstable':True,'bytes':count}
        data=b''.join(parts)
        return {'tag':tag,'present':True,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'classifications':classify(data)}
    except OSError as error:
        return {'tag':tag,'present':error.errno!=errno.ENOENT,'invalid_or_unreadable':error.errno!=errno.ENOENT}
    finally:
        if file_fd is not None:os.close(file_fd)
        for fd in reversed(fds):os.close(fd)


def diagnostic_error(error):
    """Fixed exception/errno vocabulary; never expose an exception message."""
    kind = ('timeout_expired' if isinstance(error, subprocess.TimeoutExpired) else
            'os_error' if isinstance(error, OSError) else
            'subprocess_error' if isinstance(error, subprocess.SubprocessError) else
            'value_error' if isinstance(error, ValueError) else 'other')
    names = ('EPERM', 'EACCES', 'ESRCH', 'ECHILD', 'EINTR', 'EIO', 'ENOENT',
             'ENOMEM', 'ENOSPC', 'EMFILE', 'ENFILE', 'EINVAL', 'EAGAIN', 'ETIMEDOUT')
    code = getattr(error, 'errno', None)
    name = next((name for name in names if type(code) is int and code == getattr(errno, name)), None)
    return {'kind': kind, 'errno': name if name is not None else 'other' if code is not None else None}


def bounded_diagnostic(detail):
    # Checked only after mandatory cleanup. A contract violation remains fatal.
    if len(json.dumps(detail, sort_keys=True, allow_nan=False).encode('utf-8')) > MAX_SUPERVISOR_DIAGNOSTIC_BYTES:
        raise ValueError('supervisor_diagnostic_bound')
    return detail


def remaining_ms(deadline, now):
    value = deadline - now
    return max(0, min(1500000, round(value * 1000))) if math.isfinite(value) else None


def run(command,*,cwd,env,work,deadline,output_remaining,expected_codes=(0,),clock=time.monotonic,
        deadline_source='unspecified',requested_timeout=None):
    start=clock(); output=bytearray();errors=bytearray();counts=[0,0];hashes=[hashlib.sha256(),hashlib.sha256()]
    reason=None;exit_code=None;peak=0;cleanup='not_started';process=None;selector=selectors.DefaultSelector()
    operation='preflight_deadline';primary=None;supervisor_error=None
    detail={'schema':1,'primary_failure_class':None,'primary_operation':None,'primary_exception':None,
        'leader_exit_before_cleanup':None,'supervisor_error':None,
        'deadline':{'source':deadline_source if deadline_source in ('command','shared_lane','unspecified') else 'unspecified',
            'requested_timeout_seconds':requested_timeout if type(requested_timeout) is int and 0 <= requested_timeout <= 1500 else None,
            'effective_remaining_ms_at_start':remaining_ms(deadline,start)},
        'cleanup':{'signal':{'result':'not_started','error':None},
                   'leader_wait':{'result':'not_started','error':None,'returncode':None},
                   'group_probe':{'result':'not_started','error':None,'operation':None}}}
    def observe(name, function, *args, **kwargs):
        nonlocal operation
        operation=name
        return function(*args, **kwargs)
    try:
        if deadline<=start:reason='deadline_exceeded'
        elif output_remaining<=0:reason='output_limit';operation='preflight_output_limit'
        elif observe('preflight_workspace_scan',disk_bytes,work)>4*GIB:reason='workspace_limit'
        elif observe('preflight_free_space',shutil.disk_usage,work).free<GIB:reason='free_space_floor'
        else:
            process=observe('spawn',subprocess.Popen,list(map(str,command)),cwd=cwd,env=env,stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
            observe('register_stdout',selector.register,process.stdout,selectors.EVENT_READ,0)
            observe('register_stderr',selector.register,process.stderr,selectors.EVENT_READ,1)
            next_scan=0
            while observe('pipe_state',selector.get_map) or observe('leader_poll',process.poll) is None:
                now=observe('monitor_clock',clock)
                if now>=deadline:reason='deadline_exceeded';operation='monitor_deadline';break
                if now>=next_scan:
                    used=observe('monitor_workspace_scan',disk_bytes,work);peak=max(peak,used);next_scan=now+0.5
                    if used>4*GIB:reason='workspace_limit';break
                    if observe('monitor_free_space',shutil.disk_usage,work).free<GIB:reason='free_space_floor';break
                for key,_ in observe('pipe_select',selector.select,timeout=0.05):
                    chunk=observe('pipe_read',os.read,key.fileobj.fileno(),65536)
                    if not chunk:observe('pipe_unregister',selector.unregister,key.fileobj);continue
                    idx=key.data;counts[idx]+=len(chunk);hashes[idx].update(chunk)
                    if sum(counts)>output_remaining:reason='output_limit';operation='monitor_output_limit';break
                    (output if idx==0 else errors).extend(chunk)
                if reason:break
            if reason is not None:primary=(reason,operation,None)
            exit_code=observe('leader_poll_after_loop',process.poll)
            if reason is None:
                exit_code=observe('normal_leader_wait',process.wait,timeout=max(0.1,deadline-clock()))
                used=observe('post_exit_workspace_scan',disk_bytes,work);peak=max(peak,used)
                if used>4*GIB:reason='workspace_limit'
                elif observe('post_exit_free_space',shutil.disk_usage,work).free<GIB:reason='free_space_floor'
                elif exit_code not in expected_codes:reason='child_exit';operation='child_exit_contract'
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        reason='supervisor_or_spawn_failure'
        supervisor_error={'operation':operation,'error':diagnostic_error(error)}
        if primary is None:primary=(reason,operation,diagnostic_error(error))
    finally:
        if primary is None:primary=(reason,operation if reason is not None else None,None)
        detail['primary_failure_class'],detail['primary_operation'],detail['primary_exception']=primary
        detail['supervisor_error']=supervisor_error
        detail['leader_exit_before_cleanup']=exit_code
        observed_now=clock()
        detail['deadline']['effective_remaining_ms_before_cleanup']=remaining_ms(deadline,observed_now)
        detail['deadline']['reached_before_cleanup']=observed_now>=deadline
        selector.close()
        if process is not None:
            try:
                os.killpg(process.pid,signal.SIGKILL)
                detail['cleanup']['signal']['result']='sent'
            except ProcessLookupError:detail['cleanup']['signal']['result']='group_absent'
            except OSError as error:
                reason='cleanup_failure';detail['cleanup']['signal']={'result':'error','error':diagnostic_error(error)}
            cleanup_operation='leader_wait'
            try:
                process.wait(timeout=3)
                detail['cleanup']['leader_wait']={'result':'reaped','error':None,'returncode':process.returncode}
                if exit_code is None:exit_code=process.returncode
                cleanup='process_group_killed_and_leader_reaped'
                cleanup_operation='group_deadline_clock'
                cleanup_deadline=time.monotonic()+2
                while True:
                    cleanup_operation='group_probe'
                    try:os.killpg(process.pid,0)
                    except ProcessLookupError:
                        detail['cleanup']['group_probe']['result']='absent';break
                    detail['cleanup']['group_probe']['result']='present'
                    cleanup_operation='group_deadline_clock'
                    if time.monotonic()>=cleanup_deadline:
                        reason='cleanup_failure';cleanup='process_group_still_present'
                        detail['cleanup']['group_probe']['result']='still_present_at_deadline';break
                    cleanup_operation='group_probe_sleep'
                    time.sleep(0.02)
            except (OSError,subprocess.SubprocessError) as error:
                reason='cleanup_failure';cleanup='leader_not_reaped'  # Legacy field retained; precise result below.
                if cleanup_operation=='leader_wait':
                    detail['cleanup']['leader_wait']={'result':'timeout' if isinstance(error,subprocess.TimeoutExpired) else 'error',
                        'error':diagnostic_error(error),'returncode':None}
                else:
                    detail['cleanup']['group_probe']={'result':'error','error':diagnostic_error(error),'operation':cleanup_operation}
            for stream in (process.stdout,process.stderr):
                if stream is not None:stream.close()
    record={'status':'failed' if reason else 'passed','failure_class':reason,'exit_code':exit_code,
        'seconds':round(clock()-start,3),'stdout_bytes':counts[0],'stdout_sha256':hashes[0].hexdigest(),
        'stderr_bytes':counts[1],'stderr_sha256':hashes[1].hexdigest(),'classifications':classify(bytes(output)+bytes(errors)),
        'peak_monitored_workspace_bytes':peak,'cleanup':cleanup,'supervisor_diagnostics':bounded_diagnostic(detail)}
    return record,bytes(output),bytes(errors)

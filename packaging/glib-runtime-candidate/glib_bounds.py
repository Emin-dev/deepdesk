"""First-party bounded process supervisor; reviewed new 4 GiB workspace ceiling. Never forwards child strings to CI.
Adapted conceptually from libmagic-source-candidate-v2/bounded_runtime.py;
independent receipt hashes and review are required. No downloaded imports.
"""
from __future__ import annotations
import hashlib
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


def run(command,*,cwd,env,work,deadline,output_remaining,expected_codes=(0,),clock=time.monotonic):
    start=clock(); output=bytearray();errors=bytearray();counts=[0,0];hashes=[hashlib.sha256(),hashlib.sha256()]
    reason=None;exit_code=None;peak=0;cleanup='not_started';process=None;selector=selectors.DefaultSelector()
    try:
        if deadline<=start:reason='deadline_exceeded'
        elif output_remaining<=0:reason='output_limit'
        elif disk_bytes(work)>4*GIB:reason='workspace_limit'
        elif shutil.disk_usage(work).free<GIB:reason='free_space_floor'
        else:
            process=subprocess.Popen(list(map(str,command)),cwd=cwd,env=env,stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
            selector.register(process.stdout,selectors.EVENT_READ,0);selector.register(process.stderr,selectors.EVENT_READ,1)
            next_scan=0
            while selector.get_map() or process.poll() is None:
                now=clock()
                if now>=deadline:reason='deadline_exceeded';break
                if now>=next_scan:
                    used=disk_bytes(work);peak=max(peak,used);next_scan=now+0.5
                    if used>4*GIB:reason='workspace_limit';break
                    if shutil.disk_usage(work).free<GIB:reason='free_space_floor';break
                for key,_ in selector.select(timeout=0.05):
                    chunk=os.read(key.fileobj.fileno(),65536)
                    if not chunk:selector.unregister(key.fileobj);continue
                    idx=key.data;counts[idx]+=len(chunk);hashes[idx].update(chunk)
                    if sum(counts)>output_remaining:reason='output_limit';break
                    (output if idx==0 else errors).extend(chunk)
                if reason:break
            exit_code=process.poll()
            if reason is None:
                exit_code=process.wait(timeout=max(0.1,deadline-clock()))
                used=disk_bytes(work);peak=max(peak,used)
                if used>4*GIB:reason='workspace_limit'
                elif shutil.disk_usage(work).free<GIB:reason='free_space_floor'
                elif exit_code not in expected_codes:reason='child_exit'
    except (OSError,ValueError,subprocess.SubprocessError):reason='supervisor_or_spawn_failure'
    finally:
        selector.close()
        if process is not None:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            except OSError:reason='cleanup_failure'
            try:
                process.wait(timeout=3)
                if exit_code is None:exit_code=process.returncode
                cleanup='process_group_killed_and_leader_reaped'
                cleanup_deadline=time.monotonic()+2
                while True:
                    try:os.killpg(process.pid,0)
                    except ProcessLookupError:break
                    if time.monotonic()>=cleanup_deadline:
                        reason='cleanup_failure';cleanup='process_group_still_present';break
                    time.sleep(0.02)
            except (OSError,subprocess.SubprocessError):reason='cleanup_failure';cleanup='leader_not_reaped'
            for stream in (process.stdout,process.stderr):
                if stream is not None:stream.close()
    record={'status':'failed' if reason else 'passed','failure_class':reason,'exit_code':exit_code,
        'seconds':round(clock()-start,3),'stdout_bytes':counts[0],'stdout_sha256':hashes[0].hexdigest(),
        'stderr_bytes':counts[1],'stderr_sha256':hashes[1].hexdigest(),'classifications':classify(bytes(output)+bytes(errors)),
        'peak_monitored_workspace_bytes':peak,'cleanup':cleanup}
    return record,bytes(output),bytes(errors)

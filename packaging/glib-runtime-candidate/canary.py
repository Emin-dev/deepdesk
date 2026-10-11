"""First-party checks for the exact inherited sandbox; fixed output only."""
import errno
import os
from pathlib import Path
import socket
import subprocess
import sys
mode=sys.argv[1]
def denied(call):
    try:call()
    except OSError as e:
        if e.errno not in (errno.EPERM,errno.EACCES):raise SystemExit(71)
    else:raise SystemExit(72)
if mode in ('network','loopback','bind'):
    def attempt():
        with socket.socket() as s:
            s.settimeout(1)
            if mode=='bind':s.bind(('127.0.0.1',0))
            else:s.connect(('192.0.2.1',9) if mode=='network' else ('127.0.0.1',54321))
    denied(attempt)
elif mode=='deny-write':
    def attempt():
        fd=os.open(sys.argv[2],os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
    denied(attempt)
elif mode=='allow-write':
    Path(sys.argv[2]).write_bytes(b'first-party-canary')
elif mode=='deny-read':
    denied(lambda:Path(sys.argv[2]).read_bytes())
elif mode=='inherited':
    p=subprocess.run([sys.executable,'-I','-S',__file__,'network'],capture_output=True)
    if p.returncode!=0 or p.stdout!=b'canary_ok\n' or p.stderr:raise SystemExit(73)
else:raise SystemExit(74)
print('canary_ok')

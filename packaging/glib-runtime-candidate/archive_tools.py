"""Exact bounded retrieval/extraction of six reviewed archives; no package execution."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import tarfile
import time
import urllib.parse
import urllib.request
import zipfile

class ContractError(Exception): pass

def need(ok):
    if not ok:raise ContractError()

def digest(path):
    p=Path(path);need(p.is_file() and not p.is_symlink());h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(1024**2),b''):h.update(chunk)
    return h.hexdigest()

def relative(name):
    need(isinstance(name,str) and 0<len(name)<4096 and '\\' not in name and '\x00' not in name)
    p=PurePosixPath(name);need(not p.is_absolute() and all(x not in ('','.','..') for x in name.split('/')))
    return p

class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self,hosts):self.hosts=set(hosts);self.count=0
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        self.count+=1;p=urllib.parse.urlsplit(newurl)
        need(self.count<=3 and p.scheme=='https' and p.hostname in self.hosts and p.port in (None,443) and not p.username and not p.password and not p.fragment)
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def download(pin,destination,deadline):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),OfficialRedirect(pin['redirect_hosts']))
    need(time.monotonic()<deadline)
    request=urllib.request.Request(pin['url'],headers={'User-Agent':'Deepdesk-PDF-Foundation-Static-Pins/1.0'})
    total=0
    with opener.open(request,timeout=min(10,deadline-time.monotonic())) as response,Path(destination).open('xb') as f:
        u=urllib.parse.urlsplit(response.geturl());need(response.status==200 and u.scheme=='https' and u.hostname in pin['redirect_hosts'])
        length=response.headers.get('Content-Length');need(length is None or length==str(pin['size']))
        while True:
            need(time.monotonic()<deadline)
            chunk=response.read(65536)
            if not chunk:break
            total+=len(chunk);need(total<=pin['size']);f.write(chunk)
    need(total==pin['size'] and digest(destination)==pin['sha256'])

def extract(pin,archive,destination,manifest_path,checkpoint=lambda:None):
    need(digest(archive)==pin['sha256'] and digest(manifest_path)==pin['member_manifest_sha256'])
    contract=json.loads(Path(manifest_path).read_text());rows=contract['members'];expected={r['path']:r for r in rows}
    need(len(rows)==len(expected)==pin['member_count'] and contract['archive_sha256']==pin['sha256'] and contract['expanded_bytes']==pin['expanded_bytes'])
    root=Path(destination);root.mkdir(mode=0o700);seen=set();total=0;links=[];dirs=[]
    def materialize(name,kind,size,mode,mtime,data=None,target=None):
        nonlocal total
        checkpoint();rel=relative(name);need(name not in seen and name in expected);r=expected[name]
        need(r['kind']==kind and r['size']==size and r['mode']==mode and size<=pin['max_member_bytes'])
        if pin['format']=='tar':need(r['mtime']==mtime and rel.parts[0]==pin['root'])
        seen.add(name);p=root.joinpath(*rel.parts)
        # Links are delayed until all files/directories are verified and written.
        need(not p.is_symlink() and not any(x.is_symlink() for x in p.parents if x!=root.parent))
        if kind=='directory':p.mkdir(mode=0o700,parents=True,exist_ok=True);dirs.append((p,mode,mtime))
        elif kind=='symlink':
            need(pin['id']=='python' and r['target']==target and PurePosixPath(target).name==target and target not in ('','.','..'));links.append((p,target))
        else:
            need(kind=='file' and len(data)==size and hashlib.sha256(data).hexdigest()==r['sha256'])
            total+=size;need(total<=pin['expanded_bytes']);p.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            with p.open('xb') as f:f.write(data)
            os.chmod(p,mode&0o777 if mode else 0o644)
            if mtime is not None:os.utime(p,(mtime,mtime))
    if pin['format']=='tar':
        with tarfile.open(archive) as t:
            for m in t:
                checkpoint()
                need(m.isfile() or m.isdir() or m.issym());need(not m.islnk());name=m.name.rstrip('/')
                kind='file' if m.isfile() else 'directory' if m.isdir() else 'symlink'
                need(name in expected and m.size<=pin['max_member_bytes'])
                materialize(name,kind,m.size,m.mode,m.mtime,t.extractfile(m).read(m.size+1) if m.isfile() else None,m.linkname if m.issym() else None)
    else:
        with zipfile.ZipFile(archive) as z:
            for m in z.infolist():
                checkpoint()
                name=m.filename.rstrip('/');need(name in expected and m.file_size<=pin['max_member_bytes'])
                mode=(m.external_attr>>16)&0o777;need((m.external_attr>>16)&0o170000 not in (0o120000,0o010000,0o020000,0o060000))
                materialize(name,'directory' if m.is_dir() else 'file',m.file_size,mode,None,None if m.is_dir() else z.read(m))
    need(seen==set(expected) and total==pin['expanded_bytes'])
    for p,target in links:
        need((p.parent/target).is_file() and not (p.parent/target).is_symlink());p.symlink_to(target)
    for p,mode,mtime in reversed(dirs):
        os.chmod(p,mode&0o777 if mode else 0o755)
        if mtime is not None:os.utime(p,(mtime,mtime))
    return root/pin['root'] if pin['root'] else root

def snapshot(root):
    records={};root=Path(root)
    for p in sorted(root.rglob('*')):
        name=p.relative_to(root).as_posix()
        if p.is_symlink():need(p.resolve().is_relative_to(root.resolve()));records[name]={'link':os.readlink(p)}
        elif p.is_file():records[name]={'bytes':p.stat().st_size,'sha256':digest(p)}
        else:need(p.is_dir())
    return records

"""Data-only extension for the four exact additional source archives. Never executes inputs."""
from pathlib import Path, PurePosixPath
import hashlib
import importlib.util
import json
import os
import tarfile

_spec = importlib.util.spec_from_file_location('foundation_archive', Path(__file__).with_name('archive_tools.py'))
_base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_base)
digest, snapshot, download, need = _base.digest, _base.snapshot, _base.download, _base.need
OfficialRedirect, ContractError = _base.OfficialRedirect, _base.ContractError
SOURCE_LINKS = {
    'glib-2.90.1/COPYING': 'LICENSES/LGPL-2.1-or-later.txt',
    'glib-2.90.1/gmodule/COPYING': '../LICENSES/LGPL-2.1-or-later.txt',
}


def extract(pin, archive, destination, manifest_path, checkpoint=lambda: None):
    if pin['id'] not in ('glib', 'libffi', 'make', 'libiconv'):
        return _base.extract(pin, archive, destination, manifest_path, checkpoint)
    need(digest(archive) == pin['sha256'] and digest(manifest_path) == pin['member_manifest_sha256'])
    manifest = json.loads(Path(manifest_path).read_text())
    rows = {r['path']: r for r in manifest['members']}
    need(len(rows) == len(manifest['members']) == pin['member_count'])
    need(manifest['archive_sha256'] == pin['sha256'] and manifest['expanded_bytes'] == pin['expanded_bytes'])
    root = Path(destination)
    root.mkdir(mode=0o700)
    seen, links, directories, total = set(), [], [], 0
    with tarfile.open(archive) as source:
        for member in source:
            checkpoint()
            name = member.name.rstrip('/')
            rel = _base.relative(name)
            need(rel.parts[0] == pin['root'] and name in rows and name not in seen)
            row = rows[name]
            kind = 'file' if member.isfile() else 'directory' if member.isdir() else 'symlink' if member.issym() else None
            need(kind == row['kind'] and member.mode == row['mode'] and member.mtime == row['mtime'])
            need(member.size == row['size'] and member.size <= pin['max_member_bytes'])
            target = root.joinpath(*rel.parts)
            need(not target.is_symlink() and not any(p.is_symlink() for p in target.parents if p != root.parent))
            seen.add(name)
            if kind == 'directory':
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
                directories.append((target, member))
            elif kind == 'symlink':
                need(pin['id'] == 'glib' and SOURCE_LINKS.get(name) == member.linkname == row['target'])
                links.append((target, member.linkname))
            else:
                need(kind == 'file')
                data = source.extractfile(member).read(member.size + 1)
                need(len(data) == member.size and hashlib.sha256(data).hexdigest() == row['sha256'])
                total += len(data)
                need(total <= pin['expanded_bytes'])
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with target.open('xb') as output:
                    output.write(data)
                os.chmod(target, member.mode & 0o777)
                os.utime(target, (member.mtime, member.mtime))
    need(seen == set(rows) and total == pin['expanded_bytes'])
    for target, link in links:
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        resolved = (target.parent / link).resolve(strict=True)
        need(resolved == root / pin['root'] / 'LICENSES/LGPL-2.1-or-later.txt')
        need(resolved.is_file() and not resolved.is_symlink())
        target.symlink_to(link)
    for target, member in reversed(directories):
        os.chmod(target, member.mode & 0o777)
        os.utime(target, (member.mtime, member.mtime))
    return root / pin['root']

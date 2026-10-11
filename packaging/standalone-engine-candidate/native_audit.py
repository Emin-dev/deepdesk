"""First-party static Mach-O/relative-link audit for the proposed embedded layout.

No native file is executed. Conservative per-file executable contexts are explicit:
@executable_path is NOT assumed to be the app's Contents/MacOS directory.
This does not model all dyld run-path-stack semantics or prove runtime dlopen use.
"""
from __future__ import annotations
from pathlib import Path, PurePosixPath
import hashlib
import struct

MAX_FILE_BYTES = 768 * 1024**2
ARM64 = 0x0100000C
LOADS = {0xC, 0x80000018, 0x8000001F, 0x20, 0x80000023}
MAGIC = {b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xce\xfa\xed\xfe',
         b'\xfe\xed\xfa\xce', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca',
         b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'}


def require(ok, code):
    if not ok:
        raise ValueError(code)


def relative(value):
    require(isinstance(value, str) and value and '\\' not in value and '\x00' not in value,
            'invalid-relative-path')
    path = PurePosixPath(value)
    require(not path.is_absolute() and all(x not in ('', '.', '..') for x in value.split('/')),
            'invalid-relative-path')
    return path


def apple_path(value):
    return isinstance(value, str) and value.startswith(('/usr/lib/', '/System/Library/')) and all(
        part not in ('', '.', '..') for part in value.split('/')[1:])


def parse_macho(data):
    require(isinstance(data, bytes) and 4 <= len(data) <= MAX_FILE_BYTES, 'invalid-native-size')
    magic = data[:4]
    if magic not in MAGIC:
        return None
    if magic in (b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca', b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'):
        endian = '>' if magic[:1] == b'\xca' else '<'
        wide = magic in (b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca')
        require(len(data) >= 8, 'truncated-fat-header')
        count = struct.unpack_from(endian + 'I', data, 4)[0]
        require(0 < count <= 16, 'invalid-fat-count')
        stride = 32 if wide else 20
        require(8 + count * stride <= len(data), 'truncated-fat-table')
        selected, spans = [], []
        for index in range(count):
            pos = 8 + index * stride
            cpu, subtype = struct.unpack_from(endian + 'II', data, pos)
            off, size = struct.unpack_from(endian + ('QQ' if wide else 'II'), data, pos + 8)
            require(size >= 32 and off >= 8 + count * stride and off + size <= len(data), 'invalid-fat-slice')
            require(all(off + size <= start or off >= stop for start, stop in spans), 'overlapping-fat-slice')
            spans.append((off, off + size))
            if cpu == ARM64:
                selected.append(data[off:off + size])
        require(len(selected) == 1 and selected[0][:4] in (b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf'),
                'missing-or-duplicate-arm64-slice')
        result = parse_macho(selected[0])
        require(result and result['cpu'] == ARM64, 'fat-architecture-mismatch')
        result['container'] = 'universal'
        return result
    require(magic in (b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf'), 'non-arm64-mach-o')
    endian = '<' if magic == b'\xcf\xfa\xed\xfe' else '>'
    require(len(data) >= 32, 'truncated-mach-header')
    _, cpu, subtype, filetype, count, size, flags, reserved = struct.unpack_from(endian + '8I', data)
    require(cpu == ARM64, 'non-arm64-mach-o')
    require(count <= 4096 and size <= len(data) - 32, 'invalid-load-table')
    position, limit, loads, paths, install_id, minimum = 32, 32 + size, [], [], None, None
    for _ in range(count):
        require(position + 8 <= limit, 'truncated-load-command')
        cmd, cmdsize = struct.unpack_from(endian + 'II', data, position)
        require(cmdsize >= 8 and cmdsize % 4 == 0 and position + cmdsize <= limit, 'invalid-load-command')
        if cmd in LOADS | {0xD, 0x8000001C}:
            header_size = 12 if cmd == 0x8000001C else 24
            require(cmdsize >= header_size, 'truncated-path-command')
            offset = struct.unpack_from(endian + 'I', data, position + 8)[0]
            require(header_size <= offset < cmdsize, 'invalid-load-string-offset')
            raw = data[position + offset:position + cmdsize]
            require(b'\0' in raw, 'unterminated-load-string')
            value = raw.split(b'\0', 1)[0].decode('utf-8', errors='strict')
            require(value and len(value) <= 4096, 'invalid-load-string')
            if cmd in LOADS:
                loads.append({'command': cmd, 'path': value})
            elif cmd == 0xD:
                require(install_id is None, 'duplicate-install-id')
                install_id = value
            else:
                paths.append(value)
        elif cmd == 0x32:
            require(cmdsize >= 24, 'truncated-build-version')
            platform, minimum, sdk, tools = struct.unpack_from(endian + '4I',data,position + 8)
            require(platform == 1, 'not-macos-platform')
        elif cmd == 0x24:
            require(cmdsize >= 16, 'truncated-minimum-version')
            minimum = struct.unpack_from(endian + 'I', data, position + 8)[0]
        position += cmdsize
    require(position == limit, 'load-table-size-mismatch')
    return {'cpu':cpu,'subtype':subtype,'filetype':filetype,'rpaths':paths,'loads':loads,
            'install_id':install_id,'minimum_os':minimum,'container':'thin'}


def within(root, path):
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(root), 'native-path-escapes-bundle')
    return resolved


def expanded(root, value, loader, executable):
    if value == '@loader_path' or value.startswith('@loader_path/'):
        path = loader.parent / value[len('@loader_path'):].lstrip('/')
    elif value == '@executable_path' or value.startswith('@executable_path/'):
        path = executable.parent / value[len('@executable_path'):].lstrip('/')
    else:
        raise ValueError('unsupported-or-host-native-path')
    return within(root, path)


def audit_bundle(root, contexts, *, reviewed_collisions=None):
    """contexts maps EVERY real Mach-O relative path to its executable path(s).

    A dylib may run in more than one process; all declared contexts must resolve.
    Context completeness remains a reviewed input, not an inference from basename.
    Inherited parent-image run paths are not guessed: ambiguous/unresolved cases
    require a more explicit reviewed relocation rather than a permissive fallback.
    """
    root = Path(root).resolve(strict=True)
    require(root.is_dir() and isinstance(contexts, dict), 'invalid-bundle-contexts')
    native = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            within(root,path)
            continue
        if not path.is_file():
            continue
        with path.open('rb') as stream:
            first = stream.read(4)
            if first not in MAGIC:
                continue
            require(path.stat().st_size <= MAX_FILE_BYTES,'native-size-limit')
            stream.seek(0)
            data = stream.read(MAX_FILE_BYTES + 1)
        native[str(path.relative_to(root))] = (path,parse_macho(data),hashlib.sha256(data).hexdigest())
    require(native and set(native) == set(contexts),'incomplete-native-context-set')
    collisions = {}
    for label, selector in (('basename', lambda name, meta: Path(name).name),
                            ('install-id', lambda name, meta: meta['install_id'])):
        groups = {}
        for name, (_, meta, sha) in native.items():
            key = selector(name, meta)
            if key: groups.setdefault(key, []).append({'path':name, 'sha256':sha})
        for key, members in groups.items():
            if len({item['sha256'] for item in members}) > 1:
                collisions[label + ':' + key] = sorted(members,key=lambda x:x['path'])
    require(collisions == (reviewed_collisions or {}), 'unreviewed-native-name-collision')
    records = []
    for name,(path,meta,sha) in native.items():
        relative(name)
        chosen = contexts[name]
        require(isinstance(chosen,list) and chosen and len(set(chosen)) == len(chosen),'invalid-executable-context')
        for context in chosen:
            relative(context)
            require(context in native and native[context][1]['filetype'] == 2,'context-is-not-executable')
            require(meta['filetype'] != 2 or context == name,'executable-context-mismatch')
            exe,exemeta,_ = native[context]
            directories=[]
            for owner,info in ((path,meta),(exe,exemeta)):
                for value in info['rpaths']:
                    if apple_path(value):
                        continue
                    directory = expanded(root,value,owner,exe)
                    require(directory.is_dir(),'rpath-is-not-directory')
                    if directory not in directories: directories.append(directory)
            edges=[]
            for load in meta['loads']:
                value=load['path']
                if apple_path(value):
                    edges.append({'path':value,'resolved':'apple-system'});continue
                if value.startswith('@rpath/'):
                    suffix=value[len('@rpath/'):];relative(suffix)
                    candidates=[within(root,p/suffix) for p in directories if (p/suffix).exists()]
                    candidates=list(dict.fromkeys(candidates))
                    require(len(candidates)==1,'unresolved-or-ambiguous-rpath')
                    target=candidates[0]
                else:
                    target=expanded(root,value,path,exe)
                target_name=str(target.relative_to(root))
                require(target_name in native,'native-dependency-is-not-audited-mach-o')
                edges.append({'path':value,'resolved':target_name})
            records.append({'path':name,'context':context,'sha256':sha,'loads':edges,
                            'rpaths':meta['rpaths'],'minimum_os':meta['minimum_os']})
    return {'status':'passed','kind':'static-context-bound-native-closure','native_file_count':len(native),
            'records':records,'reviewed_name_collisions':collisions,'runtime_dlopen_tested':False,'context_completeness_requires_review':True}

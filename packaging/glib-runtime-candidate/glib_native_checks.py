"""Exact Mach-O closure checks for the proposed ephemeral GLib provider layout."""
from pathlib import Path, PurePosixPath
import importlib.util
import posixpath
import struct
import hashlib

_spec = importlib.util.spec_from_file_location('foundation_native', Path(__file__).with_name('native_checks.py'))
_base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_base)
_read_spec = importlib.util.spec_from_file_location('glib_native_safe_reads', Path(__file__).with_name('safe_reads.py'))
_reads = importlib.util.module_from_spec(_read_spec)
_read_spec.loader.exec_module(_reads)
need, fixture_output = _base.need, _base.fixture_output
GLIB_COMPONENTS = ('glib', 'gobject', 'gmodule', 'gio', 'gthread', 'girepository')
GLIB_NAMES = {f'lib{name}-2.0.0.dylib': name for name in GLIB_COMPONENTS}
PROVIDER_NAMES = {
    'libintl.8.dylib', 'libpcre2-8.0.dylib', 'libffi.8.dylib',
    'libtextstyle.0.dylib', 'libgettextlib-1.0.dylib', 'libgettextsrc-1.0.dylib',
    'libdeepdesk-module.dylib', 'libiconv.2.dylib', 'libcharset.1.dylib',
}
APPLE_LOADS = _base.APPLE_LOADS | {
    '/usr/lib/libc++.1.dylib', '/usr/lib/libobjc.A.dylib',
    '/usr/lib/libncurses.5.4.dylib', '/usr/lib/libresolv.9.dylib',
    '/System/Library/Frameworks/Foundation.framework/Versions/C/Foundation',
    '/System/Library/Frameworks/AppKit.framework/Versions/C/AppKit',
    '/System/Library/Frameworks/Carbon.framework/Versions/A/Carbon',
    '/System/Library/Frameworks/SystemConfiguration.framework/Versions/A/SystemConfiguration',
}


def macho(path, provider_dir, *, promoted_path=None):
    path, provider = Path(path), Path(provider_dir)
    final = Path(promoted_path) if promoted_path is not None else path
    need(provider.name == 'providers' and provider.parent.name == 'immutable')
    data = _reads.read(path, (provider.parent.parent / 'phases', provider), 128 * 1024**2)
    need(32 <= len(data) <= 128 * 1024**2 and data[:4] == b'\xcf\xfa\xed\xfe')
    _, cpu, _, filetype, ncmds, total, _, _ = struct.unpack_from('<8I', data)
    need(cpu == 0x100000c and filetype in (2, 6) and ncmds <= 256 and total + 32 <= len(data))
    cursor, loads, identity, minos, rpaths, signature = 32, [], None, [], [], False
    allowed_dirs = {provider / 'native' / name for name in GLIB_COMPONENTS} | {provider / 'lib', provider / 'intl-with-iconv/lib'}
    for _ in range(ncmds):
        need(cursor + 8 <= 32 + total)
        cmd, size = struct.unpack_from('<II', data, cursor)
        need(size >= 8 and cursor + size <= 32 + total)
        if cmd in (0xc, 0xd, 0x80000018, 0x8000001f, 0x80000023, 0x8000001c):
            off = struct.unpack_from('<I', data, cursor + 8)[0]
            need((12 if cmd == 0x8000001c else 24) <= off < size)
            value = data[cursor+off:cursor+size].split(b'\0', 1)[0].decode('utf-8')
            need(value and '\n' not in value and '\r' not in value)
            if cmd == 0x8000001c:
                if value.startswith('@loader_path/'):
                    destination = Path(posixpath.normpath(str(final.parent / value[len('@loader_path/'):])) )
                    need(destination in allowed_dirs)
                else:
                    need(Path(value) in allowed_dirs)
                rpaths.append(value)
            elif cmd == 0xd:
                identity = value
            else:
                exact_provider = str(provider / 'lib' / Path(value).name)
                need(value in APPLE_LOADS or value == str(provider / 'intl-with-iconv/lib/libintl.8.dylib') or
                     (value == exact_provider and Path(value).name in PROVIDER_NAMES) or
                     (value.startswith('@rpath/') and value[len('@rpath/'):] in GLIB_NAMES))
                loads.append(value)
        elif cmd == 0x32:
            platform, minimum, _, _ = struct.unpack_from('<4I', data, cursor + 8)
            need(platform == 1)
            minos.append(minimum)
        elif cmd == 0x1d:
            signature = True
        cursor += size
    need(cursor == 32 + total and minos == [26 << 16] and loads)
    if filetype == 6:
        expected = '@rpath/' + path.name if path.name in GLIB_NAMES else str(provider / 'lib' / path.name)
        if final == provider / 'intl-with-iconv/lib/libintl.8.dylib':
            expected = str(final)
        need(identity == expected)
    return {'arm64': True, 'filetype': filetype, 'minimum_macos': '26.0',
            'direct_load_count': len(loads), 'rpath_count': len(rpaths),
            'implicit_signature_load_command': signature}, loads


def origin_fixture_output(data, markers, executable, provider, origins, required, *, reject_bootstrap_intl=False):
    need(len(data) <= 256 * 1024)
    lines = data.decode('utf-8').splitlines()
    observed, remainder = {}, []
    for line in lines:
        if line.startswith('origin='):
            fields = line[7:].split('|')
            need(len(fields) == 2 and fields[0] in origins and fields[0] not in observed)
            need(fields[1] == str(origins[fields[0]]))
            observed[fields[0]] = fields[1]
        else:
            remainder.append(line)
    need(set(observed) == set(origins))
    if reject_bootstrap_intl:
        expected = str(Path(provider) / 'intl-with-iconv/lib/libintl.8.dylib')
        for line in remainder:
            if line.startswith('image=') and Path(line[6:]).name == 'libintl.8.dylib':
                need(line[6:] == expected)
    return fixture_output(('\n'.join(remainder) + '\n').encode(), markers, executable, provider, required)


def recursive_provider_closure(roots, provider):
    provider = Path(provider)
    pending, observed, system = list(map(Path, roots)), {}, set()
    while pending:
        path = pending.pop()
        need(path.is_absolute() and path.is_relative_to(provider) and '..' not in path.parts)
        path = path.resolve(strict=True)
        need(path.is_relative_to(provider) and path != provider / 'lib/libintl.8.dylib')
        if path in observed:
            continue
        need(len(observed) < 64)
        record, loads = macho(path, provider, promoted_path=path)
        data = _reads.read(path, (provider,), 128 * 1024**2)
        edges = []
        for load in loads:
            if load in APPLE_LOADS:
                system.add(load)
            elif load.startswith('@rpath/'):
                name = load[len('@rpath/'):]
                need(name in GLIB_NAMES)
                target = provider / 'native' / GLIB_NAMES[name] / name
                pending.append(target)
                edges.append(target.relative_to(provider).as_posix())
            else:
                target = Path(load)
                need(target.is_relative_to(provider))
                pending.append(target)
                edges.append(target.relative_to(provider).as_posix())
        observed[path] = {'path': path.relative_to(provider).as_posix(), 'sha256': hashlib.sha256(data).hexdigest(),
                          'bytes': len(data), 'provider_edges': sorted(set(edges)), **record}
    return {'scope': 'exact non-system provider closure; Apple system imports allowlisted',
            'bootstrap_intl_rejected': True, 'provider_nodes': sorted(observed.values(), key=lambda x: x['path']),
            'system_imports': sorted(system)}

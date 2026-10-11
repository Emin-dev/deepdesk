"""Exact Mach-O closure checks for the proposed ephemeral GLib provider layout."""
from pathlib import Path, PurePosixPath
import importlib.util
import posixpath
import struct

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
    'libdeepdesk-module.dylib',
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
    allowed_dirs = {provider / 'native' / name for name in GLIB_COMPONENTS} | {provider / 'lib'}
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
                need(value in APPLE_LOADS or
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
        need(identity == expected)
    return {'arm64': True, 'filetype': filetype, 'minimum_macos': '26.0',
            'direct_load_count': len(loads), 'rpath_count': len(rpaths),
            'implicit_signature_load_command': signature}, loads

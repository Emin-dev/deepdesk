"""Relocated installed-binding fixtures; native bytes stay in bounded child pipes."""
from __future__ import annotations
import argparse
import contextlib
import ctypes
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True

CAP = 2 * 1024**2
EXPECTED_REFUSAL = 'application/x-decompression-error-gzip-Fork-is-required-to-uncompress--but-disabled'
WORKER_MARKER = b'{"native_worker": "passed"}'


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def loaded_images(prefix, library):
    image = ctypes.CDLL(None)
    count = image._dyld_image_count; count.argtypes = []; count.restype = ctypes.c_uint32
    name = image._dyld_get_image_name; name.argtypes = [ctypes.c_uint32]; name.restype = ctypes.c_char_p
    total = count(); require(0 < total < 500, 'Runtime image inventory differs')
    observed = []
    for i in range(total):
        path = Path(os.fsdecode(name(i)))
        if str(path).startswith(('/usr/lib/', '/System/Library/')) and '..' not in path.parts:
            continue
        require(path.is_file() and path.resolve().is_relative_to(prefix), 'Runtime image outside bundle/Apple closure')
        observed.append(path.resolve())
    require(library.resolve() in observed, 'Bundled libmagic image not loaded')
    return total


def fixtures(helpers):
    text = (helpers/'libmagic-pilot/synthetic_fixtures.h').read_text()
    rows = re.findall(r'static const unsigned char (\w+)\[\] = \{([^}]+)\};', text)
    result = {name: bytes(int(x.strip(), 0) for x in body.split(',')) for name, body in rows}
    require(set(result) == {'plain', 'pdf', 'png', 'gzip_text', 'bzip2_text', 'external_compress_header'},
            'Synthetic byte set differs')
    return result


def refused(call, expected):
    try:
        call()
    except ImportError as error:
        require(str(error) == expected, 'Bundled refusal category differs')
    else:
        raise RuntimeError('Missing bundled resource accepted')


def worker(case, helpers):
    # Host MAGIC/HOME/PATH candidates cannot select a different library/database.
    os.environ['MAGIC'] = '/opt/homebrew/share/misc/magic.mgc'
    if case in {'missing-library', 'missing-database'}:
        refused(lambda: __import__('magic'), 'Bundled magic resource is unavailable')
        print(WORKER_MARKER.decode(), flush=True)
        return
    import magic
    from magic import compat
    prefix = Path(sys.prefix).resolve(strict=True)
    native = prefix/'lib/deepdesk-native/libmagic'
    library = native/'lib/libmagic.1.dylib'
    require(Path(magic.__file__).resolve().is_relative_to(prefix)
            and Path(compat.__file__).resolve().is_relative_to(prefix), 'Binding origin outside bundle')
    require(magic.libmagic is not compat._libraries['magic']
            and magic.libmagic._library is not compat._libraries['magic']._library,
            'Modern and compatibility ctypes proxies are shared')
    require(magic.magic_open.restype is ctypes.c_void_p
            and compat._open.restype is compat.magic_t, 'Binding ctypes signatures collided')
    require(magic.version() == 548, 'Bundled libmagic version differs')
    modern = magic.Magic(mime=True)
    legacy = compat.open(compat.MIME_TYPE)
    require(legacy.load() == 0, 'Compatibility default load failed')
    if case == 'missing-text':
        refused(lambda: magic.magic_compile(modern.cookie, None), 'Bundled magic text sources are unavailable')
        refused(lambda: legacy.compile(None), 'Bundled magic text sources are unavailable')
        legacy.close()
        print(WORKER_MARKER.decode(), flush=True)
        return
    require(case in {'modern', 'compat'}, 'Unexpected native worker case')
    class DefaultParameter:
        _as_parameter_ = None
    for null in (ctypes.POINTER(ctypes.c_char)(), DefaultParameter()):
        require(magic.magic_load(modern.cookie, null) == 0
                and compat._load(legacy._magic_t, null) == 0, 'Typed bundled NULL default failed')
    modern_flags = magic.libmagic.magic_getflags
    modern_flags.restype = ctypes.c_int; modern_flags.argtypes = [ctypes.c_void_p]
    compat_flags = compat._libraries['magic'].magic_getflags
    compat_flags.restype = ctypes.c_int; compat_flags.argtypes = [compat.magic_t]
    m = magic.magic_open(ctypes.c_int(0)); c = compat._open(ctypes.c_int(0))
    require(m and c and modern_flags(m) == 0 and compat_flags(c) == 0,
            'Caller ctypes open flags were changed')
    magic.magic_close(m); compat._close(c)
    values = fixtures(helpers)
    expected = {'plain': 'text/plain', 'pdf': 'application/pdf', 'png': 'image/png'}
    for name, mime in expected.items():
        require(modern.from_buffer(values[name]) == mime and legacy.buffer(values[name]) == mime,
                'Bundled MIME fixture differs')
    require(magic.magic_setflags(modern.cookie, ctypes.c_int(0)) == 0
            and compat._setflags(legacy._magic_t, ctypes.c_int(0)) == 0
            and modern_flags(modern.cookie) == 0 and compat_flags(legacy._magic_t) == 0,
            'Caller zero-reset flags were changed')
    # No-fork is an explicit fixture choice, not a production loader override.
    flags = magic.MAGIC_MIME_TYPE | magic.MAGIC_COMPRESS | 0x2000000 | 0x4000000
    require(magic.magic_setflags(modern.cookie, flags) == 0 and legacy.setflags(flags) == 0,
            'Explicit fixture nofork flags failed')
    for name in ('gzip_text', 'bzip2_text'):
        require(modern.from_buffer(values[name]) == 'text/plain' and legacy.buffer(values[name]) == 'text/plain',
                'Builtin decompression fixture differs')
    require(modern.from_buffer(values['external_compress_header']) == EXPECTED_REFUSAL
            and legacy.buffer(values['external_compress_header']) == EXPECTED_REFUSAL,
            'External-only decompression was not refused')
    # Use each binding's real default operation and its own independent handle.
    if case == 'modern':
        require(magic.magic_check(modern.cookie, None) == 0, 'Modern default check failed')
        listing = magic.libmagic.magic_list
        listing.restype = ctypes.c_int; listing.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        require(listing(modern.cookie, None) == 0, 'Modern default list failed')
        require(magic.magic_compile(modern.cookie, None) == 0, 'Modern default text compile failed')
        compiled = Path.cwd()/'magic.mgc'
        require(compiled.is_file() and compiled.stat().st_size > 0, 'Modern compiled database absent')
        reopened = magic.Magic(mime=True, magic_file=str(compiled))
        require(reopened.from_buffer(values['pdf']) == 'application/pdf', 'Modern compiled database reopen failed')
    else:
        require(legacy.check(None) == 0 and legacy.list(None) == 0, 'Compatibility default check/list failed')
        require(legacy.compile(None) == 0, 'Compatibility default text compile failed')
        compiled = Path.cwd()/'magic.mgc'
        require(compiled.is_file() and compiled.stat().st_size > 0, 'Compatibility compiled database absent')
        reopened = compat.open(compat.MIME_TYPE)
        require(reopened.load(str(compiled)) == 0 and reopened.buffer(values['pdf']) == 'application/pdf',
                'Compatibility compiled database reopen failed')
        reopened.close()
    require(magic.magic_load(modern.cookie, None) == 0 and legacy.load() == 0,
            'Bindings could not reload defaults after text compilation')
    # Exercise both after compile/list; reject a late ctypes signature collision.
    require(modern.from_buffer(values['plain']) == 'text/plain' and legacy.buffer(values['plain']) == 'text/plain',
            'Binding interoperability changed after default operations')
    legacy.close()
    loaded_images(prefix, library)
    # libmagic list uses C stdio, so flush before the fixed final marker.
    process = ctypes.CDLL(None)
    flush = process.fflush; flush.argtypes = [ctypes.c_void_p]; flush.restype = ctypes.c_int
    require(flush(None) == 0, 'Native output flush failed')
    print(WORKER_MARKER.decode(), flush=True)


def driver(case, helpers, scope):
    require(scope.is_dir() and scope.resolve() == Path.cwd(), 'Fixture scope differs')
    bounded = load(helpers.parent/'engine-ci/bounded_runtime.py', 'deepdesk_magic_runtime_bounds')
    total = 0
    checks = []
    for name in (('modern', 'compat') if case == 'full' else (case,)):
        cwd = scope/name; cwd.mkdir(mode=0o700)
        capture = io.StringIO()
        with contextlib.redirect_stdout(capture):
            output = bounded.run_bounded([sys.executable, '-I', '-B', __file__, '--worker', name,
                '--helpers', helpers], cwd=cwd, env=dict(os.environ), work=scope,
                timeout=90, output_limit=CAP-total, own_session=False, public_summary=True)
        summary = json.loads(capture.getvalue())
        require(summary.get('bounded_step') == 'passed' and summary.get('stdout_bytes') == len(output),
                'Nested bounds summary differs')
        total += summary['stdout_bytes'] + summary['stderr_bytes']
        require(total <= CAP and output.splitlines() and output.splitlines()[-1] == WORKER_MARKER,
                'Native worker output contract differs')
        checks.append(name)
    print(json.dumps({'status': 'passed', 'kind': 'relocated-installed-libmagic', 'case': case,
                      'checks': checks, 'private_native_output_bytes': total,
                      'modern_compat_compile_reopen': case == 'full',
                      'default_binary_check_list': case == 'full',
                      'loaded_images_inside_bundle_or_apple': case == 'full',
                      'host_fallback_used': False, 'native_features_complete': False}, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--helpers', type=Path, required=True)
    parser.add_argument('--worker', choices=['modern', 'compat', 'missing-library', 'missing-database', 'missing-text'])
    parser.add_argument('--case', choices=['full', 'missing-library', 'missing-database', 'missing-text'])
    parser.add_argument('--scope', type=Path)
    args = parser.parse_args()
    if args.worker:
        require(args.case is None and args.scope is None, 'Mixed runtime mode')
        worker(args.worker, args.helpers)
    else:
        require(args.case is not None and args.scope is not None, 'Missing runtime mode')
        driver(args.case, args.helpers, args.scope)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Bundled libmagic runtime fixture failed; raw diagnostics withheld') from None

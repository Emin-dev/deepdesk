"""Reviewed source Make/iconv/corrected-intl build sequence; no import side effects."""
import gettext
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re

_spec = importlib.util.spec_from_file_location('correction_safe_reads', Path(__file__).with_name('safe_reads.py'))
safe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(safe)


def require(value):
    if not value:
        raise ValueError('correction_contract')


def assignments(data, key):
    result = []
    for line in data.decode().splitlines():
        if line.startswith(key + '='):
            value = line[len(key) + 1:]
            if value[:1] in ('"', "'"):
                require(len(value) >= 2 and value[-1] == value[0])
                value = value[1:-1]
            result.append(value)
    return result


def charset_staging_contract(libtool, archive, provider):
    begin, end = b'# ### BEGIN LIBTOOL CONFIG', b'# ### END LIBTOOL CONFIG'
    lines = libtool.splitlines()
    require(lines.count(begin) == lines.count(end) == 1)
    require(lines.index(begin) < lines.index(end))
    main = b'\n'.join(lines[lines.index(begin) + 1:lines.index(end)])
    for key in ('postinstall_cmds', 'finish_cmds', 'finish_eval'):
        require(assignments(main, key) == [''])
    require(assignments(main, 'hardcode_automatic') == ['yes'])
    require(assignments(main, 'build_old_libs') == ['no'])
    require(assignments(main, 'build_libtool_libs') == ['yes'])
    require(assignments(archive, 'installed') == ['no'])
    require(assignments(archive, 'old_library') == [''])
    require(assignments(archive, 'dependency_libs') == [''])
    require(assignments(archive, 'dlopen') == [''] and assignments(archive, 'dlpreopen') == [''])
    require(assignments(archive, 'libdir') == [str(provider / 'lib')])
    require(assignments(archive, 'relink_command') in ([], ['']))
    return {'shared_only': True, 'relink_command_absent_or_empty': True,
            'postinstall_finish_hooks_empty': True, 'staging_destination': 'current_phase/lib',
            'libtool_sha256': hashlib.sha256(libtool).hexdigest(), 'la_sha256': hashlib.sha256(archive).hexdigest()}


def text(path, root, maximum=1024**2):
    return safe.read(path, (root,), maximum).decode()


def prepare(lane, trees, flags, bind_gettext_config_header):
    provider, helpers = lane.provider, lane.helpers
    phase = lane.directory('gnu-make-build')
    lane.run('gnu-make-configure', ['/bin/sh', trees['make'] / 'configure', '--prefix=' + str(provider),
             '--enable-nls', '--without-guile', '--with-libintl-prefix=' + str(provider),
             '--without-libiconv-prefix'], directory=phase, timeout=180)
    require('#define ENABLE_NLS 1' in text(phase / 'src/config.h', phase))
    require(assignments(safe.read(phase / 'build.cfg', (phase,), 65536), 'prefix') == [str(provider)])
    lane.run('gnu-make-bootstrap', ['/bin/sh', trees['make'] / 'build.sh'], directory=phase, timeout=180)
    _, loads = lane.inspect('gnu-make', phase / 'make')
    require(str(provider / 'lib/libintl.8.dylib') in loads)
    items = [(phase / 'make', provider / 'bin/make', True)]
    catalogs = json.loads((helpers / 'make-catalog-contract.json').read_text())['languages']
    require(len(catalogs) == 30)
    for catalog in catalogs:
        source = trees['make'] / 'po' / (catalog['language'] + '.gmo')
        data = safe.read(source, (trees['make'],), 2 * 1024**2)
        require(hashlib.sha256(data).hexdigest() == catalog['sha256'])
        require(len(gettext.GNUTranslations(io.BytesIO(data))._catalog) == catalog['catalog_entries'])
        staged = phase / ('catalog-' + catalog['language'] + '.mo')
        with staged.open('xb') as output:
            output.write(data)
        items.append((staged, provider / 'share/locale' / catalog['language'] / 'LC_MESSAGES/make.mo', False))
        lane.checkpoint()
    lane.promote(items)
    make = provider / 'bin/make'
    lane.env.update({'MAKE': str(make), 'PATH': str(provider / 'bin') + ':' + lane.env['PATH']})
    out, err, _ = lane.run('gnu-make-version', [make, '--version'], timeout=10)
    require(out.splitlines()[0] == b'GNU Make 4.4.1' and not err)
    phase = lane.directory('gnu-make-probes')
    fixture = phase / 'Makefile'
    fixture.write_text('VALUE != printf forty-two\nall:\n\t@test "$(VALUE)" = "forty-two"\n\t@printf "gnu_make_shell_assignment_passed\\n"\n')
    out, err, _ = lane.run('gnu-make-functional', [make, '-f', fixture, '-j2', 'all'], directory=phase, timeout=10)
    require(out == b'gnu_make_shell_assignment_passed\n' and not err)
    out, err, _ = lane.run('gnu-make-nls', [make, '--help'], directory=phase, timeout=10,
                           extra_env={'LC_ALL': 'en_US.UTF-8', 'LANGUAGE': 'fr'})
    require(out.startswith('Utilisation\u00a0: '.encode()) and not err)
    print(json.dumps({'phase': 'gnu-make-provider-contract', 'status': 'passed', 'version': '4.4.1',
                      'nls_enabled': True, 'release_catalog_count': 30, 'guile_embedding': False,
                      'bootstrap_msgfmt_used': False}, sort_keys=True))

    phase = lane.directory('libiconv-build')
    lane.run('libiconv-configure', ['/bin/sh', trees['libiconv'] / 'configure', '--prefix=' + str(provider),
             '--enable-shared', '--disable-static', '--enable-nls', '--with-libintl-prefix=' + str(provider),
             '--without-libiconv-prefix'], directory=phase, timeout=180)
    lane.run('libcharset-build', [make, '-C', 'libcharset/lib', '-j2', 'libcharset.la'], directory=phase, timeout=90)
    charset = phase / 'libcharset/lib/.libs/libcharset.1.dylib'
    lane.inspect('source-libcharset', charset)
    contract = charset_staging_contract(
        safe.read(phase / 'libcharset/libtool', (phase,), 2 * 1024**2),
        safe.read(phase / 'libcharset/lib/libcharset.la', (phase,), 65536), provider)
    contract['generated_script_sha256'] = {
        name: hashlib.sha256(safe.read(phase / name, (phase,), 2 * 1024**2)).hexdigest()
        for name in ('config.status', 'libtool', 'libcharset/config.status', 'libcharset/libtool')}
    print(json.dumps({'phase': 'libcharset-staging-contract', 'status': 'passed', **contract}, sort_keys=True))
    before = hashlib.sha256(safe.read(charset, (phase,), 128 * 1024**2)).hexdigest()
    lane.run('libcharset-phase-stage', [make, '-j2', 'lib/localcharset.h'], directory=phase, timeout=45)
    require(hashlib.sha256(safe.read(phase / 'lib/libcharset.1.dylib', (phase,), 128 * 1024**2)).hexdigest() == before)
    require(hashlib.sha256(safe.read(charset, (phase,), 128 * 1024**2)).hexdigest() == before)
    lane.run('libiconv-build', [make, '-C', 'lib', '-j2', 'libiconv.la'], directory=phase, timeout=180)
    iconv = phase / 'lib/.libs/libiconv.2.dylib'
    _, loads = lane.inspect('source-libiconv', iconv)
    require(str(provider / 'lib/libcharset.1.dylib') not in loads)
    lane.promote([(iconv, provider / 'lib/libiconv.2.dylib', False),
                  (charset, provider / 'lib/libcharset.1.dylib', False),
                  (phase / 'include/iconv.h.inst', provider / 'include/iconv.h', False),
                  (phase / 'libcharset/include/libcharset.h.inst', provider / 'include/libcharset.h', False),
                  (phase / 'libcharset/include/localcharset.h.inst', provider / 'include/localcharset.h', False)])
    lane.provider_alias(provider / 'lib/libiconv.dylib', 'libiconv.2.dylib')
    lane.provider_alias(provider / 'lib/libcharset.dylib', 'libcharset.1.dylib')
    lane.symbols('source-libiconv', provider / 'lib/libiconv.2.dylib',
                 ['libiconv_open', 'libiconv', 'libiconv_close', 'libiconvctl', 'libiconvlist', '_libiconv_version'])
    lane.symbols('source-libcharset', provider / 'lib/libcharset.1.dylib', ['locale_charset'])
    lane.env['CPPFLAGS'] += ' -I' + str(provider / 'include')
    lane.env['LDFLAGS'] += ' -L' + str(provider / 'lib')
    phase = lane.directory('iconv-semantic-probes')
    for variant in ('nonconst', 'const'):
        source = helpers / ('iconv-upstream-' + variant + '.c')
        object_file, executable = phase / (variant + '.o'), phase / ('iconv-' + variant)
        lane.run('iconv-semantic-compile-' + variant, [lane.tools['clang'], *flags,
                 '-I' + str(provider / 'include'), '-Dmain=upstream_iconv_semantic_main', '-c', source, '-o', object_file],
                 directory=phase, timeout=30)
        lane.run('iconv-semantic-link-' + variant, [lane.tools['clang'], *flags,
                 '-I' + str(provider / 'include'), helpers / 'iconv_semantic_driver.c', object_file,
                 provider / 'lib/libiconv.2.dylib', '-o', executable], directory=phase, timeout=30)
        lane.inspect('iconv-semantic-' + variant, executable)
        out, err, _ = lane.run('iconv-semantic-run-' + variant, [executable, provider / 'lib/libcharset.1.dylib'],
                               directory=phase, timeout=15)
        lane.native.origin_fixture_output(out, ['upstream_iconv_semantics_and_version_passed', 'libcharset_runtime_passed'],
            executable, provider, {'iconv_open': provider / 'lib/libiconv.2.dylib',
            'iconv': provider / 'lib/libiconv.2.dylib', 'iconv_close': provider / 'lib/libiconv.2.dylib',
            'iconv_version': provider / 'lib/libiconv.2.dylib', 'locale_charset': provider / 'lib/libcharset.1.dylib'},
            ['libiconv.2.dylib', 'libcharset.1.dylib'])
        require(not err)
        print(json.dumps({'phase': 'iconv-semantic-origin-contract-' + variant, 'status': 'passed',
                          'upstream_semantic_exit': 0, 'source_functions_bound': 5}, sort_keys=True))

    intl = provider / 'intl-with-iconv'
    phase = lane.directory('gettext-iconv-build')
    build = phase / 'intl'
    build.mkdir(mode=0o700)
    lane.run('gettext-iconv-configure', ['/bin/sh', trees['gettext'] / 'gettext-runtime/intl/configure',
             '--prefix=' + str(intl), '--with-included-libintl', '--enable-nls', '--enable-shared',
             '--disable-static', '--enable-threads=posix', '--without-libintl-prefix',
             '--with-libiconv-prefix=' + str(provider)], directory=phase, subdirectory='intl', timeout=150)
    config = text(build / 'config.h', phase)
    require('#define HAVE_ICONV 1' in config)
    print(json.dumps(bind_gettext_config_header(phase), sort_keys=True))
    lane.run('gettext-iconv-headers', [make, 'libintl.h', 'libgnuintl.h'], directory=phase, subdirectory='intl', timeout=20)
    lane.run('gettext-iconv-gnulib', [make, '-C', 'gnulib-lib', '-j2', 'all'], directory=phase, subdirectory='intl', timeout=140)
    lane.run('gettext-iconv-build', [make, '-j2', 'libintl.la'], directory=phase, subdirectory='intl', timeout=90)
    library = build / '.libs/libintl.8.dylib'
    loads = lane.inspect_promoted('corrected-libintl', library, intl / 'lib/libintl.8.dylib')
    require(str(provider / 'lib/libiconv.2.dylib') in loads)
    lane.promote([(library, intl / 'lib/libintl.8.dylib', False),
                  (build / 'libintl.h', intl / 'include/libintl.h', False)])
    lane.provider_alias(intl / 'lib/libintl.dylib', 'libintl.8.dylib')
    exports = json.loads((helpers / 'provider-contract.json').read_text())['libintl_minimum_exports']
    lane.symbols('corrected-libintl', intl / 'lib/libintl.8.dylib', exports)
    lane.env['CPPFLAGS'] = '-I' + str(intl / 'include') + ' ' + lane.env['CPPFLAGS']
    lane.env['LDFLAGS'] = '-L' + str(intl / 'lib') + ' ' + lane.env['LDFLAGS']
    phase = lane.directory('gettext-iconv-probes')
    executable = phase / 'intl-probe'
    lane.run('gettext-iconv-probe-compile', [lane.tools['clang'], *flags, '-I' + str(intl / 'include'),
             helpers / 'intl_iconv_probe.c', intl / 'lib/libintl.8.dylib', '-o', executable], directory=phase, timeout=30)
    lane.inspect_runtime('corrected-intl-probe', executable)
    out, err, _ = lane.run('gettext-iconv-probe-run', [executable, lane.immutable / 'catalog'], directory=phase,
                           timeout=15, extra_env={'LC_ALL': 'en_US.UTF-8', 'LANGUAGE': 'fr'})
    lane.native.origin_fixture_output(out, ['gnu_libintl_utf8_latin1_plural_fallback_passed'], executable, provider,
        {'gettext': intl / 'lib/libintl.8.dylib'}, ['libintl.8.dylib', 'libiconv.2.dylib'], reject_bootstrap_intl=True)
    require(not err)
    print(json.dumps({'phase': 'corrected-libintl-provider-contract', 'status': 'passed',
                      'bootstrap_provider_preserved': True, 'catalog_output_codesets': ['UTF-8', 'ISO-8859-1'],
                      'selected_prefix': 'providers/intl-with-iconv'}, sort_keys=True))
    return make, intl

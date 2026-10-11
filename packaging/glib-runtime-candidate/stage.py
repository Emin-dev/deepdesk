"""Receipt-closed combined macOS source lane. Imports execute first-party code only."""
from __future__ import annotations
import argparse
import gettext
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import signal
import stat
import sys
import tempfile
import time

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


foundation = load('foundation_stage', HERE / 'foundation_stage.py')
safe_reads = load('glib_safe_reads', HERE / 'safe_reads.py')
need, digest = foundation.need, foundation.digest
SCOPE = 'glib-runtime-prerequisites-v1'
BRANCH = 'engine-glib-runtime-v1-ci'
WORKFLOW = '.github/workflows/engine-glib-runtime-v1-macos.yml'
INPUT_HASHES = dict(foundation.INPUT_HASHES,
    glib='93c941aa17d5eb1d53fe838365f29a8b4e539c222a256d974ec8f30fc413e396',
    libffi='7da3e2d9a171eb0a038f592ecad3ff2bb2550f3496d87b3b29ad0cf4430c0db4')
FALSE_GATES = {k: False for k in (
    'pango_runtime', 'pdf_rendering', 'font_closure', 'relocation', 'release_ready',
    'full_glib_install', 'generated_gir_typelibs', 'optional_profiling_instrumentation',
    'model_loaded', 'provider_queried', 'artifact_uploaded', 'cache_used')}
INPUT_SECONDS, BUILD_SECONDS = 180, 1500
OUTPUT_LIMIT = 32 * 1024**2
WORKSPACE_LIMIT = 4 * 1024**3
GLIB_OPTIONS = [
    '--wrap-mode=nofallback', '--buildtype=release', '--default-library=shared',
    '-Dnls=enabled', '-Dtests=false', '-Dinstalled_tests=false',
    '-Ddocumentation=false', '-Dman-pages=disabled', '-Dintrospection=disabled',
    '-Ddtrace=disabled', '-Dsystemtap=disabled', '-Dsysprof=disabled',
]
GLIB_MARKERS = [
    'source_libffi_version_and_closure_passed', 'glib_regex_unicode_main_context_passed',
    'gobject_generic_ffi_marshalling_and_girepository_passed', 'gmodule_private_module_passed',
    'gio_private_local_file_roundtrip_passed', 'glib_real_french_catalog_passed',
]
NEW_PHASES = {
    'libffi-configure', 'libffi-build', 'libtextstyle-configure', 'libtextstyle-build',
    'gettext-tools-configure', 'gettext-tools-gnulib', 'gettext-tools-headers',
    'gettext-tools-build', 'glib-configure', 'glib-build',
    'glib-probe-compile', 'glib-module-compile', 'glib-probe-run',
    'ncurses-probe-compile', 'ncurses-probe-run',
}


def bounded_json(path, maximum=4 * 1024**2, *, roots=None):
    return json.loads(safe_reads.read(path, roots or (HERE,), maximum))


def verify_python_commands(data, python, visibility_generator):
    """Inspect expanded Ninja commands, without running the described commands."""
    need(len(data) <= 8 * 1024**2)
    python = str(python)
    visibility_generator = str(visibility_generator)
    found_visibility, python_commands = 0, 0
    script_names = {'gen-visibility-macros.py', 'glib-mkenums', 'glib-genmarshal', 'gdbus-codegen', 'data-to-c.py'}
    for line in data.decode().splitlines():
        tokens = shlex.split(line, posix=True)
        need(len(tokens) <= 4096)
        for index, token in enumerate(tokens):
            name = Path(token).name
            if re.fullmatch(r'python(?:[0-9]+(?:\.[0-9]+)*)?', name):
                need(token == python and tokens[index + 1:index + 3] == ['-I', '-S'])
                python_commands += 1
            if name in script_names:
                need(index >= 3 and tokens[index - 3:index] == [python, '-I', '-S'])
            if token == visibility_generator:
                need(index >= 3 and tokens[index - 3:index] == [python, '-I', '-S'])
                found_visibility += 1
    need(python_commands > 0 and found_visibility > 0)
    return {'isolated_python_commands': python_commands, 'visibility_generator_commands': found_visibility}


def validate(root, receipt, execute=False):
    need(receipt.get('schema') == 1 and receipt.get('scope') == SCOPE)
    need(receipt.get('candidate_revision') == 1 and receipt.get('destination_branch') == BRANCH)
    need(receipt.get('input_sha256') == INPUT_HASHES and receipt.get('false_gates') == FALSE_GATES)
    need(receipt.get('source_changes_allowed') is False)
    need(not any(p.is_symlink() for p in HERE.rglob('*')))
    observed = {p.relative_to(HERE).as_posix() for p in HERE.rglob('*')
                if p.is_file() and p != HERE / 'review-receipt.json'}
    need(set(receipt.get('sha256', {})) == observed)
    for name, expected in receipt['sha256'].items():
        need(not name.startswith('/') and '..' not in Path(name).parts and digest(HERE / name) == expected)
    need(digest(root / WORKFLOW) == digest(HERE / 'glib-runtime-macos.yml.template'))
    if execute:
        for key in ('independent_review_passed', 'execution_approved',
                    'temporary_linker_adhoc_signing_approved', 'install_name_linker_assignment_approved',
                    'new_libffi_provider_approved', 'runner_free_eligibility_verified'):
            need(receipt.get(key) is True)
        for key in ('explicit_codesign_allowed', 'personal_signing_allowed', 'source_patch_allowed',
                    'paid_runner_allowed', 'network_during_build_allowed', 'artifact_upload_allowed'):
            need(receipt.get(key) is False)


class Lane(foundation.Lane):
    def checkpoint(self):
        need(time.monotonic() < self.deadline and self.bounds.disk_bytes(self.work) <= WORKSPACE_LIMIT)
        need(shutil.disk_usage(self.work).free >= 1024**3)

    def run(self, name, command, *, directory=None, timeout=60, expected=(0,), extra_env=None, subdirectory=None):
        self.phase = name
        self.checkpoint()
        phase = directory or self.directory(name)
        cwd = phase
        if subdirectory is not None:
            need(subdirectory == 'intl' and phase == self.phases / 'gettext-build' and
                 name in ('gettext-configure', 'gettext-headers', 'gettext-gnulib-build', 'gettext-libintl-build'))
            cwd = phase / 'intl'
            need(cwd.is_dir() and not cwd.is_symlink() and cwd.resolve().parent == phase.resolve())
        env = dict(self.env, HOME=str(phase / 'home'), TMPDIR=str(phase / 'tmp'))
        env.update(extra_env or {})
        wrapped = ['/usr/bin/sandbox-exec', '-D', 'PHASE_DIR=' + str(phase),
                   '-D', 'IMMUTABLE_DIR=' + str(self.immutable), '-D', 'CONTROL_DIR=' + str(self.root),
                   '-f', str(self.helpers / 'offline.sb'), *map(str, command)]
        record, out, err = self.bounds.run(wrapped, cwd=cwd, env=env, work=self.work,
            deadline=min(self.deadline, time.monotonic() + timeout),
            output_remaining=OUTPUT_LIMIT - self.output, expected_codes=expected)
        self.output += record['stdout_bytes'] + record['stderr_bytes']
        record = {'phase': name, **record}
        if record['status'] == 'failed':
            diagnostic = load('glib_build_diagnostics', self.helpers / 'glib_build_diagnostics.py')
            record['build_diagnostics'] = diagnostic.summarize(name, out, err,
                self.helpers / 'build-diagnostic-catalog.json', self.immutable, phase, self.root)
            record['private_diagnostics'] = [self.bounds.private_file_record(cwd / 'config.log', 'config_log'),
                self.bounds.private_file_record(cwd / 'out/meson-logs/meson-log.txt', 'meson_log')]
            if name == 'glib-probe-run':
                record['fixture_exit_contract'] = record['exit_code'] if record['exit_code'] in range(51, 71) else None
        self.steps.append(record)
        print(json.dumps(record, sort_keys=True), flush=True)
        if record['status'] != 'passed':
            raise foundation.PhaseError(record)
        return out, err, record

    def promote(self, items):
        """One trusted transaction after children are reaped; no install hooks run."""
        self.checkpoint()
        need(self.archive.snapshot(self.immutable) == self.base and len(items) <= 1024)
        targets, prepared, total = set(), [], 0
        for source, target, executable in items:
            source, target = Path(source), Path(target)
            need(source.is_file() and not source.is_symlink() and source.stat().st_size <= 128 * 1024**2)
            need(source.resolve().is_relative_to(self.phases.resolve()) or
                 source.resolve().is_relative_to(self.immutable / 'tree-glib'))
            need(target.is_relative_to(self.provider) and '..' not in target.parts and target not in targets)
            need(not target.exists() and not target.is_symlink())
            targets.add(target)
            total += source.stat().st_size
            expected = hashlib.sha256(safe_reads.read(source, (self.phases, self.immutable / 'tree-glib'), 128 * 1024**2)).hexdigest()
            prepared.append((source, target, executable, source.stat().st_size, expected))
            need(time.monotonic() < self.deadline)
        # Reserve the whole copy transaction before writing one byte. Source bytes
        # remain retained, so every promoted copy adds to the working set.
        need(self.bounds.disk_bytes(self.work) + total <= WORKSPACE_LIMIT)
        need(shutil.disk_usage(self.work).free - total >= 1024**3)
        next_scan = time.monotonic()
        for source, target, executable, size, expected in prepared:
            target.parent.mkdir(parents=True, exist_ok=True)
            copied, actual = 0, hashlib.sha256()
            with safe_reads.regular_file(source, (self.phases, self.immutable / 'tree-glib'), 128 * 1024**2) as (original, checked_size), target.open('xb') as output:
                need(checked_size == size)
                need(stat.S_ISREG(os.fstat(original.fileno()).st_mode))
                for chunk in iter(lambda: original.read(65536), b''):
                    need(time.monotonic() < self.deadline)
                    copied += len(chunk)
                    need(copied <= size)
                    output.write(chunk)
                    actual.update(chunk)
                    if time.monotonic() >= next_scan:
                        output.flush()
                        self.checkpoint()
                        next_scan = time.monotonic() + 0.5
            need(copied == size and actual.hexdigest() == expected)
            os.chmod(target, 0o555 if executable else 0o444)
            need(digest(target) == expected)
        self.checkpoint()
        self.base = self.archive.snapshot(self.immutable)

    def provider_alias(self, name, target):
        need(self.archive.snapshot(self.immutable) == self.base)
        need(name.is_relative_to(self.provider) and not name.exists() and not name.is_symlink())
        resolved = (name.parent / target).resolve(strict=True)
        need(resolved.is_relative_to(self.provider) and resolved.is_file() and not resolved.is_symlink())
        name.parent.mkdir(parents=True, exist_ok=True)
        name.symlink_to(target)
        self.base = self.archive.snapshot(self.immutable)

    def inspect_promoted(self, label, source, destination):
        record, loads = self.native.macho(source, self.provider, promoted_path=destination)
        print(json.dumps({'phase': 'native-inspect-' + label, 'status': 'passed',
                          'output_sha256': digest(source), 'output_bytes': source.stat().st_size, **record}, sort_keys=True))
        return loads

    def execute(self, trees):
        # Exact accepted providers are rebuilt first. The inherited final record only claims that foundation.
        super().execute(trees)
        py = trees['python'] / 'bin/python3.12'
        ninja = trees['ninja'] / 'ninja-1.13.2.data/scripts/ninja'
        pkgconf = self.immutable / 'toolbin/pkgconf'
        phase = self.directory('extra-sdk-tools')
        out, _, _ = self.run('tool-path-clang++', ['/usr/bin/xcrun', '--sdk', 'macosx', '--find', 'clang++'], directory=phase, timeout=10)
        cxx = out.decode().strip()
        need(cxx.startswith(('/Applications/', '/Library/Developer/', '/usr/bin/')) and not re.search(r'\s', cxx) and Path(cxx).is_file())
        print(json.dumps({'phase': 'tool-identity-clang++', 'status': 'passed', 'binary_sha256': digest(Path(cxx).resolve())}))
        self.env.update({'CXX': cxx, 'CXXFLAGS': self.env['CFLAGS'], 'OBJC': self.tools['clang'], 'OBJCFLAGS': self.env['CFLAGS']})
        flags = ['-arch', 'arm64', '-isysroot', self.env['SDKROOT'], '-mmacosx-version-min=26.0', '-O2']
        self.run('ncurses-probe-compile', [self.tools['clang'], *flags, self.helpers / 'ncurses_probe.c', '-lncurses', '-o', phase / 'ncurses-probe'], directory=phase, timeout=30)
        self.inspect('ncurses-probe', phase / 'ncurses-probe')
        out, err, _ = self.run('ncurses-probe-run', [phase / 'ncurses-probe'], directory=phase, timeout=10)
        need(out == b'sdk_ncurses_passed\n' and not err)

        phase = self.directory('libffi-build')
        self.run('libffi-configure', ['/bin/sh', trees['libffi'] / 'configure', '--prefix=' + str(self.provider),
                 '--enable-shared', '--disable-static', '--disable-builddir', '--disable-multi-os-directory', '--disable-docs'], directory=phase, timeout=120)
        self.run('libffi-build', ['/usr/bin/make', '-j2', 'libffi.la'], directory=phase, timeout=180)
        library = phase / '.libs/libffi.8.dylib'
        self.inspect('source-libffi', library)
        self.promote([(library, self.provider / 'lib/libffi.8.dylib', False),
                      (phase / 'include/ffi.h', self.provider / 'include/ffi.h', False),
                      (phase / 'include/ffitarget.h', self.provider / 'include/ffitarget.h', False),
                      (phase / 'libffi.pc', self.provider / 'lib/pkgconfig/libffi.pc', False)])
        self.provider_alias(self.provider / 'lib/libffi.dylib', 'libffi.8.dylib')
        out, _, _ = self.run('source-libffi-version', [pkgconf, '--modversion', 'libffi'], timeout=10)
        need(out.strip() == b'3.8.0')
        self.symbols('source-libffi', self.provider / 'lib/libffi.8.dylib',
            ['ffi_prep_cif', 'ffi_call', 'ffi_closure_alloc', 'ffi_prep_closure_loc', 'ffi_closure_free', 'ffi_get_version'])

        phase = self.directory('libtextstyle-build')
        self.run('libtextstyle-configure', ['/bin/sh', trees['gettext'] / 'libtextstyle/configure',
                 '--prefix=' + str(self.provider), '--enable-shared', '--disable-static',
                 '--without-libiconv-prefix', '--without-libncurses-prefix'], directory=phase, timeout=180)
        self.run('libtextstyle-build', ['/usr/bin/make', '-C', 'lib', '-j2', 'all'], directory=phase, timeout=240)
        library = phase / 'lib/.libs/libtextstyle.0.dylib'
        _, loads = self.native.macho(library, self.provider)
        need('/usr/lib/libncurses.5.4.dylib' in loads)
        self.inspect('libtextstyle', library)
        headers = [('textstyle.h', trees['gettext'] / 'libtextstyle/lib/textstyle.h'),
                   ('textstyle/version.h', phase / 'lib/textstyle/version.h'),
                   ('textstyle/woe32dll.h', phase / 'lib/textstyle/woe32dll.h')]
        # Reviewed public input header is staged through the phase for the trusted batch copier.
        staged = phase / 'reviewed-textstyle.h'
        shutil.copyfile(headers[0][1], staged)
        need(digest(staged) == digest(headers[0][1]))
        headers[0] = ('textstyle.h', staged)
        self.promote([(library, self.provider / 'lib/libtextstyle.0.dylib', False)] +
                     [(source, self.provider / 'include' / name, False) for name, source in headers])
        self.provider_alias(self.provider / 'lib/libtextstyle.dylib', 'libtextstyle.0.dylib')

        phase = self.directory('gettext-tools-build')
        self.run('gettext-tools-configure', ['/bin/sh', trees['gettext'] / 'gettext-tools/configure',
                 '--prefix=' + str(self.provider), '--enable-shared', '--disable-static', '--enable-nls',
                 '--with-libintl-prefix=' + str(self.provider), '--with-installed-libtextstyle',
                 '--with-libtextstyle-prefix=' + str(self.provider), '--with-included-libxml',
                 '--with-included-libunistring', '--without-libiconv-prefix'], directory=phase, timeout=240)
        config = safe_reads.read(phase / 'config.h', (phase,), 1024**2).decode()
        need('#define ENABLE_NLS 1' in config and '#define HAVE_LIBTEXTSTYLE 1' in config)
        self.run('gettext-tools-gnulib', ['/usr/bin/make', '-C', 'gnulib-lib', '-j2', 'all'], directory=phase, timeout=240)
        self.run('gettext-tools-headers', ['/usr/bin/make', '-C', 'src', 'built-sources'], directory=phase, timeout=60)
        self.run('gettext-tools-build', ['/usr/bin/make', '-C', 'src', '-j2', 'msgfmt', 'xgettext'], directory=phase, timeout=420)
        items = []
        for subdir, name in [('gnulib-lib', 'libgettextlib-1.0.dylib'), ('src', 'libgettextsrc-1.0.dylib')]:
            source = phase / subdir / '.libs' / name
            self.inspect(name, source)
            items.append((source, self.provider / 'lib' / name, False))
        for name in ('msgfmt', 'xgettext'):
            source = phase / 'src/.libs' / name
            self.inspect(name, source)
            items.append((source, self.provider / 'bin' / name, True))
        self.promote(items)
        self.env['PATH'] = str(self.provider / 'bin') + ':' + self.env['PATH']
        for name in ('msgfmt', 'xgettext'):
            out, _, _ = self.run(name + '-version', [self.provider / 'bin' / name, '--version'], timeout=10)
            need(out.splitlines()[0] == (name + ' (GNU gettext-tools) 1.0').encode())
        phase = self.directory('gettext-tool-probes')
        self.run('msgfmt-functional', [self.provider / 'bin/msgfmt', '--check', '-o', phase / 'proof.mo', self.helpers / 'gettext_probe.po'], directory=phase, timeout=20)
        translations = gettext.GNUTranslations(io.BytesIO(safe_reads.read(phase / 'proof.mo', (phase,), 2 * 1024**2)))
        need(translations.gettext('coffee') == 'café' and translations.ngettext('one apple', 'many apples', 2) == 'des pommes')
        self.run('xgettext-functional', [self.provider / 'bin/xgettext', '--language=C', '--from-code=UTF-8',
                 '--keyword=gettext', '--no-location', '-o', phase / 'proof.pot', self.helpers / 'gettext_probe.c'], directory=phase, timeout=20)
        need('msgid "Deepdesk extraction proof"' in safe_reads.read(phase / 'proof.pot', (phase,), 1024**2).decode())

        phase = self.directory('glib-build')
        native_file = phase / 'native.ini'
        native_file.write_text('[binaries]\n' + '\n'.join([
            'c = ' + repr(self.tools['clang']), 'cpp = ' + repr(cxx), 'objc = ' + repr(self.tools['clang']),
            'ar = ' + repr(self.tools['ar']), 'strip = ' + repr(self.tools['strip']),
            # No python binary entry: Meson 1.11 drops flags from that entry.
            # The approved adapter's shared python_command supplies -I -S instead.
            'pkg-config = ' + repr(str(pkgconf)),
            'gen-visibility-macros.py = ' + repr([str(py), '-I', '-S', str(trees['glib'] / 'tools/gen-visibility-macros.py')]),
            'msgfmt = ' + repr(str(self.provider / 'bin/msgfmt')),
            'xgettext = ' + repr(str(self.provider / 'bin/xgettext'))]) + '\n')
        self.env.update({'CPPFLAGS': self.env['CPPFLAGS'] + ' -I' + str(self.provider / 'include'),
                         'LDFLAGS': self.env['LDFLAGS'] + ' -L' + str(self.provider / 'lib')})
        self.run('glib-configure', [py, '-I', '-S', self.helpers / 'meson_entry.py', 'setup', phase / 'out', trees['glib'],
                 '--prefix=' + str(self.provider), '--libdir=lib', '--native-file=' + str(native_file), *GLIB_OPTIONS], directory=phase, timeout=180)
        intro = phase / 'out/meson-info'
        options = {x['name']: x['value'] for x in bounded_json(intro / 'intro-buildoptions.json', roots=(phase,))}
        need(options.get('nls') == 'enabled' and options.get('xattr') is True and options.get('glib_assert') is True and options.get('glib_checks') is True)
        deps = bounded_json(intro / 'intro-dependencies.json', roots=(phase,))
        ffi = [x for x in deps if x.get('name') == 'libffi']
        need(len(ffi) == 1 and ffi[0].get('version') == '3.8.0')
        need(str(self.provider / 'lib/libffi.dylib') in ffi[0].get('link_args', []) or
             str(self.provider / 'lib/libffi.8.dylib') in ffi[0].get('link_args', []))
        project = bounded_json(intro / 'intro-projectinfo.json', roots=(phase,))
        need(project['version'] == '2.90.1' and {x['name'] for x in project.get('subprojects', [])} == {'gvdb'})
        config = safe_reads.read(phase / 'out/config.h', (phase,), 1024**2).decode()
        need(re.search(r'^#define HAVE_COCOA(?: 1)?$', config, re.M) is not None and
             re.search(r'^#define HAVE_CARBON(?: 1)?$', config, re.M) is not None)
        commands, _, _ = self.run('glib-command-inventory', [ninja, '-C', phase / 'out', '-t', 'commands'], directory=phase, timeout=30)
        command_contract = verify_python_commands(commands, py, trees['glib'] / 'tools/gen-visibility-macros.py')
        print(json.dumps({'phase': 'glib-generator-isolation-contract', 'status': 'passed', **command_contract}, sort_keys=True))
        self.run('glib-build', [ninja, '-C', phase / 'out', '-j2'], directory=phase, timeout=480)
        self.promote_glib(trees['glib'], phase / 'out', py)
        self.glib_probes(py, flags)
        need(self.archive.snapshot(self.immutable) == self.base)
        self.checkpoint()
        print(json.dumps({'phase': 'combined-prerequisite-result', 'status': 'passed', 'scope': SCOPE,
            'foundation_rebuilt': True, 'source_libffi': '3.8.0', 'glib_version': '2.90.1',
            'glib_runtime': True, 'gobject_runtime': True, 'gmodule_runtime': True, 'gio_runtime': True,
            'girepository_runtime': True, 'production_catalog_count': 102, 'glib_mkenums_fixture': True,
            'output_total_bytes': self.output, **FALSE_GATES}, sort_keys=True))

    def promote_glib(self, source, build, py):
        installed = bounded_json(build / 'meson-info/intro-installed.json', roots=(build,))
        need(isinstance(installed, dict) and len(installed) < 2048)
        items, headers, pcs = [], set(), set()
        for original, destinations in installed.items():
            original = Path(original)
            destinations = destinations if isinstance(destinations, list) else [destinations]
            for destination in destinations:
                destination = Path(destination)
                need(destination.is_absolute() and destination.is_relative_to(self.provider) and '..' not in destination.parts)
                rel = destination.relative_to(self.provider).as_posix()
                if rel.endswith('.h') and rel.startswith(('include/glib-2.0/', 'include/gio-unix-2.0/', 'lib/glib-2.0/include/')):
                    need(original.resolve().is_relative_to(source) or original.resolve().is_relative_to(build))
                    need(rel not in headers)
                    headers.add(rel); items.append((original, destination, False))
                elif rel.startswith('lib/pkgconfig/') and rel.endswith('.pc'):
                    need(original.resolve().is_relative_to(build) and '/' not in rel[len('lib/pkgconfig/'):])
                    need(rel not in pcs)
                    pcs.add(rel); items.append((original, destination, False))
        need(200 <= len(headers) <= 512)
        need({'lib/glib-2.0/include/glibconfig.h', 'include/glib-2.0/glib.h', 'include/glib-2.0/glib-object.h',
              'include/glib-2.0/gio/gio.h', 'include/glib-2.0/gobject/glib-enumtypes.h'} <= headers)
        need({'lib/pkgconfig/glib-2.0.pc', 'lib/pkgconfig/gobject-2.0.pc', 'lib/pkgconfig/gmodule-2.0.pc',
              'lib/pkgconfig/gio-2.0.pc', 'lib/pkgconfig/gthread-2.0.pc', 'lib/pkgconfig/girepository-2.0.pc'} <= pcs)
        for name, component in self.native.GLIB_NAMES.items():
            original = build / component / name
            destination = self.provider / 'native' / component / name
            self.inspect_promoted(component, original, destination)
            items.append((original, destination, False))
        languages = [line.split('#', 1)[0].strip() for line in safe_reads.read(source / 'po/LINGUAS', (source,), 65536).decode().splitlines()]
        languages = [x for x in languages if x]
        need(len(languages) == len(set(languages)) == 102)
        contract = bounded_json(self.helpers / 'catalog-contract.json')
        need(languages == contract['languages'])
        for language in languages:
            original = build / 'po' / language / 'LC_MESSAGES/glib20.mo'
            data = safe_reads.read(original, (build,), 2 * 1024**2)
            need(len(data) >= 28)
            catalog = gettext.GNUTranslations(io.BytesIO(data))
            need(len(catalog._catalog) >= 2)
            if language == 'fr':
                need(catalog.pgettext('full month name', 'January') == 'janvier')
            items.append((original, self.provider / 'share/locale' / language / 'LC_MESSAGES/glib20.mo', False))
        script = build / 'gobject/glib-mkenums'
        original = safe_reads.read(source / 'gobject/glib-mkenums.in', (source,), 256 * 1024)
        expected = original.replace(b'@PYTHON@', b'/usr/bin/env python3').replace(b'@VERSION@', b'2.90.1')
        need(safe_reads.read(script, (build,), 256 * 1024) == expected)
        items.append((script, self.provider / 'share/deepdesk-build-tools/glib-mkenums.py', False))
        wrapper = build / 'deepdesk-glib-mkenums'
        wrapper.write_text('#!/bin/sh\nexec ' + shlex.quote(str(py)) + ' -I -S ' +
                           shlex.quote(str(self.provider / 'share/deepdesk-build-tools/glib-mkenums.py')) + ' "$@"\n')
        items.append((wrapper, self.provider / 'bin/glib-mkenums', True))
        self.promote(items)
        for name, component in self.native.GLIB_NAMES.items():
            self.provider_alias(self.provider / 'lib' / name, '../native/' + component + '/' + name)
            self.provider_alias(self.provider / 'lib' / name.replace('.0.dylib', '.dylib'), name)
        print(json.dumps({'phase': 'glib-provider-promotion', 'status': 'passed',
                          'library_count': 6, 'header_count': len(headers), 'pkgconfig_count': len(pcs),
                          'production_catalog_count': len(languages), 'install_hooks_executed': False}))

    def glib_probes(self, py, flags):
        phase = self.directory('glib-probes')
        pkgconf = self.immutable / 'toolbin/pkgconf'
        out, _, _ = self.run('glib-mkenums-pkgconfig-binding', [pkgconf, '--variable=glib_mkenums', 'glib-2.0'], directory=phase, timeout=10)
        need(out.strip() == str(self.provider / 'bin/glib-mkenums').encode())
        out, _, _ = self.run('glib-mkenums-functional', [self.provider / 'bin/glib-mkenums', '--fhead=BEGIN_ENUM',
            '--eprod=@EnumName@', '--vprod=@VALUENAME@=@valuenum@', '--ftail=END_ENUM', self.helpers / 'enum_probe.h'], directory=phase, timeout=15)
        need(b'DeepdeskProof' in out and b'DEEPDESK_PROOF_FORTY_TWO=42' in out and b'END_ENUM' in out)
        module = phase / 'libdeepdesk-module.dylib'
        self.run('glib-module-compile', [self.tools['clang'], *flags, '-dynamiclib', self.helpers / 'glib_module.c',
            '-Wl,-install_name,' + str(self.provider / 'lib/libdeepdesk-module.dylib'), '-o', module], directory=phase, timeout=30)
        self.inspect('private-module', module)
        self.promote([(module, self.provider / 'lib/libdeepdesk-module.dylib', False)])
        out, _, _ = self.run('glib-pkgconfig-flags', [pkgconf, '--cflags', '--libs', 'glib-2.0', 'gobject-2.0', 'gio-2.0', 'gmodule-2.0', 'girepository-2.0', 'libffi'], directory=phase, timeout=10)
        arguments = out.decode().strip().split()
        need(len(arguments) < 100 and all(re.fullmatch(r'[-A-Za-z0-9_./,+]+', x) for x in arguments))
        need(not any('/opt/' in x or '/usr/local' in x for x in arguments))
        fixture = phase / 'glib-probe'
        rpaths = ['-Wl,-rpath,' + str(self.provider / 'native' / component) for component in self.native.GLIB_COMPONENTS]
        self.run('glib-probe-compile', [self.tools['clang'], *flags, self.helpers / 'glib_probe.c', *arguments, *rpaths, '-o', fixture], directory=phase, timeout=45)
        self.inspect('glib-probe', fixture)
        out, err, _ = self.run('glib-probe-run', [fixture, self.provider / 'lib/libdeepdesk-module.dylib', phase / 'local-proof.txt'],
                              directory=phase, timeout=30, extra_env={'LC_ALL': 'en_US.UTF-8', 'LANGUAGE': 'fr'})
        self.native.fixture_output(out, GLIB_MARKERS, fixture, self.provider,
            ['libglib-2.0.0.dylib', 'libgobject-2.0.0.dylib', 'libgmodule-2.0.0.dylib', 'libgio-2.0.0.dylib',
             'libgirepository-2.0.0.dylib', 'libffi.8.dylib', 'libintl.8.dylib', 'libpcre2-8.0.dylib', 'libdeepdesk-module.dylib'])
        need(not err and not (phase / 'local-proof.txt').exists())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--validate-candidate', action='store_true')
    args = parser.parse_args()
    phase, lane = 'receipt-validation', None
    try:
        root = args.repository.resolve(strict=True)
        need(HERE == root / 'packaging/glib-runtime-candidate')
        receipt = bounded_json(HERE / 'review-receipt.json')
        validate(root, receipt, not args.validate_candidate)
        if args.validate_candidate:
            print(json.dumps({'status': 'static_candidate_integrity_passed', 'execution_approved': receipt['execution_approved'], 'native_execution': False}))
            return 0
        phase = 'host-and-destination-guards'
        need(platform.system() == 'Darwin' and platform.machine() == 'arm64' and sys.version_info >= (3, 9))
        need(os.environ.get('GITHUB_REPOSITORY') == 'Emin-dev/deepdesk' and os.environ.get('GITHUB_REF') == 'refs/heads/' + BRANCH)
        need(os.environ.get('GITHUB_EVENT_NAME') in ('push', 'workflow_dispatch'))
        need(os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted' and os.environ.get('RUNNER_OS') == 'macOS' and os.environ.get('RUNNER_ARCH') == 'ARM64')
        event_path = Path(os.environ['GITHUB_EVENT_PATH'])
        event = bounded_json(event_path, 2 * 1024**2, roots=(event_path.parent,))
        need(event.get('repository', {}).get('private') is False and event.get('repository', {}).get('full_name') == 'Emin-dev/deepdesk')
        need(Path('/usr/bin/sandbox-exec').is_file() and str(Path(sys.executable).resolve()).startswith(('/Applications/', '/Library/Developer/', '/usr/bin/')))
        modules = (load('glib_archive_tools', HERE / 'glib_archive_tools.py'), load('glib_bounds', HERE / 'glib_bounds.py'), load('glib_native_checks', HERE / 'glib_native_checks.py'))
        diagnostics = load('glib_input_diagnostics', HERE / 'glib_input_diagnostics.py')
        lock = bounded_json(HERE / 'input-lock.json')
        need(lock['scope'] == SCOPE and lock['source_changes_allowed'] is False)
        need(len(lock['inputs']) == 8 and {x['id']: x['sha256'] for x in lock['inputs']} == INPUT_HASHES)
        need(lock['total_compressed_bytes'] == 69310939 and lock['total_expanded_bytes'] == 394983369)
        temp = Path(os.environ['RUNNER_TEMP'])
        need(temp.is_dir() and shutil.disk_usage(temp).free >= 6 * 1024**3)
        def interrupted(signum, frame):
            raise foundation.LaneError()
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        with tempfile.TemporaryDirectory(prefix='deepdesk-glib-runtime-', dir=temp) as td:
            work = Path(td).resolve()
            need(not re.search(r'\s', str(work)) and not work.is_relative_to(root))
            lane = Lane(root, HERE, work, modules)
            lane.deadline = time.monotonic() + INPUT_SECONDS
            phase, trees = 'input-phase', {}
            checks = foundation.InputChecks(lane.deadline, lane.checkpoint)
            previous = signal.signal(signal.SIGALRM, interrupted)
            signal.setitimer(signal.ITIMER_REAL, INPUT_SECONDS)
            try:
                for pin in lock['inputs']:
                    phase = 'input-' + pin['id']
                    trees[pin['id']] = foundation.read_input(modules[0], diagnostics, pin, lane.immutable / pin['filename'],
                        lane.immutable / ('tree-' + pin['id']), HERE / pin['member_manifest'], lane.deadline, checks)
                    print(json.dumps({'phase': phase, 'status': 'passed', 'archive_sha256': pin['sha256'], 'archive_bytes': pin['size']}), flush=True)
                foundation.write_mo(lane.immutable / 'catalog/fr/LC_MESSAGES/deepdesk-proof.mo')
                sentinel = lane.immutable / 'host-pc/deepdesk_unreviewed_host_only.pc'
                sentinel.parent.mkdir()
                sentinel.write_text('Name: deepdesk_unreviewed_host_only\nDescription: First-party search exclusion sentinel\nVersion: 1.0\n')
                lane.base = modules[0].snapshot(lane.immutable)
                checks(force=True)
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, previous)
            phase = 'contained-execution'
            lane.deadline = time.monotonic() + BUILD_SECONDS
            lane.execute(trees)
        return 0
    except foundation.PhaseError as error:
        print(json.dumps({'phase': error.record['phase'], 'status': 'failed', 'scope': SCOPE,
                          'failure_class': error.record['failure_class'], 'exit_code': error.record['exit_code'], **FALSE_GATES}, sort_keys=True))
        return 1
    except Exception:
        print(json.dumps({'phase': lane.phase if lane is not None and phase == 'contained-execution' else phase,
                          'status': 'failed', 'scope': SCOPE, 'failure_class': 'contract_or_input_failure', **FALSE_GATES}, sort_keys=True))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

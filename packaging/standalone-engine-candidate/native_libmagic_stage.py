"""Gated patched-source build; retains complete native install for assembly.

No source, compiler, fixture or dependency execution occurs on import.
"""
from __future__ import annotations
import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys

sys.dont_write_bytecode = True
import time


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def inspect_native(load_text, command_text):
    loads = [line.strip().split(' (compatibility version', 1)[0]
             for line in load_text.splitlines()[1:] if line.startswith('\t')]
    require(loads and loads.count('@rpath/libmagic.1.dylib') == 1,
            'Relative libmagic install ID or dependency is absent')
    require(all(value == '@rpath/libmagic.1.dylib' or
                (value.startswith(('/usr/lib/', '/System/Library/')) and '..' not in Path(value).parts)
                for value in loads), 'Native load outside bundled/Apple closure')
    rpaths = re.findall(r'cmd LC_RPATH\s+cmdsize [0-9]+\s+path ([^\n]+?) \(offset [0-9]+\)', command_text)
    require(len(rpaths) == 2 and set(rpaths) == {'@loader_path', '@loader_path/../lib'},
            'Unexpected native rpath')
    minos = re.findall(r'\bminos ([0-9.]+)', command_text)
    require(len(minos) == 1 and tuple(int(x) for x in (minos[0] + '.0').split('.')[:3]) == (26, 0, 0),
            'Native minimum OS differs')
    return {'loads': loads, 'rpaths': rpaths, 'minimum_os': minos[0]}


class NativeStepFailure(RuntimeError):
    def __init__(self, phase, category):
        super().__init__('Native step failed; raw diagnostics withheld')
        self.phase = phase
        self.category = category


def sandbox_command(command, *, work, immutable, helpers, fixture=None):
    require(command and str(command[0]) != '/usr/bin/sandbox-exec', 'Nested native sandbox invocation forbidden')
    return ['/usr/bin/sandbox-exec', '-D', 'WORK_DIR=' + str(work),
            '-D', 'IMMUTABLE_DIR=' + str(immutable),
            *(['-D', 'FIXTURE_PATH=' + str(fixture)] if fixture else []),
            '-f', str(helpers / ('smoke-no-exec.sb' if fixture else 'offline.sb')),
            *map(str, command)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--review-receipt', type=Path, required=True)
    parser.add_argument('--work-root', type=Path, required=True)
    parser.add_argument('--source-archive', type=Path, required=True)
    args = parser.parse_args()
    root = args.repository.resolve(strict=True)
    helpers = root / 'packaging/standalone-engine-candidate'
    integration = load(helpers / 'libmagic_integration.py', 'deepdesk_magic_integration')
    receipt = json.loads(args.review_receipt.read_text())
    integration.validate_gate(receipt, root)
    require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'Native macOS arm64 only')
    pilot_helpers = helpers / 'libmagic-pilot'
    pilot = load(pilot_helpers / 'stage.py', 'deepdesk_retained_libmagic_pilot')
    bounded = load(pilot_helpers / 'bounded_runtime.py', 'deepdesk_magic_bounds')
    assembly = load(helpers / 'assemble.py', 'deepdesk_magic_inventory')
    require(pilot.digest(pilot_helpers / 'bounded_runtime.py') == pilot.BOUNDED_SHA, 'Bounds helper changed')
    pin = json.loads((pilot_helpers / 'source-pin.json').read_text())
    pilot.validate_pin(pin, pilot_helpers / 'source-members.json')
    members = json.loads((pilot_helpers / 'source-members.json').read_text())
    work = args.work_root
    require(work.is_absolute() and not work.exists() and not re.search(r'\s', str(work)), 'Native work root differs')
    work.mkdir(mode=0o700)
    work = work.resolve(strict=True)
    require(shutil.disk_usage(work).free >= 2 * 1024**3, 'Native free-space preflight failed')
    immutable = work / 'immutable'; immutable.mkdir(mode=0o700)
    home = work / 'home'; home.mkdir(mode=0o700)
    tmp = work / 'tmp'; tmp.mkdir(mode=0o700)
    build = work / 'build'; build.mkdir()
    prefix = work / 'install'
    # Outer parent owns this sibling. The native profile cannot write there.
    protected = work.parent / 'native-control-must-not-write'
    require(not protected.exists(), 'Native control path exists')
    env = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'HOME': str(home), 'TMPDIR': str(tmp),
           'LC_ALL': 'C', 'LANG': 'C', 'TZ': 'UTC', 'SOURCE_DATE_EPOCH': '0',
           'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1', 'MACOSX_DEPLOYMENT_TARGET': '26.0'}
    deadline = time.monotonic() + 540
    output_total = 0
    steps = []
    def run(command, *, name, cwd=work, timeout=30, fixture=None):
        nonlocal output_total
        remaining = deadline - time.monotonic()
        require(remaining > 0, 'Native stage total deadline exceeded')
        require(name in integration.NATIVE_PHASES, 'Unreviewed native step')
        command = sandbox_command(command, work=work, immutable=immutable, helpers=pilot_helpers, fixture=fixture)
        capture = io.StringIO()
        try:
            with contextlib.redirect_stdout(capture):
                output = bounded.run_bounded(command, cwd=cwd, env=env, work=work,
                    timeout=min(timeout, remaining), disk_limit=pilot.DISK_LIMIT,
                    output_limit=integration.CAP-integration.NATIVE_REPORT_RESERVE-output_total,
                    own_session=False, public_summary=True)
        except Exception as error:
            category = (pilot.FAILURE_CATEGORIES.get(error.args[0], 'unknown')
                        if type(error) is RuntimeError and len(error.args) == 1
                        and type(error.args[0]) is str else 'unknown')
            raise NativeStepFailure(name, category) from None
        summary = json.loads(capture.getvalue())
        require(summary.get('bounded_step') == 'passed' and summary['stdout_bytes'] == len(output),
                'Native bounded summary differs')
        output_total += summary['stdout_bytes'] + summary['stderr_bytes']
        require(output_total <= integration.CAP-integration.NATIVE_REPORT_RESERVE,
                'Native aggregate private output cap exceeded')
        steps.append({'name': name, 'stdout_bytes': summary['stdout_bytes'],
                      'stderr_bytes': summary['stderr_bytes'],
                      'stdout_sha256': summary['stdout_sha256'], 'stderr_sha256': summary['stderr_sha256']})
        return output
    # Retained first-party network/write/host-read canaries, before source execution.
    python = Path(sys.executable).resolve()
    net = "import errno,socket\ntry:\n s=socket.socket();s.settimeout(1);r=s.connect_ex(('192.0.2.1',9))\nexcept OSError as e:\n r=e.errno\nassert r in (errno.EPERM,errno.EACCES),r\n"
    run([python, '-I', '-c', net], name='external-network-denied', timeout=10)
    run([python, '-I', '-c', net.replace("'192.0.2.1',9", "'127.0.0.1',54321")], name='local-connect-denied', timeout=10)
    bind = "import errno,socket\ntry:\n s=socket.socket();s.bind(('127.0.0.1',0))\nexcept OSError as e:\n assert e.errno in (errno.EPERM,errno.EACCES)\nelse:\n raise RuntimeError('Bind allowed')\n"
    run([python, '-I', '-c', bind], name='local-bind-denied', timeout=10)
    write = "import errno,sys\ntry:\n open(sys.argv[1],'xb').close()\nexcept OSError as e:\n assert e.errno in (errno.EPERM,errno.EACCES)\nelse:\n raise RuntimeError('Protected write allowed')\n"
    for name, target in [('outside-write-denied', protected), ('immutable-write-denied', immutable/'no-write')]:
        run([python, '-I', '-c', write, target], name=name, timeout=10)
        require(not target.exists(), 'Native write canary mutated target')
    run([python, '-I', '-c', "import pathlib,sys;pathlib.Path(sys.argv[1]).write_text('synthetic')", work/'canary'], name='work-write-allowed', timeout=10)
    brew = Path('/opt/homebrew/bin/git'); require(brew.is_file(), 'Native read canary target missing')
    read = "import errno,sys\ntry:\n open(sys.argv[1],'rb').read(1)\nexcept OSError as e:\n assert e.errno in (errno.EPERM,errno.EACCES)\nelse:\n raise RuntimeError('Host read allowed')\n"
    run([python, '-I', '-c', read, brew], name='homebrew-read-denied', timeout=10)
    sdk = run(['/usr/bin/xcrun', '--sdk', 'macosx', '--show-sdk-path'], name='sdk-path').decode().strip()
    clang = run(['/usr/bin/xcrun', '--sdk', 'macosx', '--find', 'clang'], name='compiler-path').decode().strip()
    for value in (sdk, clang):
        require(value.startswith(('/Applications/', '/Library/Developer/', '/usr/bin/'))
                and not re.search(r'\s', value) and Path(value).exists(), 'Unexpected Apple toolchain path')
    run([clang, '--version'], name='compiler-version')
    run(['/usr/bin/sw_vers'], name='os-version')
    env.update({'CC': clang, 'CFLAGS': '-arch arm64 -isysroot ' + sdk + ' -O2',
                'CPPFLAGS': '-isysroot ' + sdk, 'SDKROOT': sdk,
                'LDFLAGS': '-arch arm64 -isysroot ' + sdk + ' -Wl,-rpath,@loader_path -Wl,-rpath,@loader_path/../lib'})
    preflight = work / 'sdk-codec-preflight'
    run([clang, '-arch', 'arm64', '-isysroot', sdk, pilot_helpers/'sdk_codec_preflight.c',
         '-lz', '-lbz2', '-o', preflight], name='codec-preflight-compile')
    preloads = pilot.parse_otool_loads(run(['/usr/bin/otool', '-L', preflight], name='codec-preflight-loads').decode())
    pilot.validate_loads(preloads, prefix, False)
    require(any('/libz.' in x for x in preloads) and any('/libbz2.' in x for x in preloads), 'SDK codecs missing')
    run([preflight], name='codec-preflight-run', timeout=10)
    archive = immutable / pin['filename']
    require(pilot.digest(args.source_archive) == pilot.SOURCE_SHA
            and args.source_archive.stat().st_size == pilot.SOURCE_SIZE, 'Native source archive input differs')
    shutil.copyfile(args.source_archive, archive)
    source = pilot.extract_exact(archive, immutable/'source', members)
    nofork = pilot.apply_overlay(source, members, json.loads((pilot_helpers/'source-overlay.json').read_text()), pilot_helpers/'compress-nofork.patch')
    configure = integration.apply_configure_overlay(source, json.loads((helpers/'libmagic-configure-overlay.json').read_text()))
    immutable_before = pilot.snapshot(immutable)
    run(['/bin/sh', source/'configure', '--prefix='+str(prefix), '--disable-static', '--enable-shared',
         '--enable-zlib', '--enable-bzlib'], name='configure', cwd=build, timeout=180)
    caps = pilot.capabilities((build/'config.h').read_text())
    run(['/usr/bin/make', '-j2'], name='make-all', cwd=build, timeout=240)
    run(['/usr/bin/make', 'install'], name='install-staged-prefix', cwd=build, timeout=60)
    library = prefix/'lib/libmagic.1.dylib'; database = prefix/'share/misc/magic.mgc'
    require(library.is_file() and database.is_file() and database.stat().st_size > 0, 'Native output absent')
    text = integration.preserve_text_sources(source, prefix,
        json.loads((helpers/'libmagic-text-fragments.json').read_text()), helpers/'libmagic-text-fragments.json')
    fixture = prefix/'libexec/deepdesk-libmagic-smoke'; fixture.parent.mkdir()
    run([clang, '-arch', 'arm64', '-isysroot', sdk, '-I'+str(prefix/'include'), '-I'+str(pilot_helpers),
         pilot_helpers/'smoke_fixture.c', prefix/'lib/libmagic.dylib',
         '-Wl,-rpath,@loader_path', '-Wl,-rpath,@loader_path/../lib', '-o', fixture], name='smoke-compile')
    native_records = []
    for path in [library, fixture, prefix/'bin/file']:
        run(['/usr/bin/lipo', path, '-verify_arch', 'arm64'], name='arm64-'+path.name)
        loads = run(['/usr/bin/otool', '-L', path], name='loads-'+path.name).decode()
        commands = run(['/usr/bin/otool', '-l', path], name='commands-'+path.name).decode()
        native_records.append({'path': str(path.relative_to(prefix)), 'sha256': pilot.digest(path.resolve()),
                               **inspect_native(loads, commands)})
    missing = work/'nonexistent-database.mgc'; require(not missing.exists(), 'Negative path exists')
    before_stage = pilot.snapshot(prefix)
    before_install = assembly.inventory_tree(prefix)
    marker = work/'native-exec-canary.marker'; marker.touch(exist_ok=False)
    canary = run([fixture, '--verify-exec-denial', marker], name='smoke-external-exec-denied', timeout=10, fixture=fixture)
    observation = pilot.native_canary_observation(marker, True, canary)
    require(observation['passed'], 'Native exec denial canary differs')
    smoke = run([fixture, library, database, missing], name='synthetic-mime-codec-database-and-external-rejection', timeout=20, fixture=fixture)
    images = pilot.validate_smoke(smoke.decode(), prefix, fixture)
    require(pilot.snapshot(immutable) == immutable_before and pilot.snapshot(prefix) == before_stage,
            'Native source/install changed during checks')
    validated_install = assembly.inventory_tree(prefix)
    require(validated_install == before_install, 'Complete native installation changed during validation')
    entries = {row['path']: row for row in validated_install['entries']}
    require(all(entries.get(row['path'], {}).get('kind') == 'file'
                and entries[row['path']]['sha256'] == row['sha256'] for row in native_records),
            'Native record hashes differ from final validated complete install')
    result = {'status': 'passed', 'kind': 'bundled-libmagic-native-build',
        'validated_install_manifest_sha256': assembly.manifest_digest(validated_install),
        'source_sha256': pilot.SOURCE_SHA, 'nofork_overlay': nofork, 'configure_overlay': configure,
        'detected_capabilities': caps, 'native_records': native_records,
        'native_exec_canary': observation, 'fixture_count': 7, 'native_step_count': len(steps),
        'native_loaded_image_count': len(images), 'private_native_output_bytes': output_total,
        'full_native_closure_verified': False, 'model_loaded': False, 'provider_queried': False, **text}
    encoded = json.dumps(result, sort_keys=True)
    require(len(encoded.encode())+1 <= integration.NATIVE_REPORT_RESERVE, 'Native fixed report reserve exceeded')
    print(encoded)


def failure_report(error):
    # The unchanged helper withholds counts on failure and can capture a final
    # chunk beyond its threshold. No exact count or upper-bound claim is valid.
    return {'status': 'failed', 'kind': 'bundled-libmagic-native-build',
            'phase': error.phase if type(error) is NativeStepFailure else 'native-controller',
            'failure_category': error.category if type(error) is NativeStepFailure else 'contract',
            'private_native_output_bytes': None,
            'private_output_measurement': 'unknown-after-failure'}


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps(failure_report(error), sort_keys=True))

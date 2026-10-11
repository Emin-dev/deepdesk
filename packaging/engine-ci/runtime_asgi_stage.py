"""Proposed full-wheelhouse / in-process ASGI lane. Execution gate defaults closed.

Downloads official exact bytes only. All builds, installs and runtime imports
execute offline in a temporary macOS sandbox after independent exact review.
No PyInstaller, native bottle, model, research query, release or upload step.
"""
from __future__ import annotations
import argparse
import configparser
import io
import tomllib
import email.parser
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import tempfile
import tarfile
import time
import zipfile
import urllib.parse
import urllib.request


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def digest(path):
    require(path.is_file() and not path.is_symlink(), "Missing or linked reviewed input")
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_helper(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def validate_built_wheel(wheel, name, version, source_contract, *, app=False):
    """Every installed non-metadata byte must equal a reviewed source byte.

    The build backend may generate bounded dist-info, but never new executable
    package content, scripts, .pth, native payload or wheel .data destinations.
    RECORD is generated metadata; pip revalidates exact whole wheel SHA below.
    """
    records, metadata_hashes, seen, total = [], {}, set(), 0
    prefix = name.replace('-', '_') + '-' + version + '.dist-info/'
    with zipfile.ZipFile(wheel) as archive:
        for member in archive.infolist():
            path = PurePosixPath(member.filename)
            require(not path.is_absolute() and '..' not in path.parts and '\\' not in member.filename
                    and member.filename not in seen and not member.flag_bits & 1, 'Unsafe built wheel member')
            require((member.external_attr >> 16) & 0o170000 != 0o120000, 'Linked built wheel member')
            seen.add(member.filename)
            total += member.file_size
            require(total <= 32 * 1024**2 and member.file_size <= 4 * 1024**2 and len(seen) < 5000,
                    'Built wheel exceeds bounds')
            if member.is_dir():
                continue
            content = archive.read(member)
            actual = hashlib.sha256(content).hexdigest()
            if member.filename.startswith(prefix):
                relative = member.filename[len(prefix):]
                require(relative in {'METADATA','WHEEL','RECORD','top_level.txt','entry_points.txt'}
                        or (relative.startswith('licenses/') and '/' not in relative[9:]),
                        'Unexpected generated dist-info member')
                if relative.startswith('licenses/'):
                    require(source_contract.get(relative[9:],{}).get('sha256') == actual, 'Built license differs from source')
                metadata_hashes[relative] = actual
            else:
                require(not member.filename.endswith(('.pth', '.pyc')) and '.data/' not in member.filename,
                        'Unexpected generated runtime payload')
                original = ('src/' if app else '') + member.filename
                require(source_contract.get(original, {}).get('sha256') == actual,
                        'Built wheel payload differs from approved source')
                records.append(member.filename)
        require(prefix + 'METADATA' in seen and prefix + 'WHEEL' in seen and prefix + 'RECORD' in seen,
                'Built wheel metadata incomplete')
        meta = email.parser.BytesParser().parsebytes(archive.read(prefix + 'METADATA'))
        require(canonical(meta.get('Name','')) == name and meta.get('Version') == version,
                'Built wheel identity differs')
        require(all('@' not in value for value in meta.get_all('Requires-Dist', [])), 'Direct URL dependency forbidden')
        wheel_meta = email.parser.BytesParser().parsebytes(archive.read(prefix + 'WHEEL'))
        require(wheel_meta.get('Root-Is-Purelib') == 'true' and wheel_meta.get_all('Tag') == ['py3-none-any'],
                'Unexpected built wheel tag or destination')
        required_notices = {'google-search-results':{'LICENSE'}, 'langdetect':{'LICENSE','NOTICE'},
            'wikipedia':{'LICENSE'}, 'jstyleson':set(), 'local-deep-research':{'LICENSE'}}.get(name,set())
        expected_notice_paths = {'licenses/' + filename for filename in required_notices}
        require({path for path in metadata_hashes if path.startswith('licenses/')} == expected_notice_paths,
                'Required source license destination set differs')
        for filename in required_notices:
            require(metadata_hashes['licenses/' + filename] == source_contract.get(filename,{}).get('sha256'),
                    'Required source license hash differs')
        if app:
            require('entry_points.txt' in metadata_hashes, 'Required application entry points absent')
            parser = configparser.ConfigParser(interpolation=None, delimiters=('=',), strict=True)
            parser.optionxform = str
            parser.read_string(archive.read(prefix + 'entry_points.txt').decode('utf-8'))
            expected_scripts = {'ldr-web':'local_deep_research.web.app:main',
                                'ldr-mcp':'local_deep_research.mcp:run_server'}
            require(not parser.defaults() and parser.sections() == ['console_scripts', 'gui_scripts']
                    and dict(parser.items('console_scripts')) == expected_scripts
                    and dict(parser.items('gui_scripts')) == {},
                    'Generated application entry points differ from reviewed pyproject declarations')
            expected_payload = {path[4:] for path in source_contract if path.startswith('src/local_deep_research/')}
            require(set(records) == expected_payload, 'Application package resource set changed')
            required = {'local_deep_research/web/fastapi_app.py',
                        'local_deep_research/defaults/settings_deepdesk_ddg.json'}
            required.update(path[4:] for path in source_contract if path.startswith(
                'src/local_deep_research/llm/providers/implementations/') and path.endswith('.py'))
            require(required <= set(records), 'Required physical engine resources absent')
            require(any(x.startswith('local_deep_research/web/templates/') for x in records)
                    and any(x.startswith('local_deep_research/web/static/') for x in records),
                    'Required UI resources absent')
        else:
            prefixes = {'google-search-results':('serpapi/','tests/'), 'langdetect':('langdetect/',),
                        'wikipedia':('wikipedia/',)}
            if name in prefixes:
                require(set(records) == {path for path in source_contract if path.startswith(prefixes[name])},
                        'Source dependency resource set changed')
            elif name == 'jstyleson':
                require(records == ['jstyleson.py'], 'jstyleson source resource set changed')
            require('entry_points.txt' not in metadata_hashes, 'Unexpected source dependency entry point')
    return {'filename': wheel.name, 'size': wheel.stat().st_size, 'sha256': digest(wheel),
            'name': name, 'version': version, 'source_payload_files': len(records),
            'source_payload_matches': True, 'generated_metadata_sha256': metadata_hashes}


def download_verified(file, destination, *, opener, deadline):
    require(Path(file['filename']).name == file['filename'], 'Invalid download filename')
    require(0 < file['size'] < 1024**3 and re.fullmatch(r'[a-f0-9]{64}',file['sha256']), 'Invalid download pin')
    remaining = deadline - time.monotonic()
    require(remaining > 0, 'Download deadline exceeded')
    target, total = destination / file['filename'], 0
    with opener.open(file['url'],timeout=min(30,remaining)) as response, target.open('xb') as stream:
        while data := response.read(1024 * 1024):
            require(time.monotonic() < deadline, 'Download deadline exceeded')
            total += len(data)
            require(total <= file['size'], 'Download exceeds pinned length')
            stream.write(data)
    require(total == file['size'] and digest(target) == file['sha256'], 'Download integrity mismatch')
    return target


def verify_notices(path, contract):
    require(digest(path) == contract['archive_sha256'], 'Notice archive differs')
    if path.name.endswith('.whl'):
        with zipfile.ZipFile(path) as archive:
            for item in contract['embedded_notices']:
                require(0 <= item['size'] <= 4 * 1024**2, 'Notice size exceeds review bounds')
                member = archive.getinfo(item['path'])
                require(member.file_size == item['size'] and hashlib.sha256(archive.read(member)).hexdigest() == item['sha256'],
                        'Embedded notice differs from reviewed manifest')
    else:
        with tarfile.open(path,'r:gz') as archive:
            for item in contract['embedded_notices']:
                require(0 <= item['size'] <= 4 * 1024**2, 'Notice size exceeds review bounds')
                member = archive.getmember(item['path'])
                require(member.isfile() and member.size == item['size']
                        and hashlib.sha256(archive.extractfile(member).read()).hexdigest() == item['sha256'],
                        'Embedded source/interpreter notice differs')


def snapshot(root):
    result = {}
    for base, dirs, names in os.walk(root, followlinks=False):
        for name in dirs + names:
            path = Path(base) / name
            relative = str(path.relative_to(root))
            if path.is_symlink():
                result[relative] = {'symlink': os.readlink(path)}
            elif path.is_file():
                result[relative] = {'sha256': digest(path), 'mode': path.stat().st_mode & 0o777}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--review-receipt', type=Path, required=True)
    args = parser.parse_args()
    root = args.repository.resolve(strict=True)
    receipt = json.loads(args.review_receipt.read_text())
    require(receipt.get('execution_approved') is True and receipt.get('scope') == 'complete-runtime-synthetic-asgi-only',
            'Separate exact full-runtime review has not approved execution')
    require(receipt.get('transport') == 'in-process-ASGI' and receipt.get('network_policy_changed') is False
            and receipt.get('real_http_execution_approved') is False, 'Unexpected ASGI transport or network scope')
    require(receipt.get('torch_selection') == 'distinct-official-PyPI-wheel-explicit-override',
            'Explicit Torch origin selection missing')
    required = {'packaging/engine-ci/runtime_asgi_stage.py', 'packaging/engine-ci/bounded_runtime.py',
        'packaging/engine-ci/runtime_checks.py', 'packaging/engine-ci/smoke_asgi_authenticated.py',
        'packaging/engine-ci/asgi_diagnostics.py', 'packaging/engine-ci/asgi-diagnostic-source-allowlist.json',
        'packaging/engine-ci/seed_fixture.py', 'packaging/engine-ci/runtime-offline.sb',
        'packaging/engine-ci/stage_a.py',
        'packaging/engine-ci/audit_archives.py', 'packaging/engine-ci/check_sqlcipher.py',
        'packaging/engine-ci/runtime-asgi-macos.yml.template', '.github/workflows/engine-runtime-asgi-macos.yml',
        'packaging/engine_entry.py', 'research/engine-ci/all-pypi-input-proposal.json',
        'research/engine-ci/python-candidate.json', 'research/engine-ci/source-build-manifest.json',
        'research/engine-ci/build-requirements.lock', 'research/engine-ci/stage-a-observed-wheel-hashes.json',
        'research/engine-ci/runtime-license-gap-review.json', 'research/engine-ci/runtime-notices-manifest.json',
        'packaging/patches/readonly-themes.patch', 'packaging/patches/managed-ddg-defaults.patch'}
    require(required <= receipt.get('sha256', {}).keys(), 'Incomplete execution review hash set')
    for filename, expected in receipt['sha256'].items():
        relative = PurePosixPath(filename)
        require(not relative.is_absolute() and '..' not in relative.parts, 'Unsafe reviewed path')
        require(digest(root / filename) == expected, 'Reviewed input changed: ' + filename)
    require(digest(root / '.github/workflows/engine-runtime-asgi-macos.yml') ==
            digest(root / 'packaging/engine-ci/runtime-asgi-macos.yml.template'), 'Deployed workflow differs')
    require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'macOS arm64 only')
    require(Path('/usr/bin/sandbox-exec').is_file(), 'Required kernel sandbox absent')
    helpers = root / 'packaging/engine-ci'
    stage_a = load_helper(helpers / 'stage_a.py', 'deepdesk_stage_a_helpers')
    archive = load_helper(helpers / 'audit_archives.py', 'deepdesk_archive_helpers')
    bounded = load_helper(helpers / 'bounded_runtime.py', 'deepdesk_bounded_helpers')
    diagnostics = load_helper(helpers / 'asgi_diagnostics.py', 'deepdesk_diagnostic_helpers')
    proposal = json.loads((root / 'research/engine-ci/all-pypi-input-proposal.json').read_text())
    candidate = json.loads((root / 'research/engine-ci/python-candidate.json').read_text())
    sources = json.loads((root / 'research/engine-ci/source-build-manifest.json').read_text())
    observed = json.loads((root / 'research/engine-ci/stage-a-observed-wheel-hashes.json').read_text())
    notices = json.loads((root / 'research/engine-ci/runtime-notices-manifest.json').read_text())
    notice_contracts = {x['filename']:x for x in notices['archives']}
    require(len(notice_contracts) == 277, 'Incomplete reviewed notice inventory')
    for item in notices['supplementary_files']:
        relative = PurePosixPath(item['local_path'])
        require(not relative.is_absolute() and '..' not in relative.parts, 'Unsafe supplementary notice path')
        require(digest(root / relative) == item['sha256'], 'Supplementary notice changed')
    require(proposal['pdm_lock_sha256'] == digest(root / 'pdm.lock') and proposal['upstream_pdm_lock_modified'] is False,
            'Immutable PDM lock changed')
    require(len(proposal['runtime']) == 268 and len(proposal['build']) == 10, 'Dependency set changed')
    torch = next(x for x in proposal['runtime'] if x['name'] == 'torch')
    require(torch['version'] == '2.14.0' and torch['file']['sha256'] ==
            'c1f844f1c750e87df4b68bc3afbc0e2b0c7ef19d7b8f666e48bdcf6a0c4f0056', 'Unexpected Torch selection')
    unique = {x['file']['filename']: x for x in proposal['runtime'] + proposal['build']}
    require(len(unique) == 276 and sum(x['file']['size'] for x in unique.values()) == 541910864,
            'Download set or exact input size changed')
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='deepdesk-runtime-api-', dir=os.environ.get('RUNNER_TEMP')) as temporary, \
         tempfile.TemporaryDirectory(prefix='deepdesk-control-', dir=os.environ.get('RUNNER_TEMP')) as controls:
        work = Path(temporary).resolve()
        immutable = work / 'immutable'
        downloads, wheels, home = immutable / 'downloads', immutable / 'wheelhouse', work / 'home'
        for path in (downloads, wheels, home):
            path.mkdir(mode=0o700, parents=True)
        require(shutil.disk_usage(work).free >= 16 * 1024**3, 'Need 16 GiB initial free space')
        deadline = started + 20 * 60
        def budget():
            remaining = deadline - time.monotonic()
            require(remaining > 0 and bounded.disk_bytes(work) <= 12 * 1024**3, 'Runtime lane budget exceeded')
            return remaining
        pyarchive = downloads / candidate['filename']
        require(candidate['url'].startswith('https://github.com/astral-sh/python-build-standalone/releases/download/20261009/')
                and candidate['sha256'] == '83dcb04777c798bd95f3687acf9ae84b09860272ee6bdfb05be8bcf9447f75b8',
                'Unexpected official interpreter input')
        download_verified(candidate,downloads,opener=urllib.request.build_opener(stage_a.OfficialPythonRedirect()),deadline=deadline)
        verify_notices(pyarchive,notice_contracts[candidate['filename']])
        for item in sorted(unique.values(), key=lambda x: x['file']['filename']):
            budget()
            origin = urllib.parse.urlsplit(item['file']['url'])
            require(origin.scheme == 'https' and origin.hostname == 'files.pythonhosted.org', 'Unexpected distribution origin')
            path = download_verified(item['file'],downloads,opener=urllib.request.build_opener(archive.PyPIRedirect()),deadline=deadline)
            inspection = archive.inspect_archive(path)
            verify_notices(path,notice_contracts[path.name])
            for pth in inspection['pth']:
                require(item['name'] == 'setuptools' and pth['path'] == 'distutils-precedence.pth'
                        and pth['sha256'] == '2638ce9e2500e572a5e0de7faed6661eb569d1b696fcba07b0dd223da5f5d224',
                        'Unreviewed executable startup file')
            if item['kind'] == 'wheel':
                shutil.copyfile(path, wheels / path.name)
        stage_a.extract_regular_tar(pyarchive, immutable / 'python-root', allow_internal_links=True)
        python = immutable / 'python-root/python/bin/python3.12'
        require(digest(python) == '6e4dac0c7c1761a63c5a603ef56397c8d3d8fa00cf8dd65fb3e6a4476b63af4b',
                'Pinned interpreter mismatch')
        env = {'PATH':'/usr/bin:/bin:/usr/sbin:/sbin', 'HOME':str(home), 'TMPDIR':str(work),
            'PIP_CONFIG_FILE':'/dev/null', 'PIP_NO_INDEX':'1', 'PIP_NO_CACHE_DIR':'1',
            'PIP_DISABLE_PIP_VERSION_CHECK':'1', 'PYTHONNOUSERSITE':'1', 'PYTHONDONTWRITEBYTECODE':'1',
            'SOURCE_DATE_EPOCH':'1791670628', 'HF_HUB_OFFLINE':'1', 'TRANSFORMERS_OFFLINE':'1',
            'HF_HUB_DISABLE_TELEMETRY':'1', 'ANONYMIZED_TELEMETRY':'false',
            'TOKENIZERS_PARALLELISM':'false', 'OMP_NUM_THREADS':'1', 'OPENBLAS_NUM_THREADS':'1',
            'PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD':'1', 'LDR_DATA_DIR':str(work / 'isolated-data')}
        readonly_env = work / 'not-yet-sealed'
        def run(command, *, cwd=work, timeout=180):
            command = ['/usr/bin/sandbox-exec', '-D', 'WORK_DIR=' + str(work),
                '-D', 'IMMUTABLE_DIR=' + str(immutable), '-D', 'READONLY_ENV=' + str(readonly_env),
                '-f', str(helpers / 'runtime-offline.sb'), *map(str, command)]
            return bounded.run_bounded(command, cwd=cwd, env=env, work=work, timeout=min(timeout,budget()))
        netprobe = "import errno,socket\ntry:\n s=socket.socket();s.settimeout(1);r=s.connect_ex(('192.0.2.1',9));s.close()\nexcept OSError as e:\n r=e.errno\nassert r in (errno.EPERM,errno.EACCES),r\n"
        writeprobe = "import errno,sys\ntry:\n open(sys.argv[1],'xb').close()\nexcept OSError as e:\n assert e.errno in (errno.EPERM,errno.EACCES)\nelse:\n raise RuntimeError('Protected write allowed')\n"
        readprobe = "import errno,sys\ntry:\n open(sys.argv[1],'rb').read(1)\nexcept OSError as e:\n assert e.errno in (errno.EPERM,errno.EACCES)\nelse:\n raise RuntimeError('Build-host Homebrew read allowed')\n"
        run([python,'-I','-c',netprobe], timeout=10)
        # Prove the retained deny profile blocks both local TCP operations.
        local_connect_probe = netprobe.replace("'192.0.2.1',9", "'127.0.0.1',54321")
        run([python,'-I','-c',local_connect_probe],timeout=10)
        local_bind_probe = "import errno,socket\ntry:\n s=socket.socket();s.bind(('127.0.0.1',54321));s.close()\nexcept OSError as e:\n assert e.errno in (errno.EPERM,errno.EACCES)\nelse:\n raise RuntimeError('Unexpected local TCP bind allowed')\n"
        run([python,'-I','-c',local_bind_probe],timeout=10)
        # Asyncio may use an internal socketpair; this grants no TCP exception.
        run([python,'-I','-c','import asyncio;asyncio.run(asyncio.sleep(0))'],timeout=10)
        for target in (Path(controls) / 'must-not-create', immutable / 'must-not-create'):
            run([python,'-I','-c',writeprobe,target], timeout=10)
            require(not target.exists(), 'Write-denial probe mutated protected tree')
        brew = Path('/opt/homebrew/bin/git')
        require(brew.exists(), 'Expected Homebrew read-denial probe unavailable')
        run([python,'-I','-c',readprobe,brew], timeout=10)
        build_env = work / 'build-env'
        run([python,'-I','-m','venv',build_env])
        build_python = build_env / 'bin/python'
        run([build_python,'-I','-m','pip','--isolated','install','--no-index','--no-cache-dir',
             '--find-links',wheels,'--require-hashes','--only-binary=:all:',
             '-r',root / 'research/engine-ci/build-requirements.lock'])
        readonly_env = build_env
        run([python,'-I','-c',writeprobe,build_env / 'must-not-create'],timeout=10)
        built_dir = work / 'built-wheels'
        built_dir.mkdir()
        built = []
        for item in proposal['runtime']:
            if item['kind'] != 'reviewed-sdist-candidate':
                continue
            source_root = work / (item['name'] + '-source')
            stage_a.extract_regular_tar(downloads / item['file']['filename'],source_root)
            children = list(source_root.iterdir())
            require(len(children) == 1 and children[0].is_dir(), 'Unexpected source layout')
            source_contract = snapshot(children[0])
            run([build_python,'-I','-m','build','--wheel','--no-isolation','--outdir',built_dir,children[0]])
            wheel = built_dir / (item['name'].replace('-','_') + '-' + item['version'] + '-py3-none-any.whl')
            built.append(validate_built_wheel(wheel,item['name'],item['version'],source_contract))
        staged = work / 'upstream-source'
        staged.mkdir()
        for item in sources['files']:
            relative = PurePosixPath(item['path'])
            require(not relative.is_absolute() and '..' not in relative.parts, 'Unsafe source manifest path')
            source = root / ('docs/upstream/README.md' if item['path'] == 'README.md' else item['path'])
            require(digest(source) == item['sha256'] and source.stat().st_size == item['size'], 'Source input differs')
            destination = staged / item['path']
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source,destination)
        for patch in ('readonly-themes.patch','managed-ddg-defaults.patch'):
            run(['/usr/bin/patch','--batch','--forward','-p1','-i',root / 'packaging/patches' / patch],cwd=staged)
        require(tomllib.loads((staged / 'pyproject.toml').read_text())['project']['scripts'] ==
                {'ldr-web':'local_deep_research.web.app:main','ldr-mcp':'local_deep_research.mcp:run_server'},
                'Reviewed upstream console-script declarations changed')
        source_contract = snapshot(staged)
        run([build_python,'-I','-m','build','--wheel','--no-isolation','--outdir',built_dir,staged])
        appwheel = built_dir / 'local_deep_research-1.10.7-py3-none-any.whl'
        built.append(validate_built_wheel(appwheel,'local-deep-research','1.10.7',source_contract,app=True))
        require(len(list(built_dir.iterdir())) == 5, 'Unexpected build output files')
        prior = {x['filename']:x['sha256'] for x in observed['built_wheels']}
        for item in built:
            item['matches_stage_a_archive_hash'] = item['sha256'] == prior[item['filename']]
            shutil.copyfile(built_dir / item['filename'],wheels / item['filename'])
        # Installation hashes are frozen from inspected build outputs, not guessed
        # from sdist hashes. A previous archive mismatch is reported, never hidden.
        runtime_items = list(proposal['runtime']) + [{'name':'local-deep-research','version':'1.10.7','extras':[]}]
        generated = {x['name']:x for x in built}
        lock = immutable / 'runtime-requirements.lock'
        lock.write_text('# Same-run inspected source-wheel outputs; no URL or floating dependency.\n' + '\n'.join(
            item['name'] + ('[' + ','.join(item.get('extras',[])) + ']' if item.get('extras') else '') +
            '==' + item['version'] + ' --hash=sha256:' +
            (generated[item['name']]['sha256'] if item['name'] in generated else item['file']['sha256'])
            for item in sorted(runtime_items,key=lambda x:x['name'])) + '\n')
        expected = {item['name']:item['version'] for item in runtime_items + proposal['build']}
        require(len(expected) == 277 and len(list(wheels.glob('*.whl'))) == 277, 'Complete wheelhouse identity set differs')
        expected_path = immutable / 'installed-identity-contract.json'
        expected_path.write_text(json.dumps(expected,sort_keys=True))
        readonly_env = work / 'not-yet-sealed'
        runtime_env = work / 'runtime-env'
        run([python,'-I','-m','venv',runtime_env])
        runtime_python = runtime_env / 'bin/python'
        run([runtime_python,'-I','-m','pip','--isolated','install','--no-index','--no-cache-dir',
            '--find-links',wheels,'--require-hashes','--only-binary=:all:',
            '-r',root / 'research/engine-ci/build-requirements.lock','-r',lock],timeout=360)
        readonly_env = runtime_env
        run([python,'-I','-c',writeprobe,runtime_env / 'must-not-create'],timeout=10)
        run([runtime_python,'-I','-m','pip','--isolated','check'])
        immutable_before, runtime_before = snapshot(immutable), snapshot(runtime_env)
        checks = json.loads(run([runtime_python,'-I',helpers / 'runtime_checks.py',
                                '--identity-contract',expected_path,'--wrapper',root / 'packaging/engine_entry.py'],timeout=180))
        require(checks.get('status') == 'passed' and checks.get('torch_version') == '2.14.0'
                and checks.get('model_loaded') is False, 'Runtime check result mismatch')
        cipher = json.loads(run([runtime_python,'-I',helpers / 'check_sqlcipher.py']))
        require(cipher.get('checks') == ['encrypted-header','correct-key-reopen','wrong-key-refused','ordinary-sqlite-refused'],
                'SQLCipher result mismatch')
        # The same kernel network denial remains active for the in-process ASGI
        # fixture. No numeric-IP/localhost profile or TCP listener is used.
        api = json.loads(run([python,'-I',helpers / 'smoke_asgi_authenticated.py',
            '--engine',root / 'packaging/engine_entry.py','--runtime-python',runtime_python,
            '--offline-profile',helpers / 'runtime-offline.sb',
            '--fixture-root',work / 'fixture','--immutable-root',immutable],timeout=360))
        if api.get('status') == 'failed':
            print(json.dumps(diagnostics.validate(api),sort_keys=True))
            raise RuntimeError('In-process ASGI fixture failed; see fixed diagnostic fields only')
        require(api.get('status') == 'passed' and api.get('kind') == 'installed-authenticated-synthetic-ASGI'
                and api.get('transport') == 'in-process-ASGI' and api.get('client_backend') == 'httpx2-2.13.1'
                and api.get('real_http_tested') is False
                and api.get('tcp_listener_tested') is False and api.get('owned_listener_identity_tested') is False
                and api.get('native_transport_tested') is False
                and api.get('fresh_process_database_reopen') is True and api.get('lifespan_completed_twice') is True
                and api.get('research_execution_tested') is False and api.get('model_loaded') is False
                and api.get('provider_queried') is False, 'Synthetic ASGI result mismatch')
        require(snapshot(immutable) == immutable_before and snapshot(runtime_env) == runtime_before,
                'Installed runtime or immutable inputs changed during tests')
        print(json.dumps({'status':'passed','scope':'complete-runtime-synthetic-asgi-only',
            'python':'3.12.15','installed_identity_count':277,'built_wheels':built,
            'runtime_lock_sha256':digest(lock),'torch_origin':'explicit-official-PyPI-override',
            'torch_version':checks['torch_version'],'sqlcipher_checks':cipher['checks'],'api_checks':api['checks'],
            'model_loaded':False,'provider_queried':False,'research_execution_tested':False,
            'standalone_bundle_created':False,'pdf_tested':False,'libmagic_tested':False,
            'native_bundle_tested':False,'artifact_uploaded':False,
            'transport':'in-process-ASGI','client_backend':'httpx2-2.13.1','real_http_tested':False,'tcp_listener_tested':False,
            'owned_listener_identity_tested':False,'native_transport_tested':False,
            'fresh_process_database_reopen':True,'lifespan_completed_twice':True,
            'network_checks':['external-connect-denied','fixture-connect-denied','fixture-bind-denied',
                              'asyncio-internal-event-loop']},sort_keys=True))


if __name__ == '__main__':
    main()

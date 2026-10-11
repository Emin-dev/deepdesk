"""Approval-closed libmagic source pilot with one exact reviewed source overlay. No activation/import side effects.
Source execution is possible only after the exact receipt and deployed workflow pass.
"""
from __future__ import annotations
import argparse
import contextlib
import difflib
import io
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import resource
import shutil
import stat
import sys
import tarfile
import tempfile
import time
import urllib.request

sys.dont_write_bytecode = True
SCOPE = 'libmagic-source-nofork-patched-synthetic-pilot-v2'
SOURCE_SCOPE = 'libmagic-source-synthetic-mime-pilot-only'
OVERLAY_BEFORE_SHA = 'f174166d37224e093cadfdde70efc9b2d467c22f99709349782df392157f789a'
OVERLAY_AFTER_SHA = 'f7b5bb8420a17d9b6cd14983adf20f77a2bbf0f9704ecc8ccda68f0b302d62eb'
OVERLAY_PATCH_SHA = 'cd8e4f541ca74e3018a2b14bd2797cf1faf33f1cfd066435ed65eb47353489d7'
SOURCE_URL = 'https://astron.com/pub/file/file-5.48.tar.gz'
SOURCE_SHA = 'ed14656883b23a364b4057c05595d93252da9bc473d30106519519d0da141283'
SOURCE_SIZE = 2693209
EXPANDED_SIZE = 5966778
BOUNDED_SHA = 'a94a58ba7e45f203fafd4d4d7a0d60ec91cd8366ac7ae8d55909c7d8b1d128f4'
NAMES = {'stage.py','bounded_runtime.py','offline.sb','sdk_codec_preflight.c','smoke_fixture.c',
         'synthetic_fixtures.h','source-pin.json','source-members.json','test_helpers.py',
         'libmagic-source-macos.yml.template','README.md','source-overlay.json','compress-nofork.patch','smoke-no-exec.sb'}
MACROS = ('ZLIBSUPPORT','BZLIBSUPPORT','XZLIBSUPPORT','ZSTDLIBSUPPORT','LZLIBSUPPORT',
          'LRZIPLIBSUPPORT','HAVE_POSIX_SPAWNP','HAVE_FORK')
EXPECTED_FIXTURES = {'fixture_pass=plain:text/plain','fixture_pass=pdf:application/pdf',
    'fixture_pass=png:image/png','fixture_pass=gzip_text_no_external_helper:text/plain',
    'fixture_pass=bzip2_text_no_external_helper:text/plain','fixture_pass=missing_database_rejected',
    'fixture_pass=external_compress_helper_rejected:application/x-decompression-error-gzip-Fork-is-required-to-uncompress--but-disabled'}
DISK_LIMIT = 1024**3
FAILURE_CATEGORIES = {
    'Bounded subprocess failed; raw output withheld':'nonzero_exit',
    'Bounded subprocess timed out':'timeout',
    'No subprocess time budget remains':'timeout',
    'Private output limit exceeded':'output_limit',
    'Bounded working-set limit exceeded':'work_limit',
    'Bounded working-set limit exceeded at completion':'work_limit',
}
REVIEWED_PHASES = frozenset({
    'external-network-denied','local-connect-denied','local-bind-denied',
    'outside-write-denied','immutable-write-denied','work-write-allowed','homebrew-read-denied',
    'sdk-path','compiler-path','compiler-version','os-version',
    'codec-preflight-compile','codec-preflight-loads','codec-preflight-run',
    'configure','make-all','install-staged-prefix','smoke-compile','smoke-external-exec-denied',
    'synthetic-mime-codec-database-and-external-rejection',
} | {kind+'-'+name for kind in ('arm64','loads','commands')
     for name in ('libmagic.1.dylib','smoke-fixture','file')})


def require(ok, message):
    if not ok:
        raise RuntimeError(message)



def run_private_step(bounded, command, *, phase, **kwargs):
    require(phase in REVIEWED_PHASES, 'Unreviewed pilot phase')
    capture = io.StringIO()
    try:
        with contextlib.redirect_stdout(capture):
            output = bounded.run_bounded(command, **kwargs)
    except Exception as error:
        category = (FAILURE_CATEGORIES.get(error.args[0], 'unknown')
                    if type(error) is RuntimeError and len(error.args) == 1
                    and type(error.args[0]) is str else 'unknown')
        print(json.dumps({'pilot_step':phase,'failure_category':category}),flush=True)
        raise RuntimeError('Bounded pilot phase failed; details withheld') from None
    return output, capture.getvalue()


def digest(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'Missing or linked input')
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024**2), b''):
            h.update(chunk)
    return h.hexdigest()


def safe_relative(value):
    p = PurePosixPath(value)
    require(bool(value) and not p.is_absolute() and '..' not in p.parts and '\\' not in value
            and '\x00' not in value and all(part not in ('','.','..') for part in value.split('/')), 'Unsafe relative path')
    return p


def validate_receipt(receipt, helpers, root, *, deployed=True):
    require(receipt.get('execution_approved') is True and receipt.get('scope') == SCOPE,
            'Execution approval is closed or scope differs')
    require(receipt.get('source_sha256') == SOURCE_SHA and receipt.get('source_changes_allowed') == 'exact-reviewed-compress-nofork-overlay-only',
            'Source contract differs')
    require(receipt.get('source_overlay_approved') is True and receipt.get('source_overlay_before_sha256') == OVERLAY_BEFORE_SHA
            and receipt.get('source_overlay_after_sha256') == OVERLAY_AFTER_SHA
            and receipt.get('source_overlay_patch_sha256') == OVERLAY_PATCH_SHA, 'Exact source overlay approval is closed or differs')
    require(receipt.get('destination_branch') == 'engine-libmagic-source-v2-ci', 'Destination differs')
    require(receipt.get('temporary_linker_adhoc_signing_approved') is True and
            receipt.get('install_name_linker_assignment_approved') is True and
            receipt.get('explicit_codesign_allowed') is False, 'Temporary linker effects not separately approved')
    require(set(receipt.get('sha256', {})) == NAMES, 'Exact review set differs')
    for name, sha in receipt['sha256'].items():
        require(re.fullmatch(r'[0-9a-f]{64}', sha) and digest(helpers / name) == sha,
                'Reviewed candidate input differs: ' + name)
    require(digest(helpers / 'bounded_runtime.py') == BOUNDED_SHA, 'Reviewed bounds helper differs')
    if deployed:
        require(digest(root / '.github/workflows/engine-libmagic-source-v2-macos.yml') ==
                digest(helpers / 'libmagic-source-macos.yml.template'), 'Active workflow differs')


def validate_pin(pin, members_path):
    require(pin.get('url') == SOURCE_URL and pin.get('sha256') == SOURCE_SHA
            and pin.get('size') == SOURCE_SIZE and pin.get('expanded_bytes') == EXPANDED_SIZE
            and pin.get('version') == '5.48' and pin.get('members') == 655
            and pin.get('source_changes_allowed') is False and pin.get('scope') == SOURCE_SCOPE,
            'Exact source pin differs')
    require(digest(members_path) == pin.get('source_members_sha256'), 'Source member contract differs')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('Unexpected source redirect; no alternate route allowed')


def download(target, deadline, opener=None):
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    remaining = deadline - time.monotonic()
    require(remaining > 0, 'No download budget')
    total = 0
    request = urllib.request.Request(SOURCE_URL, headers={'User-Agent':'Deepdesk-Libmagic-Source-Pilot/1.0'})
    with opener.open(request, timeout=min(30, remaining)) as response, Path(target).open('xb') as f:
        require(response.status == 200 and response.geturl() == SOURCE_URL, 'Unexpected source response')
        declared = response.headers.get('Content-Length')
        require(declared is None or declared == str(SOURCE_SIZE), 'Unexpected source Content-Length')
        while True:
            require(time.monotonic() < deadline, 'Source download timeout')
            chunk = response.read(65536)
            if not chunk:
                break
            total += len(chunk)
            require(total <= SOURCE_SIZE, 'Source exceeds pinned length')
            f.write(chunk)
    require(total == SOURCE_SIZE and digest(target) == SOURCE_SHA, 'Source integrity mismatch')


def extract_exact(archive, destination, contract):
    require(digest(archive) == SOURCE_SHA and contract.get('archive_sha256') == SOURCE_SHA,
            'Source archive differs')
    records = contract.get('members', [])
    expected = {r['path']:r for r in records}
    require(len(records) == len(expected) == 655 and contract.get('expanded_bytes') == EXPANDED_SIZE,
            'Source member set differs')
    destination.mkdir(mode=0o700)
    seen, total, directories = set(), 0, []
    with tarfile.open(archive, 'r:gz') as t:
        for m in t:
            relative = safe_relative(m.name.rstrip('/'))
            require(relative.parts[0] == 'file-5.48' and m.name not in seen, 'Source root/duplicate differs')
            require(m.name in expected and (m.isfile() or m.isdir()), 'Unreviewed or linked source member')
            r = expected[m.name]
            require(m.size == r['size'] and m.mode == r['mode'] and m.mtime == r['mtime']
                    and ('directory' if m.isdir() else 'file') == r['type'], 'Source metadata differs')
            seen.add(m.name); total += m.size
            require(total <= EXPANDED_SIZE and m.size <= 2*1024**2, 'Source expansion differs')
            target = destination.joinpath(*relative.parts)
            if m.isdir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True); directories.append((target,m))
            else:
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                data = t.extractfile(m).read(m.size+1)
                require(len(data) == m.size and hashlib.sha256(data).hexdigest() == r['sha256'], 'Source member changed')
                with target.open('xb') as f:
                    f.write(data)
                os.chmod(target, m.mode & 0o777)
                os.utime(target, (m.mtime,m.mtime))
    require(seen == set(expected) and total == EXPANDED_SIZE, 'Incomplete exact source')
    for target,m in reversed(directories):
        os.chmod(target, m.mode & 0o777); os.utime(target,(m.mtime,m.mtime))
    return destination / 'file-5.48'



def overlay_inventory(source):
    result = {}
    for p in [source, *sorted(source.rglob('*'))]:
        require(not p.is_symlink(), 'Source overlay linked member')
        rel = 'file-5.48' + ('/' + p.relative_to(source).as_posix() if p != source else '')
        st = p.stat()
        require(p.is_file() or p.is_dir(), 'Source overlay special member')
        item = {'path':rel,'type':'file' if p.is_file() else 'directory','size':st.st_size if p.is_file() else 0,
                'mode':st.st_mode & 0o777,'mtime':int(st.st_mtime)}
        if p.is_file(): item['sha256'] = digest(p)
        result[rel] = item
    return result


def overlay_expected(contract):
    rows = contract.get('members', [])
    result = {r['path'].rstrip('/'):r for r in rows}
    require(len(result) == len(rows), 'Duplicate source overlay member')
    return {name:dict(row,path=name) for name,row in result.items()}


def patched_source_bytes(original, overlay, patch):
    require(overlay.get('schema') == 1 and overlay.get('scope') == 'exact-single-compress-nofork-guard-move'
            and overlay.get('archive_sha256') == SOURCE_SHA and overlay.get('member') == 'file-5.48/src/compress.c'
            and overlay.get('relative_path') == 'src/compress.c' and overlay.get('changed_members_allowed') == 1
            and overlay.get('patch_filename') == 'compress-nofork.patch' and overlay.get('source_license_notice_retained') is True,
            'Source overlay scope differs')
    require(overlay.get('before_sha256') == OVERLAY_BEFORE_SHA and hashlib.sha256(original).hexdigest() == OVERLAY_BEFORE_SHA
            and len(original) == overlay.get('before_size'), 'Source overlay before bytes differ')
    require(overlay.get('after_sha256') == OVERLAY_AFTER_SHA and overlay.get('patch_sha256') == OVERLAY_PATCH_SHA
            and hashlib.sha256(patch).hexdigest() == OVERLAY_PATCH_SHA, 'Source overlay patch contract differs')
    before = overlay['before_block'].encode(); after = overlay['after_block'].encode()
    require(before and after and original.count(before) == 1 and original.count(after) == 0, 'Source overlay block cardinality differs')
    modified = original.replace(before,after,1)
    require(hashlib.sha256(modified).hexdigest() == OVERLAY_AFTER_SHA and len(modified) == overlay.get('after_size'),
            'Source overlay after bytes differ')
    canonical_patch = ''.join(difflib.unified_diff(original.decode().splitlines(keepends=True),
        modified.decode().splitlines(keepends=True),fromfile='a/src/compress.c',tofile='b/src/compress.c')).encode()
    require(patch == canonical_patch, 'Source overlay patch text differs')
    return modified


def apply_overlay(source, contract, overlay, patch_path):
    before = overlay_inventory(source); expected = overlay_expected(contract)
    require(before == expected, 'Source overlay input tree differs from original archive')
    target = source / 'src/compress.c'
    modified = patched_source_bytes(target.read_bytes(),overlay,patch_path.read_bytes())
    metadata = target.stat()
    with target.open('wb') as stream: stream.write(modified)
    os.chmod(target,metadata.st_mode & 0o777)
    os.utime(target,ns=(metadata.st_atime_ns,metadata.st_mtime_ns))
    expected_after = {name:dict(row) for name,row in expected.items()}
    expected_after['file-5.48/src/compress.c'].update(size=len(modified),sha256=OVERLAY_AFTER_SHA)
    after = overlay_inventory(source)
    require(after == expected_after and [name for name in before if before[name] != after[name]] == ['file-5.48/src/compress.c'],
            'Source overlay changed undeclared members or metadata')
    return {'archive_sha256':SOURCE_SHA,'patch_sha256':OVERLAY_PATCH_SHA,'member':'file-5.48/src/compress.c',
            'before_sha256':OVERLAY_BEFORE_SHA,'after_sha256':OVERLAY_AFTER_SHA,'changed_members':1,'original_manifest_verified':True,
            'all_other_members_and_metadata_unchanged':True}


def snapshot(root):
    result = {}
    root = Path(root).resolve()
    for path in sorted(root.rglob('*')):
        rel = str(path.relative_to(root))
        if path.is_symlink():
            require(path.resolve().is_relative_to(root), 'Staged symlink escapes prefix')
            result[rel] = {'link':os.readlink(path)}
        elif path.is_file():
            result[rel] = {'size':path.stat().st_size,'sha256':digest(path)}
        elif path.is_dir():
            continue
        else:
            raise RuntimeError('Unexpected staged special member')
    return result


def capabilities(text):
    values = {name: bool(re.search(r'^#define '+name+r' 1$',text,re.M)) for name in MACROS}
    require(values['ZLIBSUPPORT'] and values['BZLIBSUPPORT'], 'Required builtin codec missing')
    return values


def apple_path(path):
    return path.startswith(('/usr/lib/','/System/Library/')) and '..' not in PurePosixPath(path).parts


def parse_otool_loads(text):
    values = []
    for line in text.splitlines()[1:]:
        if line.startswith('\t'):
            value = line.strip().split(' (compatibility version',1)[0]
            require(bool(value) and value.startswith('/') and '..' not in PurePosixPath(value).parts,
                    'Unreviewed relative/loader load command')
            values.append(value)
    require(values, 'No native load commands observed')
    return values


def validate_loads(loads, prefix, allow_prefix):
    for value in loads:
        if apple_path(value):
            continue
        p = Path(value)
        require(allow_prefix and p.is_file() and p.resolve().is_relative_to(prefix.resolve()),
                'Undeclared native load dependency')


def validate_smoke(text, prefix, executable):
    lines = text.splitlines()
    require(set(line for line in lines if line.startswith('fixture_pass=')) == EXPECTED_FIXTURES
            and len([x for x in lines if x.startswith('fixture_pass=')]) == 7
            and lines.count('pilot_patched_build_mime_two_codecs_and_external_rejection_passed') == 1,
            'Synthetic fixture result differs')
    require(all(line in EXPECTED_FIXTURES or line == 'pilot_patched_build_mime_two_codecs_and_external_rejection_passed'
                or line.startswith('loaded_image=') for line in lines), 'Unexpected fixture output')
    images = [line[len('loaded_image='):] for line in lines if line.startswith('loaded_image=')]
    require(images and len(images) < 500, 'Runtime loaded-image inventory missing/oversize')
    for value in images:
        if apple_path(value):
            continue
        p = Path(value)
        require(p.is_file() and (p.resolve() == executable.resolve() or p.resolve().is_relative_to(prefix.resolve())),
                'Runtime image outside exact staged closure')
    require(any(Path(x).name.startswith('libmagic.') for x in images), 'Loaded libmagic absent')
    return images


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--review-receipt', type=Path, required=True)
    args = parser.parse_args()
    root = args.repository.resolve(strict=True)
    helpers = root / 'packaging/libmagic-source-candidate-v2'
    receipt_path = args.review_receipt if args.review_receipt.is_absolute() else root / args.review_receipt
    require(receipt_path.resolve() == helpers / 'review-receipt.json' and not receipt_path.is_symlink(), 'Receipt location differs')
    receipt = json.loads(receipt_path.read_text())
    validate_receipt(receipt,helpers,root)
    require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'Native macOS arm64 only')
    require(os.environ.get('GITHUB_REPOSITORY') == 'Emin-dev/deepdesk' and
            os.environ.get('GITHUB_REF') == 'refs/heads/engine-libmagic-source-v2-ci', 'CI destination guard failed')
    event_path = Path(os.environ.get('GITHUB_EVENT_PATH',''))
    require(event_path.is_file() and event_path.stat().st_size < 2*1024**2, 'CI event metadata missing')
    event = json.loads(event_path.read_text())
    require(event.get('repository',{}).get('private') is False and
            event.get('repository',{}).get('full_name') == 'Emin-dev/deepdesk', 'Public repository guard failed')
    require(Path('/usr/bin/sandbox-exec').is_file(), 'Sandbox unavailable')
    require(sys.version_info >= (3,9) and not str(Path(sys.executable).resolve()).startswith(
        ('/opt/homebrew/','/opt/local/','/usr/local/','/Library/Frameworks/Python.framework/')), 'Unreviewed host Python')
    spec = importlib.util.spec_from_file_location('libmagic_exact_bounds', helpers / 'bounded_runtime.py')
    bounded = importlib.util.module_from_spec(spec); spec.loader.exec_module(bounded)
    pin = json.loads((helpers / 'source-pin.json').read_text()); validate_pin(pin,helpers/'source-members.json')
    members = json.loads((helpers/'source-members.json').read_text())
    started = time.monotonic(); deadline = started + 540
    with tempfile.TemporaryDirectory(prefix='deepdesk-libmagic-',dir=os.environ.get('RUNNER_TEMP')) as td, \
         tempfile.TemporaryDirectory(prefix='deepdesk-libmagic-control-',dir=os.environ.get('RUNNER_TEMP')) as ctl:
        work = Path(td).resolve(); controls = Path(ctl).resolve()
        require(not re.search(r'\s',str(work)) and shutil.disk_usage(work).free >= 2*1024**3, 'Work preflight failed')
        immutable = work/'immutable'; immutable.mkdir(mode=0o700)
        home = work/'home'; home.mkdir(mode=0o700); tmp=work/'tmp'; tmp.mkdir(mode=0o700)
        build=work/'build';build.mkdir();prefix=work/'install'
        env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','HOME':str(home),'TMPDIR':str(tmp),
             'LC_ALL':'C','LANG':'C','TZ':'UTC','SOURCE_DATE_EPOCH':'0',
             'PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1','MACOSX_DEPLOYMENT_TARGET':'26.0'}
        steps=[]; output_total=0
        def run(command, *, name, cwd=work, timeout=30, sandbox=True, smoke_exec=None):
            nonlocal output_total
            remaining=deadline-time.monotonic(); require(remaining>0,'Pilot total deadline exceeded')
            if sandbox:
                command=['/usr/bin/sandbox-exec','-D','WORK_DIR='+str(work),'-D','IMMUTABLE_DIR='+str(immutable),
                         *(['-D','FIXTURE_PATH='+str(smoke_exec)] if smoke_exec else []),
                         '-f',str(helpers/('smoke-no-exec.sb' if smoke_exec else 'offline.sb')),*map(str,command)]
            before=time.monotonic()
            output,private_summary=run_private_step(bounded,command,phase=name,cwd=cwd,env=env,work=work,
                timeout=min(timeout,remaining),disk_limit=DISK_LIMIT,output_limit=2*1024**2,public_summary=True)
            summary=json.loads(private_summary)
            require(summary.get('bounded_step')=='passed' and summary.get('stdout_bytes')==len(output),
                    'Bounds summary differs')
            output_total+=summary['stdout_bytes']+summary['stderr_bytes']
            require(output_total<=8*1024**2,'Aggregate private output cap')
            steps.append({'name':name,'seconds':round(time.monotonic()-before,3),
                          'stdout_bytes':summary['stdout_bytes'],'stdout_sha256':summary['stdout_sha256'],
                          'stderr_bytes':summary['stderr_bytes'],'stderr_sha256':summary['stderr_sha256']})
            print(json.dumps({'pilot_step':name,'status':'passed','seconds':steps[-1]['seconds']}),flush=True)
            return output
        # First-party sandbox canaries, before any input download/package execution.
        py=Path(sys.executable).resolve()
        net="import errno,socket\ntry:\n s=socket.socket(); s.settimeout(1)\n r=s.connect_ex(('192.0.2.1',9))\nexcept OSError as e:\n r=e.errno\nassert r in (errno.EPERM,errno.EACCES),r\n"
        run([py,'-I','-c',net],name='external-network-denied',timeout=10)
        run([py,'-I','-c',net.replace("'192.0.2.1',9","'127.0.0.1',54321")],name='local-connect-denied',timeout=10)
        bind="import errno,socket\ntry:\n s=socket.socket();s.bind(('127.0.0.1',0))\nexcept OSError as e:\n assert e.errno in (errno.EPERM,errno.EACCES)\nelse:\n raise RuntimeError('Bind allowed')\n"
        run([py,'-I','-c',bind],name='local-bind-denied',timeout=10)
        probe="import errno,sys\ntry:\n open(sys.argv[1],'xb').close()\nexcept OSError as e:\n assert e.errno in (errno.EPERM,errno.EACCES)\nelse:\n raise RuntimeError('Protected write allowed')\n"
        for name,target in [('outside-write-denied',controls/'no-write'),('immutable-write-denied',immutable/'no-write')]:
            run([py,'-I','-c',probe,target],name=name,timeout=10);require(not target.exists(),'Write canary mutated target')
        run([py,'-I','-c',"import pathlib,sys;pathlib.Path(sys.argv[1]).write_text('synthetic')",work/'canary'],name='work-write-allowed',timeout=10)
        brew=Path('/opt/homebrew/bin/git');require(brew.is_file(),'Read-denial canary target missing')
        readprobe="import errno,sys\ntry:\n open(sys.argv[1],'rb').read(1)\nexcept OSError as e:\n assert e.errno in (errno.EPERM,errno.EACCES)\nelse:\n raise RuntimeError('Homebrew read allowed')\n"
        run([py,'-I','-c',readprobe,brew],name='homebrew-read-denied',timeout=10)
        sdk=run(['/usr/bin/xcrun','--sdk','macosx','--show-sdk-path'],name='sdk-path').decode().strip()
        clang=run(['/usr/bin/xcrun','--sdk','macosx','--find','clang'],name='compiler-path').decode().strip()
        for value in (sdk,clang):
            require(value.startswith(('/Applications/','/Library/Developer/','/usr/bin/')) and not re.search(r'\s',value)
                    and Path(value).exists(), 'Unexpected Apple toolchain path')
        compiler=run([clang,'--version'],name='compiler-version').decode();os_version=run(['/usr/bin/sw_vers'],name='os-version').decode()
        env.update({'CC':clang,'CFLAGS':'-arch arm64 -isysroot '+sdk+' -O2','CPPFLAGS':'-isysroot '+sdk,
                    'LDFLAGS':'-arch arm64 -isysroot '+sdk,'SDKROOT':sdk})
        preflight=work/'sdk-codec-preflight'
        run([clang,'-arch','arm64','-isysroot',sdk,helpers/'sdk_codec_preflight.c','-lz','-lbz2','-o',preflight],name='codec-preflight-compile')
        preloads=parse_otool_loads(run(['/usr/bin/otool','-L',preflight],name='codec-preflight-loads').decode())
        validate_loads(preloads,prefix,False)
        require(any('/libz.' in p for p in preloads) and any('/libbz2.' in p for p in preloads),'SDK codec load evidence missing')
        codec_versions=run([preflight],name='codec-preflight-run',timeout=10).decode()
        source_archive=immutable/pin['filename'];download(source_archive,min(deadline,time.monotonic()+60))
        source=extract_exact(source_archive,immutable/'source',members)
        overlay=json.loads((helpers/'source-overlay.json').read_text())
        source_provenance=apply_overlay(source,members,overlay,helpers/'compress-nofork.patch')
        before_immutable=snapshot(immutable)
        run(['/bin/sh',source/'configure','--prefix='+str(prefix),'--disable-static','--enable-shared',
             '--enable-zlib','--enable-bzlib'],name='configure',cwd=build,timeout=180)
        caps=capabilities((build/'config.h').read_text())
        run(['/usr/bin/make','-j2'],name='make-all',cwd=build,timeout=240)
        run(['/usr/bin/make','install'],name='install-staged-prefix',cwd=build,timeout=60)
        library=prefix/'lib/libmagic.1.dylib';database=prefix/'share/misc/magic.mgc'
        require(library.is_file() and database.is_file() and database.stat().st_size>0,'Required native/data output missing')
        fixture=work/'smoke-fixture'
        run([clang,'-arch','arm64','-isysroot',sdk,'-I'+str(prefix/'include'),'-I'+str(helpers),
             helpers/'smoke_fixture.c',prefix/'lib/libmagic.dylib','-o',fixture],name='smoke-compile')
        native_records=[]
        for p in [library,fixture,prefix/'bin/file']:
            require(p.is_file(),'Expected native output absent')
            run(['/usr/bin/lipo',p,'-verify_arch','arm64'],name='arm64-'+p.name)
            loads=parse_otool_loads(run(['/usr/bin/otool','-L',p],name='loads-'+p.name).decode())
            validate_loads(loads,prefix,True)
            commands=run(['/usr/bin/otool','-l',p],name='commands-'+p.name).decode()
            require('LC_RPATH' not in commands,'Unexpected native rpath requires review')
            minos=re.findall(r'\bminos ([0-9.]+)',commands)
            require(len(minos)==1 and tuple(int(x) for x in (minos[0]+'.0').split('.')[:3])==(26,0,0),
                    'Native minimum OS differs from exact macOS26 pilot target')
            native_records.append({'path':str(p.relative_to(work)),'sha256':digest(p.resolve()),'loads':loads,
                'load_commands_sha256':hashlib.sha256(commands.encode()).hexdigest(),
                'minimum_os':minos[0],'code_signature_load_command_present':'LC_CODE_SIGNATURE' in commands})
        missing=work/'nonexistent-database.mgc';require(not missing.exists(),'Negative path exists')
        before_stage=snapshot(prefix)
        exec_probe="import errno,subprocess\ntry:\n subprocess.run(['/usr/bin/true'],check=True)\nexcept OSError as e:\n assert e.errno in (errno.EPERM,errno.EACCES)\nelse:\n raise RuntimeError('External exec allowed')\n"
        run([py,'-I','-c',exec_probe],name='smoke-external-exec-denied',timeout=10,smoke_exec=py)
        smoke=run([fixture,library,database,missing],name='synthetic-mime-codec-database-and-external-rejection',timeout=20,smoke_exec=fixture).decode()
        images=validate_smoke(smoke,prefix,fixture)
        require(snapshot(immutable)==before_immutable and snapshot(prefix)==before_stage,'Input/staged bytes changed')
        result={'status':'passed','scope':SCOPE,'source_sha256':SOURCE_SHA,'source_members':655,
            'native_execution':'scoped-source-build-and-synthetic-fixtures','source_changed':True,'source_provenance':source_provenance,'source_patch_scope':'single-nofork-guard-move',
            'compiler_version':compiler.strip(),'sdk':sdk,'os_version':os_version.strip(),'codec_versions':codec_versions.strip(),
            'detected_capabilities':caps,'installed_manifest':before_stage,'native_records':native_records,
            'loaded_images':images,'steps':steps,'total_seconds':round(time.monotonic()-started,3),
            'working_set_bytes':bounded.disk_bytes(work),'max_single_child_rss_bytes':resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
            'tested_fixtures':sorted(EXPECTED_FIXTURES),'external_helper_rejection_fixture_verified':True,'full_decompression_verified':False,'external_helpers_verified':False,
            'full_native_closure_verified':False,'weasyprint_verified':False,'engine_frozen':False,'relocation_verified':False,
            'clean_machine_app_verified':False,'model_loaded':False,'provider_queried':False,'artifact_uploaded':False,
            'temporary_linker_adhoc_signatures_in_scope':True,'explicit_codesign_invoked':False,
            'personal_signing_identity_used':False,'notarization_performed':False}
        serialized=json.dumps(result,sort_keys=True)
        require(len(serialized.encode())<256*1024,'Public result too large')
        print(serialized)


if __name__ == '__main__':
    main()

"""Data-only native/Python integration and output accounting. No payload import."""
from __future__ import annotations
import base64
import contextlib
import csv
import hashlib
import io
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil

CAP = 2 * 1024**2
NATIVE_RELATIVE = 'lib/deepdesk-native/libmagic'
SOURCE_SHA = 'ed14656883b23a364b4057c05595d93252da9bc473d30106519519d0da141283'
WHEEL_SHA = 'c212960ad306f700aa0d01e5d7a325d20548ff97eb9920dcd29513174f0294d3'

NATIVE_REPORT_RESERVE = 4096
NATIVE_PHASES = frozenset({
    'external-network-denied', 'local-connect-denied', 'local-bind-denied',
    'outside-write-denied', 'immutable-write-denied', 'work-write-allowed', 'homebrew-read-denied',
    'sdk-path', 'compiler-path', 'compiler-version', 'os-version', 'codec-preflight-compile',
    'codec-preflight-loads', 'codec-preflight-run', 'configure', 'make-all', 'install-staged-prefix',
    'smoke-compile', 'smoke-external-exec-denied', 'synthetic-mime-codec-database-and-external-rejection',
    'native-controller',
} | {kind + '-' + name for kind in ('arm64', 'loads', 'commands')
     for name in ('libmagic.1.dylib', 'deepdesk-libmagic-smoke', 'file')})
NATIVE_CATEGORIES = frozenset({'nonzero_exit', 'timeout', 'output_limit', 'work_limit', 'unknown', 'contract'})


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def digest(path):
    require(path.is_file() and not path.is_symlink(), 'Missing or linked integration input')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_gate(receipt, root):
    for name in ('execution_approved', 'managed_policy_execution_approved',
                 'libmagic_execution_approved', 'libmagic_source_overlays_approved',
                 'libmagic_binding_overlay_approved', 'libmagic_install_id_assignment_approved',
                 'compiler_linker_adhoc_signature_permitted'):
        require(receipt.get(name) is True, 'Bundled libmagic exact approval is closed')
    require(receipt.get('scope') == 'standalone-relocated-core-checks'
            and receipt.get('libmagic_contract') == 'bundled-file-5.48-358-text-fragments-separate-bindings'
            and receipt.get('libmagic_pilot_commit') == 'c1056e0ffba9793aff99f24d824478f9b1001c8a'
            and receipt.get('base_commit') == '109ce9dc56231f314e5a2fec558514652e20f502'
            and receipt.get('destination_branch') == 'engine-standalone-libmagic-ci'
            and receipt.get('workflow_path') == '.github/workflows/engine-standalone-libmagic-macos.yml'
            and receipt.get('native_features_complete') is False
            and receipt.get('network_policy_changed') is False,
            'Bundled libmagic review scope differs')
    for relative, expected in receipt.get('sha256', {}).items():
        path = PurePosixPath(relative)
        require(not path.is_absolute() and '..' not in path.parts, 'Unsafe integration review path')
        require(digest(root / path) == expected, 'Bundled libmagic reviewed input changed')
    required = {p.relative_to(root).as_posix() for p in
                (root / 'packaging/standalone-engine-candidate').rglob('*')
                if p.is_file() and p != root / 'packaging/standalone-engine-candidate/review-receipt.json'}
    require(required <= receipt.get('sha256', {}).keys(), 'Bundled libmagic review set incomplete')


def apply_configure_overlay(source, contract):
    path = source / 'configure'
    original = path.read_bytes()
    before, after = contract['before_block'].encode(), contract['after_block'].encode()
    require(contract.get('member') == 'file-5.48/configure'
            and contract.get('replacements') == 2
            and before == b'-install_name \\$rpath/\\$soname'
            and after == b'-install_name @rpath/\\$soname'
            and len(original) == contract['before_size']
            and hashlib.sha256(original).hexdigest() == contract['before_sha256']
            and original.count(before) == 2 and original.count(after) == 0,
            'Source configure install-ID input differs')
    modified = original.replace(before, after)
    require(len(modified) == contract['after_size']
            and hashlib.sha256(modified).hexdigest() == contract['after_sha256'],
            'Source configure install-ID output differs')
    metadata = path.stat()
    path.write_bytes(modified)
    os.chmod(path, metadata.st_mode & 0o777)
    os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    return {'member': 'configure', 'before_sha256': contract['before_sha256'],
            'after_sha256': contract['after_sha256'], 'install_id': '@rpath/libmagic.1.dylib'}


def preserve_text_sources(source, prefix, contract, contract_path):
    require(digest(source / 'magic/Makefile.am') == contract['makefile_sha256'],
            'Upstream MAGIC_FRAGMENTS declaration changed')
    rows = contract['fragments']
    require(contract['count'] == len(rows) == len({r['name'] for r in rows}) == 358,
            'Upstream text fragment set differs')
    text = prefix / 'share/misc/magic'
    text.mkdir()
    for row in rows:
        path = PurePosixPath(row['source'])
        require(not path.is_absolute() and '..' not in path.parts
                and path.parts[0] == 'magic' and Path(row['name']).name == row['name'],
                'Unsafe magic text source path')
        original = source / path
        require(digest(original) == row['sha256'] and original.stat().st_size == row['size']
                and original.stat().st_mode & 0o777 == row['mode'], 'Magic text source changed')
        shutil.copy2(original, text / row['name'])
        require(digest(text / row['name']) == row['sha256'], 'Magic text copy differs')
    shutil.copy2(contract_path, prefix / 'share/misc/deepdesk-text-fragments.json')
    notices = prefix / 'share/doc/file-5.48'
    notices.mkdir(parents=True)
    shutil.copy2(source / 'COPYING', notices / 'COPYING')
    require(digest(notices / 'COPYING') == digest(source / 'COPYING'), 'Native license copy differs')
    return {'preserved_text_fragments': 358, 'default_compile_input': 'share/misc/magic',
            'default_load_check_list_input': 'share/misc/magic.mgc'}


def inventory_digest(manifest):
    encoded = json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')
    return hashlib.sha256(encoded).hexdigest()


def verify_tested_install(native, result, *, inventory):
    """Run only after the outer owned process-group cleanup has returned.

    Bind every file/mode/link to the controller's validated final snapshot, and
    bind its audited binary hashes to that same snapshot. This is evidence
    continuity for the local prototype, not a concurrent-host security boundary.
    """
    expected = result.get('validated_install_manifest_sha256')
    require(type(expected) is str and re.fullmatch(r'[0-9a-f]{64}', expected),
            'Validated native installation identity is absent')
    manifest = inventory(native)
    require(inventory_digest(manifest) == expected,
            'Native install changed after controller validation or outer cleanup')
    records = result.get('native_records')
    expected_paths = {'lib/libmagic.1.dylib', 'bin/file', 'libexec/deepdesk-libmagic-smoke'}
    require(type(records) is list and len(records) == len(expected_paths)
            and all(type(row) is dict for row in records)
            and {row.get('path') for row in records} == expected_paths,
            'Validated native audit record set differs')
    entries = {row['path']: row for row in manifest['entries']}
    for record in records:
        entry = entries.get(record['path'], {})
        require(entry.get('kind') == 'file' and entry.get('sha256') == record.get('sha256'),
                'Audited native binary differs from validated complete install')
    return manifest


def integrate(prefix, native, helpers, *, inventory, expected_native_manifest):
    """Preserve the complete install; replace exactly loader.py and its RECORD."""
    before = inventory(prefix)
    original_native = inventory(native)
    require(original_native == expected_native_manifest, 'Native install changed before exact copy')
    destination = prefix / NATIVE_RELATIVE
    require(not destination.exists(), 'Native destination already exists')
    site = prefix / 'lib/python3.12/site-packages'
    contract = json.loads((helpers / 'python-magic-original-members.json').read_text())
    require(contract['wheel_sha256'] == WHEEL_SHA, 'Binding wheel origin differs')
    for name, row in contract['members'].items():
        if name.endswith('/RECORD'):
            continue  # pip regenerates this installation metadata.
        path = site / name
        require(digest(path) == row['sha256'] and path.stat().st_size == row['size'],
                'Installed python-magic source differs from pinned wheel')
    dist = site / 'python_magic-0.4.27.dist-info'
    record = dist / 'RECORD'
    old_record = record.read_bytes()
    record_rows = list(csv.reader(io.StringIO(old_record.decode())))
    names = set()
    for row in record_rows:
        require(len(row) == 3 and row[0] not in names, 'Installed RECORD shape differs')
        relative = PurePosixPath(row[0])
        require(not relative.is_absolute() and '..' not in relative.parts
                and relative.parts[0] in {'magic', dist.name}, 'Installed RECORD path differs')
        path = site / relative
        require(path.is_file() and not path.is_symlink(), 'Installed RECORD file missing')
        if row[0] != dist.name + '/RECORD':
            value = base64.urlsafe_b64encode(hashlib.sha256(path.read_bytes()).digest()).rstrip(b'=').decode()
            require(row[1] == 'sha256=' + value and row[2] == str(path.stat().st_size),
                    'Installed RECORD integrity differs')
        names.add(row[0])
    actual = {p.relative_to(site).as_posix() for root in (site / 'magic', dist)
              for p in root.rglob('*') if p.is_file()}
    require(names == actual, 'Installed binding payload is incomplete or unrecorded')
    loader = site / 'magic/loader.py'
    before_loader = digest(loader)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(native, destination, symlinks=True, copy_function=shutil.copy2)
    require(inventory(native) == original_native == inventory(destination), 'Full native copy differs')
    # This overlay has no import-time effect during integration; bytes only.
    loader.write_bytes((helpers / 'bundled_magic_loader.py').read_bytes())
    provenance = {'schema': 1, 'wheel_sha256': WHEEL_SHA, 'native_source_sha256': SOURCE_SHA,
                  'modified_installed_sources': {'magic/loader.py': {
                      'before_sha256': before_loader, 'after_sha256': digest(loader)}},
                  'record_before_sha256': hashlib.sha256(old_record).hexdigest(),
                  'reason': 'Fixed bundled library and binary/text defaults; separate ctypes proxies; no host lookup',
                  'removed_payloads': []}
    provenance_path = dist / 'deepdesk-overlay.json'
    require(not provenance_path.exists(), 'Overlay provenance already exists')
    provenance_path.write_text(json.dumps(provenance, sort_keys=True, indent=2) + '\n')
    names.add(provenance_path.relative_to(site).as_posix())
    output = io.StringIO(newline='')
    writer = csv.writer(output, lineterminator='\n')
    for name in sorted(names):
        if name == dist.name + '/RECORD':
            writer.writerow([name, '', ''])
        else:
            data = (site / name).read_bytes()
            value = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
            writer.writerow([name, 'sha256=' + value, str(len(data))])
    record.write_text(output.getvalue())
    after = inventory(prefix)
    old_entries = {x['path']: x for x in before['entries']}
    new_entries = {x['path']: x for x in after['entries']}
    changed = {str(loader.relative_to(prefix)), str(record.relative_to(prefix))}
    require(all(name in new_entries and (name in changed or row == new_entries[name])
                for name, row in old_entries.items()), 'An unrelated installed Python payload changed')
    added = set(new_entries) - set(old_entries)
    require(all(name in {'lib/deepdesk-native', str(provenance_path.relative_to(prefix))}
                or name == NATIVE_RELATIVE or name.startswith(NATIVE_RELATIVE + '/') for name in added),
            'Unexpected installed payload addition')
    require(inventory(native) == original_native, 'Original native installation changed')
    return {'overlay_provenance': provenance, 'record_after_sha256': digest(record),
            'original_native_manifest': original_native, 'complete_native_install_preserved': True,
            'all_unmodified_python_payloads_preserved': True}


def measured_result(output, summary):
    """Charge private nested native bytes and actual outer stdout/stderr once."""
    require(summary.get('bounded_step') == 'passed'
            and type(summary.get('stdout_bytes')) is int
            and type(summary.get('stderr_bytes')) is int
            and summary['stdout_bytes'] == len(output) and summary['stderr_bytes'] >= 0,
            'Measured outer summary differs')
    result = json.loads(output)
    if result.get('status') == 'failed':
        require(set(result) == {'status', 'kind', 'phase', 'failure_category',
                               'private_native_output_bytes', 'private_output_measurement'}
                and result.get('kind') == 'bundled-libmagic-native-build'
                and result.get('phase') in NATIVE_PHASES
                and result.get('failure_category') in NATIVE_CATEGORIES
                and result.get('private_native_output_bytes') is None
                and result.get('private_output_measurement') == 'unknown-after-failure',
                'Unreviewed native failure diagnostic')
        # A failed bounded child supplies no measured summary. Its last read may
        # overshoot the monitored threshold by a chunk. Never invent a private
        # count, upper bound, or successful combined-output acceptance for it.
        print(json.dumps({'native_step': result['phase'],
                          'failure_category': result['failure_category']}, sort_keys=True), flush=True)
        raise RuntimeError('Bundled native step failed; fixed diagnostics only') from None

    private = result.get('private_native_output_bytes')
    require(type(private) is int and private >= 0, 'Private native byte count is absent')
    combined = private + summary['stdout_bytes'] + summary['stderr_bytes']
    require(combined <= CAP, 'Combined private native and outer output cap exceeded')
    result['combined_private_and_outer_output_bytes'] = combined
    return result


def run_measured(runner):
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        output = runner()
    result = measured_result(output, json.loads(captured.getvalue()))
    return result

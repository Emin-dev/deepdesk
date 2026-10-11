"""Proposed first-party relocation checks; no CLI or implicit execution path.

A future exact-reviewed stage provides its bounded sandbox runner. This module
never falls back to an unsandboxed subprocess, host Python or network permission.
Synthetic tests inject a fake runner and never execute dependency payloads.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re

EXPECTED_IMPORTS = ['fastapi','starlette','uvicorn','pydantic','sqlalchemy','sqlcipher3',
    'lxml.etree','cryptography','numpy','pandas','pyarrow','torch','faiss',
    'sentence_transformers','weasyprint']
EXPECTED_SCOPE = 'standalone-relocated-engine-native-checks'
CORE_SCOPE = 'standalone-relocated-core-checks'


def require(ok, code):
    if not ok:
        raise ValueError(code)


def manifest_digest(manifest):
    return hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()


def relocate_bundle(source, destination, *, work_root, expected_manifest, inventory):
    """Move only an exact manifested disposable candidate inside a caller work tree."""
    work = Path(work_root)
    require(work.is_absolute() and not work.is_symlink(),'invalid-work-root')
    work = work.resolve(strict=True)
    source, destination = Path(source), Path(destination)
    require(source.is_absolute() and destination.is_absolute(),'absolute-bundle-path-required')
    require(not source.is_symlink() and source.is_dir() and not destination.exists()
            and not destination.is_symlink(),'invalid-relocation-endpoints')
    source = source.resolve(strict=True)
    parent = destination.parent.resolve(strict=True)
    require(source != work and source.is_relative_to(work) and parent.is_relative_to(work)
            and not parent.is_relative_to(source),'relocation-outside-disposable-work')
    require(source.name == 'DeepdeskEngine.app' and destination.name == source.name,
            'unexpected-helper-name')
    require(' ' in str(destination.relative_to(work))
            and any(ord(c) > 127 for c in str(destination.relative_to(work))),
            'relocation-must-cover-space-and-unicode')
    require(inventory(source) == expected_manifest,'source-bundle-manifest-mismatch')
    source.rename(destination)
    require(not source.exists() and not source.is_symlink(),'original-bundle-still-present')
    require(inventory(destination) == expected_manifest,'relocated-bundle-manifest-mismatch')
    return {'status':'passed','kind':'manifest-preserving-relocation',
            'bundle_manifest_sha256':manifest_digest(expected_manifest),
            'native_code_executed':False,'original_location_absent':True}


def validate_self_test(raw, *, core_only=False):
    require(isinstance(raw,bytes) and len(raw) <= 8192,'invalid-self-test-output-size')
    def unique_pairs(pairs):
        out={}
        for key,value in pairs:
            require(key not in out,'duplicate-self-test-field')
            out[key]=value
        return out
    try:
        value=json.loads(raw.decode('utf-8'),object_pairs_hook=unique_pairs)
    except (UnicodeError,json.JSONDecodeError):
        raise ValueError('invalid-self-test-json') from None
    require(isinstance(value,dict) and set(value)=={'status','kind','python','sqlcipher','imported',
                'provider_sources','network_research_tested','authenticated_api_tested'},'invalid-self-test-schema')
    require(value['status']=='passed' and value['kind']==('packaging-core-self-test' if core_only else 'packaging-self-test')
            and value['python']=='3.12.15' and value['imported']==(EXPECTED_IMPORTS[:-1] if core_only else EXPECTED_IMPORTS),'self-test-contract-mismatch')
    require(isinstance(value['sqlcipher'],str) and re.fullmatch(r'[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,2}(?: community)?',value['sqlcipher']),
            'unrecognized-sqlcipher-version-format')
    require(type(value['provider_sources']) is int and 1 <= value['provider_sources'] <= 256,
            'invalid-provider-source-count')
    require(value['network_research_tested'] is False and value['authenticated_api_tested'] is False,
            'unexpected-self-test-claim')
    return value


def checked_self_test(bundle, *, receipt, expected_manifest, inventory, bounded_sandbox_runner, core_only=False):
    """Run only under an explicitly supplied previously-reviewed bounded runner.

    The receipt is one control inside the future stage, not standalone authority.
    That stage must hash-bind its deployed workflow, every control file, source/
    native inputs, assembled payload and sandbox profile, and validate canaries.
    """
    require(isinstance(receipt,dict) and receipt.get('execution_approved') is True
            and receipt.get('scope')==(CORE_SCOPE if core_only else EXPECTED_SCOPE),'standalone-execution-not-approved')
    require(receipt.get('native_input_review_complete') is (False if core_only else True)
            and receipt.get('network_policy')=='deny-all-tcp'
            and receipt.get('original_build_read_denied') is True
            and receipt.get('bundle_write_denied') is True,
            'standalone-native-containment-gate-incomplete')
    require(receipt.get('bundle_manifest_sha256')==manifest_digest(expected_manifest),
            'approved-bundle-manifest-mismatch')
    bundle=Path(bundle).resolve(strict=True)
    require(inventory(bundle)==expected_manifest,'bundle-manifest-changed-before-run')
    executable=bundle/'Contents/MacOS/DeepdeskEngine'
    require(executable.is_file() and not executable.is_symlink(),'missing-helper-executable')
    require(callable(bounded_sandbox_runner),'bounded-runner-required')
    result=validate_self_test(bounded_sandbox_runner([str(executable),'--core-self-test' if core_only else '--self-test'],timeout=180),core_only=core_only)
    require(inventory(bundle)==expected_manifest,'bundle-mutated-during-self-test')
    return {'status':'passed','kind':('relocated-helper-core-self-test' if core_only else 'relocated-helper-self-test'),
            'python':result['python'],'sqlcipher':result['sqlcipher'],'imported':result['imported'],
            'provider_sources':result['provider_sources'],'bundle_unchanged':True,
            'native_features_complete':False,'real_http_tested':False,'models_tested':False,
            'remaining_native_checks':['loaded-image-origins','pdf-render','libmagic-database',
                'pandoc-odt','missing-native-resource-refusal']}

# Approval-closed libmagic source pilot v2

This separate candidate corrects one statically verified file/libmagic 5.48 control-flow defect. Frozen v1 is unchanged and unapproved. V2 has not executed source, compiled its fixtures, or activated CI.

## Exact source and one permitted change

The official archive remains https://astron.com/pub/file/file-5.48.tar.gz, SHA-256 `ed14656883b23a364b4057c05595d93252da9bc473d30106519519d0da141283`, 2,693,209 bytes compressed and 5,966,778 expanded. `source-pin.json` and all 655 records in `source-members.json` are copied unchanged from v1; their original unchanged-source scope describes acquisition and initial materialization only. V2 additionally requires its independently approved overlay. The built source is explicitly modified.

`compress-nofork.patch` moves the existing nofork rejection block from inside the builtin decoder branch to immediately after that branch returns, before the external-helper path. No decoder, optional codec selection, error string or other production source behavior is changed.

- Original `src/compress.c`: `f174166d37224e093cadfdde70efc9b2d467c22f99709349782df392157f789a` (31,086 bytes)
- Patched member: `f7b5bb8420a17d9b6cd14983adf20f77a2bbf0f9704ecc8ccda68f0b302d62eb` (31,082 bytes)
- Exact patch: `cd8e4f541ca74e3018a2b14bd2797cf1faf33f1cfd066435ed65eb47353489d7`

`source-overlay.json` binds the original archive, exact member, before/after hashes and byte blocks, patch hash and one-member limit. First-party code verifies the entire extracted original tree including modes/mtimes, checks the canonical patch text, applies one exact byte replacement, preserves metadata, then verifies only that member's bytes/size changed. The license notice is retained. No patch utility, fuzzy matching or source hook executes. All later source/build processes see an immutable patched source tree. The result records both official input and modified-member provenance; it never calls this an unchanged-source build.

The original defect rejects mandatory builtin gzip/bzip2 decoders when MAGIC_NO_COMPRESS_FORK is set while leaving external helpers unguarded. V2 retains the no-helper flag and exact text/plain expectations. This is a local candidate patch, not an upstream release or upstream-approved change.

## Native fixture and separate execution policies

The original synthetic text, PDF, PNG, gzip, bzip2 and missing-database checks remain. One additional 16-byte deliberately incomplete .Z header begins `1f 9d 90`. Exact source maps it to method 0, which has no builtin decoder regardless of optional codec macros. With COMPRESS_TRANSP and NO_COMPRESS_FORK, the corrected guard must yield exactly `application/x-decompression-error-gzip-Fork-is-required-to-uncompress--but-disabled`, before any pipes/spawn path. This proves refusal of this recognized external-only method, not working .Z decompression or full external-helper closure.

Build/configure legitimately execute compiler tools and generated helpers under `offline.sb`. Native smoke instead uses `smoke-no-exec.sb`, which adds process-exec denial with one exact executable-path allowance for the fixture. The same smoke policy is first canary-tested with only the exact first-party orchestration interpreter allowed; attempted `/usr/bin/true` execution must raise EPERM/EACCES. Missing files, timeouts, successful execution and other errors fail. During actual smoke, only the exact C fixture path is allowed, so a source regression cannot invoke host decompression helpers. This policy restricts executable paths; it does not claim to prohibit fork-without-exec or re-execution of the one allowed path. Its actual Mac behavior remains a fail-closed runtime gate.

The harness verifies libmagic version 548, the exact loaded dylib realpath, explicit matching magic.mgc, all seven fixed results and loaded-image paths. Only compiled-in synthetic bytes are processed. Static output checks require arm64, exact macOS26 minimum target, no unexpected rpath, and Apple/staged load closure. Immutable input and staged-output hashes are checked after smoke.

## Inherited bounds and approvals

The direct unauthenticated source download rejects redirects and alternative sources and is size/hash/deadline checked. Materialization accepts only pinned regular files/directories, with a 2 MiB member cap. No GHCR/token flow, package manager, extra source inputs, models or provider requests are involved. The host Apple `/usr/bin/python3` orchestrates only first-party code/canaries; version >=3.9 and non-Homebrew/MacPorts/usr/local/third-party-Frameworks location are required.

The unchanged bounds helper SHA-256 is `a94a58ba7e45f203fafd4d4d7a0d60ec91cd8366ac7ae8d55909c7d8b1d128f4`. Limits remain a 10-minute workflow, 540-second stage, two compiler workers, 1 GiB monitored work tree, 2 MiB captured output per step and 8 MiB aggregate stdout/stderr. Raw child errors are withheld. Child maximum RSS is reported, not aggregate-enforced; process-session escape and hard disk quotas are not claimed. All native/build children inherit network denial, outside-work and source-tree write denial, and Homebrew/MacPorts/usr/local read denial.

SDK zlib/bzip2 headers, linking and runtime versions are preflighted; configure requires both codecs while preserving all other upstream autodetection. Undeclared linkage blocks success. Default make generates matching magic.mgc with the new file helper; no make check, global install, formula hook or Python package installation runs.

The inactive template targets only public Emin-dev/deepdesk, dedicated `engine-libmagic-source-v2-ci`, standard `macos-26`, exact v2 candidate/workflow push filters and workflow_dispatch. It has read-only contents permission, pinned checkout, no persisted credentials, cache or artifact uploads. The deployed workflow must match the template exactly.

Execution approval, exact source-overlay approval, install-ID assignment approval and temporary implicit linker ad-hoc-signature approval all default false. Darwin libtool assigns install_name and may use dylib_file. No explicit codesign/install_name_tool invocation was found in the retained generated build surfaces. Personal signing identity/keychain use, explicit codesign, notarization and releases are outside scope.

## Verification boundary

Run `python -B -I packaging/libmagic-source-candidate-v2/test_helpers.py` for first-party synthetic helper tests only. Static archive materialization and patch verification do not execute source. Independent review and root GO must precede any approval change or workflow activation; any changed candidate byte requires re-freezing.

Success means only the exact patched-source build, matching database, synthetic MIME, two builtin codec checks and one external-only refusal fixture passed. Full decompression, external helpers, optional codec coverage, relocation, WeasyPrint, complete native closure, engine freeze, clean-machine app and redistribution clearance remain unestablished.


## Publication v3: lipo command-order correction

The first v3 runtime delta is one Python command-vector reorder: `/usr/bin/lipo INPUT -verify_arch arm64`. The prior vector put INPUT after `arm64`; Apple's parser treats all trailing values after `-verify_arch` as architecture names. The architecture requirement remains mandatory, and no binary validation, source input/overlay, fixture expectation, sandbox profile, timeout, output bound or workflow is relaxed.

Primary sources read on 2026-10-11:

- [Apple cctools lipo parser](https://raw.githubusercontent.com/apple-oss-distributions/cctools/main/misc/lipo.c), lines 432–451: computes the number of architecture values from the remaining argument count and validates each remaining argument as an architecture. Lines 467–470 separately recognize input filenames before that terminal option.
- [Apple lipo manual](https://raw.githubusercontent.com/apple-oss-distributions/cctools/main/man/lipo.1), lines 101–109: documents the required file-before-option order and zero/nonzero verification status.

A first-party AST regression pins the single lipo invocation to the exact corrected list and rejects the previous ordering, an alternate architecture, and replacement with a non-verifying inspection command. This source-backed correction has not been run on macOS in the v3 preparation step. The preceding v2 CI report reached configure, make, staged installation and fixture compilation before its first lipo command failed; that is partial build evidence, not completed native/fixture proof.

The v3 receipt is reset closed pending independent exact review and root approval. A second, separately identified small v3 delta wraps the unchanged bounded helper with fixed failure classification. Exact known first-party RuntimeError messages map to nonzero_exit, timeout, output_limit or work_limit. Other exceptions or non-exact messages map to unknown. Only a hardcoded reviewed phase name and fixed category are printed; arbitrary exception text and prior trace context are suppressed, and the step still raises a fixed failure. Successful output, source inputs, sandbox, process cleanup and all runtime assertions remain unchanged. First-party tests cover every mapped message, secret-bearing unknown failures, no leakage from captured helper stdout, rejected unreviewed phase names and failure after the fixed summary. No raw child stderr is exposed.

# Exact gettext input diagnostic, prepared only

This is an inactive, input-only diagnostic for `input-gettext` in PDF prerequisite run
38126636047, job 114432246694. That run failed with `contract_or_input_failure` before
build/native phases; its cause has not been established. The base is
`f52e37049b7d280e53e07013ccd14da3c3ac53d3` on `engine-pdf-foundation-v1-ci`.
The dedicated prospective branch is `engine-pdf-input-diagnostic-ci`.

## Exact scope

The only source archive is GNU gettext 1.0, requested at the original
`https://ftpmirror.gnu.org/gettext/gettext-1.0.tar.gz`, 32,694,085 bytes,
SHA-256 `85d99b79c981a404874c02e0342176cf75c7698e2b51fe41031cf6526d974f1a`.
Only `ftpmirror.gnu.org` and `mirrors.ocf.berkeley.edu` remain allowed. There is
no alternate URL, HEAD probe, retry, mirror choice, proxy, or widened policy.
The unchanged helper may issue the original request plus its existing maximum
three accepted HTTPS redirects. No rejected redirect is followed.

The complete original `archive_tools.py`, `input-lock.json`, and
`members/gettext.json` remain in `packaging/pdf-foundation-candidate` and are
hash-bound by both constants and the closed receipt. They are not modified or
copied into this new package. The exact recovered source remains preserved.
Only the gettext pin is selected; the other five inputs are not fetched.

The diagnostic imports the verified first-party helper and uses its unchanged
`download()` and `extract()` functions. A Python tracing callback observes only
returns from its download/redirect functions. It does not patch urllib, replace
its opener, change TLS verification, mutate accepted inputs, or replace archive
validation. Tests alone substitute a first-party mock transport.

Only downloaded data is written, hashed, parsed, and extracted. There is no
subprocess, build, dependency installation, shell evaluation, or downloaded
Python import. Extracted files may carry the original reviewed archive modes,
but are never executed. PDF runtime, builds, native checks, release readiness,
models, and providers remain unproved regardless of this diagnostic's result.

## Bounds and output

Execution is limited to a public `Emin-dev/deepdesk` macOS 26 arm64 GitHub job on
exactly the diagnostic branch. The job uses standard `macos-26`, three minutes,
read-only repository permission, pinned checkout action, exact event SHA,
no persisted checkout credentials, and an environment stripped to a fixed list.
The event file is inspected only for exact repository identity/public status.
No user secrets are supplied by the workflow. There are no caches or artifacts.

A fresh temporary directory is used. The original 120-second shared input timer,
2 GiB temporary-work ceiling, 4 GiB initial free-space floor, 1 GiB ongoing
free-space floor, and checkpoint-triggered disk scans throttled to two seconds
are preserved. Scans occur before and after download and at extraction
checkpoints; their actual gap can exceed two seconds. Each extraction member
also receives a deadline check. Exact archive/member
sizes and hashes remain enforced by the original helper. Cleanup is attempted
on success and handled failures, with an additional ten-second cleanup timer;
cleanup failure makes the result fail. Forced runner termination can prevent
cleanup and output, as with any process; the runner workspace is ephemeral.

The Python diagnostic emits one JSON object no larger than 4 KiB. The fixed
schema contains status, phase, failure category, numeric original-helper source
line, bounded HTTP status/downloaded byte count, at most four redirect records,
host categories, input-verification booleans, cleanup state, and false runtime
proof gates. Only host categories (`origin`, `allowed_mirror`, `other`,
`missing`, `malformed`, `unobserved`) are logged. No raw URL, redirect target,
response body/header, exception message, traceback, filename, filesystem path,
secret, or downloaded bytes are logged. GitHub's ordinary checkout/workflow
logs are separate from this diagnostic's <=4 KiB result.

Classification covers DNS, TLS/certificate, timeout, HTTP, transport and local
I/O errors; denied redirect count/scheme/host/port/userinfo/fragment or malformed
URL; response status/scheme/host/length; downloaded size/hash; and extraction
contracts/parser failures with an exact original-helper source line. Composite
contract checks retain their original source line rather than guessing which
member field failed. An unknown failure stays a fixed unknown category. An
HTTP redirect rejected by urllib before the helper can be classified from a
sanitized Location scheme, without following it. Unattributable ValueError is
honestly grouped as `network_url_or_value_error`.

## Closed preparation and separate activation

`review-receipt.json` binds every package file except itself, the three unchanged
original files, and the exact matching workflow/template bytes. It rejects
extra package files, symlinks, modified inputs, altered workflow bytes, unknown
receipt keys, and missing or false execution/review approval. The receipt is a
closed integrity manifest, not a cryptographic signature or independent proof
of approval. Only an authorized publication after exact review may set its two
boolean approval fields to true. No execution or publication is authorized by
this candidate. The separate reviewer/approver record belongs outside this
closed runtime package.

Before publication, validate that the dedicated branch is based on the stated
base commit and contains only these reviewed new files. Existing foundation
workflows are outside this diagnostic's branch trigger. The template and
prospective `.github/workflows/engine-pdf-input-diagnostic-macos.yml` are identical.
No GitHub or Library operation is part of preparation.

Offline regression tests run the actual unchanged helper with in-memory
first-party mock HTTP responses and inert first-party tar fixtures. No network
request, third-party download, downloaded-code execution, or macOS CI run is
performed during preparation. From a reconstructed review tree containing the
unchanged original files, static validation is:

    /usr/bin/python3 -I -B packaging/pdf-input-diagnostic-candidate/diagnose.py --repository REVIEW_TREE

Tests accept the root of the preserved snapshot as their single positional
argument:

    python3 -I -B packaging/pdf-input-diagnostic-candidate/test_diagnostic.py PRESERVED_SNAPSHOT_ROOT

The published workflow's `--execute` path remains fail-closed until separate
review and execution approval are recorded. Passing input diagnostics would
prove only this input's retrieval and data extraction on that run, not explain
historical failures or validate any PDF runtime.

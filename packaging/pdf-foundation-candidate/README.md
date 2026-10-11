# Inactive PDF foundation prerequisite candidate

This candidate implements the six exact inputs in the prepared PDF prerequisite plan. It is not activated, and its review receipt is closed. No downloaded source, wheel, native executable, configure script or native test has been executed during preparation.

## Narrow result

A future successful run would prove only:

- The private Meson/Ninja/pkgconf toolchain works with the observed Apple SDK.
- Apple SDK libffi `ffi_prep_cif`/`ffi_call`, iconv, zlib and framework probes work.
- PCRE2 10.49's required 8-bit provider has Unicode and actual JIT, with the 26 GLib-required exports.
- GNU gettext 1.0's standalone gettext-runtime/intl target builds real libintl, loads an actual synthetic MO catalog, preserves UTF-8 and plural translations, and exposes the required APIs.

GLib/GObject/GIO, Pango, font closure, PDF rendering, relocation, signed application/release readiness and model/provider activity remain false. This lane never launches them. The source-preserving libintl-only target is adequate for this prerequisite proof; it does not provide xgettext/msgfmt or establish GLib catalog generation. The following GLib lane must explicitly prove both tools and installed catalogs, because Meson can warn and silently skip every PO target when msgfmt is absent.

## Exact inputs and notices

`input-lock.json` pins six URLs, hashes, compressed/expanded sizes, redirect hosts and exact member manifests. The immutable input set is 61,858,201 compressed / 335,134,815 expanded bytes including the existing CPython input. Member manifests enumerate all files/directories and the ten approved Python sibling symlinks, with hashes and tar mtimes. No new dependency, fallback, wrap, package manager or source patch is allowed.

`notices-manifest.json` hashes 89 notice/author files preserved from these exact archives. `notices/` is execution-review evidence, not a declaration that redistribution obligations are fully discharged. GNU libintl/header licensing is LGPL-2.1-or-later with included-code notices; other gettext build/program portions include GPL-3.0-or-later. PCRE2's core and JIT notices, pkgconf COPYING/AUTHORS, Meson and Ninja Apache-2.0 notices and the existing Python-distribution notices are preserved.

The Ninja input is the scikit-build PyPI distribution, not an assertion that its binary equals Ninja's GitHub release. Its exact binary contains the native version string `1.13.2.git.kitware.jobserver-pipe-1`; the candidate checks that value rather than mistakenly expecting a plain upstream version string. The GNU and GitHub official redirects are bounded to the exact previously observed host sets. A changed mirror/redirect, length, hash or member is a stop; there is no alternate-route retry.

## Containment and immutability

- Only first-party receipt validation, retrieval and archive reading occur before the offline phase. All downloaded execution, including Python, Meson, Ninja, configure shell helpers/conftests, compiler children and generated test binaries, occurs beneath the same hash-reviewed sandbox profile.
- A fresh phase directory is the only writable subtree for each subprocess. Inputs, source trees, Python, wheels and frozen providers are in a separate immutable subtree. The whole repository is denied writes. No build hook is granted write access to control files, runtime or inputs.
- There is no `make install`. The coordinator validates expected Mach-O outputs, copies only selected tools/dylibs/headers/pkg-config files into an immutable prefix, and creates two known provider aliases plus the pkg-config tool alias. Input/frozen snapshots are checked before each trusted copy and after tests. Provider install names point to that ephemeral immutable prefix; relocation remains untested.
- The candidate preserves release source bytes and timestamps. It runs only declared build targets: pkgconf static tool, PCRE2's libpcre2-8.la, standalone gettext headers/gnulib/libintl. No gettext top-level/tools build, gperf, libffi source/WrapDB fallback, GLib build, font download or cache generation occurs.
- Environment/PATH/pkg-config search are explicitly constructed. No inherited user site, DYLD, compiler cache, credentials or provider environment is forwarded. Homebrew/MacPorts and framework-Python reads are denied. The sample Meson project uses `--wrap-mode=nofallback`.
- The first-party sandbox canaries test external/loopback/bind denial, child inheritance, immutable/control/other-phase write denial, permitted phase writes and actual Homebrew read denial. They run first with Apple host Python and then the pinned Python. Canaries must pass; a failure ends the run.

The sandbox remains an unexecuted candidate. Its macOS behavior requires independent review and real canary validation. No successful containment claim is made from Linux/static tests.

## Budgets and cleanup

Standard public-repository macos-26 arm64 only, guarded push or manual dispatch on the exact candidate branch, contents:read, pinned checkout with credentials not persisted. A 12-minute job limit bounds 120 seconds of retrieval/extraction plus 540 seconds of contained build/probes and a 60-second reserve. No cache/artifact upload, larger runner, secret, explicit codesign, keychain or release step exists.

The coordinator checks initial free space >=4 GiB, a 2 GiB working-set ceiling, 1 GiB free-space floor, two make/Ninja workers and an 8 MiB aggregate private-output ceiling. The supervisor polls resource limits and the shared absolute build deadline. Each command runs in a newly owned process group; the group is killed and its leader reaped on every outcome, and a surviving group causes failure. The temporary workspace is removed on exit.

Process groups do not prevent a deliberately session-detaching program from escaping group cleanup. The sandbox's write/network restrictions remain inherited by descendants, but this candidate does not claim containment of arbitrary malicious daemon behavior. Its execution review must confirm that the exact chosen configure/build targets and fixed tests do not deliberately daemonize. No daemon/service target is selected; no arbitrary user build hook is accepted. This limitation must not be represented as a proof of arbitrary-code process confinement.

## Useful diagnostics from the first run

Each subprocess emits a first-party record with the exact phase, status, numeric exit where available, captured byte counts/hashes, elapsed time, monitored peak workspace bytes, cleanup result and fixed allowlisted classifications. Child stdout/stderr are never printed. First-party probe compile failures additionally identify mentions from a fixed header/API allowlist, and probe exit codes map to fixed fixture-failure names. On failure, only hashes/counts/classifications from the expected config.log or Meson log are emitted; no arbitrary log line, workflow command, path or child-supplied JSON is exposed. Broad exception handling emits only a fixed failure classification and the current phase, never exception text or a traceback.

This allows a failed configure, compile, sandbox canary, missing target or linker problem to be diagnosed without another blind source-build run. A failed phase is terminal; no automatic rerun or graph expansion occurs.

## Review gates and local validation

`review-receipt.json` hashes every candidate file except itself and pins the six input hashes and false gates. Execution additionally requires independent_review_passed, execution_approved and explicit approval of the compiler/linker's temporary ad-hoc signature/install-name effects. These are all false now. Personal signing and explicit codesign remain forbidden.

The first-party static integrity command is:

`python -I packaging/pdf-foundation-candidate/stage.py --repository <workspace-root> --validate-candidate`

`test_helpers.py` uses stdlib, mocked processes and tiny first-party archive fixtures only. It does not execute any downloaded package/source/native bytes. Tests cover raw-output suppression, bounded failure metadata, deadline/output limits, negative exits, path/redirect rejection, exact fixture extraction, catalog data, sandbox shape and the closed receipt. Native C fixtures are prepared but not compiled locally.

Before activation: independently review exact source/generator/build prerequisites and all receipt-bound candidate bytes, review the adapted security helpers/profile, verify standard public-runner eligibility, and explicitly approve the closed execution gate. No workflow has been copied into `.github/workflows` by this preparation.

## Isolated v2 corrections, still inactive

This revision was copied from the exact frozen publication-v1 candidate. Its local review directory is `packaging/pdf-foundation-candidate-v2`; publication must map it to the unchanged deployed `packaging/pdf-foundation-candidate` path and existing dedicated branch/workflow. Frozen v1 and its evidence remain untouched. The receipt has candidate_revision=2 and all approvals reclosed.

- Archive extraction keeps deadline/hash/size checks per member, while full workspace/free-space scans occur at most every two seconds plus explicit phase boundaries. Input handling runs no downloaded code; its exact archive sizes and expansion totals remain enforced.
- Failed Meson setup diagnostics read the actual `out/meson-logs/meson-log.txt` using the existing stable no-follow bounded reader.
- The Meson adapter locates the wheel at the pinned interpreter's immutable sibling `tree-meson`, verifies core module hashes, and never consumes a CLI argument. Before importing Meson's main module it updates the shared `python_command` list in place to `[sys.executable, '-I', '-S']`. Generated internal helpers/regeneration keep those flags and the same adapter path. The adapter rejects missing isolation before wheel imports. No downloaded source bytes are patched.
- CI now runs a real Meson `--internal copy` and verifies the copied bytes. It then changes only a mutable copy of the first-party sample project's version from 1.0 to 1.1 and uses Ninja's generated regeneration rule; the resulting introspection JSON must report 1.1. Original control files and downloaded source stay immutable.
- Invalid byte 0xff must return the exact PCRE2 10.49 header/source error `PCRE2_ERROR_UTF8_ERR21` (-23). A separate valid non-match must return `PCRE2_ERROR_NOMATCH` (-1), so an arbitrary negative cannot satisfy the UTF-8 rejection check.

The new regression tests remain first-party mocks/static checks. They do not import Meson or execute any downloaded/runtime/native source locally. Real macOS internal-helper/regeneration and native behavior are future CI proofs, not claimed results.

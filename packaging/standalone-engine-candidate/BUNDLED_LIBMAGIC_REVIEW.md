# New reconstructed bundled-libmagic integration v3: closed for review

This is a new reconstruction, not the lost unpublished v3. No historical GO or
hash identity is reused. Publication, activation, core/policy execution, native
execution, both native source overlays, the installed binding overlay and linker
install-ID/ad-hoc effects are closed in the new review receipt. Reconstructed
v1 and v2 remain frozen. This separate v3 addresses only the remaining v2
binding conversion-order finding `R1-order`; the accepted v2 fixes for caller
flags, post-cleanup native identity and honest failed-output accounting are
unchanged. The predecessor manifest is
`34e6bf21bbea9423fdbbc70d1e5d183f5faa35f081d11401834e13528f3b8dfb`;
the consolidated v2 NO-GO report SHA-256 is
`10eceddbe725dfab6b2c23d220f61fb56287f3f9ee2e3ef4f5a33d277bad7d13`.

## Exact foundations

- Current core parent: `109ce9dc56231f314e5a2fec558514652e20f502`, the accepted
  83-file policy-v5 snapshot (manifest SHA-256
  `749a4d073ef011441c2d4e2610834c467dabf5625ce99df9b5dc592381ebf2c2`).
  Its macOS run `38126508714` passed the 16 policy, 14 core import, four
  SQLCipher, 20 in-process ASGI and 277 distribution identity checks. The one
  exact urllib3 socket-creation import probe remained denied and reported.
- Native pilot: `c1056e0ffba9793aff99f24d824478f9b1001c8a`, branch
  `engine-libmagic-source-v2-ci`, run `38112930054`. All 18 published files were
  recovered at the exact commit and matched their Git blob SHA-1 and sizes.
  The retained first-party controls are in `libmagic-pilot/`; their own old
  receipt is reclosed and no additional active native-pilot workflow is added.
- Official source: `https://astron.com/pub/file/file-5.48.tar.gz`, 2,693,209 bytes,
  SHA-256 `ed14656883b23a364b4057c05595d93252da9bc473d30106519519d0da141283`.
- Existing python-magic 0.4.27 wheel: 13,840 bytes, SHA-256
  `c212960ad306f700aa0d01e5d7a325d20548ff97eb9920dcd29513174f0294d3`.
  Both input archives were acquired and inspected only as data during preparation.

The eventual publication target is the dedicated `engine-standalone-libmagic-ci`
branch based on the exact accepted core commit. Its new workflow is
`.github/workflows/engine-standalone-libmagic-macos.yml`; the accepted core
workflow/template and core branch stay untouched.

## Small installed-runtime change

The accepted managed wrapper, launcher, policy checks, urllib3 denial handling,
network/write/read-denial profiles, core checks, ASGI fixture, SQLCipher checks
and the bounded subprocess helper remain byte-identical. The stale assembly
wrapper default and one stale core-mode AST comparison are refreshed to their
accepted policy-v5 identities. The diagnostic catalog adds only the exact
installed loader overlay with explicit before/after provenance.

Only `magic/loader.py` is replaced in the installed Python package. Its old
member hash is `279a11466f7de3450e7f7aefdca2264fedb333da5aff44515a2f891741ad8e55`.
The new source is `bundled_magic_loader.py`, pinned by the execution receipt and
added to the redacted source-location catalog. The modern `magic/__init__.py`
and compatibility `magic/compat.py` bytes remain unchanged. Their separate
existing calls to `load_lib()` now create separate CDLL proxies and separate
ctypes function objects, preventing their different argument types from leaking
into each other.

The loader uses only
`Resources/Python/lib/deepdesk-native/libmagic/lib/libmagic.1.dylib`.
There is no `find_library`, Homebrew, system library search or fallback. Missing
required resources raise fixed import failures. Null load/check/list arguments
select the bundled binary `share/misc/magic.mgc`. Null compile arguments select
the complete bundled text directory `share/misc/magic`, because `FILE_COMPILE`
is a text parser. Explicit database arguments remain available for compiling
and reopening caller-selected databases. A per-call lazy filename parameter
runs only when ctypes reaches argument 2, after ctypes converts argument 1 and
freezes the native cookie pointer. In that slot it calls the binding's declared
filename converter once, retains its conversion/owner, snapshots the resulting
native pointer value and selects the bundled default if that final pointer is
NULL. The original `_as_parameter_` objects are never re-read during delegation.
A synchronous cookie converter can therefore change the filename before its
conversion, just as in ctypes; a later filename converter cannot change the
already-frozen native cookie. Explicit non-NULL filenames, ctypes exception
categories and left-to-right failure order are preserved. The overlay's fixed
missing-resource ImportError remains intact. No shared or per-call `argtypes`
mutation is used: public signatures/getters and the separate modern/compat
function objects remain unchanged. This contract does not claim protection
against arbitrary concurrent caller memory mutation.

`magic_open` and `magic_setflags` remain passed through without wrapping or
modifying flags, including `c_int(0)` and resetting flags to zero.
`MAGIC_NO_COMPRESS_FORK` is requested explicitly only by the reviewed
decompression fixtures; no production flag restriction is introduced.

Before changing anything, integration checks all pinned original wheel members
and all installed RECORD entries. It regenerates RECORD, adds
`python_magic-0.4.27.dist-info/deepdesk-overlay.json`, and verifies that every
previously installed file is still present. Except for loader.py and RECORD,
every old file, mode and relative symlink remains unchanged. No Python package,
native extension, Pandoc helper or known blocker is pruned.

## Native source, full install and relocation

The unchanged accepted nofork patch moves the existing guard after the builtin
return and before external helper selection. Exactly one additional member,
`configure`, receives two exact substitutions of libtool's Darwin install-name
assignment. The new linked ID is `@rpath/libmagic.1.dylib`. No `install_name_tool`
or explicit codesign invocation is used. Both linker rpaths are loader-relative:
`@loader_path` (also needed by the build-local helper) and
`@loader_path/../lib` (the installed helper layout). Every library/helper/fixture
is checked for arm64, macOS 26 minimum, those exact rpaths and Apple/bundled
load commands before successful completion.

The build still uses the official pinned source, exact source-member inventory,
mandatory SDK zlib/bzip2 preflight, two make workers and the retained native
seven-fixture suite plus executable-only exec-denial canary. The complete make
install output is preserved, including bin/file, dylibs/symlinks, header,
libtool metadata and manpages. All 358 upstream MAGIC_FRAGMENTS, including
Header and Localstuff, are copied unchanged into the same flat text-directory
shape used by upstream's Makefile. A fragment identity manifest and COPYING
notice are retained beside the install. The first-party native fixture is
retained under libexec.

The controller binds its audited binary hashes to a final canonical complete
install inventory (all files, directories, modes and relative links) and emits
that inventory's SHA-256. After outer process-group cleanup returns, the parent
recomputes and requires that digest and the three audited binary hashes before
copying. Integration rechecks that same inventory immediately before the copy
and requires source/destination equality afterward. A mutation in the handoff
must fail instead of becoming a new baseline. This is artifact-evidence
continuity, not a claim of protection against concurrent host mutation or
process-session escape. The full native install is exact-copied into the Python
prefix before the existing full-prefix assembly. Its temporary original is removed after copy
verification. The app is moved to a path containing spaces and Unicode; its
pre-move app path is removed as before. The original Python/build prefixes
remain physically present but sandbox-read-denied, exactly as in the accepted
core. This does not claim their deletion.

After the move, the unchanged native C fixture and executable-only canary run
again with the moved library and binary database. Fresh installed-binding
workers exercise both modern and compatibility MIME, gzip/bzip2, external-only
refusal, default load/check/list, real default text compilation, and reopen of
the newly generated binary database. Every loaded non-Apple image must be
inside the moved Python prefix, and the moved libmagic image must appear.
Fresh negative workers verify missing dylib, binary DB, and text refusal. Each
resource is restored in finally, with full bundle equality checked afterward;
the original final full-bundle equality gate remains in force.

## Bounds, fixtures and evidence limits

`bounded_runtime.py` remains byte-identical, SHA-256
`a94a58ba7e45f203fafd4d4d7a0d60ec91cd8366ac7ae8d55909c7d8b1d128f4`.
The source build keeps its 540-second/1-GiB/two-worker limits inside the existing
20-minute/12-GiB core stage and 25-minute workflow. All source-build and runtime
children receive exactly one network-deny profile. A bounded, scrubbed
`/usr/bin/python3 -I -S -B` child runs only reviewed first-party stdlib
orchestration outside containment; downloaded/native children each receive one
pilot profile and share its outer owned process group. The moved C fixtures use
one new profile consisting of the byte-identical relocation denies plus the
exact-fixture exec restriction. No nested sandbox-exec profile is attempted.
Native stderr/stdout are not forwarded. Successful counts come from the
unchanged helper's private measured summary, not estimates. The measured private
native bytes plus actual outer stdout/stderr must fit the existing 2-MiB cap;
portable tests accept an exact-cap case with 4,870 private bytes and reject +1.
The native build reserves 4 KiB within that same cap for its bounded fixed JSON
report. Failed native steps expose only an allowlisted phase/category; their
private byte count is explicitly `null` with `unknown-after-failure`, and the
parent rejects the failed result without claiming an exact count, upper bound
or successful combined-cap acceptance. The unchanged helper may retain a final
read chunk (up to 65,536 bytes) before detecting an output-limit breach. Output,
time and disk limits are monitored thresholds, not hard instantaneous kernel
quotas. Static and mocked tests reject nested profiles and ensure only the
trusted host orchestrator is outside containment.

Both real default `magic_list` calls remain. The independent v1 source review
estimated a conservative 1,696,824 bytes for both full listings, not an observed
runtime result or a bound on compile warnings/other output. The actual combined
successful native/private plus outer output must still pass the unchanged
2-MiB cap. No listing truncation, alternate minimal database or accounting
exclusion has been introduced.

Run `python3 -I -B packaging/standalone-engine-candidate/run_portable_tests.py`
for the portable first-party stdlib/mock suite. The published workflow runs the
same tests before the gated source/runtime stage. Preparation may parse, copy,
hash and patch downloaded bytes as data; it does not import, install, configure,
build or execute those dependencies. A local data-only check verifies all 655
source members, the exact two changed source members, all 358 text fragments,
and RECORD regeneration against the real pinned wheel.

This candidate has not run on macOS. A passing independent source review is
required before a new exact GO, publication or activation. Later integrated
success would establish only these synthetic bundled-libmagic/core checks.
PDF/Pango/GLib/Fontconfig, Pandoc arm64 replacement, full native/export closure,
redistribution completeness, real HTTP/native transport, Keychain, models,
provider queries, actual research, signing/notarization, DMG and release remain
unestablished. No new artifacts/cache uploads or release actions are added.

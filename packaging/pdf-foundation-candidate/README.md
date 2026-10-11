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

The Ninja input is the scikit-build PyPI distribution, not an assertion that its binary equals Ninja's GitHub release. Its exact binary contains the native version string `1.13.2.git.kitware.jobserver-pipe-1`; the candidate checks that value rather than mistakenly expecting a plain upstream version string. GNU gettext now uses the canonical ftp.gnu.org URL and only that hostname. Other inputs retain their exact previously reviewed redirect host sets. A changed mirror/redirect, length, hash or member is a stop; there is no alternate-route retry.

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

These classifications are unscoped substring mentions, including from successful commands and configure feature tests. They do not establish a failure cause. Revision 4 below adds bounded grammar-aware observations for failed make build steps. A failed phase is terminal; no automatic rerun or graph expansion occurs.

## Review gates and local validation

`review-receipt.json` hashes every candidate file except itself and pins the six input hashes and false gates. Execution additionally requires independent_review_passed, execution_approved and explicit approval of the compiler/linker's temporary ad-hoc signature/install-name effects. These are all false now. Personal signing and explicit codesign remain forbidden.

The first-party static integrity command is:

`python -I packaging/pdf-foundation-candidate/stage.py --repository <workspace-root> --validate-candidate`

`test_helpers.py` uses stdlib, mocked processes and tiny first-party archive fixtures only. It does not execute any downloaded package/source/native bytes. Tests cover raw-output suppression, bounded failure metadata, deadline/output limits, negative exits, path/redirect rejection, exact fixture extraction, catalog data, sandbox shape and the closed receipt. Native C fixtures are prepared but not compiled locally.

Before activation: independently review exact source/generator/build prerequisites and all receipt-bound candidate bytes, review the adapted security helpers/profile, verify standard public-runner eligibility, and explicitly approve the closed execution gate. The existing frozen workflow is retained byte-for-byte; this revision has not been published or activated.

## Preserved v2 corrections (historical)

This revision was copied from the exact frozen publication-v1 candidate. Its local review directory is `packaging/pdf-foundation-candidate-v2`; publication must map it to the unchanged deployed `packaging/pdf-foundation-candidate` path and existing dedicated branch/workflow. Frozen v1 and its evidence remain untouched. The receipt has candidate_revision=2 and all approvals reclosed.

- Archive extraction keeps deadline/hash/size checks per member, while full workspace/free-space scans occur at most every two seconds plus explicit phase boundaries. Input handling runs no downloaded code; its exact archive sizes and expansion totals remain enforced.
- Failed Meson setup diagnostics read the actual `out/meson-logs/meson-log.txt` using the existing stable no-follow bounded reader.
- The Meson adapter locates the wheel at the pinned interpreter's immutable sibling `tree-meson`, verifies core module hashes, and never consumes a CLI argument. Before importing Meson's main module it updates the shared `python_command` list in place to `[sys.executable, '-I', '-S']`. Generated internal helpers/regeneration keep those flags and the same adapter path. The adapter rejects missing isolation before wheel imports. No downloaded source bytes are patched.
- CI now runs a real Meson `--internal copy` and verifies the copied bytes. It then changes only a mutable copy of the first-party sample project's version from 1.0 to 1.1 and uses Ninja's generated regeneration rule; the resulting introspection JSON must report 1.1. Original control files and downloaded source stay immutable.
- Invalid byte 0xff must return the exact PCRE2 10.49 header/source error `PCRE2_ERROR_UTF8_ERR21` (-23). A separate valid non-match must return `PCRE2_ERROR_NOMATCH` (-1), so an arbitrary negative cannot satisfy the UTF-8 rejection check.

The new regression tests remain first-party mocks/static checks. They do not import Meson or execute any downloaded/runtime/native source locally. Real macOS internal-helper/regeneration and native behavior are future CI proofs, not claimed results.

## Preserved canonical GNU input revision 3 (historical)

The proposed normal parent is `f52e37049b7d280e53e07013ccd14da3c3ac53d3`, on the unchanged `engine-pdf-foundation-v1-ci` branch and existing workflow. This is a separate candidate; the 116-file approved v2 freeze is untouched. All four review/execution/signing-effect approval flags are false. Prior approval metadata is removed and does not authorize this revision.

The [GNU gettext 1.0 release announcement](https://lists.gnu.org/archive/html/info-gnu/2026-01/msg00007.html) identifies `https://ftp.gnu.org/gnu/gettext/gettext-1.0.tar.gz` and the already pinned SHA-256 `85d99b79c981a404874c02e0342176cf75c7698e2b51fe41031cf6526d974f1a`. Only that URL and gettext's redirect list change in the lock; the list is now solely `ftp.gnu.org`. No previously denied mirror is contacted or added. Versions, sizes, hashes, member manifests, notices and every other pin remain unchanged. An optional local no-redirect data-only archive fetch did not produce response metadata or archive bytes; fresh archive/member verification is not claimed.

The separate input-only diagnostic run [38128686839](https://github.com/Emin-dev/deepdesk/actions/runs/38128686839), at commit `38278848c86340ac09fd93673ada31773ebcadae`, rejected an HTTP 302 host outside its old allowlist before downloading bytes. This establishes that request's failure. It does not retrospectively establish the exact cause of the earlier generic foundation failure in run 38126636047.

`archive_tools.py` remains byte-for-byte unchanged. The small input wrapper preserves download/extract ordering and all checkpoints. A passive observer, derived from the reviewed input-only diagnostic, reads only the exact helper's download/redirect frames. Each of all six pins supplies its own origin and existing host policy. The observer never follows a redirect, changes a request, patches a helper, retries, or relaxes a condition. Tracing is restored in `finally` before extraction and any downloaded execution.

An input failure emits one fixed small record with download/extract/checkpoint subphase, fixed failure class, numeric helper line/status/byte count and at most four host-category redirect decisions. No URL, headers, response body, filesystem path, exception text or traceback is emitted. The existing terminal failure summary retains that class; failure still stops the lane. Classification covers host/redirect policy, status, Content-Length, size, hash, network, extraction and input-boundary failures. Line-based classification is tied to the receipt-bound unchanged helper hash.

`test_input_diagnostics.py` adds only offline mocks and inert first-party tar data. It checks each pin's own host policy, same-host acceptance, denied redirects before following, fixed status/length/size/hash/network/extraction errors, hostile exception messages, trace restoration, retained checkpoints, and the real stage's fatal failure path with temporary-workspace cleanup. `test_helpers.py` remains unchanged. No downloaded package, configure script, source build, native fixture or macOS sandbox is executed locally.

The workflow, sandbox, build targets, budgets, probes, dependency/source graph and native assertions remain unchanged. Foundation success, GLib/Pango/PDF rendering, relocation and release readiness remain unproven. An exact independent review and explicit root approval are required before any publication or runtime execution.


## Preserved build diagnostic revision 4 (historical)

The proposed normal parent is `e886f6db7d0a6383aa91854378f08e2656d2fa42`, tree `90189ebc83b70c2c6b47df98a9c58685773a5189`, on the same `engine-pdf-foundation-v1-ci` branch and unchanged workflow. The exact approved 119-file v3 snapshot is preserved. All four execution/review/temporary-linker-effect approvals are reclosed and earlier approval metadata is removed. This revision has not been published or executed.

[Run 38130019693](https://github.com/Emin-dev/deepdesk/actions/runs/38130019693) reached `pkgconf-build`, which exited 2. All six inputs, containment canaries, pinned Python/Ninja checks, and the actual SDK compile/inspect/run probe had passed. Its private stderr/stdout are no longer available in the public log; their hashes and byte counts are retained there. The generic `permission_denied` marker also occurred in successful steps, and `source_regeneration_attempt` in config.log is not proof of a regeneration failure. No exact failure cause is claimed.

`build_diagnostics.py` runs only after an already-failed declared make build phase. It interprets the already-bounded private stdout/stderr without another command, file capture, environment read, source execution, or request. The old byte/hash/classification metadata and terminal failure semantics are untouched. Stdout and stderr are analyzed independently; their order is not combined. It retains the first observed error and first failing make target in each stream even if warnings fill the small event list. An observed compiler command or target-derived rule role is explicitly not a proven failing executable or root cause.

The receipt-bound `build-diagnostic-catalog.json` is derived from the exact pinned pkgconf 3.0.8 tar (SHA-256 `943f0bc88bcaeceb630b00262e2a8ad5ea4fac3fba72a4267d8b9ec6b35d1194`). Preparation read it only as archive data and independently matched all 46 selected file hashes to the existing member manifest. Its 43 explicit make targets carry exact Makefile.in rule-line evidence; 50 known dependency-output paths derive from those recipes. Public C identifiers exclude comments and quoted literals, and public header names come from literal includes. Source diagnostic locations must match a known relative source path or the exact immutable source root, and fit the source's line count. Only its public basename, role, bounded line/column, and pinned source hash are emitted. Known generated make targets/output paths are distinguished from pinned source files.

Compiler severity and useful messages are preserved through fixed reviewed grammars (undeclared identifier/type/member/function, conflicting types, missing header, output-file or temporary-file failure, spawn denial, unsupported option, linker failure). Within a recognized message, only allowlisted public identifiers/header names/known target paths or fixed path roles are retained; other operands are replaced individually. An unrecognized message is identified as such and withheld. There is no raw tail or arbitrary fallback text. Standalone permission or regeneration markers are not promoted to failure evidence. Other declared make build phases use only generic fixed grammars; they cannot borrow pkgconf source/target names.

The parser scans at most the existing 8 MiB capture ceiling per input stream and 32,768 lines, rejects lines over 8,192 bytes, non-ASCII/control characters and workflow-command markers, limits message text to 240 characters and event lists to six per stream, and enforces a 16 KiB encoded record ceiling. It reports truncation/rejection/omission counts without exposing the rejected content. Raw bytes, argv, environment values, unreviewed names, paths, URLs, credentials and exception messages remain private. Parser errors produce a fixed unavailable status while preserving the original failed subprocess record.

The existing 43 offline tests remain, with only the expected revision and current-parent assertions updated. New first-party fixtures cover allowlisted and unknown source/target/message operands, secret-bearing paths/URLs/options, warnings versus fatal errors, ignored make failures, per-stream first-target ordering, malformed/control/oversized diagnostics, output caps and mocked Lane.run integration. No downloaded dependency, configure script, compiler, make, native fixture or sandbox is executed locally.

All build commands, target lists, environment construction, deadlines, worker counts, output/disk/free-space budgets, archive policies, dependency pins, probes, sandbox profile, cleanup and false gates remain unchanged. Exact independent review and a durable checkpoint must precede root approval and the sole publisher's one authorized rerun. This is a diagnostic amendment to the existing foundation lane, not a new diagnostic branch or a source/runtime expansion.


## Preserved sanitized stderr revision 5 (NO-GO, historical)

The normal parent is the exact published commit `4b83100cc76be279a5b62b166f03d3c166e57c63`, tree `95c2b1cf1ddfd2a26a66bd6b18135547a818dfbb`, on the unchanged branch/workflow. Its approved 123-file v4 snapshot remains preserved. All four review/execution/temporary-linker-effect flags are closed again, and previous approval metadata is removed. No v5 publication or execution is authorized by the historical approvals.

[Run 38131806922](https://github.com/Emin-dev/deepdesk/actions/runs/38131806922) again reached `pkgconf-build`. The improved v4 record identified make target `libpkgconf.la` (Makefile.in:1582), recipe exit 1; make exited 2. Its stderr contained 23 lines / 2,119 bytes, all scanned, but only the final make failure was recognized. No exact linker cause was established. Independent read-only review of the pinned archive found that ltmain.sh:821–839 emits padded `libtool:   error:` messages, including continuation lines, which v4's tool grammar missed. Default silent rules explain why an observed full command was absent. Neither fact identifies the still-private actual message.

Revision 5 retains the same structured classifications and additionally recognizes libtool's padded severity prefix. More importantly, every failed declared make build step now includes a bounded, explicitly sanitized stderr excerpt. Unknown tool error prose and continuation lines survive without requiring a preselected message grammar. This is intended to expose the actual underlying tool error in the next separately approved run. It does not promise that a prior failure will reproduce or that any future output will fit the cap.

The excerpt reads only already-captured private stderr. It does not obtain environment contents, argv, additional logs, or any new process output; raw stdout and raw full streams remain private. It replaces exact source/work/immutable/control/home/tmp prefixes and generic runner/home/toolchain/Windows/relative paths with path roles. Exact public source/target/output suffixes and familiar public system-tool names remain when useful. Quoted paths with spaces are redacted as a unit. URLs/userinfo, labeled credential fields/options, recognizable service-token/JWT/key patterns and nonpublic opaque strings are removed. Private-key blocks and folded credential values are suppressed. Direct environment assignments, shell traces, command echoes and compiler defines are suppressed. Terminal controls and workflow-command markers are neutralized before serialization. Redaction is pattern-based and deliberately preserves ordinary unfamiliar prose; it is not a guarantee that an arbitrary unlabeled short string can be identified as secret. The existing explicit, credential-free build environment is unchanged.

At most 64 stderr lines are considered for display: the first 16 and final 48 within the existing 8 MiB/32,768-line scan bound. Short output is complete; a synthetic exact 23-line / 2,119-byte fixture verifies the prior failure's scale. Each displayed line is capped at 512 characters and the entire encoded excerpt at 6,144 bytes. Budget trimming removes middle context while keeping the beginning and final error context, and exposes omission/truncation counts. Over-8,192-byte input lines are replaced entirely. The existing 16 KiB complete diagnostic-record cap is unchanged; duplicate event-list entries are removed first if necessary so the excerpt and first error/target records have priority.

The 70 existing tests remain, with current revision/parent assertions updated. Their strict no-unreviewed-text assertions still apply to the structured fields; the new excerpt intentionally has a different, redaction-based disclosure contract. Twenty-four new offline fixtures exercise padded libtool and unknown ld errors, exact prior-sized output, public tool/name retention, runner/source/work/tmp/quoted/Windows paths, credential labels/prefixes/URLs/keys, command/environment suppression, controls/workflow markers, truncation, and output-priority caps. No downloaded code, compiler, make, configure script or native program runs during preparation.

`stage.py` changes only its candidate revision relative to v4. Build commands, target lists, inputs, source graph, environment, sandbox, budgets, probes, cleanup, private byte/hash capture, failure semantics and false gates are unchanged. A fresh exact independent review, durable checkpoint and root approval must precede the sole publisher's one authorized rerun.


## Preserved structural redaction revision 6 (NO-GO, historical)

This isolated correction preserves the exact unactivated v5 freeze (manifest `73d0c738c5dc4f157339ff2079837c1478d4fb7fc74e1ea177eb76184a46e3f7`). Publication still has the same normal parent, published v4 commit `4b83100cc76be279a5b62b166f03d3c166e57c63` and tree `95c2b1cf1ddfd2a26a66bd6b18135547a818dfbb`. There has been no v5/v6 run. All four approvals are closed and a fresh exact independent GO is required.

Independent review rejected v5 for four concrete structural redaction gaps. Fourteen synthetic examples demonstrated command/env values surviving quoted/wrapped/colored forms, quoted/JSON credential labels or password operands being missed, empty credential labels losing state across blank lines, and quoted compiler definitions being only partly removed. These are recognizable syntax cases, separate from the acknowledged inability to identify every arbitrary unlabeled short secret. The complete original fixture data is receipt-bound as `disclosure-regression-fixtures.json`.

Revision 6 fixes those cases together:

- Terminal color/OSC controls are removed before structural inspection; other incomplete or unrecognized escape forms omit the whole line. C0 and eight-bit control spellings cannot hide a command prefix. Direct assignments, quoted familiar tool names, env/shell wrappers and nested traces are recognized after normalization. Explicit libtool link/compile/execute command-echo contexts are suppressed as whole lines; genuine severity messages in those contexts remain reviewable.
- Credential labels accept ordinary and escaped quotes, JSON field syntax, and whitespace-separated quoted operands. Known credential fields are redacted conservatively through the end of their line.
- Empty credential labels and their state are recognized in the same normalized view. Blank lines do not consume the pending value. The next value and indented continuations remain hidden even when the label lies outside the selected excerpt head/tail.
- Compiler definitions use inert shell-word spans, including quoted values, escaped spaces, separate `-D` arguments and diagnostics that render quotes backslash-escaped. Complete operands are removed before display truncation; malformed operands are handled conservatively.

The excerpt remains useful rather than category-only. Ordinary unfamiliar libtool/ld/compiler error text and continuation prose still survive. Tests retain the complete exact synthetic 23-line / 2,119-byte failure-sized fixture. The same private capture, 64-line selection, 512-character line cap, 6 KiB encoded excerpt cap and 16 KiB diagnostic cap remain unchanged; omission counts remain visible. The excerpt policy marker is now `bounded_sanitized_stderr_v2`.

All 94 prior tests are retained, with revision expectations refreshed. Fifteen additional regression tests include every exact reviewer fixture and systematic combinations of quotes, whitespace, terminal colors, command wrappers, nested traces, JSON/escaped credential labels, blank lines, omitted regions and quoted/escaped definitions. Positive controls require useful unfamiliar prose to remain visible. The tests are inert first-party text fixtures and mocks, with no downloaded source or native execution.

There are no changes to build commands/targets, inputs, source catalog, environment, sandbox, process cleanup, private capture limits, deadlines, worker/resource budgets, probes, native assertions or false gates. `stage.py` differs from published v4 only in candidate revision. Publication and one bounded run remain contingent on exact review, a durable checkpoint and separate root activation approval.


## Preserved definition-suffix revision 7 (publication blocked, historical)

The exact v6 freeze is preserved (manifest `e463e1db672e6d03cfd932be450abc1e594dc0e434dbcabd1d82fc72bf0cec7f`). Its independent review confirmed the original fourteen disclosure cases were fixed and all 109 tests passed, but found four nested rendered-quote cases where compiler-definition parsing stopped at an embedded quote and exposed the rest of the operand. V6 remains unactivated. The normal publication parent is still published v4 commit `4b83100cc76be279a5b62b166f03d3c166e57c63` and its unchanged tree.

Revision 7 removes the definition operand parser entirely. A four-line helper finds the first recognized `-D` token and replaces the whole suffix through the end of that line with a fixed redaction marker. It does not try to interpret nested quotes, escapes, operand boundaries or trailing arbitrary command text. The definition-free prefix can remain useful; ordinary unfamiliar libtool/ld/compiler error lines and their continuation prose are unaffected. The excerpt policy marker is `bounded_sanitized_stderr_v3`.

All four exact independent-review examples are preserved byte-for-byte, including their hexadecimal input encodings, in the receipt-bound `nested-definition-regression-fixtures.json`. Six additional tests cover those examples, 360 combinations of single/double quotes and outer/inner escape lengths, simple/separate/multiple/malformed definitions, useful nondefinition prose and the complete prior-sized 23-line / 2,119-byte fixture. The original 109 tests remain; only candidate revision expectations and the three expectations that formerly retained text after a definition are updated for the deliberately stricter suffix policy.

All other v6 structural fixes remain intact, including normalized command/env suppression, quoted credential labels and pending-value state across blank lines. Private raw-output capture, original failure behavior, structured metadata, selection and output caps are unchanged. No build command, target, input, environment, sandbox, budget, probe, source catalog or runtime assertion changes. No downloaded/native execution or remote action occurs in preparation. All four approval flags are closed; a fresh exact GO, durable checkpoint and root activation approval are still required before a bounded run.


## Inert-fixture revision 8, closed pending exact review

The approved v7 snapshot is preserved (manifest `99cef94e40187cd13d1346cbf1f35b243e53275db5dd0b6656fb059190ce6a38`); its technical review had passed. Publication stopped when GitHub rejected a tree batch with HTTP 422 and a repository-rule secret-detection message. No matched value or path was disclosed. The rejected batch contained three test files. No commit/ref update occurred; the normal parent remains published v4 commit `4b83100cc76be279a5b62b166f03d3c166e57c63`, with tree `95c2b1cf1ddfd2a26a66bd6b18135547a818dfbb`.

Private inspection found hand-written synthetic test markers, including eight provider-shaped literals with ordered alphabet/digit content, a non-key payload inside a standard-looking key block, and a dummy redirect-URL userinfo fixture. These originated in first-party test preparation, not user accounts or credential retrieval. No real credential was found. Because GitHub supplied no match detail, this does not establish which fixture triggered the rule. Original values are not repeated in the classification report.

Revision 8 changes test data only, plus normal revision/receipt/provenance documentation. The three rejected files now use explicitly invalid test labels. Provider tests contain no realistic provider-shaped value, and do not split, encode or otherwise reconstruct one. Redaction coverage is divided explicitly: eight invalid sentinel cases exercise the unchanged replacement pipeline through a test-only matcher; an independent test pins the exact production pattern and checks all eight family markers, case-insensitive matching and boundary structure. The production matcher itself is byte-identical to the already-reviewed v7 version. This is a transparent test-contract split, not a claim that invalid sentinels are real provider credentials.

The key-block test uses an explicitly invalid test block type and a payload whose strict base64 decoding is asserted to fail. It still exercises private-block state across omitted lines. Opaque-value, credential-label, command/env, quoted/escaped definition, continuation, path/control and useful-prose tests retain their behavior with clearly invalid markers. All eighteen exact independent-review regression data fixtures are unchanged. Candidate revision expectations are refreshed; the production diagnostic helper, input observer, archive helper, source catalog, profiles and workflow remain byte-identical.

All 116 offline tests pass. No downloaded/native execution, remote request, authentication attempt, scanner configuration change, allowlist or identical retry was performed. The rejected action was not bypassed, and GitHub acceptance is not claimed. All four approval flags are reclosed; any new publication requires exact review, a durable checkpoint and separate root approval of this changed candidate. Commands, targets, inputs, environment, budgets, probes, cleanup, failure semantics and false gates remain unchanged.


## Tool invocation spelling, revision 9 (closed candidate)

Published v8 (`f4377a3646eae8139e6592529483e4059202d181`) exposed the useful underlying message: `libtool: no output file (-o) specified`, immediately before `make: *** [libpkgconf.la] Error 1`. The five earlier cache-permission messages are not established as causal.

Pinned pkgconf configure selects its own generated GNU libtool wrapper. That wrapper's static archive recipe invokes AR, followed by RANLIB with the archive path. The stage resolves xcrun's selected invocation spelling before exporting tool paths. Apple libtool/ranlib can select mode by argv[0], so resolving a ranlib alias to its libtool target loses the required mode. This is a definite invocation-spelling defect and strong source-supported explanation; the exact runner symlink and child argv were not observed, and the public Apple source is not claimed byte-identical to that runner.

The sole runtime correction stores the already-validated xcrun spelling for invocation. Existing resolved-target binary identity hashing is retained, as are allowed roots, whitespace/file checks, tool-discovery commands, source recipes, compiler flags, environment keys, source inputs, sandbox, budgets, canaries, probes, redaction and failure controls. No extra command, tool, download or permission is added.

Seven new inert orchestration tests exercise all six tool roles, an actual data-only ranlib-to-libtool symlink, resolved-byte hashing, all three allowed roots, invalid roots, whitespace, a missing file and unchanged lookup/compile limits. Every subprocess call is mocked; no native or downloaded payload is run. The exact source and terminal evidence is receipt-linked through `tool-dispatch-provenance.json` and included in the review archive. V8 remains preserved. This candidate is closed pending exact independent review, checkpoint and separate activation approval.


## Contained standalone gettext layout, revision 10 (closed candidate)

The published revision 9 run passed pkgconf, Meson build/regeneration, PCRE2 build/native checks/26 exports, and gettext configure/headers/gnulib. The remaining make failure names bindtextdom.lo and an undisclosed relative prerequisite. Cache-permission messages do not establish its cause.

The exact pinned gettext 1.0 source proves a build-topology defect: standalone intl configure generates config.h in its current build directory, but all 25 explicit .lo rules require ../config.h. The prior flat build directory placed that prerequisite outside the gettext phase, where no header is generated. This precisely fits the observed error; the redacted log does not independently prove the missing path spelling.

Revision 10 retains the same standalone configure and three make commands, targets and timeouts. They now run in the fixed intl child directory of the original gettext phase. The sandbox PHASE_DIR, HOME and TMPDIR stay at the original phase root. The optional child-working-directory selection is accepted only for those four named gettext steps, that phase and the literal intl child; other values and missing/symlink children fail before subprocess creation. All other steps retain their existing working-directory behavior. Failure config.log hashing now follows the actual working directory.

After configure, a first-party guard checks the generated regular config.h and creates the fixed phase/config.h -> intl/config.h alias. Both remain inside the original phase. Its generated bytes, size and SHA-256 are verified and recorded without publishing header content. Existing paths, dangling aliases, source/build symlinks, empty or oversized headers fail closed. The alias avoids a stale header copy. Library/header inspection and freezing use the new child build paths. Source recipes, sources, compiler options, permissions, budgets, diagnostics, probes, containment canaries and false gates are unchanged. No missing-prerequisite check is ignored. The full gettext-runtime configure/tool graph is not invoked.

The receipt-bound gettext-layout-contract.json contains exact member hashes and source excerpts, every affected object prerequisite, and the gnulib configuration-header relation. The only bare parent-relative prerequisite in those 25 explicit shared-object rules is ../config.h; gnulib's own ../config.h still resolves to the real child header. Twelve new inert tests cover the actual first-party orchestration, every affected object dependency, generated-byte binding, preserved sandbox root and command limits, child-path rejection, private diagnostic hashes, and the previous missing-parent topology. No make, compiler, source payload or native program is executed locally. Activation requires fresh exact review and approval.


## Provider-only locale, revision 11 (closed candidate)

Published v10 completed contained gettext header binding, libintl compilation/native inspection/nine exports and PCRE2's 26 exports. The final native fixture passed its PCRE2 checks, explicit en_US.UTF-8 setlocale call, LANGUAGE=fr setup and domain setup, then exited 36 at the singular coffee translation assertion without output. Native plural/fallback and loaded-image checks remain unreached.

The pinned gettext lookup path explains the environment conflict. For the global locale on macOS, gnulib reads LC_ALL, then the category variable, then LANG rather than querying the global setlocale result. The gettext C/C.* guard returns before LANGUAGE is considered. The lane's LC_ALL=C therefore suppresses the French catalog selection despite the fixture's successful explicit setlocale call; that call does not replace the environment variable.

The only runtime amendment adds extra_env={'LC_ALL':'en_US.UTF-8'} to provider-probe-run. All build/configure/compile and other probe steps retain LC_ALL=C and LANG=C. The native fixture still sets LANGUAGE=fr itself, selects the same already-proven available locale, and enforces every unchanged PCRE2, singular/plural, fallback and image assertion. Command argv, paths, timeout, sandbox, generated catalog, native fixture bytes, sources, hashes and all budgets remain unchanged.

The exact 230-byte generated MO catalog was independently accepted by Python's standard GNUTranslations parser with the expected UTF-8 singular, two plural forms and missing-key fallback. This is catalog validation, not a substitute for native locale lookup. Nine new inert tests capture the actual first-party provider run's effective environment through mocked subprocess bounds, preserve the global C environment and runtime controls, reproduce the prior C suppression in a clearly labeled source-policy model, validate the MO binary tables/identity and pin all native assertions. Five exact source members and the independent v10 terminal evidence are bound in the review package. No source/native payload is executed locally. Fresh exact review and activation approval are required.

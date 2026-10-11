# First-party launcher corrected compile diagnostic candidate v2

Preparation only; no workflow is activated here. Execution requires a separate exact reviewed receipt with `approved_to_execute=true`. An inactive receipt must retain `approved_to_execute=false`. This is one compile-only diagnostic, not a full engine retry or authorization to run its output.

## Confirmed original result and minimal correction

The original full lane, run38108522424 / job114379040136, failed at the first-party launcher compiler step after its offline preparation. The separate original-source diagnostic [run38109566493](https://github.com/Emin-dev/deepdesk/actions/runs/38109566493) then captured compiler exit1 and `launcher.c:59:38`: undeclared identifier O_NOFOLLOW. No compiled output existed and no launcher/runtime payload was executed. Three additional compiler-driver records remain unclassified; they are unresolved and are not explained away by this macro fix.

The source defines `_XOPEN_SOURCE=700`, which Darwin maps to `_POSIX_C_SOURCE=200809L`; Apple's published fcntl feature guard hides O_NOFOLLOW unless Darwin extensions are enabled. The v2 source adds only three lines after X/Open700 and before headers, defining `_DARWIN_C_SOURCE=1` on Apple when it is not already defined. O_NOFOLLOW, compiler warnings, the sandbox, all function bodies and all launcher behavior code remain unchanged.

Primary source references:

- [Apple XNU cdefs.h](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/cdefs.h), X/Open-to-POSIX feature-test mapping
- [Apple XNU fcntl.h](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/fcntl.h), the feature guard containing O_NOFOLLOW

The corrected source has passed a first-party macro-visibility model and the existing 20 launcher contract cases on Linux. These are not an Apple SDK compilation. The corrected Mac compile and exact execution approval remain pending. This v2 candidate retains the same command, clean environment, deny profile, bounds and output classifications; it does not broaden diagnostic text or bypass the remaining unknown driver records. A clean corrected compiler result is required before proposing any complete engine-runtime retry.

## Exact scope

`diagnose_compile.py --repository ROOT --review-receipt FILE`:

1. Requires arm64 macOS and explicit receipt approval.
2. Requires the exact six-file `sha256` map: this helper, its tests, this README, the diagnostic workflow template, the exact corrected standalone launcher, and the unchanged original runtime deny profile. It checks the deployed `.github/workflows/engine-launcher-compile-diagnostic-macos.yml` is byte-identical to the reviewed template. It rechecks reviewed inputs after capture.
3. Creates only fresh temporary home, immutable and read-only-prefix fixtures under RUNNER_TEMP. No interpreter archive, wheel, package installation, model, provider or data source is fetched or accessed.
4. Repeats the original clang arguments exactly: `/usr/bin/clang -std=c11 -O2 -Wall -Wextra -Werror REVIEWED_LAUNCHER -o TEMP/DeepdeskEngine`, under `/usr/bin/sandbox-exec` with the unchanged `runtime-offline.sb` and the same clean environment values. Only disposable path values differ.
5. Captures compiler stdout/stderr privately in memory. Limits: 120-second total inner budget, at most 90 seconds for the compiler, 64 KiB combined private output, 64 MiB temporary work. It checks disk size during execution and after EOF and terminates the owned process group on every completion/failure path, before deleting temporary fixtures. It does not claim to prevent descendant session escape.
6. Emits one JSON summary with compiler exit status, capture status, byte counts/hashes and fixed diagnostic records. It never runs the resulting launcher. The temporary compiler/linker may produce ordinary ad-hoc-signature metadata as part of linking, but this helper never calls codesign, accesses signing identities, publishes or retains an artifact.

Corrected launcher SHA-256: `148b2cddcedcc8b1d23daccd29bd834b900baf5e3a4d1dc7e0d534a50cbcbe1b`.
Original launcher SHA-256, reconstructed by removing only the three reviewed macro lines: `b23fc0b7c2d5a3bf0ed88a99521128518d770f2878024da50a867725d499738a`.
Original profile SHA-256: `9d4f464140e5bb35efb2f937e820349b6f7a47482d4fcb2a618cc489b9bf4710`.

A nonzero compiler exit can still yield a successful diagnostic job if it was captured within bounds. The result always separately reports `compiler_exit_code`, `generated_executable_executed=false`, `runtime_dependencies_downloaded=false`, `native_features_complete=false` and `runtime_lane_ready=false`. Do not describe a completed diagnostic as a successful launcher build unless the compiler actually returned zero.

## Public diagnostics

Only diagnostics whose source location matches the exact pinned launcher path may emit a source basename/line/column, and the only approved basename is `launcher.c`. Locations must fall within that source and a bounded column range. Approved identifiers/headers become fixed messages; compiler driver, linker and sandbox failures become fixed classifications without paths. Unknown messages become `Unclassified compiler diagnostic withheld`. Header traces, excerpts, caret lines, arbitrary quoted strings, control sequences, environment contents and unknown paths are not forwarded. At most 20 records are emitted; the remaining lines are counted. There is no raw-log fallback or artifact upload.

If all useful records remain unclassified, review a narrowly expanded classifier before another diagnostic; do not print the entire stderr buffer. The current classifier recognizes the confirmed original missing O_NOFOLLOW declaration, known missing declarations/types/headers, several fixed type/format classes, and temporary/output/tool/link/sandbox failures.

## Local regression tests

`python3 -B -m unittest discover -s packaging/launcher-compile-diagnostic -p 'test_diagnose_compile.py' -v`

These run only host-standard-library first-party fixtures. They test exact command/environment parity, receipt and workflow integrity, refusal of mutable reviewed-source/profile substitutions, bounded nonzero capture, output/time/disk limits, process-group cleanup paths, location bounds, record caps and diagnostic non-disclosure. They do not execute Apple clang or an actual engine payload on this Linux host. An additional strict regression verifies the corrected source hash and reconstructs the exact original source hash by removing only the three approved macro lines. The original Mac error is established; the corrected SDK26.5 compile remains pending.

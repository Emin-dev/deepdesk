# First-party launcher compile diagnostic candidate

Preparation only; no workflow is activated here. Execution requires a separate exact reviewed receipt with `approved_to_execute=true`. An inactive receipt must retain `approved_to_execute=false`. This is one compile-only diagnostic, not a full engine retry or authorization to run its output.

## Evidence and leading cause

Run 38108522424 / job 114379040136 reached the exact first-party clang command at `standalone_stage.py` lines 414–415 after offline dependency installation/checking. It failed with the generic bounded-process error; compiler stderr was intentionally withheld. The preflight identifies Apple clang 21.0.0, macOS 26.6.2 and SDK 26.5. The source and sandbox hashes below still match that lane.

The leading source-backed hypothesis is feature-test-macro visibility: `launcher.c` defines `_XOPEN_SOURCE=700`, which Darwin maps to `_POSIX_C_SOURCE=200809L`; Apple's published `sys/fcntl.h` exposes `O_NOFOLLOW` only outside strict POSIX mode or when `_DARWIN_C_SOURCE` is enabled. `native_image` uses this flag. This predicts an undeclared-identifier error, but the exact installed SDK/compiler result must still establish it.

Primary source references:

- [Apple XNU cdefs.h](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/cdefs.h), X/Open-to-POSIX feature-test mapping
- [Apple XNU fcntl.h](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/fcntl.h), the feature guard containing O_NOFOLLOW
- [Apple dyld.h](https://github.com/apple-oss-distributions/dyld/blob/main/include/mach-o/dyld.h), stdint inclusion and _NSGetExecutablePath declaration; these do not show the same guard

The clean environment/profile could separately affect tool selection, SDK discovery, temporary files or compiler caches. The existing outer preflight ran outside that exact clean environment, so it does not eliminate those alternatives. This diagnostic deliberately preserves the original clean environment and deny profile rather than bypassing them.

If the predicted declaration error is confirmed, the smallest proposed source change is to define `_DARWIN_C_SOURCE` on Apple before any headers while retaining `_XOPEN_SOURCE=700`. Do not delete `O_NOFOLLOW`, invent its numeric value, drop `-Werror`, weaken the sandbox or run a full dependency lane as the first diagnostic. A separately reviewed corrected source must pass a real arm64 Mac compile under identical flags/profile, the existing synthetic launcher tests, and an explicit compile-only original-vs-fixed declaration regression. No such fix is applied in this directory.

## Exact scope

`diagnose_compile.py --repository ROOT --review-receipt FILE`:

1. Requires arm64 macOS and explicit receipt approval.
2. Requires the exact six-file `sha256` map: this helper, its tests, this README, the diagnostic workflow template, the original standalone launcher, and the original runtime deny profile. It checks the deployed `.github/workflows/engine-launcher-compile-diagnostic-macos.yml` is byte-identical to the reviewed template. It rechecks reviewed inputs after capture.
3. Creates only fresh temporary home, immutable and read-only-prefix fixtures under RUNNER_TEMP. No interpreter archive, wheel, package installation, model, provider or data source is fetched or accessed.
4. Repeats the original clang arguments exactly: `/usr/bin/clang -std=c11 -O2 -Wall -Wextra -Werror ORIGINAL_LAUNCHER -o TEMP/DeepdeskEngine`, under `/usr/bin/sandbox-exec` with the unchanged `runtime-offline.sb` and the same clean environment values. Only disposable path values differ.
5. Captures compiler stdout/stderr privately in memory. Limits: 120-second total inner budget, at most 90 seconds for the compiler, 64 KiB combined private output, 64 MiB temporary work. It checks disk size during execution and after EOF and terminates the owned process group on every completion/failure path, before deleting temporary fixtures. It does not claim to prevent descendant session escape.
6. Emits one JSON summary with compiler exit status, capture status, byte counts/hashes and fixed diagnostic records. It never runs the resulting launcher. The temporary compiler/linker may produce ordinary ad-hoc-signature metadata as part of linking, but this helper never calls codesign, accesses signing identities, publishes or retains an artifact.

Original launcher SHA-256: `b23fc0b7c2d5a3bf0ed88a99521128518d770f2878024da50a867725d499738a`.
Original profile SHA-256: `9d4f464140e5bb35efb2f937e820349b6f7a47482d4fcb2a618cc489b9bf4710`.

A nonzero compiler exit can still yield a successful diagnostic job if it was captured within bounds. The result always separately reports `compiler_exit_code`, `generated_executable_executed=false`, `runtime_dependencies_downloaded=false`, `native_features_complete=false` and `runtime_lane_ready=false`. Do not describe a completed diagnostic as a successful launcher build unless the compiler actually returned zero.

## Public diagnostics

Only diagnostics whose source location matches the exact pinned launcher path may emit a source basename/line/column, and the only approved basename is `launcher.c`. Locations must fall within that source and a bounded column range. Approved identifiers/headers become fixed messages; compiler driver, linker and sandbox failures become fixed classifications without paths. Unknown messages become `Unclassified compiler diagnostic withheld`. Header traces, excerpts, caret lines, arbitrary quoted strings, control sequences, environment contents and unknown paths are not forwarded. At most 20 records are emitted; the remaining lines are counted. There is no raw-log fallback or artifact upload.

If all useful records remain unclassified, review a narrowly expanded classifier before another diagnostic; do not print the entire stderr buffer. The current classifier recognizes the predicted missing O_NOFOLLOW declaration, known missing declarations/types/headers, several fixed type/format classes, and temporary/output/tool/link/sandbox failures.

## Local regression tests

`python3 -B -m unittest discover -s packaging/launcher-compile-diagnostic -p 'test_diagnose_compile.py' -v`

These run only host-standard-library first-party fixtures. They test exact command/environment parity, receipt and workflow integrity, refusal of mutable original-source/profile substitutions, bounded nonzero capture, output/time/disk limits, process-group cleanup paths, location bounds, record caps and diagnostic non-disclosure. They do not execute Apple clang or an actual engine payload on this Linux host. The public Apple headers support the hypothesis but are not a substitute for the exact SDK26.5 observation.

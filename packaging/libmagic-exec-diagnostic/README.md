# Approval-closed source-free exec-canary diagnostic

This candidate diagnoses the failed Python execution-restriction canary from libmagic v3 run 38110605570/job 114385185336. It does not download/build libmagic, compile anything, execute a generated native payload or start MIME smoke. The frozen pilot remains unchanged.

## Exact inputs and execution shape

- Scope: `libmagic-python-exec-canary-diagnostic-only`
- Dedicated branch: `engine-libmagic-exec-diagnostic-ci`
- Reviewed base provenance: `827c358df7a5956515a60e9fe1e75184791a2e28`; parent publication must bind this base. The runtime checks the receipt value and exact candidate/workflow hashes rather than invoking git.
- Exact unchanged `bounded_runtime.py`: `a94a58ba7e45f203fafd4d4d7a0d60ec91cd8366ac7ae8d55909c7d8b1d128f4`
- Exact unchanged `offline.sb`: `b1ef4e080f63c8b50de664fe217ebd9887684454cdc7b94290aa2998cfd9802d`
- Exact unchanged `smoke-no-exec.sb`: `981b85c11f138be1f44192791fd1ebe2896096c976d9741f9e4207a677aef3a4`

Execution defaults false. Before child execution, the stage requires the exact reviewed file set, frozen helper/profile hashes, public Emin-dev/deepdesk and its dedicated branch, native Darwin arm64, supported host Apple Python selection, and an active workflow byte-identical to `libmagic-exec-diagnostic-macos.yml.template`. Scope flags forbid source downloads, compiler execution, generated native payload execution and profile changes.

The interpreter is exactly the pilot's `Path(sys.executable).resolve()`; no alternate executable is selected or allowed. The same clean environment is used, including HOME/TMPDIR, PATH, locale, deployment target and SDK/compiler variables. Two read-only xcrun calls determine SDK and clang paths; clang is never invoked. Only hashes/fixed classes of paths are public, never arbitrary paths or environment values.

One separately explicit read-only host identity observation runs after approval: host stdlib ctypes accesses `_NSGetExecutablePath` from the already loaded process image (`CDLL(None)`), using one buffer capped at 16 KiB. It canonicalizes the returned current-process image path only for comparison with the existing resolved interpreter. Public data is equality, a fixed path/basename class and SHA-256; no private path or arbitrary basename is emitted. API/parse failures yield fixed unavailable fields and never trigger another executable selection or extra allowance. This calls an existing Apple runtime API, not a generated native payload, and does not compile or load a library from a new path.

Apple's primary API declaration and return contract: https://raw.githubusercontent.com/apple-oss-distributions/dyld/main/include/mach-o/dyld.h (`_NSGetExecutablePath`). It describes an executable path that can include symlinks, so canonical comparison is explicit. A mismatch proves only identity mismatch between this running image and declared interpreter path; it supports investigation of forwarding but does not by itself establish why the later child failed. No local Apple API call occurs in preparation; tests inject synthetic paths/errors.

Four bounded child calls occur:

1. SDK path query under offline.sb.
2. Compiler path query under offline.sb.
3. Entry-only control under offline.sb, using `py -I -c CONTROL MARKER`.
4. Instrumented original probe under smoke-no-exec.sb, using `py -I -c PROBE MARKER` and the same single literal py execution allowance. It attempts only the original fixed `/usr/bin/true` command. Only an OSError with EPERM/EACCES counts as denied. Success of that attempted exec is a failure, not accepted containment.

Both first-party Python bodies write only fixed tokens into fresh work-local markers; no untrusted/downloaded code participates. The restrictive profile is not broadened for a possible interpreter launcher.

## Strict evidence and failure semantics

The control must exit zero with empty stdout and exactly `entered\n`. The probe writes `entered`, `imports_ready`, and one reviewed outcome. Parent reads markers only after the bounds helper terminates and reaps its owned process. Reading requires a regular, non-linked, single-link file, O_NOFOLLOW, stable inode and at most 128 bytes. Exact ordered token sequences only are accepted.

- Missing entry is reported as `python_entry_not_observed`, not as proof of launch denial. Startup or marker-write failure is also possible.
- Entered incomplete/import/setup/probe results are distinct fixed classifications.
- EPERM/EACCES result plus successful child exit is the only passing canary.
- Unexpected errno, nonzero subprocess exit, other exception, setup exception or unexpectedly allowed exec all retain failure.
- Invalid marker, zero/nonzero-result mismatch, timeout, output/work limit or unknown child failure never passes.

The unchanged bounds helper deliberately does not return an exact exit code, stdout/stderr counts or hashes on failed children. This diagnostic can distinguish successful exit from its fixed `nonzero_exit` classification, not recover the numerical exit status. It does not pretend missing failed-output metadata is available. Other fixed bounds categories remain inconclusive. No raw stdout/stderr or arbitrary exception text/trace context is exposed, even on unknown failures; child stdout cannot issue workflow commands. Public output contains fixed phases/status/categories, controlled booleans, byte counts and SHA-256 values only.

## Bounds and cleanup

The workflow is standard public macos-26, read-only, three minutes, with no cache/artifact upload. Inner budget is 120 seconds and each of four children is capped at 10 seconds. Work is monitored at 64 MiB. Each child reserves at most 16 KiB private stdout+stderr, including a failed child whose actual count is withheld; four reservations make a strict 64 KiB aggregate capture allowance. The helper terminates the owned process group and reaps its root process; TemporaryDirectory removes the fresh work tree. These remain monitored resource bounds, not hard disk/RSS isolation or a guarantee against process-session escape.

All existing profile restrictions remain: network denial, writes confined to work and denied in immutable, and reads denied from Homebrew, MacPorts, usr/local and third-party Python frameworks. The smoke policy additionally permits execution only at the exact py path. The marker diagnostic is bounded observation of that policy, not permission to bypass it.

## Review and verification

Run `python -B -I packaging/libmagic-exec-diagnostic/test_helpers.py` for first-party synthetic tests. Probe tests mock subprocess, so they never invoke the fixed system command. Bounds tests use only first-party Python children to test output/time/disk limits and cleanup. No downloaded source, Apple native probe or MIME fixture runs locally.

Independent exact review and root GO are required before changing approval or activating the workflow. Success establishes only this diagnostic canary result; it does not establish the prior failure's cause, libmagic MIME success, full decompression, complete native closure or a finished app.

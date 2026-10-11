# Inactive configure-only iconv diagnostic v2

This is a bounded diagnostic candidate for the failure in [run 38145315109](https://github.com/Emin-dev/deepdesk/actions/runs/38145315109), job 114487313754, published commit `3859ae2946cb77d65dfca9430da34a3922c23acc`. It does not fix the failure or attempt a complete GLib build. All execution/publication approvals are closed.

## Observed failure and unresolved cause

The accepted foundation passed again. Source libffi 3.8.0 compiled and passed Mach-O identity, package version and six export checks. Its executable closure and GObject fixture were not reached. Libtextstyle configure exited successfully; its subsequent build failed with `_iconv_ostream_create` undefined from `<initial-undefines>` while linking `libtextstyle.la`. GLib and gettext-tool runtime tests were not reached.

Pinned gettext 1.0 source explains a precise potential mechanism: the constructor is compiled only when `HAVE_ICONV` is true. Its false branch supplies the other methods but no constructor, while the export list still requires that constructor. The ordinary library object list includes `iconv-ostream.c`; it is not an optional omitted make target. This matches the observed single-symbol failure, but the actual generated `HAVE_ICONV` value is absent from the retained v1 log.

The configure script distinguishes link availability from working conversion semantics. Its semantic test includes known loss-reporting bugs, including one observed on macOS 14.4. The accepted SDK fixture only exercised representable UTF-8 conversion. It did not prove this stronger conversion contract. The exact cause on the actual macOS 26 runner is still unconfirmed.

A manual library-search failure by itself does not omit `-liconv`: the pinned configure falls back to that flag even if no `.dylib` or `.a` was found. It then performs a separate link retry. This diagnostic neither forces a configure cache result nor substitutes/removes iconv, NLS or an exported API.

## Exact scope and stop

All eight input identities, source trees, environment construction, sandbox profiles, native provider build commands and bounds are unchanged from reviewed v1. The `Lane.execute` bytes through the complete libtextstyle configure invocation are hash-bound in `iconv-diagnostic-contract.json`. The lane:

1. Rebuilds and rechecks the original six-input foundation.
2. Repeats the approved SDK ncurses and source-libffi build/version/export checks.
3. Repeats the identical libtextstyle configure.
4. Reads three bounded generated files through no-follow regular-file descriptors, emits fixed observations, then stops. It never invokes libtextstyle make or later gettext/GLib build commands.

A successful diagnostic job means only that this bounded observation step completed. The workflow and final record explicitly leave libtextstyle build, gettext tools, GLib/GObject/GModule/GIO/GIRepository runtime, libffi closure, Pango, fonts, rendering, relocation and release false. Unknown observations are inconclusive and cannot turn into a successful native-build claim.

## Fixed diagnostic disclosure

`iconv_config_facts.py` permits only fixed field names with booleans, allowlisted enums, bounded integer lists or null. It reads at most 2 MiB of `config.log`, 1 MiB of `config.h`, and 1 MiB of `lib/Makefile`; each input has line/count limits. Its JSON record is at most 4 KiB. Missing, oversized, symlinked, duplicated or unrecognized values become explicit unknown/rejected facts. No file contents, command lines, paths, environment values or exception text are emitted.

Fields report the exact `am_cv_func_iconv`, `am_cv_func_iconv_works` and `am_cv_lib_iconv` cache decisions, the header/Makefile `HAVE_ICONV` values, and the generated iconv link-expression class. Numeric exit statuses are extracted only after execution markers at the pinned configure source line 26816; compiler statuses are not relabeled as program statuses. At most two executions correspond to the upstream mutable/const declaration variants. No diagnostic text asserts a cause automatically.

A confirmed `HAVE_ICONV=0` plus a successfully executed nonzero upstream semantic test would support selecting a separately reviewed official GNU libiconv source provider. An availability failure would instead need its exact SDK/header/link facts investigated. If iconv is enabled, the missing export needs a build-symbol/topology investigation. No such provider selection or fix is made here.

## Unchanged protections and approvals

The single standard public-repository `macos-26` job retains the 30-minute cap, 180-second input window, 1,500-second contained execution deadline, two workers, 4 GiB workspace, 1 GiB free floor, 6 GiB initial free requirement and 32 MiB private output cap. It retains the secret-free environment, offline writable-phase sandbox, source integrity, process-group cleanup, read-only token and no cache/artifact-upload policy. Inputs and all existing licenses/notices remain identical. Five additional exact source files support the diagnosis; they are data only.

`BOUNDARY-REVIEW.md` retains official standard-runner/public-repository billing evidence. The publisher must recheck public visibility before any approved activation. No paid/larger/self-hosted runner, new credential, user Mac, explicit signing, source patch, install hook or post-link mutation is permitted.

The v1 frozen, approved and terminal snapshots remain unchanged. Final independent review and root approval of the exact new manifest are required before a rerun. Preparation and first-party tests do not execute downloaded code or a native payload.

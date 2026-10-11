# Inactive source iconv / GNU Make correction v3

This receipt-closed candidate preserves the passed foundation, adds official source GNU Make 4.4.1 and GNU libiconv 1.19, rebuilds a separate iconv-enabled GNU libintl, then resumes the reviewed gettext-tools/GLib/NLS/native checks. It has not run on macOS. No downloaded source, configure script, compiler input, wheel or native payload has been executed during preparation. Independent review and exact root approval are required before activation.

## Evidence and corrected scope

The original six-input foundation passed at commit `93a9f9fcbb5aba836597c99c78eb71800535de1f`, run [38140547420](https://github.com/Emin-dev/deepdesk/actions/runs/38140547420). Its approved manifest is `503d59215eee0c59c4c254b9b0e06704aaad968f2da40e209ce36cf270c26c49`. The original snapshot, code and provider fixtures remain unchanged. Every future lane rebuilds those inputs; no native artifact is retained.

Combined v1, commit `3859ae2946cb77d65dfca9430da34a3922c23acc`, failed in [38145315109](https://github.com/Emin-dev/deepdesk/actions/runs/38145315109) at libtextstyle's missing `iconv_ostream_create` export. The source includes the object unconditionally, but compiles that constructor only with `HAVE_ICONV`. Other stub methods remain when iconv is unavailable.

The separately reviewed configure-only diagnostic at commit `ea4c57fa499ea532f5e83ba40b44296fafbd2e80`, run [38147645628](https://github.com/Emin-dev/deepdesk/actions/runs/38147645628), observed iconv availability, a failed working-iconv test, disabled `HAVE_ICONV`, and exact upstream program exits `[2,2]`. The saved log SHA-256 is `8e41532fd8b981f3d2fcfcb29f11c24cba215aa378e1c220913f16b7d7c4634c`. Bit 2 means the U+0142-to-ISO-8859-1 test returned zero where the upstream check rejects that result. The diagnostic did not retain converted bytes or this test's actual function/image origin. No particular returned character or repaired behavior is inferred.

V3 preserves that evidence and makes a visible new provider choice. It does not force a configure cache result, delete an export, disable conversion/NLS, alter upstream source, or relax sandbox permissions.

## Exact inputs, notices and tools

The existing eight pins remain byte-identical: CPython 3.12.15+20261009, Meson 1.11.0, Ninja 1.13.2, pkgconf 3.0.8, PCRE2 10.49, gettext 1.0, source libffi 3.8.0 and GLib 2.90.1. Two new official inputs are:

- [GNU Make 4.4.1](https://ftp.gnu.org/gnu/make/make-4.4.1.tar.gz): 2,348,200 bytes, SHA-256 `dd16fb1d67bfab79a72f5e8390735c49e3e8e70b4945a15ab1f81ddb78658fb3`. It is the highest release in the [current official directory](https://ftp.gnu.org/gnu/make/). Its detached signature verifies using GNU's HTTPS keyring; signature/primary fingerprints and the limited trust statement are in `input-evidence/make/SOURCE-INPUT.json`.
- [GNU libiconv 1.19](https://ftp.gnu.org/gnu/libiconv/libiconv-1.19.tar.gz): 5,921,103 bytes, SHA-256 `88dd96a8c0464eca144fc791ae60cd31cd8ee78321e67397e25fc095c4a19aa6`. Its official detached signature verifies with the GNU keyring. `input-evidence/libiconv/SOURCE-INPUT.json` and the independent source/target reports retain exact provenance, notices and release evidence.

Ten archives total 77,580,242 compressed and 426,518,901 expanded bytes. Every member, mode, timestamp and content hash is locked. New archives have no links. Existing exact GLib license links remain the only added-source link exceptions. Source copies are inspection data, never imported as Python code.

GNU Make is GPL-3.0-or-later and ephemeral build-only. GNU libiconv/libcharset libraries and headers carry LGPL-2.1-or-later notices; their tools/build/documentation have the retained distinct licenses. Exact COPYING/AUTHORS/documentation notices and source headers are included. No new binary package, package manager, mirror, credential or dependency download is proposed.

Libiconv's declared requirement is GNU Make >=4.0 for this out-of-tree graph. The accepted gettext source's actual runtime PO Makefile also uses the `!=` construct and requires >=4.0 despite older top-level dependency prose. This does not retroactively invalidate the narrowly selected, already-passed foundation targets; v3 binds the new supported Make to all correction/downstream Make invocations.

## Build order and retained behavior

1. Rebuild the exact original foundation and source libffi checks. Preserve xcrun invocation spelling separately from resolved binary hashes, standalone intl's guarded phase/config.h alias and probe-only UTF-8 locale. The original `providers/lib/libintl.8.dylib` remains unchanged.
2. Configure GNU Make with NLS enabled and the bootstrap GNU libintl, then use its documented `build.sh` bootstrap. This does not enter `po/all` or require msgfmt. Preserve all 30 release `.gmo` catalogs, verify their member hashes and LINGUAS coverage, bind the configured locale prefix, and require a French help lookup plus real `!=` shell-assignment behavior. Only optional Guile embedding is disabled, explicitly for this ephemeral build tool. No complete Guile-enabled Make distribution is claimed.
3. Configure GNU libiconv shared-only, leaving its encoding defaults unchanged. Build the genuine `libcharset/lib/libcharset.la` target. Inspect the unique main Libtool CONFIG section and `.la` metadata: shared-only, no active relink command, no shared postinstall/finish hooks, exact provider install prefix. Hash the generated scripts/metadata. Then run the genuine top-level `lib/localcharset.h` prerequisite, which stages only libcharset libraries/headers inside the same writable phase. Require staged dylib bytes to equal the original. Build `lib/libiconv.la` without entering `src`, PO, docs or test install targets.
4. Promote exact unmodified libiconv/libcharset dylibs and configured public headers. Libiconv's soname is `libiconv.2.dylib`; libcharset's is `libcharset.1.dylib`. Their absolute install identities are bound to this ephemeral provider prefix. Libiconv compiles localcharset directly and does not dynamically depend on the separate charset library. That upstream prerequisite output is independently verified and retained in the ephemeral provider set; it is not asserted to be a necessary app dependency.
5. Compile and run both unchanged upstream working-iconv C test variants extracted from the pinned gettext configure heredoc. Only its normal empty/`const` substitution and a compiler-only main-symbol rename are used. Both must return zero. The driver checks GNU version 1.19 and actual function/image origins for conversion entry points and the charset library. A passing version or export list alone is insufficient.
6. Rebuild the same GNU gettext libintl source with the new iconv provider into `providers/intl-with-iconv`. The original bootstrap provider is neither replaced nor overwritten. Require its generated `HAVE_ICONV`, nine exports, direct native dependency on the new libiconv, actual UTF-8 and ISO-8859-1 catalog output, singular/plural/fallback behavior and the corrected libintl image origin.
7. Build libtextstyle and real msgfmt/xgettext with explicit new iconv/corrected-intl prefixes, GNU Make, SDK ncurses and unchanged XML/Unicode/tree-sitter implementations. Require the actual libtextstyle working-iconv facts to pass, NLS/iconv config macros, exact native identities and functional extraction/catalog checks.
8. Resume the reviewed GLib 2.90.1 build and full fixture suite: regex/Unicode/main-context dispatch, source-libffi executable closure, GObject generic marshalling, GModule loading, GIO local files, GIRepository construction, production French catalog lookup, and configured glib-mkenums. Add GLib conversion and unrepresentable-input checks. Preserve all 102 production catalogs and all selected installed C headers/pkg-config files.

The exact library-only target avoids libiconv `src/all`'s chmod-777 hook by never selecting that target. It does not patch the source hook or run generic install. The phase-local libcharset install helper is a real, narrowly disclosed upstream staging operation with its own closed approval gate. Final promotion remains bounded byte-for-byte copying. It performs no explicit codesign, install-name edit or install-time relink.

## Provider selection and native closure

Downstream include/link search places corrected intl first, then the source iconv prefix. Configure prefixes are explicit. Pinned Meson 1.11's iconv/intl dependency code and compiler search implementation are included: external CPPFLAGS/LDFLAGS participate in the header/link probes and ordered `-L` search. Dependency metadata alone is not proof of origin.

Mach-O validation requires exact arm64/macOS-26 identities. GLib must actually import the new iconv and corrected intl install IDs. All new runtime inspections reject the bootstrap intl ID. Actual loaded-image and function-origin checks reject missing, duplicate, mismatched or silently selected bootstrap providers. The final graph recursively checks all non-system provider edges, records hashes and normalized paths, and separately records allowlisted Apple system imports. This is this prerequisite set's closure, not complete application or font closure.

GLib's existing immutable component-relative `@rpath` layout remains unchanged. There is no post-link mutation, personal signing, source patch or fabricated package version. Absolute iconv/intl prefixes have not been relocated; relocation remains false.

## Honest exclusions and bounds

The earlier GLib exclusions remain explicit: generated docs/manuals, upstream test installations, generated GIR/typelib metadata and optional DTrace/SystemTap/sysprof instrumentation. Typelibs can be runtime requirements of other bindings; tracing is a runtime capability. The exact accepted WeasyPrint CFFI/Pango boundary does not consume them. GIRepository runtime and Pango-required glib-mkenums remain. Other CLI/install outputs are not promoted; this is not a full GLib or libiconv CLI installation.

Pango, font/data closure, PDF rendering, relocation, release readiness, models and provider queries remain false. Later Pango work must preserve Fontconfig/FreeType/PangoFT2, Cairo/PangoCairo, libthai and HarfBuzz subset/vector behavior, including HarfBuzz 13+ for the accepted WeasyPrint color-glyph path. No later prerequisite is silently dropped.

The standard public-repository `macos-26` job keeps the previously proposed bounds: 30 minutes; 180-second input retrieval; a shared 1,500-second contained execution deadline; two workers; 4 GiB monitored workspace; 1 GiB free floor; 6 GiB initial free space; 32 MiB aggregate private output. The expanded combined graph is not yet timed on macOS. A budget failure is terminal and does not authorize an automatic expansion or retry.

The offline one-writable-phase sandbox, read-only controls/sources/providers, secret-free environment, cleanup and normal diagnostic secret scanning remain. Builds stay in locale C; fixed translation fixtures alone use `en_US.UTF-8`/French. Captured stderr excerpts remain capped at 6 KiB inside 16 KiB records; no raw config log is disclosed. Known fixture failures have fixed numeric/enum diagnostics. Post-child first-party staging uses exclusive-create and bounded no-follow reads.

Official free-standard-runner evidence is retained in `BOUNDARY-REVIEW.md`; the sole publisher must recheck public repository visibility before activation. No paid/larger/self-hosted runner, billing change, cache, artifact/package/release upload, new credential or user-Mac action is authorized. The existing process-group cleanup limitation for arbitrary session-detaching malicious daemons remains; no daemon target is selected.

## Closed review boundary

The receipt binds every file and all ten input hashes. New Make execution, source iconv selection, internal charset staging and corrected-intl selection each have an explicit closed approval gate, alongside execution/publication/review/compiler-effect gates. First-party tests use fabricated metadata/Mach-O bytes and data-only archive inspection. They cannot establish a successful native build. Every earlier frozen/approved/terminal snapshot is preserved.

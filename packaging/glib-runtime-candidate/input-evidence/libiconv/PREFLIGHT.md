# GNU libiconv 1.19: conditional source-input preflight

Status: data-only; no configure, build, test, native execution, installation, packaging, provider activation or publication. Existing accepted/frozen snapshots were not changed. This is research for a future reviewed correction, not execution approval. The parent subsequently reported SDK iconv exists=yes, works=no and upstream semantic-test exits [2,2]; that report is not independently verified by this preflight.

## Current exact input

The official [GNU directory](https://ftp.gnu.org/gnu/libiconv/) and [project download](https://www.gnu.org/software/libiconv/) both identify 1.19 as the newest release observed on 2026-10-11. This is a current-release proposal, not a compatibility pin. The initially inspected 1.18 is explicitly superseded. 1.19's ChangeLog:116–121 records a GB18030 buffer-overrun correction; using 1.18 merely to avoid a newer build tool would lose that correction. This is not a comprehensive vulnerability audit.

- Archive: [libiconv-1.19.tar.gz](https://ftp.gnu.org/gnu/libiconv/libiconv-1.19.tar.gz), 5,921,103 bytes.
- SHA-256: `88dd96a8c0464eca144fc791ae60cd31cd8ee78321e67397e25fc095c4a19aa6`.
- [Official detached signature](https://ftp.gnu.org/gnu/libiconv/libiconv-1.19.tar.gz.sig): 228 bytes, SHA-256 `30374a9cf2846418fc34977eb2b92094c3edb76021d57de541699e2b5e32dc9b`.
- Existing system GnuPG returned GOODSIG/VALIDSIG and exit 0 using only the [official GNU keyring](https://ftp.gnu.org/gnu/gnu-keyring.gpg). Signer fingerprint: `E0FFBD975397F77A32AB76ECB6301D9E1BBEAC08`, Bruno Haible. The isolated empty home reported TRUST_UNDEFINED: authenticity relies on GNU's HTTPS keyring distribution, not an independently established web of trust. No personal keyring or credentials were read/changed; no automatic key retrieval.
- The [official release index](https://lists.gnu.org/archive/html/bug-gnu-libiconv/2026-03/index.html) links the 2026-03-07 announcement. Its message page returned HTTP 502/timeouts; no separately published announcement checksum is claimed.

`SOURCE-INPUT.json` binds all exact inputs. `../evidence/archive-1.19-members.json` hashes every regular member: 1,109 files, 33 directories, no links. Selected inspected source copies are mode 0644 under `../evidence/source-1.19/`; no copied source script was executed.

## Licenses and notices

Exact unmodified notice files are retained and hashed in SOURCE-INPUT.json:

- libiconv library and installed iconv header: LGPL-2.1-or-later in lib/iconv.c and include/iconv.h.in.
- libcharset's implementation, public headers and relocation stub: LGPL-2.0-or-later per their own headers. The distributed COPYING.LIB text is LGPL 2.1. Do not flatten this distinction into a false package-wide single license.
- The separate iconv executable is GPL-3.0-or-later (src/iconv.c:1–15); README:148–152 also assigns documentation to GPL.
- Retain COPYING.LIB, libcharset/COPYING.LIB, COPYING and upstream notices alongside a future corresponding-source/license manifest. Actual distribution compliance must be reviewed for the selected shared-library packaging; this preflight is not that legal review. Build machinery has its own notices/exceptions in the retained source archive.

## Build requirements and generated files

DEPENDENCIES specifies native C compiler/runtime/linker, shell, core POSIX utilities, cmp/diff, grep/awk and GNU Make >=4.0, or a qualifying native *BSD make for in-tree builds. No prerequisite third-party runtime package is mandatory for the libraries. Gnulib localizations are recommended for the separate programs, not a dependency to fetch here. sed and usual platform archive/install tools are used by the actual scripts. Future arm64 validation must bind the chosen Apple compiler, SDK, linker/inspection tools and Make identity; they have not been executed/queried here.

The archive ships Autoconf 2.72-generated configure scripts, Automake 1.18.1-generated srclib/Makefile.in and Libtool 2.5.4 machinery. Release builds need not bootstrap these. HACKING's old Automake 1.16.x sentence is stale relative to Makefile.devel's explicit 1.18 and the generated file. Do not run autogen, Makefile.devel, gnulib refresh, gperf or maintainer regeneration.

`../evidence/mtime-preflight.json` checks the five main generated targets against their archive prerequisites. All dependencies exist and none is newer:

- aclocal.m4: 1772871974; maximum input mtime 1772871970 (125 dependencies)
- configure: 1772871975; maximum 1772871974 (126)
- srclib/Makefile.in: 1772871975; maximum 1772871974 (128)
- config.h.in: 1772871976; maximum 1772871974 (126)
- include/iconv.h.build.in: 1772871976; maximum 1772871871 (2)

These correspond to 2026-03-07 08:26:14–16 UTC. libcharset/configure and config.h.in are 1772871982 (08:26:22 UTC). Full per-member mtimes are retained. Preserve archive times during future extraction; do not touch generated outputs to hide a new prerequisite. This static check does not claim that every possible maintainer rule has been evaluated.

## Darwin arm64 linkage and API

Source-derived expectations, not native build observations:

- build-aux/config.guess:1457–1458 recognizes arm64 Darwin as aarch64-apple-darwin. Future binaries must independently prove arm64 architecture and the approved SDK/deployment target.
- lib/Makefile.in uses version-info 9:1:7; bundled Darwin Libtool rules imply libiconv.2.dylib, unversioned libiconv.dylib symlink, compatibility 10.0.0/current 10.1.0.
- libcharset/lib/Makefile.in uses 1:0:0; expected libcharset.1.dylib plus libcharset.dylib symlink, compatibility/current 2.0.0.
- m4/libtool.m4:1158 and 2697–2707 set the install name to the selected libdir plus soname. This is not automatically @rpath. Any later relocation must be independently reviewed and verified with actual native identities/dependencies; do not use ambient DYLD paths to conceal incorrect linkage.
- libiconv directly compiles localcharset.c plus iconv.c and compat.c. Its upstream link rule has no libcharset.la/-lcharset edge. A normal build still produces/stages libcharset as a separate sibling, not an external source dependency.
- Installed iconv.h uses `_LIBICONV_VERSION 0x0113` and maps iconv_t/open/iconv/close to the libiconv-prefixed namespace. Header and library selection must agree; unprefixed SDK symbols are not provider proof. `ICONV_CONST` is genuinely configured, not forced.
- Unsuffixed GNU conversion is strict: unrepresentable output returns EILSEQ; transliteration/discard require explicit suffixes (man/iconv.3:48–69; man/iconv_open.3:223–237). EUC-JP and Unicode converters are included. New tests must reuse the exact accepted gettext working-iconv semantic cases, including U+0142 loss handling, and verify native dependency resolution, rather than force HAVE_ICONV or cache answers.

## Stop gates

See LIBRARY-TARGETS.md for the genuine upstream library-only closure and the excluded chmod hook. See GETTEXT-MAKE.md for the pre-existing gettext PO Make>=4 issue. No Make archive/tool was acquired here. Stop and return for review if an additional source, tool, maintainer regeneration, permission change or unlisted runtime dependency appears. This report does not change NLS, optional encodings, cache results, exports or provider choice.

# Library-only upstream target boundary (not executed)

All references below are to the exact libiconv 1.19 archive. These are target descriptions for a future approved recipe, not an activation script.

1. Upstream top-level configure creates top/build Makefiles, config.h and lib/config.h, include/iconv.h from the annotated build template, and include/iconv.h.inst from the public template. It recursively configures libcharset (configure.ac:219–232). libcharset configure produces its config.h, Makefiles and build/public variants of libcharset.h and localcharset.h. Configure still performs genuine compile/link/run detection; this preflight has not run it.
2. In a fresh isolated build root, top Makefile's explicit `lib/localcharset.h` target (Makefile.in:41–42) enters libcharset, builds its `all`, then invokes its `install-lib` with absolute buildroot/lib as both libdir and includedir. This creates the localcharset header needed by libiconv and local charset library/header artifacts inside the build tree. libcharset `all` only enters its library subdirectory.
3. Library subdirectory `all` (lib/Makefile.in:67–70) compiles iconv.lo, localcharset.lo and compat.lo and links the complete libiconv.la. This retains the full library code and configured encodings; it does not enter src, PO, man, tests or install-tests. The make identity must propagate consistently to recursive invocations.
4. lib/Makefile `install-lib` (97–99) performs its library-only `all` and Libtool install into an explicitly selected libdir. It does not stage public iconv.h. A separate, explicit reviewed copy of generated include/iconv.h.inst to the final include/iconv.h is needed; there is no header-only top-level install target.
5. If the separate charset library/public headers belong in the approved closure, libcharset/Makefile `install-lib` (38–44) builds its library-only `all`, installs the library into explicit libdir, installs include/libcharset.h.inst as libcharset.h, and installs annotated include/localcharset.h as localcharset.h. This target has no src/PO/CLI recursion.

Critical exclusions:

- Top-level `all` recursively enters lib, srclib, src, po, man, tests and install-tests. Top-level `install-lib` depends on this `all`: its name does not make it a library-only build.
- src/Makefile.in:75–76 executes chmod 777 on the current src build directory during `all`. Do not run this hook or patch it away under this research authorization. The genuine library-only target closure above never reaches it.
- Generic top-level install/install-strip enters the separate program/docs/localizations and is outside the proposed library-only boundary.
- Top-level check/check-extra and installcheck expand scope into executable tests/CLI. Even library Makefile `check` is merely `all`, not a semantic acceptance test.
- GNU Make >=4.0 is the release's declared general build prerequisite. The selected hand-written library targets do not visibly contain the PO `!=` construct, but this is not evidence that an older Make is an approved supported substitute.
- The plain `install-lib` targets use direct libdir/includedir overrides, not a generic DESTDIR safety wrapper. Bind both destinations to a reviewed fresh staging prefix before any future action. This preflight stages nothing.

No source patch, altered export, cache override or iconv/NLS feature disablement is required to identify these existing targets. An explicit future provider decision must still choose flags, optional extra encodings, staging paths and native verification requirements.

## Libtool helper effects within the charset prerequisite

Bundled Libtool install mode sources the generated .la, copies the shared library and .la metadata, and creates/replaces library-name symlinks in buildroot/lib (libcharset/build-aux/ltmain.sh:4647–4755). Static output, if enabled, additionally copies .a, applies chmod 0644 and runs configured RANLIB (libcharset/m4/libtool.m4:1591–1596; ltmain.sh:4920–4941). This is an actual upstream install helper, though confined by the target overrides to the phase build tree.

Darwin's macro sets hardcode_automatic=yes (m4/libtool.m4:1141), which clears the generated relink_command (ltmain.sh:11136–11137). Its platform branch leaves shared postinstall_cmds, finish_cmds and finish_eval empty. These are source-derived expectations: a future guarded recipe should verify the generated values and destinations before entering this helper, and stop on nonempty unexpected hooks. An explicitly reviewed shared-only configuration must propagate into the libcharset subconfigure if static artifacts and RANLIB install effects are excluded. This is not an implicit request to add flags.

# GLib/Pango prerequisite boundary review

Reviewed 2026-10-11, approximately 13:04–13:11 UTC. This is an independent, data-only review. It does not approve publication or execution and does not claim a GLib/Pango native build or rendering pass.

## Decision

The proposed single 30-minute job on the standard `macos-26` runner has no runner-minute charge while `Emin-dev/deepdesk` remains public. Preserve the guards below; no billing, runner, access or activation changes are needed or authorized.

For the exact accepted WeasyPrint **70.0** CFFI consumer, API documentation, manuals, installed upstream test suites, generated GIR/typelibs and optional tracing are not prerequisites for its native text/font calls. This conclusion is restricted to that consumer and the specified Pango C build. It is not a claim that typelibs or tracing are universally development-only or that all GLib/Pango features remain available.

**Required output discovered:** a provider intended for the Pango source build must retain GLib's configured `glib-mkenums` script and the corresponding `glib-2.0.pc` tool path, alongside installed generated headers. Pango invokes it even when introspection is disabled. Removing every “development tool” would break or contaminate the next build.

## 1. Official runner and cost boundary

- GitHub's standard-public-runner table lists `macos-26` as arm64, 3 M1 CPU cores, 7 GB RAM, 14 GB SSD. Standard runners are free for public repositories. The label is distinct from larger-runner choices. [GitHub-hosted runner specifications](https://docs.github.com/en/actions/reference/runners/github-hosted-runners#standard-github-hosted-runners-for-public-repositories)
- A fresh read-only GitHub connector lookup returned repository ID `1413757711`, full name `Emin-dev/deepdesk`, visibility `public`, archived `false`. Exact result: `github-repository-observation.json`. [Repository](https://github.com/Emin-dev/deepdesk)
- Private-repository jobs use plan-included minutes and can incur charges beyond their allowance. Larger runners are billed even for public repositories and cannot consume included minutes. Neither category is authorized here. [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [Larger-runner billing](https://docs.github.com/en/actions/concepts/runners/larger-runners#billing)
- GitHub-hosted jobs have a six-hour limit; the proposed explicit 30-minute timeout is below it. A timeout limits resource use but does not establish that a build will finish successfully. [Actions limits](https://docs.github.com/en/actions/reference/limits)
- Artifact storage is separate from the runner-minute conclusion and shares allowance with GitHub Packages. Cache has a separate 10 GB repository allowance; opted-in capacity beyond that can be charged. Workflow logs and job summaries do not count against artifact storage allowance. This candidate must not upload artifacts, save caches, publish packages or create custom image snapshots. No billing or cache setting changes are part of this review. [Storage billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions#how-storage-billing-works), [Cache usage and eviction](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching#usage-limits-and-eviction-policy)

Required workflow/publisher guards:

1. Recheck exact repository `Emin-dev/deepdesk` remains public immediately before publication/dispatch. At job level, fail closed or skip unless `github.repository == 'Emin-dev/deepdesk'` and `github.event.repository.private == false`; the guard belongs before runner allocation, not only in a later shell step. Verify event availability for the actual trigger.
2. Literal `runs-on: macos-26`, one job, no matrix, no label input/expression, no runner group, no larger/self-hosted/custom-image fallback. Confirm actual `RUNNER_ARCH=ARM64` and Darwin host before native steps. Do not relabel or reconfigure any runner.
3. `timeout-minutes: 30`; preserve the reviewed trigger, exact candidate/commit and sole-publisher/root-GO boundary. A failed or timed-out run does not authorize another run or a larger machine by itself.
4. At most `contents: read` token permissions; all other permissions absent/none, no `id-token: write`, no repository/billing/settings mutations, no persistent token checkout credentials. Inspect nested/composite actions and scripts for uploads/caches, not only top-level YAML.
5. No `upload-artifact`, `actions/cache`, setup-action package caches, cache API saves, package/container/release uploads or image `snapshot`. Keep machine evidence in bounded logs/summary for this pilot. Normal transient local downloads/build files do not constitute retained Actions artifacts.
6. No spend, payment method, paid activation, extra access, secrets, model/provider traffic or user-Mac use. Existing read access suffices for this review.

Official HTML/checksum retrieval evidence and hashes are in `online-source-evidence.json`; the linked pages were also checked with the web tool. This review does not inspect the owner's overall billing balance or promise that unrelated account usage is free.

## 2. Exact inputs and provenance

All sources were read as data. No downloaded package import, setup/configure/Meson execution, install, C compilation or native execution occurred.

- GLib 2.90.1 archive SHA-256: `93c941aa17d5eb1d53fe838365f29a8b4e539c222a256d974ec8f30fc413e396`. Independently matched both the author's archive and a fresh [official GNOME checksum](https://download.gnome.org/sources/glib/2.90/glib-2.90.1.sha256sum). [Archive](https://download.gnome.org/sources/glib/2.90/glib-2.90.1.tar.xz)
- Pango 1.58.2 archive SHA-256: `342385b6ca3b7c73455d7c80a13b7dbe4489e00bc3bd4c5bd6ed4dce421e374a`. Independently matched both the author's archive and a fresh [official GNOME checksum](https://download.gnome.org/sources/pango/1.58/pango-1.58.2.sha256sum). [Archive](https://download.gnome.org/sources/pango/1.58/pango-1.58.2.tar.xz)
- The accepted `standalone-libmagic-reconstructed-v8-approved/candidate/research/engine-ci/all-pypi-input-proposal.json` pins WeasyPrint 70.0, wheel `weasyprint-70.0-py3-none-any.whl`, SHA-256 `5043e55e38d2a2af2b2b871e869697b1f65dad5f8b4a3677961d04ceacf9c5fe`. Downloaded that exact pinned wheel as data and verified the digest before AST/text inspection. [Pinned release metadata](https://pypi.org/pypi/weasyprint/70.0/json)
- Meson 1.11.0 wheel SHA-256 `9774eb62bbf2cb8043aa3feb771c09b510d112c0c382221e29aea7453ecce753` matches accepted foundation snapshot `packaging/pdf-foundation-candidate/input-lock.json`. Three Meson source files were read from this verified wheel to confirm tool/catalog lookup behavior. No Meson code ran.

`input-hashes.json` identifies the three principal inputs. `consumer-source-analysis.json` records the WeasyPrint import/native-load analysis and exact GLib language inventory. Source references below are relative to this review's `evidence/` directory.

## 3. GLib output and option boundaries

### Runtime library set is independent of generated GIR

GLib `meson.build:2815–2822` enters `glib`, `gobject`, `gthread`, `gmodule`, `gio` and `girepository` unconditionally. `girepository/meson.build:190–259` builds and installs `libgirepository-2.0`, enters compiler/decompiler/inspector unconditionally, and only gates its `introspection` subdirectory with `enable_gir`. Thus `-Dintrospection=disabled` does not mean “no introspection library” or “no GI compiler.” Preserve all six installed runtime dylibs and their dependency closure.

`meson.build:2702–2717` describes scanner-driven GIR generation and locally built typelib compilation. With generation disabled, GLib, GLibUnix, GObject, GModule, Gio, GioUnix and GIRepository generated metadata are omitted on this Unix platform (`girepository/introspection/meson.build`). Typelibs describe APIs that introspection bindings load at runtime (`girepository/gitypelib.c:36–43`). Such bindings would need these missing outputs. This candidate must not claim to preserve their functionality.

### Docs and upstream tests

`documentation=false`, `man-pages=disabled`, `tests=false`, `installed_tests=false` omit generated manuals/reference documentation and upstream test binaries/install metadata. Test subdirectories are conditional (`meson.build:172–179, 2824–2826`); library builds are not. The public GLib test utility API remains in the library source list (`glib/meson.build:327` includes `gtestutils.c`), so disabling the upstream suite is not removal of the public test API. Documentation paths are gated in `docs/reference/meson.build` and its children.

No pass of those omitted upstream tests can be claimed. A focused synthetic smoke proves only its tested cases; full native behavior, relocation, release packaging and end-to-end rendering remain unproved.

### Tracing is an explicit instrumentation exclusion

`sysprof=disabled` omits optional runtime trace recording. `glib/gtrace-private.h` makes tracing macros no-ops without `HAVE_SYSPROF`; `glib/gtrace.c` identifies its API as internal and describes zero runtime cost when configured out. This is optional instrumentation, not just “profiling metadata.” In GLib 2.90.1, the macOS DTrace path is explicitly unsupported/disabled (`meson.build:2631–2641`); SystemTap depends on DTrace (`2687–2689`). Do not describe disabled profiling as an unchanged diagnostic feature.

### NLS/catalogs must remain

`nls=enabled` requires `xgettext` and enters `po` (`meson.build:2829–2831`); `po/meson.build` uses `i18n.gettext('glib20', preset: 'glib')`. The archive contains exactly 102 `po/*.po` files and exactly the same 102 entries in `po/LINGUAS` (recorded in JSON). Exact Meson 1.11 `i18n.py:417–442` reads all LINGUAS entries and compiles each to `<locale>/LC_MESSAGES/glib20.mo`; its `read_linguas` implementation reads the file directly. Preserve the complete set, not just a sampled language. Enabling the option alone does not prove installed files were retained or locale/domain lookup works after provider promotion; those need inventory and actual translated-message assertions.

## 4. Required Pango build-time output

Pango `pango/meson.build:87–96` invokes `gnome.mkenums` unconditionally; its generated C source is part of `libpango` (`:119–130`). Disabling GIR does not disable this GType enum generation. GLib installs a configured Python `glib-mkenums` script in `gobject/meson.build:89–111`, and `glib/meson.build:485` exports `${bindir}/glib-mkenums` through `glib-2.0.pc`.

Exact Meson `mesonbuild/modules/gnome.py:310–323, 2055` resolves this tool using the native `glib-2.0` dependency and `glib_mkenums` variable. The ephemeral provider must include that exact configured script, keep its interpreter valid inside the approved toolchain, and ensure the exported path resolves inside the provider. An outside-prefix fallback is a failure, even if it happens to generate valid-looking files. Keep generated installed `gobject/glib-enumtypes.h`, normal C headers and `.pc` files. A synthetic enum generation comparison can exercise this without needing a Pango build yet.

With GIR/docs/tests disabled, no other GLib generator use was found in Pango's production Meson files. The broader GLib CLI/generator install is not established as required for this narrow Pango consumer. If only selected tools are promoted, label the provider as a prerequisite subset rather than a complete GLib release installation.

## 5. Exact WeasyPrint 70.0 consumer boundary

All 69 Python modules were statically parsed. There are no `gi`, `girepository` or Python `gobject` imports; source/text search found no GIR/typelib loading. `weasyprint/text/ffi.py:469–525` uses CFFI direct `dlopen` and explicit C declarations for GObject, Pango, HarfBuzz, Fontconfig and PangoFT2. `text/fonts.py:99–105` creates a PangoFT2 font map and applies the Fontconfig configuration. These calls require the native libraries and their data/dependency closure, not generated introspection bindings.

Pango 1.58.2 directly requires GLib/GObject/GIO >= 2.88, FriBidi >= 1.0.6 and HarfBuzz >= 11.0.0 (`meson.build:210–238, 281–285`). Introspection metadata generation is separately gated (`:533–540`). Runtime C sources examined do not load GIRepository metadata.

Critical preservation requirements:

- Explicitly enable Fontconfig on macOS. Pango `meson.build:258–261` disables automatic Fontconfig selection on Darwin; leaving the default can remove the required FT2 path.
- Explicitly require and verify Fontconfig >= 2.17.0 and FreeType. `build_pangoft2` depends on both being found (`:330–335`); PangoFT2 contains the `pango_fc_*` and `pango_ft2_*` entry points WeasyPrint calls. Verify the feature result and actual dylib, not just command-line options.
- Keep HarfBuzz subset and vector deliberately. WeasyPrint allows them to fail loading, but subset absence changes subsetting to fontTools (`pdf/fonts.py:204–217`), while vector absence loses COLR color-glyph rendering (`pdf/fonts.py:102–109`, `text/fonts.py:369–375`). For that vector feature WeasyPrint itself calls for HarfBuzz 13+; Pango's 11.0 minimum alone is not enough to establish it.
- Keep Fontconfig configuration/fonts/cache behavior and the intended locale/Unicode/text-shaping behavior. Missing font configuration is warned about in `text/fonts.py:29–74`; falling back to host fonts would not prove a relocatable provider.
- Do not sweep additional runtime options into the “development exclusions”: disabling libthai changes Thai break analysis (`pango/break-thai.c:63–115`); disabling Cairo removes PangoCairo capability even though this WeasyPrint wheel does not directly load it. Such feature changes need explicit scope rather than inference from absence of a CFFI load.
- `documentation=false`, `man-pages=false`, `build-testsuite=false`, `build-examples=false`, `introspection=disabled` and `sysprof=disabled` have the narrow omissions described above. Pango's own `pango-trace-private.h` also compiles trace calls away without sysprof. They do not authorize deleting the C enum generator or runtime backends.

Suggested accurate exclusion statement:

> This prerequisite build retains the native C library interfaces and NLS/catalog inputs required by the pinned Pango/WeasyPrint CFFI path. It omits generated API/manual documentation, upstream test/example installations, generated GIR/typelib binding metadata, and optional profiling instrumentation. Introspection-based bindings and profiling are outside this candidate's tested feature boundary. The provider includes the GLib enum generator required to build Pango; it is not yet a full release installation or a rendering/relocation pass.

## Verification still required before a next execution

Independently review exact candidate bytes and all effective build/install options, then obtain root GO through the sole publisher. Confirm the public/standard/no-storage/no-access workflow guards. Verify the promoted glib-mkenums path/interpreter, six runtime libraries, all headers/pkg-config metadata, all 102 catalog outputs, synthetic native symbol/origin/GObject-libffi/GModule/GIO/translation assertions, and absence of host-provider contamination. Later Pango/WeasyPrint rendering, real models, relocation and release are separate unproved stages. This report changed no GitHub object or setting and used no user Mac.

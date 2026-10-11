# Runtime license gaps: exact-version supplementary evidence

2026-10-11 UTC. Static review only; no package or bundled executable ran. Existing frozen stage-A and runtime files were not changed.

## Result

All seven missing **top-level** license texts have been sourced from official, exact release-tag commits and retained with SHA-256 and Git-blob verification. The four pure-Python distributions have their project notice gaps supplemented. The three distributions containing native code still need complete native/dependency and redistribution review. This is not a legal-compatibility or release approval.

**Material blocker:** the selected `pypandoc_binary-1.17-py3-none-macosx_11_0_arm64.whl` actually contains a thin **x86_64** Pandoc executable. Its wheel label does not establish native Apple-Silicon compatibility.

## Exact sources

| Distribution | Project license | Exact upstream commit | License SHA-256 | Wheel source identity |
|---|---|---|---|---|
| langchain-community 0.4.2 | MIT | [7c10a5fa327f](https://github.com/langchain-ai/langchain-community/tree/7c10a5fa327f6aaaf7c932822a9e5d144891406e) | `a01dcffdc1291b4043f2a81d249a9f3e45c9036f2308c9cdfeefe18371371e80` | 1204 .py/.pyi match; 0 unmatched |
| langchain-text-splitters 1.1.2 | MIT | [58c4e5bbdd9d](https://github.com/langchain-ai/langchain/tree/58c4e5bbdd9d18d7fe7ec83b5a05477d06fe2a8e) | `4ec67e4ca6e6721dba849b2ca82261597c86a61ee214bbf21416006b7b2d0478` | 13 .py/.pyi match; 0 unmatched |
| langsmith 0.14.1 | MIT | [c51e72202613](https://github.com/langchain-ai/langsmith-sdk/tree/c51e722026138478b728884d9a3b504ef2ba8ea0) | `34e0b9842c7a31d34e53bc7eb224e81e07a34996106e029bbc72dea2d449f496` | 305 .py/.pyi match; 0 unmatched |
| loguru 0.7.3 | MIT | [ae3bfd1b85b6](https://github.com/Delgan/loguru/tree/ae3bfd1b85b6b4a3db535f69b975687c79498be4) | `b35d026cc7aca9d5859a02eb87ddf7a386a24c986838651bd1f283f94e003327` | 20 .py/.pyi match; 0 unmatched |
| primp 2.0.1 | MIT | [cf29cd94f339](https://github.com/deedy5/primp/tree/cf29cd94f339c1a69ec7f271f532f0f2411aa06e) | `64f0fdb426abd21f75b48e2ff93b9976b8c374bab3538af33d3c6d3f7c7efae7` | 1 .py/.pyi match; 1 unmatched |
| pypandoc-binary 1.17 | MIT | [51af11f47a78](https://github.com/JessicaTegner/pypandoc/tree/51af11f47a783e31dab230269527d02f6fe08a20) | `7e20c0e8f3d425c66500ab55508393f80f6bddb29fed599c13d166ecb863758c` | 6 .py/.pyi match; 0 unmatched |
| tokenizers 0.23.2 | Apache-2.0 | [88a4498ad4ea](https://github.com/huggingface/tokenizers/tree/88a4498ad4ea1a9487b0a9b0ff881383fd5a06a3) | `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4` | 25 .py/.pyi match; 0 unmatched |

The source checks recompute each relevant wheel member’s Git blob SHA-1 and compare it with the official tree at the release commit. The 1,204 community, 13 text-splitters, 305 langsmith, 20 loguru, six pypandoc and 25 tokenizers Python/stub files all match. Primp’s stub matches; its tiny generated import wrapper has no source-tree counterpart. Source archives and manifests provide additional Primp evidence. These checks do not reproduce native binaries.

Release tags are `libs/community/v0.4.2`, `langchain-text-splitters==1.1.2`, `v0.14.1`, `0.7.3`, `v2.0.1`, `v1.17` and `v0.23.2`, respectively. Official PyPI metadata links these packages to the corresponding repositories, and the selected wheel filenames/hashes/sizes match the proposal and locally verified bytes.

All copied upstream files are under `runtime-license-supplements/<project>/upstream/`. Full immutable URLs, SHA-256s, sizes and Git blob IDs are in `runtime-license-supplements/upstream-text-inventory.json`. The report JSON carries every selected wheel hash.

## Pandoc: separate wrapper and executable review

- Pypandoc 1.17’s wrapper is MIT. The bundled program identifies as Pandoc 3.9 through `pandoc-3.9-inplace` strings; no `--version` was invoked.
- Pandoc 3.9’s [official COPYRIGHT](https://github.com/jgm/pandoc/blob/19c1f6552b12c70741674f509f8064ae506f29db/COPYRIGHT) and [COPYING](https://github.com/jgm/pandoc/blob/19c1f6552b12c70741674f509f8064ae506f29db/COPYING.md) establish GPL-2.0-or-later, with separately described component terms. Both full texts are retained.
- Exact bundled member: `pypandoc/files/pandoc`, 119,565,632 bytes, SHA-256 `d7b1e75cd20ee6a788a1399492be07d4559949e18e55f34cfc5c91807fdfa90d`.
- Header magic `0xfeedfacf`, CPU type `0x01000007`, CPU subtype `0x3`: a thin x86_64 executable, not arm64 or universal. Primp and tokenizers’ native headers separately do identify as arm64.
- The [v1.17 build workflow](https://github.com/JessicaTegner/pypandoc/blob/51af11f47a783e31dab230269527d02f6fe08a20/.github/workflows/ci.yaml) invokes the downloader’s default `latest` and declares both Mac wheel architectures. It does not pin a Pandoc version or digest at that call. This is supporting provenance, not proof that an unexamined upstream release archive is byte-identical.
- The [official Pandoc 3.9 release](https://github.com/jgm/pandoc/releases/tag/3.9) lists separate arm64 and x86_64 Mac archives/installers. Their filenames, sizes and provider SHA-256 digests were recorded only; no native artifact was downloaded or substituted.

### Source-delivery / source-offer inventory

The wheel has six wrapper Python files, one native executable and four metadata files. It contains neither complete Pandoc source nor a written source offer nor a standalone Pandoc license/notice file. The upstream notice points to the [3.9 source tree](https://github.com/jgm/pandoc/tree/3.9) and the [3.9 Hackage source archive](https://hackage.haskell.org/package/pandoc-3.9/pandoc-3.9.tar.gz). Exact-commit cabal/stack manifests and macOS packaging scripts are preserved.

Before redistribution, choose and satisfy the applicable corresponding-source route under the chosen GPL version for the actual shipped binary, including relevant dependency sources, modifications and build/install scripts. An upstream source URL is recorded evidence; it is not treated as a completed source-delivery plan or an invented written offer. The exact native binary’s full build provenance and dependency closure remain open.

The retained Pandoc COPYRIGHT covers GPL module notices, BSD-3-Clause `pandoc-types`, dual-licensed data templates, the embedded Lua MIT text, a dzslides WTFPL declaration and additional copyrights. The dzslides declaration is not itself the full WTFPL text. The COPYRIGHT also has a WASM MIT notice; retention does not assert that WASM content is present in the Mac executable. It is not proven to exhaust all statically linked Haskell/C dependency notices.

No blanket conclusion is made that GPL Pandoc makes the entire app incompatible. Review the actual process boundary, packaging and licensing arrangement. The current mislabeled x86_64 payload is independently unsuitable as evidence of a native-arm64 package.

## Remaining native notices

- **Primp 2.0.1:** retained root MIT plus all release-tree LICENSE variants for vendored primp-h2 and primp-rustls. The source lock records 423 packages, including cryptography/compression candidates such as aws-lc, ring and zstd. This is a superset including optional/build/test/platform dependencies, not a linked-wheel SBOM. Exact target/features and actual bundled third-party notices remain open.
- **Tokenizers 0.23.2:** the official Apache-2.0 license also matches the exact-version sdist’s tokenizers/LICENSE. The bindings source lock records 153 packages. Source defaults include `onig` and `esaxx_fast` (C/C++), so the root Apache text alone does not close native notices.
- **Pypandoc-binary 1.17:** wrapper MIT and Pandoc notices are now available; architecture correction, complete source-delivery and native third-party notice closure remain.

## Evidence and checks

- `runtime-license-gap-review.json`: exact inputs, all license hashes/URLs, status per wheel, Pandoc inventory and remaining actions
- `runtime-license-supplements/upstream-text-inventory.json`: every retained upstream file, SHA-256 and matching Git blob
- `runtime-license-supplements/wheel-tag-source-comparison.json`: per-member source-hash checks and native member hashes/CPU types
- `runtime-license-supplements/pypi-source-inventory.json` and `sdist-tag-source-comparison.json`: verified exact-version source archives and release comparisons
- `runtime-license-supplements/pandoc-3.9/bundled-binary-static-evidence.json`: static header/load-command/embedded-string observations
- `runtime-license-supplements/{primp-2.0.1,tokenizers-0.23.2}/cargo-lock-inventory.json`: source dependency inventories

Source archives are retained under `audit/engine-ci/runtime-license-source-archives/`; only archive/text readers were used. The large community sdist was not downloaded because all 1,204 wheel Python members matched the exact release tree. PyPI-published provenance for langsmith, loguru and pypandoc-binary was retained and decoded; subject hashes match the locally checked wheels, but signatures, certificate chains and transparency proofs were not independently verified.

No installation, package import, native loading, executable invocation, model download, bottle download, remote write or input substitution occurred.

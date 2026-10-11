# Standalone launcher and non-executing assembly candidate

Preparation only. These first-party sources are not an activated CI workflow, an execution approval, a distribution build or a claim of native-feature completeness. No prior frozen artifact, production wrapper, PDM lock or upstream source is modified by these helpers.

## Exact runtime shape

- `DeepdeskEngine.app/Contents/MacOS/DeepdeskEngine`: compiled `launcher.c`
- `DeepdeskEngine.app/Contents/Resources/Python/`: complete, directly installed standalone CPython prefix, including every reviewed wheel member
- `DeepdeskEngine.app/Contents/Resources/Python/bin/python3.12`: fixed native interpreter; a relative alias may target another regular executable directly in this same `bin` directory
- `DeepdeskEngine.app/Contents/Resources/engine_entry.py`: unchanged wrapper by default, SHA-256 `c150823f009f0a9f004923413444894e95f3681d81f0fb94537be75cf7f778b9`; the separately reviewed candidate wrapper requires an explicit exact hash as described below
- `DeepdeskEngine.app/Contents/Info.plist`: generated candidate metadata, identifier `app.deepdesk.engine`; not a signing or release receipt

The native caller can keep the existing enclosing path `Deepdesk.app/Contents/Helpers/DeepdeskEngine.app/Contents/MacOS/DeepdeskEngine`. This candidate does not populate inference resources or the separate native curated-model catalog.

The launcher gets its own executable path from `_NSGetExecutablePath` on macOS and resolves it canonically. It never derives it from `argv[0]`, cwd, PATH or an environment-selected program. It validates its fixed `Contents/MacOS` suffix and requires structural directories to be real directories. It resolves fixed interpreter/wrapper paths component by component, refuses absolute, escaping, missing or looping symlinks, and catches escape-and-return paths through a directory symlink followed by `..`. The wrapper must remain the fixed regular file; an internal wrapper alias is also refused.

Only no arguments, exactly `--self-test`, or the separately named candidate flag `--core-self-test` are accepted. The launcher replaces itself using absolute `execve` with `[interpreter, '-I', '-B', wrapper, optional fixed test flag]`, preserving the supervisor-owned PID. The core flag is not a fallback: the candidate wrapper must explicitly implement it and report its reduced scope while full `--self-test` remains unchanged. The default frozen wrapper does not implement the core flag and will reject it; a caller must not silently substitute test modes. Its failure status is 78 with fixed diagnostics that do not disclose supplied paths or environment values. A minimal native-header gate rejects text/shebang dispatch. The production branch requires a thin little-endian 64-bit ARM64 Mach-O executable, matching the exact approved CPython archive. ELF is accepted only in the Linux synthetic-test branch; universal/fat images are not silently substituted. This quick header gate does not replace complete Mach-O/load-command/code-signature inspection.

### `@executable_path` and image placement

After `execve`, the main executable is `Contents/Resources/Python/bin/python3.12` (or its canonical same-directory target). Therefore every interpreter/dylib `@executable_path` calculation uses `Contents/Resources/Python/bin`, never `Contents/MacOS`. The launcher does not copy or move the interpreter to `MacOS`, flatten its `lib` directory, change cwd, or rewrite load commands. A future static graph audit must use this interpreter root for its load closure and separately use each native CLI executable's own directory when that CLI runs as a main program. Actual loaded-image path evidence on arm64 macOS remains required.

## Environment boundary

The `execve` environment is constructed from an explicit allowlist:

- `HOME`, `TMPDIR`, `LANG`, `LC_ALL`, `LC_CTYPE`, `TZ`
- `LDR_WEB_HOST`, `LDR_WEB_PORT`, `LDR_DATA_DIR`
- `DEEPDESK_INSTANCE_NONCE`, `DEEPDESK_INFERENCE_API_KEY`, `DEEPDESK_INFERENCE_URL`, `DEEPDESK_INFERENCE_MODEL`

All other names are dropped, including every `PYTHON*`, `DYLD*`, `LD_*`, `__PYVENV_LAUNCHER__`, venv/Conda/PIP selectors, PATH, arbitrary `LDR_*` overrides, executable selectors, Fontconfig/libmagic/Pandoc/WeasyPrint loader overrides, and incoming `HF_HUB_OFFLINE` / `TRANSFORMERS_OFFLINE`. No offline flag is added to production research. The unchanged wrapper itself sets both offline flags to `1` in `--self-test` before its package checks; actual egress denial still requires the separately reviewed sandbox.

Removing inherited PATH prevents that value from choosing the interpreter; it does not make the entire Python application free of host CLI fallback. Standard library/process APIs may use a platform-default command search when PATH is absent. Provider/driver payloads are retained but their complete external-tool behavior is unproved. Exact bundled native loader/data maps, native CLI launch paths, Fontconfig resources and browser-resource decisions remain unimplemented gates. Do not claim these features work from this launcher test.

A program cannot scrub injection variables before its own dynamic loader runs. The native supervisor must already supply a sanitized environment; production signing/hardened-runtime policy needs separate review. This launcher narrows the environment of the interpreter it executes, but is not an anti-tampering boundary, sandbox, signature verifier or defense against a same-user concurrent filesystem attacker. Hashes are enforced during assembly and by the future sealed-tree checks, not reimplemented in this C launcher.

## Assembly API and preservation

`assemble.py` imports only host standard-library modules. It does not download, install, import or execute code from the payload, invoke an interpreter, compile, sign, rewrite load commands, or run CI. Its library API is:

`assemble_bundle(prefix, wrapper, launcher, destination, *, expected_prefix_manifest, expected_launcher_sha256, expected_wrapper_sha256=WRAPPER_SHA256)`

`inventory_tree(root)` returns schema `deepdesk-content-v1` with sorted `entries`. Each has a relative `path` (including `.`) and integer POSIX `mode`; directories have `kind='directory'`, regular files have `kind='file'`, `size` and `sha256`, and symbolic links have `kind='symlink'` and their literal relative `target`.

The complete caller-provided prefix manifest must match the actual input before copying. A newly generated manifest alone is not approval or proof of interpreter/wheel provenance: the future caller must pin an independently reviewed exact manifest to the complete input receipt. The compiled launcher's expected hash must likewise be tied to an exact source/compiler/SDK/flags receipt. Wrapper bytes default to the frozen hash above. Selecting a candidate wrapper requires an explicit `expected_wrapper_sha256` from that candidate's independently reviewed receipt; no hash is inferred from the provided file, and neither an automatic fallback nor a mutable feature-ready flag is accepted. The returned receipt records the exact selected wrapper hash. Supplying an arbitrary freshly calculated hash does not establish review or approval. Common venv markers, redirected structural directories, missing standard-library members, non-executable interpreters, privileged mode bits, special files and unsafe symlinks are refused.

The helper creates an absent output named `DeepdeskEngine.app` exclusively; it never merges into or overwrites an existing output, symlink or input prefix. It uses symlink-preserving, metadata-preserving copies and retains every prefix member, including distribution metadata, hidden resources, headers, licenses, providers, build tools and browser/driver package members. It performs no pruning. Source and staged full manifests are compared again after copy, alongside wrapper/launcher hashes and modes. A failure removes only the helper's newly created partial output, including copied read-only directories. Caller inputs and prior outputs are not cleaned up.

The returned receipt includes the full bundle manifest and stable canonical-JSON SHA-256 values. It always states `native_features_complete=false`, `ready_for_execution=false` and `payload_execution_performed=false`; no caller flag can turn these into success gates. This receipt describes preservation of file bytes, POSIX modes and relative link targets. Ownership, hardlink topology, ACLs, xattrs/resource forks and final code signatures are not independently proved by this manifest, even where `copy2` may preserve some metadata.

Inputs and output parents must be exclusively controlled and not concurrently mutated. Repeated checks catch ordinary drift, but this is not a race-resistant or privileged installer. The assembly helper has no independent wall-clock/process-group/disk-space monitor. A future reviewed outer stage must enforce its deadline, measured expanded-byte/work cap and cleanup, and must refuse to start if inputs do not fit those bounds. No 12-GiB-fit or macOS runtime claim follows from these local synthetic tests.

## Focused verification

Run only the first-party synthetic tests with the host's existing Python:

- `python3 -B -m unittest discover -s packaging/standalone-engine-candidate -p 'test_assemble.py' -v`
- `python3 -B -m unittest discover -s packaging/standalone-engine-candidate -p 'test_launcher.py' -v`

The launcher tests use `/usr/bin/clang` or `/usr/bin/cc`, compile only this first-party launcher and a first-party C probe, and execute a compiled synthetic interpreter. They never execute the production wrapper, an actual downloaded CPython archive, wheels, browser assets or third-party hooks. The wrapper is read only to prove copy/hash preservation. The default frozen hash and explicit candidate-wrapper hash paths are both tested without executing either wrapper. The macOS launcher probe requires an arm64 macOS host; the current local result uses Linux. A separate pure-header C probe tests acceptance of ARM64 executable headers and rejection of x86_64, ARM32, dylib, non-thin and shebang headers without executing those bytes.

Coverage includes all-member/mode/link preservation; relocation with spaces and Unicode and no original path; exact arguments and preserved PID; environment stripping with managed inputs retained; venv, missing-resource, non-executable, path-escape, escape-and-return, link-loop, wrapper/hash, shebang and existing-output negative cases; and corruption/source-drift cleanup. These remain synthetic helper proofs. Arm64 macOS `_NSGetExecutablePath`, dyld/RPATH resolution, loaded native-image closure, SQLCipher, PDF/libmagic, real application lifecycle, network/HTTP integration, signatures/notarization and redistribution clearance have not been established here.

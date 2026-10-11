# Complete installed runtime + authenticated synthetic API: proposed stage B1

Prepared 2026-10-11 UTC. **Execution is unapproved.** The receipt is fail-closed. This is a new scope beyond the passed source-wheel/SQLCipher stage A.

## Actual stage-A evidence

GitHub run [38099846861](https://github.com/Emin-dev/deepdesk/actions/runs/38099846861), commit `80b63b943444f280946ed10fdd2c2458f7a1871d`, passed on macOS 26.6.2 arm64 with the pinned CPython 3.12.15. Independently re-read job status, job logs and empty artifact list. The five reviewed source wheels built and all four real SQLCipher assertions passed: encrypted header, correct-key reopen, wrong-key refusal, ordinary-SQLite refusal. Saved log SHA-256: `ccbdbd6d7cdaff2a4a0e4e09563dfc34f293708e24ec79b38facbdb32fe5e0de`.

`stage-a-observed-wheel-hashes.json` records actual outputs. One successful build is not proof of reproducible wheel archives.

## Proposed result and exact scope

1. Download the exact 276 unique distribution archives already statically inspected: 541,910,864 bytes. Add the separately pinned 25,165,569-byte official Astral CPython archive. No dependency resolver may fetch anything else.
2. Rebuild the same four small source distributions and patched upstream application with the reviewed backend/build tools, offline. Capture source file hashes **before** build. Every wheel's installed non-metadata byte must equal that approved source payload; the complete expected package resource set is required. Validate exact package identity/version, pure-Python tag, metadata destinations, no new scripts/native payload/`.pth`, and exact required source LICENSE/NOTICE destinations and hashes. The application entry-point file must contain exactly the reviewed ldr-web and ldr-mcp declarations.
3. Report whether each archive hash equals stage A. A mismatch is visible and does not silently weaken a byte-reproducibility claim: there is no such claim. Reviewed source provenance and checked installed payloads govern this build recipe. Hash-lock each inspected same-run output into the ephemeral runtime lock before installation. Emit archive and generated-metadata hashes in the bounded receipt.
4. Install all 268 runtime dependencies and the app, with all ten build tools retained for exact provenance. Two build/runtime overlaps yield 277 unique installed identities, excluding interpreter-bundled pip. All inputs are local hash-verified wheels; no source execution during install. Run offline `pip check` and exact installed identity/version census.
5. Import the explicitly listed major Python/native-wheel packages, including the distinct PyPI Torch, without creating a model or running tensor inference. Verify the reviewed wrapper's physical provider source/default/template/static resources and repeat all four SQLCipher checks.
6. Run the unchanged production wrapper through the pinned installed interpreter. Test real auth, CSRF, account-context isolation and encrypted database persistence with a fresh synthetic account, then read a clearly labeled synthetic persisted report. This validates an installed engine, not a frozen app.

No PyInstaller hook/spec runs. No external native bottle, model weight, inference runtime, browser payload, provider request, signing identity, DMG, release or artifact upload is involved. All upstream features remain installed; absent native-library support is neither hidden nor replaced.

## Explicit Torch packaging decision

Immutable upstream `pdm.lock` remains SHA-256 `12f4ec96700e7ccf44ed29ae621d8737544b9ac9a8ebeccf2cf3a1a58a887f00`.

The original CPU-index Torch 2.14.0 wheel hash is `ab7e226c18d3cbc134dfa952d18ab1df202055dd33446837c8fd050ad449e6f5`. Its denied linked artifact was not retrieved, retried by another route, or treated as equivalent to PyPI.

This lane proposes a **new explicit packaging input**: official PyPI `torch-2.14.0-cp312-cp312-macosx_14_0_arm64.whl`, 127,303,200 bytes, SHA-256 `c1f844f1c750e87df4b68bc3afbc0e2b0c7ef19d7b8f666e48bdcf6a0c4f0056`. The complete proposed input manifest is `all-pypi-input-proposal.json`, SHA-256 `ec0733c361635536914d05cbd797e0c04802dadaff71acf9994bcc7e0ce08fda`. Official PyTorch installation documentation uses PyPI on macOS, but that is provenance/rationale, not compatibility proof. Eight inspected native headers are arm64; notice files are retained. The approval receipt requires the explicit distinct-origin selection, and actual import/version validation is part of this proposed run.

## Synthetic API contract

- Fresh temporary HOME/data; no user account, database, provider key, or inherited launch credential.
- Random generated fixture username/password and process nonce. Initial health sends **no nonce or cookie**; only after the owned live child's response identity matches may later requests send the nonce.
- Unauthorized history denial; real registration and cookie session; anonymous/authenticated CSRF refresh; wrong-token and wrong-account-context rejection; only an **empty** query request, which pinned upstream rejects before research startup; assert history remains empty.
- Logout and owned shutdown. While stopped, a CI-only helper opens that synthetic account with the actual SQLCipher/ORM and requires an empty research/resource/queue state before writing one completed synthetic record and `.invalid` citation. Its credentials travel only through bounded stdin, never process arguments or logs. The helper is not added to the production app.
- Restart, unauthenticated persisted-report denial, wrong-password refusal, correct-password login, explicit username check, report/status/history/settings reads, already-terminal stop, logout and owned shutdown.
- Login/lifespan still perform ordinary upstream local background work: settings migration, library initialization, scheduler setup, encrypted backup, orphan reconciliation, queue registration and cleanup/news threads. The fresh empty account and completed-only seed provide no runnable research job. Kernel networking is restricted to the one fixture server port.
- This Python client does not certify native URLSession/Keychain behavior. Already-terminal stop does not establish active-job cancellation. No valid research job, provider enumeration or model endpoint is requested.

## Containment, cost and failure bounds

Candidate dedicated branch: `engine-runtime-api-ci`, based on `80b63b943444f280946ed10fdd2c2458f7a1871d`. The push trigger and job guard require exactly public `Emin-dev/deepdesk` and that branch. Pinned checkout action, read-only contents permission and no persisted checkout credentials. Standard `macos-26`; no cache/upload actions or paid/larger runner.

25-minute job hard limit; 20-minute inner deadline; 12-GiB continuously checked fresh work limit; at least 16 GiB initial free space. Actual inspected package expansion is 1,919,499,023 bytes before Python/venvs/copies; the proposed limit includes these copies. Downloads are pinned and deadline/size/hash bounded. Subprocess output is privately captured with a combined 2-MiB limit and never forwarded raw, so dependency logs cannot issue workflow commands. HTTP responses are bounded to 2 MiB. Synthetic stdin is capped at 16 KiB. The seed subtree budget is 128 MiB.

Build/install/import stages use kernel network denial. API stages allow only the chosen `127.0.0.1:PORT`; an external documentation-network target and a different loopback port must both return EPERM/EACCES, never a timeout or connection refusal. All profiles deny writes outside the fresh work tree and to immutable input/runtime trees. A separate control-tree and protected-input write probe must fail. `/opt/homebrew`, `/usr/local` and external Python frameworks are read-denied, with an actual Homebrew-path denial canary. No sandbox fallback is allowed.

The controller owns a new process group and removes leftover descendants after each bounded command. Nested fixture/server/seed children remain in that group. This does not claim kernel prevention of arbitrary malicious session escape; reviewed source provenance and the no-secrets, ephemeral runner remain part of the trust boundary. Runtime and immutable inputs are hashed before and after import/API execution. The production wrapper/source and control helpers remain outside downloaded-code write access.

## Remaining independent-review and acceptance gates

- Independently review final helper/profile/workflow bytes, source payload contract, receipt coverage, exact Torch override and license manifest. Record a new explicit scope approval before activation; stage-A approval is insufficient.
- Only helper syntax, 28 bounded/source-wheel synthetic tests, 11 transport/handshake tests and the prior 16 helper tests have run locally. These are Linux first-party checks, not macOS/backend success.
- License provenance is tied to actual package archives and authoritative supplementary texts. Presence of a root license is not complete transitive/native redistribution clearance. No runtime binary is distributed by this lane.
- **Native export gap:** the arm64-labelled pypandoc-binary 1.17 wheel contains an x86_64 Pandoc executable, so it cannot satisfy a native-only standalone export stack. Its replacement, notices and source-delivery obligations require a separate reviewed selection; nothing is silently swapped here.
- PDF/WeasyPrint Pango/font stack, libmagic and its `magic.mgc`, native relocation/architecture closure, browser availability and frozen-bundle cold start remain untested. See `NATIVE-LIBRARY-PROPOSAL.md`; no Homebrew fallback is permitted in this lane.
- Real model loading/inference, research/citations, UI-to-engine integration, model switching, clean-machine no-setup launch, signing/notarization, all-in-one DMG and download verification remain later gates. The sole final real inference run stays on the M5.

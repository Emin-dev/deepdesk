# Native checkpoint verification

Initial source checkpoint was prepared on 2026-10-10 in Linux. The subsequent reviewed signing-API correction passed 28 XCTest tests (15 core, 13 identity/download) and arm64 release compilation on macOS 26.6.2 / Xcode 26.6 / Swift 6.3.3 at [commit 3f35953a](https://github.com/Emin-dev/deepdesk/actions/runs/38097545856).

The current synthetic UI-host changes have not yet been compiled or launched. No model download, real account creation, Keychain persistence, or inference was performed by these checks.

## Passed locally

- Python JSON parsing of both shipped and test catalog copies; copies match.
- Catalog deduplication: two target choices reference 31 unique immutable files, 36,011,825,235 bytes combined. The shared draft is represented once per on-disk path.
- Info.plist parses; target minimum is macOS 26.4.
- `bash -n scripts/build-app.sh`.
- Independent static security review was applied to cache paths, bounded resume metadata, no-follow regular-file reads/writes, duplicate setup/activation prevention, exact runtime model identity, token casing, transient inference-key propagation, and process ownership retention.

## Not yet established

- Compilation/tests of the subsequent UI-host changes, resource-bundle loading, or native UI/accessibility behavior. The baseline source compilation and 28 mock tests passed as recorded above.
- Real URLSession cookie behavior against the actual Python engine. Core transport tests are mocks; do not count them as live integration.
- Keychain persistence, unlock/denial UI, application identity upgrades, signing entitlements, or data recovery.
- Splash runtime execution, both actual 27B models, thinking output, sustained memory usage, model switch teardown, GPU-child cleanup, pause/resume against live large files, and live web search.
- Signed app build, notarization, mounted DMG install, cold start, or update installation.

## Required integration contracts

- Research helper must apply its nonce/origin/Host middleware and accept the three `DEEPDESK_INFERENCE_*` launch variables. API secrets must be injected into the provider only in memory and excluded from persisted snapshots.
- Managed search defaults must register the exact built-in `ddg` engine before the client selects it. No `duckduckgo` ID guess and no silent alternative-engine fallback.
- Inference helper must establish its own process group before spawning Metal workers, emit its launch nonce on admitted responses, accept only the fixed loopback Host, and perform cleanup on SIGTERM.
- Inference source cache path is `Models/<component-id>/<filename>`; there is no extra literal `files` directory.
- The app bundle must include the SwiftPM `Deepdesk_Deepdesk.bundle`, curated full runtime manifest, Splash runtime, and both helper entrypoints.
- Signed Info.plist must include the real `DeepdeskSigningTeamID`; ad-hoc builds intentionally cannot bootstrap or read the production identity.

## Test gaps to close on macOS

Exercise interrupted downloads and hash failure, duplicate clicks, cancel while queued/running, sign-in expiry, a failed model switch, closing/reopening the main window, and quitting with an active research or model process. Confirm no orphaned group remains before another 27B model loads. The M1 CI machine can compile and run mocks; the final M3+ Mac test is needed for actual inference.

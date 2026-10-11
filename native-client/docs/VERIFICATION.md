# Native checkpoint verification

Source-only checkpoint prepared on 2026-10-10 in Linux. No macOS compile, UI launch, model download, account creation, or credential storage was performed.

## Passed locally

- Python JSON parsing of both shipped and test catalog copies; copies match.
- Catalog deduplication: two target choices reference 31 unique immutable files, 36,011,825,235 bytes combined. The shared draft is represented once per on-disk path.
- Info.plist parses; target minimum is macOS 26.4.
- `bash -n scripts/build-app.sh`.
- Independent static security review was applied to cache paths, bounded resume metadata, no-follow regular-file reads/writes, duplicate setup/activation prevention, exact runtime model identity, token casing, transient inference-key propagation, and process ownership retention.

## Not yet established

- `swift test`, SwiftUI compilation, resource-bundle loading, or native UI/accessibility behavior.
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

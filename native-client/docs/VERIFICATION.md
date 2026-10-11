# Native checkpoint verification

Initial source checkpoint was prepared on 2026-10-10 in Linux. The subsequent reviewed signing-API correction passed 28 XCTest tests (15 core, 13 identity/download) and arm64 release compilation on macOS 26.6.2 / Xcode 26.6 / Swift 6.3.3 at [commit 3f35953a](https://github.com/Emin-dev/deepdesk/actions/runs/38097545856).

The final synthetic UI checkpoint at [commit e69107a703e3ec789677433b63df2bdcc13e7945](https://github.com/Emin-dev/deepdesk/commit/e69107a703e3ec789677433b63df2bdcc13e7945) passed **all 28 core XCTest tests, all 6 synthetic UI tests, and arm64 release compilation** in [run 38100079182](https://github.com/Emin-dev/deepdesk/actions/runs/38100079182) on 2026-10-11. The tested source manifest SHA-256 was `dcf718f8513a976960ce0596d9448aabd0ffbb67599c3d93dee9a170ba2747dd`. Window resizing was exercised without a skip: the visible window width changed from 1000 to 984 points, at screen origin (12, 31).

All six allowlisted synthetic-window screenshot receipts were size/hash-verified and their pixels inspected. Horizontal clipping was corrected; light/dark controls and the pinned synthetic sheet labels were legible. Capture caveats remain: the macOS Dock overlaps part of a footer, and the report capture's yellow synthetic banner is partly covered by the toolbar. The test window title still identifies the synthetic host. These are limitations of the captured evidence, not proof of complete visual or accessibility coverage. No Actions artifacts were uploaded; the bounded synthetic images are in the public job logs.

The earlier [first UI run](https://github.com/Emin-dev/deepdesk/actions/runs/38098632449) passed 2 of 6 tests, and the [first correction](https://github.com/Emin-dev/deepdesk/actions/runs/38099207221) passed 5 of 6. The final run above supersedes those failed checkpoints for the tested source. No model download, real account creation, Keychain persistence, Python engine, inference, or real web research was performed by these synthetic checks.

## Passed locally

- Python JSON parsing of both shipped and test catalog copies; copies match.
- Catalog deduplication: two target choices reference 31 unique immutable files, 36,011,825,235 bytes combined. The shared draft is represented once per on-disk path.
- Info.plist parses; target minimum is macOS 26.4.
- `bash -n scripts/build-app.sh`.
- Independent static security review was applied to cache paths, bounded resume metadata, no-follow regular-file reads/writes, duplicate setup/activation prevention, exact runtime model identity, token casing, transient inference-key propagation, and process ownership retention.

## Not yet established

- Full production UI and accessibility behavior, including VoiceOver and a complete accessibility audit. The six isolated synthetic UI tests and six reviewed captures cover only the documented fixture flows.
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

Repeat the covered fixture flows against the real bundled runtime. Exercise interrupted live downloads and hash failure, duplicate clicks, cancel while queued/running, sign-in expiry, a failed model switch, closing/reopening the main window, and quitting with an active research or model process. Confirm no orphaned group remains before another 27B model loads. The M1 CI machine can compile and run mocks; the final M3+ Mac test is needed for actual inference.

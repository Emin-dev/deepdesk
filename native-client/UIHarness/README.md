# Synthetic native UI tests

This is a separate, permanently labeled test app. It compiles the same SwiftUI views and ResearchStore as Deepdesk with explicit memory-only research, identity, and model-download fixtures. It never runs the production app entrypoint. No launch argument, environment variable, or runtime switch enables fixtures in the production app.

The test host is sandboxed without network entitlements. It has no bundled helper, inference runtime, model weights, real credentials, or Keychain calls. Model verification returns only a host-private temporary path. Source links are intercepted inside the host. Fixture setup bypasses neither the release app's signing gate nor its hardware checks: it supplies separate in-memory services to the separate target. The inert process-supervisor objects are never started. All fixture questions and reports are synthetic.

## Verified synthetic checkpoint

[Commit e69107a703e3ec789677433b63df2bdcc13e7945](https://github.com/Emin-dev/deepdesk/commit/e69107a703e3ec789677433b63df2bdcc13e7945) passed **all 6 synthetic UI tests, all 28 core tests, and arm64 release compilation** in [run 38100079182](https://github.com/Emin-dev/deepdesk/actions/runs/38100079182) on 2026-10-11. The tested source manifest was `dcf718f8513a976960ce0596d9448aabd0ffbb67599c3d93dee9a170ba2747dd`. The real resize assertion passed without a skip: window width changed from 1000 to 984 points at visible origin (12, 31).

All six synthetic screenshot receipts were decoded, hash/size-verified, and visually inspected. The visible-screen fit resolved horizontal clipping, and the pinned synthetic sheet labels and light/dark controls were clear. Residual capture caveats are a Dock footer overlay and a yellow synthetic report banner partly covered by the toolbar; the synthetic window title remains visible. A window-rectangle capture can include intersecting system overlays. No Actions artifacts were uploaded; these bounded fixture-only pixels appear in public job logs.

Historical runs remain available: the [first run](https://github.com/Emin-dev/deepdesk/actions/runs/38098632449) passed 2 of 6 tests, and the [first correction](https://github.com/Emin-dev/deepdesk/actions/runs/38099207221) passed 5 of 6. The final tested commit above supersedes them. The current documentation-only checkpoint does not change that tested app or harness code.

## Passing synthetic coverage (not a production-runtime pass)

- First-use encryption disclosure must be accepted before setup.
- Splash is selected by default; model download progress, pause/resume, use, second-model error/retry, queued-download cancellation, sheet disappearance and reopening.
- Real shared ResearchStore start/poll/cancel and successful completion state transitions driven by a deterministic service.
- History selection with a distinct report/query from the stopped run and native report rendering; unsafe source URL is not clickable; safe source link is intercepted; no WebView.
- Research start failure, Command-Return and Command-N, labeled/hittable accessibility elements, resizing (separate explicit skip if the screen cannot accommodate it), light/dark appearance.
- Screenshots request the synthetic host window rectangle (system overlays can still intersect it) and are attached to the runner-local test result for internal visual inspection. The test does not establish full VoiceOver or accessibility-audit compliance.

## Run on a macOS 26.4+ arm64 Xcode 26 runner

```sh
bash native-client/UIHarness/run-ui-tests.sh "$RUNNER_TEMP/deepdesk-synthetic-ui"
```

`generate_project.py` creates a deterministic local Xcode project, with no downloads or third-party generator dependency. The host links the local DeepdeskCore package and references production view files directly. `run-ui-tests.sh` requires a new output directory and keeps logs and `.xcresult` there. Do not upload the host as a user-facing release artifact. Do not upload Actions artifacts or Library files. The optional reviewed `export-synthetic-screenshots.py RESULT.xcresult` helper emits only six allowlisted manual synthetic-window attachment names to logs, with SHA-256 receipts. These synthetic pixels are visible in public Actions logs. It locally exports attachments to a temporary directory, selects only named regular image files, emits resized JPEGs of at most 120 KiB each, and enforces a total 1 MiB log ceiling. Temporary exports are removed on exit. Unknown metadata layouts or oversized images are skipped; that leaves visual inspection unverified. No automatic desktop screenshots are emitted.

The reviewed CI uses a read-only macOS job using the existing selected Xcode, `swift test`, `swift build -c release`, then the command above. No signing secrets, model downloads, network account setup, or TCC/OS-security changes. UI automation requires the runner's already-supported Xcode test permissions; report any missing permission rather than weakening the host sandbox.

A pass establishes synthetic UI behavior only. Real encrypted registration, model loading, thinking, DuckDuckGo research, nested runtime signatures, app launch from DMG, and production signing remain separate integration gates.

Apple references: [XCUIElement](https://developer.apple.com/documentation/xcuiautomation/xcuielement), [XCUICoordinate](https://developer.apple.com/documentation/xcuiautomation/xcuicoordinate), [App Sandbox](https://developer.apple.com/documentation/security/app-sandbox).

# Synthetic native UI tests

This is a separate, permanently labeled test app. It compiles the same SwiftUI views and ResearchStore as Deepdesk with explicit memory-only research, identity, and model-download fixtures. It never runs the production app entrypoint. No launch argument, environment variable, or runtime switch enables fixtures in the production app.

The test host is sandboxed without network entitlements. It has no bundled helper, inference runtime, model weights, real credentials, or Keychain calls. Model verification returns only a host-private temporary path. Source links are intercepted inside the host. Fixture setup bypasses neither the release app's signing gate nor its hardware checks: it supplies separate in-memory services to the separate target. The inert process-supervisor objects are never started. All fixture questions and reports are synthetic.

## Planned coverage (not a test result)

- First-use encryption disclosure must be accepted before setup.
- Splash is selected by default; model download progress, pause/resume, use, second-model error/retry, queued-download cancellation, sheet disappearance and reopening.
- Real shared ResearchStore start/poll/cancel and successful completion state transitions driven by a deterministic service.
- History selection with a distinct report/query from the stopped run and native report rendering; unsafe source URL is not clickable; safe source link is intercepted; no WebView.
- Research start failure, Command-Return and Command-N, labeled/hittable accessibility elements, resizing (separate explicit skip if the screen cannot accommodate it), light/dark appearance.
- Screenshots capture only the synthetic host window and are attached to the runner-local test result for internal visual inspection. The test does not establish full VoiceOver or accessibility-audit compliance.

## Run on a macOS 26.4+ arm64 Xcode 26 runner

```sh
bash native-client/UIHarness/run-ui-tests.sh "$RUNNER_TEMP/deepdesk-synthetic-ui"
```

`generate_project.py` creates a deterministic local Xcode project, with no downloads or third-party generator dependency. The host links the local DeepdeskCore package and references production view files directly. `run-ui-tests.sh` requires a new output directory and keeps logs and `.xcresult` there. Do not upload the host as a user-facing release artifact. Do not upload Actions artifacts or Library files. The optional reviewed `export-synthetic-screenshots.py RESULT.xcresult` helper emits only six allowlisted manual synthetic-window attachment names to logs, with SHA-256 receipts. These synthetic pixels are visible in public Actions logs. It locally exports attachments to a temporary directory, selects only named regular image files, emits resized JPEGs of at most 120 KiB each, and enforces a total 1 MiB log ceiling. Temporary exports are removed on exit. Unknown metadata layouts or oversized images are skipped; that leaves visual inspection unverified. No automatic desktop screenshots are emitted.

Proposed CI expansion: a read-only macOS job using the existing selected Xcode, `swift test`, `swift build -c release`, then the command above. No signing secrets, model downloads, network account setup, or TCC/OS-security changes. UI automation requires the runner's already-supported Xcode test permissions; report any missing permission rather than weakening the host sandbox.

A pass establishes synthetic UI behavior only. Real encrypted registration, model loading, thinking, DuckDuckGo research, nested runtime signatures, app launch from DMG, and production signing remain separate integration gates.

Apple references: [XCUIElement](https://developer.apple.com/documentation/xcuiautomation/xcuielement), [XCUICoordinate](https://developer.apple.com/documentation/xcuiautomation/xcuicoordinate), [App Sandbox](https://developer.apple.com/documentation/security/app-sandbox).

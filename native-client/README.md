# Deepdesk native macOS client

Deepdesk uses a SwiftUI-only interface and keeps the upstream Local Deep Research Python engine. There is no WebView, Electron shell, external Ollama setup, API-key editor, or user-facing Settings page.

## Supported target

- Apple Silicon **M3 or newer**, **macOS 26.4 or newer** for the embedded Splash 1.3.1 runtime.
- The two 27B model entries conservatively require at least **36 GiB** of unified memory; **48 GiB** is recommended by the researched catalog. Runtime admission remains authoritative.
- Build with Xcode 26.4+ and its macOS SDK. The app is arm64 only. The SwiftUI material fallback is an implementation guard, not a promise of support for older macOS releases.

## User flow

1. Review the local encrypted-research disclosure. A properly signed production build creates and verifies an app-scoped Keychain identity, then uses the real upstream session/CSRF registration and login flow.
2. Choose a built-in model. **Qwen3.8 27B (Splash)** is the default; **Qwen3.8 27B Uncensored** is the other option. Models download inside the app from pinned public Hugging Face revisions.
3. Deepdesk verifies SHA-256 for every target/draft file, loads one target through the embedded runtime, and verifies the served model ID. The shared draft downloads only once.
4. Ask a question and allow external web searches. This no-key configuration selects the built-in **DuckDuckGo (`ddg`)** engine with the upstream source-based research strategy. The managed engine must include its `ddg` default configuration, which upstream lacks. Search outages, blocks, and rate limits are shown as failures; there is no silent Wikipedia fallback or claim of offline research.
5. Follow real progress, stop a run cooperatively, revisit history, read native report blocks, and open individually validated source links.

Thinking is on by default for the verified model templates and Splash `xhigh` configuration. The UI does not synthesize a reasoning stream. Only one model target may remain resident during a switch.

## Runtime boundary

The Python research helper is expected at:

`Deepdesk.app/Contents/Helpers/DeepdeskEngine.app/Contents/MacOS/DeepdeskEngine`

The embedded inference entrypoint is:

`Deepdesk.app/Contents/Resources/SplashRuntime/python/bin/python3 -I -B Deepdesk.app/Contents/Resources/deepdesk_inference.py`

The wrappers and their packaging belong to the repository-level `packaging/` directory. Missing or incompatible helpers leave the UI in an explicit unavailable state.

Research startup requires a token-free health response bearing `X-Deepdesk-Instance`. Subsequent requests send `X-Deepdesk-Request` and still use upstream cookies, CSRF, and auth-context headers. Inference startup requires a token-free `/ready` response bearing `X-Deepdesk-Inference-Instance`, followed by an authenticated exact-model check. These nonces address port collisions and browser-origin requests; they are not strong authentication against a malicious process running as the same user.

The inference key is passed to the research wrapper through **DEEPDESK_INFERENCE_API_KEY**, alongside **DEEPDESK_INFERENCE_URL** and **DEEPDESK_INFERENCE_MODEL**. The wrapper injects it directly into the managed provider in memory. Do not substitute the upstream registered `LDR_LLM_OPENAI_ENDPOINT_API_KEY` setting, which can be included in effective-settings snapshots. A model/key change restarts and re-authenticates the owned research helper.

## Data and privacy

- Research data: `~/Library/Application Support/Deepdesk/Engine`.
- Model components: `~/Library/Application Support/Deepdesk/Models/<component-id>/<filename>`.
- Keychain service: `dev.emin.deepdesk.local-identity.v1`; Data Protection Keychain, `WhenUnlockedThisDeviceOnly`, non-synchronizing.
- Identity transition marker: `~/Library/Application Support/Deepdesk/identity-state.json`; contains only a state enum, never credentials.
- Passwords, sessions, CSRF values, launch tokens, and inference keys are not written to preferences or app logs. Child stdout/stderr are drained and discarded.
- Lost Keychain material with an existing marker/database blocks automatic setup. Ambiguous registration is reconciled with the same credential by login only. There is no replacement-key or plaintext fallback.
- Current key storage does not support moving encrypted research to another Mac by copying its files. A recovery/export workflow has not been implemented.
- No model download begins without the user's download action. Allowed redirect hosts are exactly `huggingface.co` and `us.aws.cdn.hf.co`; files use immutable revisions and SHA-256, never pickle or remote Python model code.

Existing symlinked cache/data paths are rejected. Partial and hash reads use no-follow, non-blocking opens and regular-file checks; metadata reads are bounded. Ancestor substitution by a malicious same-user process is outside the current filesystem threat boundary; this is not a fully descriptor-relative `openat` sandbox.

## Signing gate

Production encrypted onboarding requires a valid non-ad-hoc code signature whose Team ID matches the **DeepdeskSigningTeamID** value sealed into Info.plist before signing. The source plist intentionally contains no invented Team ID. Missing signing identity fails closed, including for an existing key. Packaging must configure and verify Keychain entitlements and designated-requirement continuity on the final Mac. Ad-hoc CI artifacts are not functional signed releases and cannot create a production identity.

## Build and verification

On a suitable Mac:

```sh
cd native-client
swift test
./scripts/build-app.sh /absolute/output-directory
```

The script builds an arm64 native app bundle and copies its SwiftPM resource bundle. It refuses to overwrite an existing app. It does not supply Python/Splash runtime binaries, sign, notarize, or create a DMG; repository packaging owns those stages.

Tests cover exact API payload names, login/CSRF rotation, unknown and terminal statuses, cancellation acknowledgement, history/report shapes, redirect/source URL constraints, no automatic start replay, instance identity, identity persistence/reconciliation/concurrency, catalog/path validation, metadata bounds, and strong-ETag range rules. They use synthetic identity fixtures and never create a real local account or Keychain item.

**Verification:** [Commit e69107a703e3ec789677433b63df2bdcc13e7945](https://github.com/Emin-dev/deepdesk/commit/e69107a703e3ec789677433b63df2bdcc13e7945) passed all **28 core XCTest tests, 6 isolated synthetic UI tests, and arm64 release compilation** in [macOS run 38100079182](https://github.com/Emin-dev/deepdesk/actions/runs/38100079182). All six bounded screenshot receipts were hash-verified and visually inspected; horizontal clipping was fixed. Minor capture caveats remain: a Dock footer overlay and a partly toolbar-covered yellow synthetic report banner. The [verification record](docs/VERIFICATION.md) preserves the tested manifest and limits. These checks use a [separate synthetic UI host](UIHarness/README.md), not the production runtime. Full accessibility, Keychain behavior, actual backend HTTP integration, Splash inference, signed upgrades, notarization, and a real DMG install remain integration gates. An M1 cloud runner cannot establish M3+ model runtime compatibility.

## API and design references

- [Pinned Local Deep Research source](https://github.com/LearningCircuit/local-deep-research/tree/b0ac4dea5a407c51e465e802b9928d34569a8db1)
- [Apple Liquid Glass API](https://developer.apple.com/documentation/swiftui/view/glasseffect(_:in:))
- [Apple NavigationSplitView](https://developer.apple.com/documentation/swiftui/navigationsplitview)
- [Apple ephemeral URLSession configuration](https://developer.apple.com/documentation/foundation/urlsessionconfiguration/ephemeral)
- [Apple code signing information](https://developer.apple.com/documentation/security/seccodecopysigninginformation(_:_:_:))
- [Apple Keychain accessibility](https://developer.apple.com/documentation/security/ksecattraccessiblewhenunlockedthisdeviceonly)
- [Splash 1.3.1 release](https://github.com/incoai/splash/releases/tag/1.3.1)

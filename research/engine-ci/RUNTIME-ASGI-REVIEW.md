# Installed runtime and in-process ASGI fixture: separate bounded proposal

Prepared 2026-10-11 UTC. Execution requires this proposal's exact review receipt.

## Verified starting point

B1 v4 run [38102069441](https://github.com/Emin-dev/deepdesk/actions/runs/38102069441), commit `976662a6ddab65bf43d9af6e2b54b1f9397a7884`, reached 20 successful bounded subprocesses on macOS 26.6.2 arm64. Exact source control flow establishes complete offline installation, the 277-distribution census, 14 major imports including the separately selected official PyPI Torch 2.14.0, production resource checks and four SQLCipher assertions before the first loopback-profile canary failed. Authenticated API and the final immutable-tree checks did not run. Source-built wheel hashes were not emitted because the final receipt was not reached.

The unchanged-profile/system-true diagnostic [38102972746](https://github.com/Emin-dev/deepdesk/actions/runs/38102972746), commit `8663a4f8d884554e0f3107ecdf3b1c35e4098793`, confirmed numeric-network-host parser rejection: child exit 65, stderr 62 bytes, SHA-256 `ed28254e8452483283fcde93b651bf8da2db4d87e9bb5b51f7db702d76046483`. No diagnostic socket or dependency execution occurred. A wider localhost policy was not approved.

## Transport change and exact claim

This proposal never uses the broken loopback profile, grants networking, or creates a TCP listener. All builds, installs, imports and ASGI workers use the unchanged `runtime-offline.sb`, SHA-256 `9d4f464140e5bb35efb2f937e820349b6f7a47482d4fcb2a618cc489b9bf4710`.

The CI-only helper imports uvicorn and Starlette before any local_deep_research import. It replaces only `uvicorn.run` inside that fresh worker, loads the byte-identical production wrapper and calls its unchanged `serve()`. That executes managed environment validation, resource checks, inference-provider guards, real middleware installation and upstream `web.app.main()` startup code, including configuration/logging/thread-hook/legacy cleanup. The interception requires exactly one call, the reviewed app target and the complete exact launch keyword dictionary. The production wrapper file is never edited.

The interception resolves the already configured real app, wraps only ASGI response sending with a 2-MiB body cap, and uses a context-managed Starlette TestClient. This drives the real ASGI lifespan, auth/CSRF/session middleware, routes, SQLCipher and ORM. It does not mock route results or remove upstream features. Starlette 1.3.1 selects the already installed **httpx2 2.13.1**, not httpx 0.28.1; this exact backend is asserted and reported. Static archive/member provenance is in `asgi-transport-static-review.json`.

TestClient dispatches in-process. Its host/client address fields are synthetic ASGI metadata, not observed network endpoints. The asyncio loop can create an internal AF_UNIX socketpair; this is not a claim of zero sockets. The unchanged network-deny profile remains authoritative, with no fallback if the loop is incompatible. Before any source builds, actual denial canaries require EPERM/EACCES for external connect, local TCP connect and local TCP bind at the synthetic scope port; an asyncio internal-event-loop check must also pass under that unchanged profile. Outer process deadlines bound stalled requests; the helper does not claim an httpx timeout limits ASGI application execution.

## Fixture sequence

1. A fresh worker enters real lifespan and checks health without a nonce/cookie, then validates returned instance metadata. This checks middleware semantics, not ownership of a TCP listener.
2. Wrong Host, browser Origin/Sec-Fetch-Site, wrong nonce and missing nonce requests are rejected by production middleware. The non-nonce cases carry a valid nonce so those boundaries are independently exercised.
3. Real registration, cookie session, username identity, anonymous/authenticated CSRF, wrong-token and wrong-account-context denial. Only an empty query is submitted; it must fail before research starts and history must remain empty. Logout and real lifespan shutdown complete.
4. The first process exits before the existing offline ORM seed writes one completed synthetic report with a `.invalid` citation. Fresh synthetic credentials travel only through bounded stdin. The empty research/resource/queue and fixture-marker checks remain unchanged.
5. A distinct fresh worker enters real lifespan, rejects unauthenticated report access and a wrong password, logs in with the correct key, verifies username, and reads status/report/citation/history/settings. An already-terminal stop and logout run; lifespan shutdown completes. Distinct worker process IDs are required. This establishes cross-process encrypted-data reopen if successful, not server process supervision.

Lifespan and login retain their normal local background tasks. There is no runnable research record, provider selection/query, model endpoint or model payload. TestClient suppresses redirect following and persists cookies using its actual pinned client implementation. Response body chunks are capped before TestClient buffers them. No sensitive user data, credentials or repository secrets are passed to workers.

## Unchanged provenance and bounds

The same 276 official exact distribution archives (541,910,864 bytes) and pinned CPython archive are used. Source-wheel provenance, complete payload/entry-point/license validation, same-run wheel hash locking, notice checks, offline pip install/check, exact identity census, imports and SQLCipher checks remain unchanged from reviewed B1 v4. The immutable upstream PDM lock remains unchanged. The separate official PyPI Torch hash remains `c1f844f1c750e87df4b68bc3afbc0e2b0c7ef19d7b8f666e48bdcf6a0c4f0056`; this does not claim equivalence to the unavailable CPU-index artifact.

Dedicated public-repository branch `engine-runtime-asgi-ci`, based on B1 v4 commit `976662a6ddab65bf43d9af6e2b54b1f9397a7884`. Standard macos-26 arm64, read-only pinned checkout, no persisted credentials, no cache or artifact uploads. The 25-minute job, 20-minute inner deadline, 12-GiB work bound, 16-GiB initial free-space gate, bounded private output and 16-KiB synthetic stdin remain. Worker phases are limited to 120 seconds each; seed 90 seconds; combined controller 360 seconds; fixture subtree 128 MiB. Owned process-group cleanup and final immutable/runtime tree checks remain. No network or filesystem denial is loosened.

## Remaining required gates

A successful run would establish installed-runtime and in-process ASGI semantics only. It would not establish real HTTP/TCP binding, token-free wrong-listener collision protection, owned-server health readiness/termination, native URLSession cookie/redirect behavior, Keychain, active research cancellation, model loading/inference, provider research, PDF/libmagic, native library relocation, standalone packaging, signing/notarization or DMG installation.

Real HTTP/native launch remains a separate required integration gate; it is not waived. The known arm64-wheel/x86_64 Pandoc issue and native-library/license/source-delivery gates remain open. All models and final inference remain outside this CI scope, with the final real inference reserved for the M5.

## First ASGI run and bounded diagnostic amendment

Run [38103924632](https://github.com/Emin-dev/deepdesk/actions/runs/38103924632), commit `64667cd9b328606001c3482e48fba9058e7831f4`, passed 23 bounded commands including external/local-connect/local-bind denial, asyncio internal-loop compatibility, full runtime build/install/import and SQLCipher checks. The fixture controller then failed; its private output did not establish the inner failing phase. No ASGI success is claimed.

The diagnostic amendment retains the same workflow, profiles, input packages, wrapper, seed implementation, routes and assertions. The register/persisted workers and unchanged seed main are invoked through one CI diagnostic envelope. A failed worker returns a fixed `failed` record; the controller forwards only a validated diagnostic schema; the outer stage prints that schema and still fails the job. It never upgrades a diagnostic result to API success.

Public fields are fixed phase/checkpoint IDs, fixed exception and causal-category names, a fixed assertion ID when an exact reviewed assertion text matches, and an exact allowlisted public source filename plus bounded line number. No exception message, arguments, locals, response, URL, raw type name or arbitrary traceback filename is emitted. Unknown values map to fixed unknown categories. The source allowlist contains 1,099 installed-package and 1,090 standard-library paths derived from exact already-reviewed archives/source, with hashes. Its own bytes are receipt-bound. Seed behavior and synthetic input are unchanged; only its CI entry dispatch receives the diagnostic envelope.

Private exception context is written only into the isolated temporary runner fixture tree, with no locals and a 1-MiB cap. It is never uploaded or printed and is removed with the temporary fixture. Existing 2-MiB captured-output, time, disk, stdin and process bounds remain intact. Synthetic tests cover secret-bearing messages/types/filenames, malformed/oversized schemas, exact source-path allowlisting, startup/routes/shutdown/seed failure reporting and unchanged success output.

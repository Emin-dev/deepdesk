# Standalone managed-policy integration: preparation only

Execution, managed-policy execution, publication and activation are false. This copied candidate extends accepted standalone-core v2 commit `32e4c8aeb287a5474c4203a754b880e0d96feb16`; the accepted snapshot and source-only proposal remain frozen. The existing core14 imports, SQLCipher4 checks, ASGI20 checks, complete payload preservation, sandbox profiles and workflow resource limits are retained.

## Production delta and refreshed pins

Both wrapper variants add only `LDR_LLM_REQUIRE_LOCAL_ENDPOINT=true` and `LDR_EMBEDDINGS_REQUIRE_LOCAL=true` after complete managed key/model/HTTP-loopback tuple validation. The exact 13-name launcher whitelist is unchanged. Invalid tuples still fail. Without a managed tuple, no new policy override is introduced; separately selected non-managed/cloud settings are unchanged by the delta. This is not implementation or approval of a future cloud mode.

The production wrapper is SHA-256 `7e4fdbe84458f1e8aed760d44852ff3a9823c729f56d161f3dd163120f118f65`. The standalone core wrapper is `ad8fc34f04809ad9b6a43922d47709a112e6aaedf04ddc427cae968edc5264d2`. Assembly’s default wrapper pin, portable wrapper/stage tests, diagnostic wrapper inventory, static ASGI source evidence and review receipt are refreshed together. The two wrappers’ production functions still have equivalent ASTs; their self-test difference remains unchanged.

## Separate installed-runtime contract

`packaging/engine-ci/managed_policy_checks.py` is a new bounded child, invoked through the relocated bundled interpreter only after core/import/SQLCipher checks. It gets a new `managed-policy-fixture-scope`, narrowed as the existing sandbox’s sole WORK_DIR. HOME/TMPDIR are already narrowed by the parent before process startup; the child creates only its new `fixture` directory, sets fresh HOME/TMPDIR/LDR_DATA_DIR/HF cache paths and removes inherited LDR/managed settings before upstream imports.

It loads the actual assembled wrapper with `runpy` without invoking `serve` or `__main__`, verifies the exact wrapper hash and installed prefix/resource root, imports the real installed provider/registry/policy modules, and verifies the pinned policy source hash. The real installed `policy.py` SHA-256 is `b2046d1402a2ceab865fc1457b199ca7894a37bf7090c05d95cdcde44542b085`, tied to the existing reviewed source manifest.

Using only a fixed synthetic bearer-shaped key, approved model ID and `http://127.0.0.1:18544/v1`, it starts both local-policy environment flags false, invokes the actual managed installer, and verifies restoration plus key removal. No listener exists at that address. It calls real `context_from_snapshot(snapshot, primary_engine='ddg', allow_dns=False)` with explicit `policy.egress_scope=public_only` and hostile false snapshot toggles. Requiring the returned scope to stay public_only prevents private/adaptive scope coupling from masking a missing environment lock.

Actual unmodified policy decisions must exactly be:

- Cloud OpenAI LLM: denied / `provider_cloud_only`
- URL-configurable LLM with URL absent: denied / `provider_url_unset`
- Managed exact loopback LLM URL: allowed / `provider_local`
- OpenAI embeddings without local override: denied / `provider_cloud`
- Unknown embeddings provider: denied / `provider_unknown`
- OpenAI-compatible embeddings at exact loopback URL: allowed / `provider_local_endpoint`
- In-process sentence_transformers classification: allowed / `provider_local`

These are policy decisions, not successful provider construction or inference. Generic `internal_error` never counts as expected denial. No policy evaluator, context, DNS resolver or DNS cache is patched. The pinned `allow_dns=False` affects context construction only; later evaluators can still resolve a public literal, so this probe deliberately does not exercise that resolver path. Foreign literal rejection is instead tested through the actual managed wrapper endpoint guard.

For guard safety, the provider’s underlying factory is replaced with an always-failing first-party sentinel before the real wrapper captures it. The real installed registry must bind the wrapper’s guarded classmethod. Exact foreign-URL and wrong-model failures must occur before that sentinel, and an unrelated cloud registry entry must remain unchanged. No valid-model factory invocation is performed. Even if a guard regresses, the sentinel prevents original provider/model construction and fails the job.

## Containment, diagnostics and failure behavior

The existing `standalone-offline.sb` and `runtime-offline.sb` are byte-identical. All network operations, including loopback, remain kernel-denied. No socket, bind, connect, DNS, subprocess or process launch is needed by this child; an additional Python audit hook marks and rejects attempts before execution. This hook supplements the sandbox and is not a general tamper-proof security boundary. It is specific to this non-ASGI probe; existing ASGI event-loop/socketpair behavior is unchanged.

The unchanged outer bounded runner enforces the existing global20-minute budget/work12GiB/output2MiB cap and a new per-child120-second ceiling. Work is limited to the fresh policy fixture scope by the existing profile. No network allowances, nested sandbox, install, model assets, native build or extra resource limits are introduced.

Public output is a single fixed schema of check IDs, status and allowlisted exception class. A duplicate of the original stdout pipe is reserved for final JSON; descriptor1 is redirected permanently to private stderr so native writes and late stdio flushes cannot corrupt or leak into public JSON. Exception messages, keys, URLs, snapshots, tracebacks and raw dependency output are never printed publicly. The parent rejects more than2048 bytes, invalid UTF-8/JSON, duplicate keys, extra fields, missing/reordered checks or unexpected success claims. A failed record is printed only after fixed-schema validation and always raises a fatal stage error. Timeout/output/disk/process failures remain fatal with raw output withheld.

Success is reported separately as `managed_policy_contract`; it never changes `model_loaded`, `provider_queried`, `research_execution_tested`, `real_http_tested`, `tcp_listener_tested` or `native_transport_tested` from false. The original core/import, SQLCipher and ASGI assertions remain intact. Full-bundle/runtime/immutable-input manifests are still verified after all checks.

## Local preparation tests and unverified stages

Portable first-party tests reside beside their helpers and derive paths only from the checkout. They never require local audit/native/upstream directories or an installed engine. Existing first-party C, assembly, relocation, diagnostic and synthetic bounds suites remain runnable. New tests substitute inert in-memory upstream modules; they do not execute downloaded dependencies or actual policy source locally. They cover both wrapper modes, partial/invalid tuples, cloud-mode noninterference, sentinel regressions, fixed failure/check IDs, malformed/oversized reports and descriptor-level output isolation.

The installed probe is prepared but not executed. The already accepted v2 result is still evidence for its frozen input bytes; it does not prove this new candidate’s managed policy or inference. Independent exact-input review must approve the refreshed receipt and separate policy gate before any publication/CI action. Real inference, models, external research, real HTTP/native transport, native/export closure, signing/notarization and distribution remain separate unverified gates.

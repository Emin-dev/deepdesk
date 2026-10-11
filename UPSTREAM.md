# Upstream provenance

Deepdesk incorporates Local Deep Research source from https://github.com/LearningCircuit/local-deep-research.

- Source commit: `b0ac4dea5a407c51e465e802b9928d34569a8db1`
- Source tree: `daee4ca481e19c40fbe4646ad0cf495252dce102`
- License: MIT, Copyright (c) 2025 LearningCircuit
- Snapshot: 4,399 source files, totaling 64,432,051 bytes
- Import method: a pinned source archive copied into an independently created repository. The upstream Git history is not copied or rewritten.

Every imported file is recorded in `UPSTREAM_MANIFEST.json` with its original path, current path, original Git blob hash, mode and size. All 4,399 files were verified against the pinned upstream Git tree before import. The `LICENSE` file is preserved verbatim. Separate third-party asset attribution is recorded in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Original authorship metadata and copyright notices remain intact.

## Intentional path changes

| Original location | Imported location | Reason |
| --- | --- | --- |
| `.github/workflows/*` | `upstream-workflows/*` | Preserve all 74 YAML workflows and their README without enabling upstream scheduled jobs, paid-provider calls, publishing or repository-writing automation. |
| `.github/CODEOWNERS`, `.github/FUNDING.yml`, `.github/dependabot.yml`, `.github/release.yml`, `.github/sync-config.yml` | `upstream-github-config/<original filename>` | Preserve upstream-specific ownership, sponsorship, dependency bots and release configuration without activating it in this independent repository. |
| `README.md`, `SECURITY.md`, `CONTRIBUTING.md` | `docs/upstream/<original filename>` | Preserve upstream product, security and contribution documentation without presenting upstream commitments as Deepdesk commitments. Relative links in these archived files refer to the original repository layout. |
| `.github/PULL_REQUEST_TEMPLATE/*` | `upstream-github-config/PULL_REQUEST_TEMPLATE/*` | Preserve upstream CI instructions without claiming inactive automation runs in Deepdesk. |

No imported file content was rewritten during the snapshot step. `README.md`, `SECURITY.md`, `CONTRIBUTING.md`, `THIRD_PARTY_NOTICES.md`, this document, and the manifest are new Deepdesk documentation. The Python package and import namespace remain `local-deep-research` and `local_deep_research` for compatibility; native macOS additions use the Deepdesk name.

## Execution and release boundary

Source verification is not a security certification or proof of runtime correctness. Upstream setup scripts, third-party dependencies, model downloads, services and CI were not executed during the import. The inactive workflows are retained for reference and must not be copied back into `.github/workflows` without a specific review of their triggers, permissions, external actions, secrets, costs and publication destinations.

In particular, the upstream release workflow runs on pushes to `main` and fans out into security scans, Docker tests, model-provider tests, release creation, Docker publishing and PyPI publishing. Other workflows schedule automatic dependency updates, write comments and labels, update repository files, use OIDC or expect personal-access-token credentials. Those behaviors are not enabled by this import.

Native macOS builds, app signing, notarization and distribution will be documented and verified separately. No DMG download is represented as available before the actual asset exists and is checked.

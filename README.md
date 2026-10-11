# Deepdesk

A focused deep-research workspace for macOS, built around a native SwiftUI interface and the Local Deep Research engine.

## macOS app

The native app and installer are in development. A verified DMG is not available yet. This README will link to a download only after the app has been built and the published release asset has been checked.

The macOS interface is being built in SwiftUI, with Liquid Glass on supported macOS versions. The research engine remains Python. The existing `local_deep_research` module and package identifiers are retained for compatibility while the new product is named **Deepdesk**.

## Source and attribution

Deepdesk is an independent source-copy project based on [LearningCircuit/local-deep-research](https://github.com/LearningCircuit/local-deep-research), pinned to commit [`b0ac4dea5a407c51e465e802b9928d34569a8db1`](https://github.com/LearningCircuit/local-deep-research/tree/b0ac4dea5a407c51e465e802b9928d34569a8db1). It is not a GitHub fork and does not claim original authorship of the upstream engine.

- [MIT license](LICENSE), including the original 2025 LearningCircuit copyright
- [Third-party notices](THIRD_PARTY_NOTICES.md), including sound-source attribution
- [Provenance and import policy](UPSTREAM.md)
- [Complete file-by-file source manifest](UPSTREAM_MANIFEST.json)
- [Original upstream README](docs/upstream/README.md)

The upstream workflows are preserved as inactive reference files in `upstream-workflows/`. Upstream repository-specific bot, sponsor and ownership configuration is preserved in `upstream-github-config/`. No imported workflow is enabled by this source import.

## Development status

This initial snapshot is a source foundation, not a tested macOS release. Upstream dependencies, service integrations and model downloads have not been installed or run as part of the import. See the original upstream documentation for the Python engine's supported development workflows; native macOS build and packaging instructions will accompany the client.

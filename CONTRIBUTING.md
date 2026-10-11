# Contributing to Deepdesk

Deepdesk combines a native SwiftUI macOS client with the inherited Python Local Deep Research engine. Preserve the original MIT license and attribution when changing inherited code.

This initial import does not enable upstream CI, release automation, provider-funded tests or dependency-update bots. Archived workflow files in `upstream-workflows/` are reference material, not an active test system. A green repository page is not evidence that the app or engine has been tested.

Before proposing changes:

1. Read [UPSTREAM.md](UPSTREAM.md) and distinguish inherited engine code from Deepdesk additions.
2. Inspect the relevant setup and test scripts before running them. Avoid networked services, model downloads or paid-provider tests without deliberately configuring them.
3. Report exactly which checks ran and which remain unverified. Native macOS build and packaging checks require the documented macOS toolchain.
4. Keep secrets, signing identities, private research and generated runtime data out of commits.
5. Preserve provenance when modifying imported files and document deliberate changes from the pinned source snapshot.

The original contribution guide is preserved in [docs/upstream/CONTRIBUTING.md](docs/upstream/CONTRIBUTING.md). Its upstream automation and maintenance rules describe the original project.

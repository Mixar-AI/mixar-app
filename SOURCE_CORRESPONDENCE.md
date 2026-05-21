<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Source Correspondence

This document tracks the source-to-binary mapping for Mixar App public releases.

## First Public Release

Planned launch version: `1.8.4` or `2.0.0`, to be finalized before public launch.

Current source candidate:

- Current repo version: `1.8.4`
- Local tag: `v1.8.4`
- Commit: `6059503017c04ce5f23088584a304d7bd01a3bed`
- Subject: `chore: bump version to 1.8.4 [skip ci]`
- Blender upstream submodule commit: `f52ba4dcdf5f669c1bc57f39a0e056be30d3ab60`

If the launch version is bumped to `2.0.0`, the public tag, app version, release binaries, checksums, and download page must all use the same final version.

## Release Rule

Public release binaries must be built from the exact public source tag.

Before publishing binaries:

1. Finalize the launch version.
2. Commit the version bump, if any.
3. Create the public source tag in `mixar-app`.
4. Build macOS and Windows binaries from that tag.
5. Publish checksums for release artifacts.
6. Keep the source tag, binary version, release notes, and download page in sync.

## Source Package Contents

The public source release must include:

- Mixar App source for the release tag
- Build and package scripts used for the release
- The `upstream` submodule pointer and instructions for fetching Blender source
- License files and SPDX metadata
- Scripts needed to regenerate generated build inputs from source

Do not publish the full private Git history.

## Private Material

Build configuration, signing credentials, hosted service credentials, and private deployment infrastructure are not part of the public source repository and must not be published.

## Derived Works

Mixar's texture painting module is, in part, a derivative work of the open-source [ucupaint](https://github.com/ucupumar/ucupaint) addon by [ucupumar](https://github.com/ucupumar), licensed GPL-3.0-or-later.

Derived paths in this repository:

- `src/scripts/mixar/modules/paint/core/lib/lib.blend` — modified from ucupaint's `lib_281.blend`
- `src/scripts/mixar/modules/paint/core/io/connections/layer_connections_*.py` — adapt ucupaint's layer/channel connection patterns
- `src/scripts/mixar/modules/paint/core/layer/create_channels.py` — adapts ucupaint's channel creation logic
- `src/scripts/mixar/modules/paint/ui/lists/channel_uilist.py` — channel UI list patterns
- `src/scripts/mixar/modules/paint/ui/utils/ui_helpers_texture_sets_channels.py` — channel settings UI patterns

Attribution is recorded in [NOTICE.md](NOTICE.md) and per-file copyright in [REUSE.toml](REUSE.toml). All derivations are distributed under GPL-3.0-or-later, consistent with ucupaint's license.

Upstream ucupaint source: `https://github.com/ucupumar/ucupaint`.

<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Notices

Mixar App is a project of Adeveda Enterprises Private Limited, built on top of Blender.

## Corporate Structure

The Mixar product is developed and operated by:

- **Adeveda Enterprises Private Limited** — a company incorporated in India. Current copyright holder of the Mixar source code and brand assets.
- **Mixar Inc** — a company incorporated in the United States. Operates Mixar's hosted backend services and US-facing commercial operations.

Copyright in this repository is currently held by Adeveda Enterprises Private Limited. An intra-group assignment of intellectual property to Mixar Inc is planned; copyright notices in this repository will be updated to reflect Mixar Inc at that time. The assignment will not affect the GPL-3.0-or-later license under which this source is published, nor users' rights under that license.

Blender is free software. Blender-derived files and upstream materials retain their own notices and licenses. File-level SPDX metadata and [REUSE.toml](REUSE.toml) are the authoritative source for per-file licensing in this repository.

The Mixar name, Mixar logo, Mixie name, and related brand assets are trademarks or pending trademarks of Adeveda Enterprises Private Limited. The source code license does not grant trademark rights, and Mixar brand-asset files (logos, icons, wordmarks) are governed separately by [LICENSES/LicenseRef-Mixar-Brand.txt](LICENSES/LicenseRef-Mixar-Brand.txt) — not by GPL-3.0-or-later. See [TRADEMARKS.md](TRADEMARKS.md).

Mixar hosted backend services are not included in this public source repository.

## Third-Party Software Acknowledgements

### ucupaint

Mixar's texture painting module builds on the open-source [ucupaint](https://github.com/ucupumar/ucupaint) addon by [ucupumar](https://github.com/ucupumar), used under the terms of the GNU General Public License version 3 or later.

Specifically:

- **Asset library** — `src/scripts/mixar/modules/paint/core/lib/lib.blend` is a modified version of ucupaint's `lib_281.blend`, containing layer/channel node groups derived from the original.
- **Layer and channel architecture** — files under `src/scripts/mixar/modules/paint/core/io/connections/`, `src/scripts/mixar/modules/paint/core/layer/create_channels.py`, and parts of the UI under `src/scripts/mixar/modules/paint/ui/` adapt ucupaint's patterns for channel handling, normal/height layer composition, and connection topology. Mixar's adaptations have been substantially modified and integrated with Mixar's wider feature set, but the design lineage is ucupaint's.

ucupaint's license is GPL-3.0-or-later (see [LICENSES/GPL-3.0-or-later.txt](LICENSES/GPL-3.0-or-later.txt)). Mixar's adaptations of ucupaint code are also distributed under GPL-3.0-or-later, consistent with the original license. Per-file SPDX metadata and [REUSE.toml](REUSE.toml) record per-file copyright attribution.

We thank ucupumar for the open-source work that made Mixar's texture-painting module possible.

<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-2.0-or-later -->

# Vendored: 3DGS Render by KIRI Engine (v4.1.5)

Upstream: https://github.com/Kiri-Innovation/3dgs-render-blender-addon
Tag: `v4.1.5` (commit `453301d`), Blender 4.3–5.0. Do NOT bump to v5.x —
that line targets Blender 5.1+.

Renders Gaussian splats (3DGS PLY) in real time via a geometry-nodes +
shader setup. Mixar uses it for splat environments (World Labs worlds and
locally imported `.spz`/`.ply` splats): `bootstrap/kiri_3dgs_addon.py`
auto-enables it, and `moodboard/core/world_labs_importer.py` drives its
Serpens-generated operators (`sna.dgs_render_import_ply_e0a3a` to import,
`sna.dgs_render_create_proxy_from_mesh_d5b41` to build the render proxy).

## What was changed vs upstream

Nothing in code. Omitted from vendoring:

- `wheels/` (~1 GB across platforms: open3d, scipy, dash/flask/plotly).
  The import + render path needs none of them; `open3d` is imported
  lazily at two sites and availability-guarded (its density-based outlier
  filtering feature reports "disabled" without it). scipy/dash/etc. are
  never imported by the addon code.
- `blender_manifest.toml` (extension metadata). We load it as a classic
  add-on via its `bl_info`, discovered from `scripts/addons_core/`
  (Blender maps the bundled scripts dir to `addons_core`, not `addons`).

One asset is transformed: `assets/3DGS Render APPEND V4.blend` (the
geometry-nodes group + material + HQ object the import operator appends)
is NOT in the upstream git repo (gitignored; release-zip-only, upstream
ships it uncompressed at 190 MB). We vendor a losslessly recompressed
resave (Blender `save_as_mainfile(compress=True)` from the Mixar build,
62 MB) — `wm.append` reads it identically; validated end-to-end (import,
modifiers, proxy, render).

## Render model (why a splat can look like a green point cloud)

- Viewport: the render **proxy** (`Create Proxy From Active`) draws via
  the addon's own GPU shader pipeline during interactive redraws.
- F12 / animation renders: the splat mesh's `KIRI_3DGS_Render_GN` builds
  camera-facing quads from view/projection matrices pushed into modifier
  sockets — per-object `sna_dgs_object_properties.update_mode =
  'Enable Camera Updates'` (+ `cam_update` for the active camera) must be
  on, or the render is black. KIRI's "Advanced Render" operator automates
  per-frame updates for animations; Director shot-render integration
  should drive the same path.

## Updating

Shallow-clone the desired tag and re-copy `__init__.py`, `assets/`,
`LICENSE`, `README.md`, `Important`; re-extract the APPEND blend from the
release zip (recompress as above). Re-verify the two operator ids above
still exist — `world_labs_importer.py` pins them.

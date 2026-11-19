<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-2.0-or-later -->

# Vendored: 3DGS Render by KIRI Engine (v4.1.5)

Upstream: https://github.com/Kiri-Innovation/3dgs-render-blender-addon
Tag: `v4.1.5` (commit `453301d`), which targets Blender 4.3–5.0; Mixar runs it
on Blender 5.2 with the IO patch below. Upstream v5.x requires Blender 5.1+
and was not evaluated for 5.2's modifier IO; bumping is a separate decision.

Renders Gaussian splats (3DGS PLY) in real time via a geometry-nodes +
shader setup. Mixar uses it for splat environments (World Labs worlds and
locally imported `.spz`/`.ply` splats): `bootstrap/kiri_3dgs_addon.py`
auto-enables it, and `moodboard/core/world_labs_importer.py` drives its
Serpens-generated operators (`sna.dgs_render_import_ply_e0a3a` to import,
`sna.dgs_render_create_proxy_from_mesh_d5b41` to build the render proxy).

## What was changed vs upstream

**Two code patches**, both marked `MIXAR PATCH` in `__init__.py`.

**Visibility patch**: per-object visibility. `assets/vert.glsl` culls a
gaussian whose object visibility flag (slot 2 of the 15-float-per-object
metadata texture) is `< 0.5`, but every upstream writer of that slot hardcodes
`1.0`, so splats kept drawing through the addon's `SpaceView3D` handler no
matter what the user did in the outliner — there was no way to hide a splat at
all. The patch adds `mixar_object_visibility(obj)` /
`mixar_visibility_signature()` near the top of the file, feeds the former into
all four metadata writers, and — because a hide changes no transform, and the
texture is only refreshed when one does — adds a visibility check next to
`check_any_transforms_changed()` in `sna_viewport_render_A3941`'s draw loop,
plus `mixar_last_visibility` in `cleanup_multi_object_cache`'s teardown list.
Pinned by `tests/test_splat_lifecycle.py`; re-apply it on any vendor bump.

**Blender 5.2 IO patch**: 5.2 removed ID-property access on modifiers, so
`mod['Socket_N']` (read or write) raises `TypeError`; geometry-nodes inputs
live at `mod.properties.inputs.<Socket_N>.value`. The helper
`mixar_gn_input(modifier, socket_id)` (next to the visibility helpers) returns
that input and raises on a missing socket. Ported call sites: the
`update_mode` and `cam_update` callbacks, which also act on the property owner
(`self.id_data`) instead of the active object (Mixar sets them on objects that
are not active, often from scripts with no area) and only enter camera view from a
3D view; the PLY import operator's two writes (`Socket_50` Update Mode, a menu
whose items are the `update_mode` enum identifiers, and `Socket_61` material);
and `update_gaussian_splat_camera` inside
`sna_update_camera_single_time_9EF18` (the cam_update timer's target); the
same-named copy in the Align-To-View operator is still unported. The add-on's
other `['Socket_N']` sites and the panels' `'["Socket_N"]'` property rows are
still unported. Mixar's `enable_render_updates` keeps the Render GN
viewport-off after setting `update_mode` (KIRI's GPU proxy is built from the
evaluated mesh). Pinned by `tests/test_kiri_blender52_io.py`; re-apply it on
any vendor bump.

Deletion is handled Mixar-side instead (nothing to patch here):
`moodboard/core/splat_lifecycle.py` reconciles KIRI's process-global cache and
textures after outliner deletions — see its module docstring.

Omitted from vendoring:

- `wheels/` (~1 GB across platforms: open3d, scipy, dash/flask/plotly).
  The import + render path needs none of them; `open3d` is imported
  lazily at two sites and availability-guarded (its density-based outlier
  filtering feature reports "disabled" without it). scipy/dash/etc. are
  never imported by the addon code.
- `blender_manifest.toml` (extension metadata). We load it as a classic
  add-on via its `bl_info`, discovered from `scripts/addons_core/`
  (Blender maps the bundled scripts dir to `addons_core`, not `addons`).

One asset is transformed: `assets/3DGS Render APPEND V4.blend` (the
geometry-nodes groups + material + HQ/Wire objects the addon appends)
is NOT in the upstream git repo (gitignored; release-zip-only, upstream
ships it uncompressed at 190 MB). We vendor a stripped, compressed resave
(6.7 MB): upstream's file also carries KIRI's demo scene, whose four sample
splat objects (`Faces to 3DGS`, `Faces to 3DGS.001`, `Points to 3DGS`,
`Point Edit cubone` — flamingo/cubone point clouds) were ~150 MB of mesh
data that nothing ever appends. Those objects and their meshes were removed
(their only users were the demo collections and the demo Camera's DOF focus)
and the file saved with `save_as_mainfile(compress=True)`. Every node group,
material, image and appended object is unchanged — verified by appending
each one from the old and new file and diffing the result, and by running
the real import (`sna.dgs_render_import_ply_e0a3a`) + proxy
(`sna.dgs_render_create_proxy_from_mesh_d5b41`) operators against both.
The only ID that no longer survives the save is `KIRI_3DGS_Animate_GNborken`,
an orphaned broken copy used solely by a deleted demo object's modifier and
never referenced by the addon. On a vendor bump, re-apply the same strip
(delete those demo objects + meshes, compressed save).

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
still exist — `world_labs_importer.py` pins them — and re-apply the
visibility and Blender 5.2 IO patches (`tests/test_splat_lifecycle.py` and
`tests/test_kiri_blender52_io.py` fail until you do).

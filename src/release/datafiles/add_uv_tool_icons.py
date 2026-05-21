# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Add Mixar UV Tool / UV Functions toolbar icons to `toolbar.blend`.

This is a one-shot authoring script. It opens the Mixar overlay
`icons_blend/toolbar.blend`, imports the upstream
`tool_settings.svg` and `edge_seam.svg` glyphs, converts them to
flat filled meshes with white vertex colors, normalises them to the
toolbar `-1..1` coordinate space, names them so the icon-export
pipeline picks them up, and saves the file in-place.

Run headless from the repo root:

    build/Dev/bin/mixar.exe -b \
        src/release/datafiles/icons_blend/toolbar.blend \
        --python src/release/datafiles/add_uv_tool_icons.py

Then regenerate the `.dat` files (this also updates the
`ICON_GEOM_NAMES` block in the editors `CMakeLists.txt`):

    build/Dev/bin/mixar.exe -b --factory-startup \
        --python src/release/datafiles/mixar_icons_geom_update.py

Re-running this script is safe — the two named mesh objects are
removed and recreated on every run.
"""

__all__ = ("main",)

import os
import sys

import bpy


# Names the toolbar `ToolDef`s reference. Each becomes `<name>.dat`
# after `blender_icons_geom.py` runs.
_ICONS = (
    # (mesh-object name, upstream SVG filename)
    ("ops.uv_tool", "tool_settings.svg"),
    ("ops.uv.mark_seam", "edge_seam.svg"),
)


def _resolve_svg_dir() -> str:
    """Return the absolute path to `upstream/release/datafiles/icons_svg`.

    `__file__` points at `src/release/datafiles/add_uv_tool_icons.py`,
    so the upstream tree sits four levels up.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.normpath(os.path.join(here, "..", "..", ".."))
    return os.path.join(
        repo_root, "upstream", "release", "datafiles", "icons_svg"
    )


def _ensure_export_collection():
    """Return the `Export` collection — the icon-export script reads
    from this group, ignoring everything else in the file."""
    coll = bpy.data.collections.get("Export")
    if coll is None:
        coll = bpy.data.collections.new("Export")
        bpy.context.scene.collection.children.link(coll)
    return coll


def _remove_existing(name: str) -> None:
    obj = bpy.data.objects.get(name)
    if obj is not None:
        mesh = obj.data if obj.type == 'MESH' else None
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def _import_svg(svg_path: str) -> list:
    """Import an SVG; return the list of newly-created objects."""
    before = set(bpy.data.objects)
    bpy.ops.import_curve.svg(filepath=svg_path)
    return list(set(bpy.data.objects) - before)


def _curves_to_filled_mesh(objects: list, joined_name: str):
    """Convert imported curve objects to a single filled mesh."""
    # SVG paths import as Bezier curves with `fill_mode='NONE'`; in 2D
    # mode with the splines marked cyclic, the curve→mesh convert step
    # tessellates the enclosed area into faces. Force both settings so
    # the resulting mesh actually has polygons (not just outline edges).
    for ob in objects:
        if ob.type == 'CURVE':
            ob.data.dimensions = '2D'
            ob.data.fill_mode = 'BOTH'
            for spline in ob.data.splines:
                spline.use_cyclic_u = True

    # Select all imported objects and make one of them active.
    bpy.ops.object.select_all(action='DESELECT')
    for ob in objects:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]

    bpy.ops.object.convert(target='MESH')

    # `convert` keeps the same objects but replaces their data — refresh.
    converted = [o for o in bpy.context.selected_objects if o.type == 'MESH']
    if not converted:
        raise RuntimeError("Curve→mesh conversion produced no mesh objects.")

    if len(converted) > 1:
        bpy.context.view_layer.objects.active = converted[0]
        bpy.ops.object.join()

    obj = bpy.context.active_object
    obj.name = joined_name
    obj.data.name = joined_name

    # Fallback: if the conversion left only edge loops (cyclic curves
    # without fill data), triangulate the enclosed regions manually.
    if len(obj.data.polygons) == 0:
        _fill_edge_loops_to_faces(obj)

    print(f"[mixar-icons]   {joined_name}: "
          f"{len(obj.data.vertices)} verts, "
          f"{len(obj.data.polygons)} polys")

    return obj


def _fill_edge_loops_to_faces(obj) -> None:
    """Last-ditch face fill — for each edge loop in the mesh, treat its
    vertex ring as a polygon and triangulate via the edit-mode fill +
    triangulate operators. Required when curve→mesh leaves only edges."""
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    # `edge_face_add` builds n-gons from selected edge loops.
    bpy.ops.mesh.edge_face_add()
    bpy.ops.mesh.quads_convert_to_tris(
        quad_method='BEAUTY', ngon_method='BEAUTY')
    bpy.ops.object.mode_set(mode='OBJECT')


def _normalize_to_unit(obj) -> None:
    """Center the mesh and uniformly scale it so its longest axis spans
    `target` units. Also flips Y (SVG → Blender axis convention) and
    flattens Z so the icon-export sort is deterministic."""
    me = obj.data
    if len(me.vertices) == 0:
        raise RuntimeError(f"Mesh {obj.name!r} has no vertices.")

    xs = [v.co.x for v in me.vertices]
    ys = [v.co.y for v in me.vertices]
    bbox_min = (min(xs), min(ys))
    bbox_max = (max(xs), max(ys))
    cx = (bbox_min[0] + bbox_max[0]) * 0.5
    cy = (bbox_min[1] + bbox_max[1]) * 0.5
    extent = max(bbox_max[0] - bbox_min[0], bbox_max[1] - bbox_min[1])
    if extent <= 0.0:
        raise RuntimeError(f"Degenerate bounding box for {obj.name!r}.")

    # Existing toolbar `.dat` icons leave significant padding inside
    # their -1..1 frame so the glyph reads as a centred symbol. Fit
    # into ±0.55 (≈65 % of the previous ±0.85 fit) so the wrench /
    # mark-seam glyphs sit visually at the same scale as neighbouring
    # tool icons instead of crowding their slot edges.
    target = 1.1
    scale = target / extent
    for v in me.vertices:
        v.co.x = (v.co.x - cx) * scale
        # Blender Y points up, SVG Y points down — flip during
        # normalize. The flip reverses triangle winding (which the
        # icon export rejects via signed-area check) so we follow
        # up with `_flip_face_normals` to restore CCW winding.
        v.co.y = -(v.co.y - cy) * scale
        v.co.z = 0.0

    _flip_face_normals(obj)

    # Reset object transform so the (centered) mesh-space coords are
    # what the export script writes out.
    obj.location = (0.0, 0.0, 0.0)
    obj.rotation_euler = (0.0, 0.0, 0.0)
    obj.scale = (1.0, 1.0, 1.0)


def _flip_face_normals(obj) -> None:
    """Flip face winding for every polygon. Required after a Y-flip on
    a 2D mesh — the geometry is mirrored but the loop order is still
    CW from the original CCW, so `area_tri_signed_2x_v2` in the icon
    export rejects every triangle as zero/negative area.
    """
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.flip_normals()
    bpy.ops.object.mode_set(mode='OBJECT')


def _paint_white(obj) -> None:
    """Add (or reuse) a CORNER byte-color attribute filled with white.
    `blender_icons_geom.py` skips meshes without an active color
    attribute, so this is required for the icon to export."""
    me = obj.data
    ca = me.color_attributes.active_color
    if ca is None or ca.domain != 'CORNER' or ca.data_type != 'BYTE_COLOR':
        # Drop any non-matching active attribute and create a fresh one.
        if ca is not None:
            me.color_attributes.remove(ca)
        ca = me.color_attributes.new(
            name="Color", type='BYTE_COLOR', domain='CORNER',
        )
        me.color_attributes.active_color = ca

    white = (1.0, 1.0, 1.0, 1.0)
    for elem in ca.data:
        elem.color = white


def _move_to_export(obj, export_coll) -> None:
    """Remove from any current collection and re-link under `Export`."""
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    export_coll.objects.link(obj)


def _create_icon(name: str, svg_path: str, export_coll) -> None:
    print(f"[mixar-icons] importing {svg_path!r} as {name!r}")
    new_objects = _import_svg(svg_path)
    if not new_objects:
        raise RuntimeError(f"Import of {svg_path!r} produced no objects.")

    obj = _curves_to_filled_mesh(new_objects, name)
    _normalize_to_unit(obj)
    _paint_white(obj)
    _move_to_export(obj, export_coll)


def main() -> int:
    svg_dir = _resolve_svg_dir()
    export_coll = _ensure_export_collection()

    for name, svg_filename in _ICONS:
        svg_path = os.path.join(svg_dir, svg_filename)
        if not os.path.exists(svg_path):
            print(f"[mixar-icons] WARN: {svg_path} not found — skipping",
                  file=sys.stderr)
            continue
        _remove_existing(name)
        _create_icon(name, svg_path, export_coll)

    # Overwrite the .blend in place so the next icon-export run sees
    # the new geometry. Save compressed to match upstream's storage
    # format (uncompressed saves balloon the file from ~3 MB to ~18 MB
    # — mostly redundant bone/material data the icon export ignores).
    bpy.ops.wm.save_mainfile(compress=True)
    print("[mixar-icons] saved", bpy.data.filepath)
    return 0


if __name__ == "__main__":
    sys.exit(main())

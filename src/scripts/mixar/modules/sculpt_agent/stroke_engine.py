# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Replay backend-synthesized sculpt strokes through Blender's stroke pipeline.

The backend plans trajectories in the image space of a named camera (the one
it rendered for localization), as normalized (u, v) points with per-point
pressure. This engine:

1. aligns the live 3D viewport with that camera (free-view alignment — the
   sculpt operator raycasts through REGION mouse coordinates, so the region's
   view matrices are what ground each stroke element),
2. converts every (u, v) to a world ray from the camera and raycasts the
   evaluated scene for the surface point (off-surface tail points fall back
   to the view plane through the last hit — a Grab stroke may leave the
   silhouette),
3. projects hits back into the region for the operator's mouse coords, and
4. runs ``bpy.ops.sculpt.brush_stroke`` per stroke with the requested brush,
   then restores mode, view, and camera.

Runs inside the Mixar ScriptExecutor sandbox (main thread, real GUI window).
"""

from __future__ import annotations

import bpy
from bpy_extras import view3d_utils
from mathutils import Vector

from .mapping import (
    frame_point,
    pressure_profile,
    ray_plane_intersect,
    ray_through,
    resample_polyline,
)

# Canonical brush keys → Blender 4.3+ Essentials sculpt-brush asset names.
# bpy.data.brushes name-matching is tried first (covers legacy builds and
# already-activated assets); the asset library is the fallback.
_BRUSH_ASSETS = {
    "draw": "Draw",
    "draw_sharp": "Draw Sharp",
    "clay": "Clay",
    "clay_strips": "Clay Strips",
    "inflate": "Inflate/Deflate",
    "grab": "Grab",
    "elastic_deform": "Elastic Grab",
    "snake_hook": "Snake Hook",
    "smooth": "Smooth",
    "crease": "Crease Sharp",
    "blob": "Blob",
    "flatten": "Flatten/Contrast",
    "pinch": "Pinch/Magnify",
}
_ESSENTIALS_BLEND = "brushes/essentials_brushes-mesh_sculpt.blend/Brush/"


def _find_view3d():
    """(window, area, region, rv3d) for the largest live VIEW_3D region.

    Prefers a window showing the current (pinned) scene so the raycast and
    the on-screen stroke agree on what is visible.
    """
    best = None
    best_key = (-1, -1)
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            space = area.spaces.active
            rv3d = getattr(space, "region_3d", None)
            if region is None or rv3d is None:
                continue
            same_scene = 1 if window.scene == bpy.context.scene else 0
            key = (same_scene, region.width * region.height)
            if key > best_key:
                best_key = key
                best = (window, area, region, rv3d)
    return best


def _align_view_to_camera(rv3d, space, cam_obj, pivot: Vector, distance: float):
    """Free-view align the region to the camera's position/orientation.

    Free view (not camera-lock): camera-lock zoom/offset makes region↔image
    mapping depend on draw-time state, while a free view aligned to the same
    axis only needs to see the same front surface — mouse coords are obtained
    by PROJECTING the exact raycast hit, so small FOV differences between the
    viewport and the camera do not shift where the brush lands.
    """
    quat = cam_obj.matrix_world.to_quaternion()
    rv3d.view_perspective = "PERSP"
    rv3d.view_rotation = quat
    rv3d.view_location = pivot
    rv3d.view_distance = max(0.05, distance)
    if hasattr(space, "lens") and getattr(cam_obj.data, "lens", None):
        space.lens = cam_obj.data.lens
    # Recompute the lazy view matrices NOW — projection below must not wait
    # for the next redraw.
    rv3d.update()


def _activate_brush(override, brush_key: str) -> str:
    """Activate the requested sculpt brush; returns the name actually active."""
    want = _BRUSH_ASSETS.get(brush_key, brush_key.replace("_", " ").title())
    # 1) An already-loaded datablock (legacy builds / previously used assets).
    for brush in bpy.data.brushes:
        if brush.use_paint_sculpt and brush.name.lower() == want.lower():
            bpy.context.tool_settings.sculpt.brush = brush
            return brush.name
    # 2) The bundled Essentials asset library (Blender 4.3+ brush assets).
    try:
        with bpy.context.temp_override(**override):
            bpy.ops.brush.asset_activate(
                asset_library_type="ESSENTIALS",
                asset_library_identifier="",
                relative_asset_identifier=_ESSENTIALS_BLEND + want,
            )
        active = bpy.context.tool_settings.sculpt.brush
        if active is not None:
            return active.name
    except Exception:
        pass
    # 3) Loose name match as a last resort (e.g. "Clay Strips" vs "Clay strips").
    for brush in bpy.data.brushes:
        if brush.use_paint_sculpt and want.lower() in brush.name.lower():
            bpy.context.tool_settings.sculpt.brush = brush
            return brush.name
    current = bpy.context.tool_settings.sculpt.brush
    return current.name if current else "(none)"


def _set_brush_dynamics(size_px: int, strength: float):
    ts = bpy.context.tool_settings
    ups = ts.unified_paint_settings
    brush = ts.sculpt.brush
    size_px = max(3, int(size_px))
    strength = min(1.0, max(0.0, float(strength)))
    if getattr(ups, "use_unified_size", False):
        ups.size = size_px
    if brush is not None:
        brush.size = size_px
    if getattr(ups, "use_unified_strength", False):
        ups.strength = strength
    if brush is not None:
        brush.strength = strength


def _set_symmetry(obj, use_x: bool):
    mesh = obj.data
    for holder, attr in ((mesh, "use_mirror_x"), (bpy.context.tool_settings.sculpt, "use_symmetry_x")):
        try:
            setattr(holder, attr, bool(use_x))
        except (AttributeError, TypeError):
            pass


def _vertex_snapshot(obj):
    import numpy as np

    mesh = obj.data
    n = len(mesh.vertices)
    buf = np.empty(n * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", buf)
    return buf.reshape(n, 3)


def _displacement_stats(before, after):
    import numpy as np

    if before.shape != after.shape:
        # Topology changed (dyntopo etc.) — displacement is undefined.
        return {"verts_before": int(before.shape[0]), "verts_after": int(after.shape[0])}
    delta = np.linalg.norm(after - before, axis=1)
    moved = delta > 1e-6
    return {
        "verts_total": int(delta.shape[0]),
        "verts_moved": int(moved.sum()),
        "mean_move": float(delta[moved].mean()) if moved.any() else 0.0,
        "max_move": float(delta.max()) if delta.shape[0] else 0.0,
    }


def apply_strokes(params: dict) -> dict:
    """Apply agent-planned sculpt strokes. See module docstring for the flow.

    params:
        object_name: mesh object to sculpt (must exist in the current scene).
        camera_name: camera whose image space the stroke coords live in.
        strokes: [[{"u","v","p"?}, ...], ...] — normalized image coords,
            u left→right, v bottom→top, optional per-point pressure.
        brush: canonical brush key (see _BRUSH_ASSETS; default "draw").
        radius_world: brush radius in WORLD units (converted to region px at
            each stroke's first hit — view-independent sizing).
        strength: 0..1 brush strength (default 0.5).
        stroke_mode: "NORMAL" | "INVERT" | "SMOOTH" (default "NORMAL").
        pressure_profile: "flat" | "ease" (default per-brush).
        use_symmetry_x: mirror strokes across X (default False).

    Returns a dict with success, brush_used, strokes_applied, per-stroke hit
    counts, and vertex displacement stats.
    """
    obj = bpy.data.objects.get(str(params.get("object_name") or ""))
    if obj is None or obj.type != "MESH":
        return {"success": False,
                "error": f"mesh object '{params.get('object_name')}' not found"}
    cam = bpy.data.objects.get(str(params.get("camera_name") or ""))
    if cam is None or cam.type != "CAMERA":
        return {"success": False,
                "error": f"camera '{params.get('camera_name')}' not found — "
                         "run the sculpt view capture first"}
    strokes_in = params.get("strokes") or []
    if not strokes_in:
        return {"success": False, "error": "no strokes provided"}

    found = _find_view3d()
    if found is None:
        return {"success": False, "error": "no 3D viewport available for sculpting"}
    window, area, region, rv3d = found
    override = {
        "window": window, "screen": window.screen, "area": area,
        "region": region, "scene": bpy.context.scene,
    }

    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()

    # World-space camera frame (view_frame corners are camera-local).
    cam_matrix = cam.matrix_world
    corners_local = cam.data.view_frame(scene=scene)
    corners = [tuple(cam_matrix @ c) for c in corners_local]
    cam_origin = tuple(cam_matrix.translation)
    cam_forward = tuple(-(cam_matrix.to_quaternion() @ Vector((0.0, 0.0, 1.0))))

    # Make the target sculptable and remember what we change.
    prev_active = bpy.context.view_layer.objects.active
    prev_hidden = obj.hide_get()
    prev_view = {
        "perspective": rv3d.view_perspective,
        "rotation": rv3d.view_rotation.copy(),
        "location": rv3d.view_location.copy(),
        "distance": rv3d.view_distance,
    }
    obj.hide_set(False)
    obj.hide_viewport = False
    bpy.context.view_layer.objects.active = obj
    for other in bpy.context.selected_objects:
        other.select_set(False)
    obj.select_set(True)

    # Pivot the aligned view on the object so the whole target is in front
    # of the near plane, at the camera's distance from it.
    bbox_world = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    center = sum(bbox_world, Vector()) / 8.0
    distance = (Vector(cam_origin) - center).length

    result: dict = {"success": True}
    try:
        with bpy.context.temp_override(**override):
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.mode_set(mode="SCULPT")

        _align_view_to_camera(rv3d, area.spaces.active, cam, center, distance)

        brush_key = str(params.get("brush") or "draw")
        brush_used = _activate_brush(override, brush_key)
        strength = float(params.get("strength", 0.5))
        radius_world = float(params.get("radius_world", 0.0))
        radius_frac = params.get("radius_frac")
        # Camera-frame geometry for radius_frac → world conversion (fraction of
        # the camera frame's width at the hit's depth, perspective-correct).
        frame_width = (Vector(corners[0]) - Vector(corners[3])).length
        frame_center = sum((Vector(c) for c in corners), Vector()) / 4.0
        frame_depth = max(1e-6, (frame_center - Vector(cam_origin)).dot(Vector(cam_forward)))
        stroke_mode = str(params.get("stroke_mode") or "NORMAL").upper()
        if stroke_mode not in ("NORMAL", "INVERT", "SMOOTH"):
            stroke_mode = "NORMAL"
        profile = str(
            params.get("pressure_profile")
            or ("ease" if brush_key in ("grab", "snake_hook", "elastic_deform") else "flat")
        )
        _set_symmetry(obj, bool(params.get("use_symmetry_x", False)))

        before = _vertex_snapshot(obj)

        applied = 0
        hit_counts: list[int] = []
        for stroke in strokes_in:
            pts = [(float(p["u"]), float(p["v"])) for p in stroke]
            # Dense sampling in image space: ~0.5% of the frame per step.
            pts = resample_polyline(pts, max_gap=0.005)
            pressures = pressure_profile(len(pts), profile)
            explicit = [p.get("p") for p in stroke]
            if any(x is not None for x in explicit) and len(explicit) == len(pts):
                pressures = [float(x) if x is not None else 1.0 for x in explicit]

            def _cast_to_target(origin, direction):
                """Raycast that punches through occluders until it reaches the
                TARGET object (up to 8 re-casts) — the edit must land on the
                asset being sculpted, not on scenery in front of it."""
                start = Vector(origin)
                direc = Vector(direction)
                for _ in range(8):
                    ok, loc, _n, _i, hit_obj, _m = scene.ray_cast(depsgraph, start, direc)
                    if not ok:
                        return None
                    hit_root = hit_obj.original if hasattr(hit_obj, "original") else hit_obj
                    if hit_root == obj:
                        return tuple(loc)
                    start = Vector(loc) + direc * 1e-4
                return None

            elements = []
            last_hit = None
            hits = 0
            for i, (u, v) in enumerate(pts):
                target = frame_point(corners, u, v)
                origin, direction = ray_through(cam_origin, target)
                hit = _cast_to_target(origin, direction)
                if hit is not None:
                    loc3 = hit
                    last_hit = loc3
                    hits += 1
                else:
                    # Off-silhouette tail: view plane through the last hit
                    # (or the object center before any hit).
                    anchor = last_hit or tuple(center)
                    fallback = ray_plane_intersect(origin, direction, anchor, cam_forward)
                    if fallback is None:
                        continue
                    loc3 = fallback
                mouse = view3d_utils.location_3d_to_region_2d(
                    region, rv3d, Vector(loc3)
                )
                if mouse is None:
                    continue
                if not elements:
                    # Resolve the brush radius at first contact. radius_frac is
                    # a fraction of the camera frame's width AT THE HIT DEPTH
                    # (perspective-correct); radius_world is used verbatim.
                    r_world = radius_world
                    if radius_frac is not None:
                        depth = max(
                            1e-6,
                            (Vector(loc3) - Vector(cam_origin)).dot(Vector(cam_forward)),
                        )
                        r_world = float(radius_frac) * frame_width * depth / frame_depth
                    if r_world <= 0.0:
                        r_world = 0.05 * max(obj.dimensions[:] or (1.0,))
                    # Convert the world radius to region pixels at first contact.
                    quat = rv3d.view_rotation
                    right = quat @ Vector((1.0, 0.0, 0.0))
                    edge = view3d_utils.location_3d_to_region_2d(
                        region, rv3d, Vector(loc3) + right * r_world
                    )
                    size_px = int((edge - mouse).length) if edge is not None else 35
                    _set_brush_dynamics(size_px, strength)
                elements.append({
                    "name": "stroke",
                    "location": loc3,
                    "mouse": (mouse.x, mouse.y),
                    "mouse_event": (mouse.x, mouse.y),
                    "pen_flip": False,
                    "is_start": len(elements) == 0,
                    "size": max(3, int(bpy.context.tool_settings.sculpt.brush.size))
                    if bpy.context.tool_settings.sculpt.brush else 35,
                    "pressure": pressures[i] if i < len(pressures) else 1.0,
                    "time": float(len(elements)) * 0.02,
                    "x_tilt": 0.0,
                    "y_tilt": 0.0,
                })
            hit_counts.append(hits)
            if len(elements) < 2:
                continue
            with bpy.context.temp_override(**override):
                bpy.ops.sculpt.brush_stroke(
                    stroke=elements, mode=stroke_mode, ignore_background_click=True
                )
            applied += 1

        after = _vertex_snapshot(obj)
        result.update({
            "brush_requested": brush_key,
            "brush_used": brush_used,
            "strokes_applied": applied,
            "strokes_requested": len(strokes_in),
            "surface_hits_per_stroke": hit_counts,
            "displacement": _displacement_stats(before, after),
        })
        if applied == 0:
            result["success"] = False
            result["error"] = (
                "no stroke reached the mesh — the target may be occluded from "
                "this view or the coordinates missed the object; re-localize "
                "from a different canonical view"
            )
    except Exception as exc:  # surfaced to the backend as a script error
        result = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        try:
            with bpy.context.temp_override(**override):
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
        try:
            rv3d.view_perspective = prev_view["perspective"]
            rv3d.view_rotation = prev_view["rotation"]
            rv3d.view_location = prev_view["location"]
            rv3d.view_distance = prev_view["distance"]
            rv3d.update()
        except Exception:
            pass
        try:
            obj.hide_set(prev_hidden)
            if prev_active is not None:
                bpy.context.view_layer.objects.active = prev_active
        except Exception:
            pass

    return result

# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene Gen Experimental — Step 5: Place in Scene operator."""

import math

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def _get_tab(context):
    scene = context.scene
    if not hasattr(scene, 'mixie_moodboard_sidebar'):
        return None
    sidebar = scene.mixie_moodboard_sidebar
    if not hasattr(sidebar, 'tab_scene_gen_exp'):
        return None
    return sidebar.tab_scene_gen_exp


def _find_mesh_for_chain_id(chain_id, prefer_lp=True):
    """Find a mesh for a given chain_id.

    When *prefer_lp* is True, returns LP mesh first (falls back to HP).
    When False, returns HP mesh first (falls back to LP).
    """
    lp = None
    hp = None
    for obj in bpy.data.objects:
        if obj.type != 'MESH' or "mixar_chain_id" not in obj:
            continue
        if obj["mixar_chain_id"] != chain_id:
            continue
        if obj.name.endswith("_low"):
            lp = obj
        elif obj.name.endswith("_high"):
            hp = obj
    if prefer_lp:
        return lp or hp
    return hp or lp


def _get_local_bbox_dims(obj):
    """Return (dx, dy, dz) from the object's local-space bounding box."""
    bb = obj.bound_box
    xs = [v[0] for v in bb]
    ys = [v[1] for v in bb]
    zs = [v[2] for v in bb]
    return (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))


def _extract_z_rotation(quat):
    """Extract Z-axis (yaw) rotation in radians from a (w, x, y, z) quaternion."""
    w, x, y, z = quat
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def _compute_uniform_scale(local_dims, target_dims):
    """Compute a uniform scale factor to match the mesh to target dimensions.

    Uses height (Z) as the primary reference since the pivot is at the
    bottom — this gives the most visually correct placement.  Falls back
    to the largest dimension if Z is near-zero (flat objects).
    """
    lz, tz = local_dims[2], target_dims[2]
    if lz > 1e-6 and tz > 1e-6:
        return tz / lz

    l_max = max(local_dims)
    t_max = max(target_dims)
    if l_max > 1e-6 and t_max > 1e-6:
        return t_max / l_max
    return 1.0


def count_placeable(context):
    """Count checked labels that have a mesh and valid spatial data."""
    tab = _get_tab(context)
    if not tab or not tab.has_result:
        return 0
    prefer_lp = getattr(tab, 'place_mesh_type', 'LP') == 'LP'
    count = 0
    for label in tab.objects:
        if not label.selected or not label.chain_id:
            continue
        if all(v == 0.0 for v in label.dimensions):
            continue
        if _find_mesh_for_chain_id(label.chain_id, prefer_lp=prefer_lp):
            count += 1
    return count


class MIXIE_OT_scene_gen_exp_place_in_scene(Operator):
    """Place generated meshes at their scene reconstruction positions"""

    bl_idname = "mixie.scene_gen_exp_place_in_scene"
    bl_label = "Place in Scene"
    bl_description = (
        "Position, rotate, and scale generated meshes using spatial data "
        "from scene reconstruction"
    )
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        eligible = count_placeable(context)
        if eligible == 0:
            self.report({"WARNING"}, "No eligible meshes to place")
            return {"CANCELLED"}
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        tab = _get_tab(context)
        if not tab or not tab.has_result:
            self.report({"WARNING"}, "Run Step 1 first")
            return {"CANCELLED"}

        prefer_lp = getattr(tab, 'place_mesh_type', 'LP') == 'LP'
        placed = 0
        skipped = 0

        for label in tab.objects:
            if not label.selected or not label.chain_id:
                continue

            dims = tuple(label.dimensions)
            if all(v == 0.0 for v in dims):
                skipped += 1
                continue

            mesh = _find_mesh_for_chain_id(label.chain_id, prefer_lp=prefer_lp)
            if not mesh:
                skipped += 1
                continue

            center = tuple(label.center)
            rotation = tuple(label.rotation)

            # --- Scale ---
            local_dims = _get_local_bbox_dims(mesh)
            scale_factor = _compute_uniform_scale(local_dims, dims)
            mesh.scale = (scale_factor, scale_factor, scale_factor)

            # --- Rotation (Z-axis only + 180° correction) ---
            z_angle = _extract_z_rotation(rotation) + math.pi
            mesh.rotation_euler = (0.0, 0.0, z_angle)

            # --- Position ---
            # Pivot is at the bottom of the mesh, so location = bottom
            # of the target bounding box (center minus half target height).
            mesh.location = (
                center[0],
                center[1],
                center[2] - dims[2] / 2.0,
            )

            placed += 1
            logger.debug(
                "[SceneGenExp] Placed '%s' at (%.2f, %.2f, %.2f) scale=%.3f rot_z=%.1f°",
                label.label, center[0], center[1], center[2] - dims[2] / 2.0,
                scale_factor, math.degrees(z_angle),
            )

        if placed == 0:
            self.report({"WARNING"}, f"No meshes placed ({skipped} skipped)")
            return {"CANCELLED"}

        msg = f"Placed {placed} mesh(es)"
        if skipped:
            msg += f" ({skipped} skipped)"
        self.report({"INFO"}, msg)
        return {"FINISHED"}


# Scene Gen Experimental disabled — operator intentionally not registered.
# classes = (MIXIE_OT_scene_gen_exp_place_in_scene,)
classes = ()

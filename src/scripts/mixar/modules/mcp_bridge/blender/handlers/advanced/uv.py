"""
Advanced UV handlers for Blender MCP Bridge.
Provides: uv/unwrap, uv/pack-islands, uv/info
"""

import math
import bpy
import bmesh
from ...utils.response import ok_response, error_response, not_found
from ...utils.context_helpers import ensure_context_for_object, temp_override, safe_operator_call
from .. import register_handler


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _get_mesh_object(name):
    """Return (obj, None) or (None, error_response) for a MESH object."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, not_found(name)
    if obj.type != "MESH":
        return None, error_response(
            f"Object '{name}' is of type '{obj.type}', not 'MESH'."
        )
    return obj, None


# ─── Handlers ──────────────────────────────────────────────────────────────────

def _handle_uv_unwrap(params):
    """
    UV unwrap a mesh object.
    Route: POST /api/uv/unwrap
    """
    object_name = params.get("object_name")
    method = params.get("method", "SMART_PROJECT").upper()
    angle_limit = params.get("angle_limit", 66.0)
    island_margin = params.get("island_margin", 0.02)

    if not object_name:
        return error_response("Parameter 'object_name' is required.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    valid_methods = ("SMART_PROJECT", "UNWRAP", "CUBE_PROJECT", "CYLINDER_PROJECT", "SPHERE_PROJECT")
    if method not in valid_methods:
        return error_response(
            f"Unknown unwrap method '{method}'. Valid: {', '.join(valid_methods)}."
        )

    try:
        ensure_context_for_object(obj)

        # Switch to Edit Mode
        bpy.ops.object.mode_set(mode="EDIT")

        try:
            # Select all faces so the unwrap covers the full mesh
            with temp_override("VIEW_3D"):
                bpy.ops.mesh.select_all(action="SELECT")

            with temp_override("VIEW_3D"):
                if method == "SMART_PROJECT":
                    angle_rad = math.radians(angle_limit)
                    bpy.ops.uv.smart_project(
                        angle_limit=angle_rad,
                        island_margin=island_margin,
                    )

                elif method == "UNWRAP":
                    bpy.ops.uv.unwrap(
                        method="ANGLE_BASED",
                        margin=island_margin,
                    )

                elif method == "CUBE_PROJECT":
                    bpy.ops.uv.cube_project()

                elif method == "CYLINDER_PROJECT":
                    bpy.ops.uv.cylinder_project()

                elif method == "SPHERE_PROJECT":
                    bpy.ops.uv.sphere_project()

        finally:
            bpy.ops.object.mode_set(mode="OBJECT")

        # Determine active UV layer name
        uv_layer_name = None
        if obj.data.uv_layers.active:
            uv_layer_name = obj.data.uv_layers.active.name

        return ok_response({
            "object_name": obj.name,
            "method": method,
            "uv_layer": uv_layer_name,
            "uv_layer_count": len(obj.data.uv_layers),
        })

    except Exception as e:
        try:
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
        return error_response(f"UV unwrap (method={method}) failed: {e}")


def _handle_uv_pack_islands(params):
    """
    Pack UV islands for a mesh object.
    Route: POST /api/uv/pack-islands
    """
    object_name = params.get("object_name")
    margin = params.get("margin", 0.001)
    rotate = params.get("rotate", True)

    if not object_name:
        return error_response("Parameter 'object_name' is required.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    if not obj.data.uv_layers:
        return error_response(
            f"Object '{object_name}' has no UV layers. Unwrap it first."
        )

    try:
        ensure_context_for_object(obj)
        bpy.ops.object.mode_set(mode="EDIT")

        try:
            with temp_override("VIEW_3D"):
                bpy.ops.mesh.select_all(action="SELECT")

            with temp_override("VIEW_3D"):
                bpy.ops.uv.pack_islands(margin=margin, rotate=rotate)

        finally:
            bpy.ops.object.mode_set(mode="OBJECT")

        # Estimate island count via BMesh (count connected UV components)
        island_count = _estimate_uv_island_count(obj)

        return ok_response({
            "object_name": obj.name,
            "margin": margin,
            "rotate": rotate,
            "estimated_island_count": island_count,
        })

    except Exception as e:
        try:
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
        return error_response(f"UV pack islands failed: {e}")


def _estimate_uv_island_count(obj):
    """
    Estimate the number of UV islands by counting connected UV face components.
    Uses a standalone BMesh (freed after use).
    """
    try:
        bm = bmesh.new()
        try:
            bm.from_mesh(obj.data)
            bm.faces.ensure_lookup_table()

            uv_layer = bm.loops.layers.uv.active
            if uv_layer is None:
                return 0

            # Build UV adjacency: faces sharing a UV edge are in the same island
            visited = set()
            islands = 0

            def _get_face_uv_verts(face):
                return frozenset(tuple(loop[uv_layer].uv) for loop in face.loops)

            uv_map = {face.index: _get_face_uv_verts(face) for face in bm.faces}

            for face in bm.faces:
                if face.index in visited:
                    continue
                # BFS to find all faces connected in UV space
                islands += 1
                queue = [face]
                visited.add(face.index)
                while queue:
                    current = queue.pop()
                    current_uvs = uv_map[current.index]
                    for edge in current.edges:
                        for linked_face in edge.link_faces:
                            if linked_face.index in visited:
                                continue
                            # Check if they share UV coordinates
                            if current_uvs & uv_map[linked_face.index]:
                                visited.add(linked_face.index)
                                queue.append(linked_face)

            return islands
        finally:
            bm.free()
    except Exception:
        return -1  # Unknown


def _handle_uv_info(params):
    """
    Get UV layer information for a mesh object.
    Route: POST /api/uv/info
    """
    object_name = params.get("object_name")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    try:
        mesh = obj.data
        uv_layers = mesh.uv_layers

        has_uvs = len(uv_layers) > 0
        active_layer = uv_layers.active.name if uv_layers.active else None

        layer_info = []
        for layer in uv_layers:
            # Count UV loops and compute coverage with a standalone BMesh
            loop_count = 0
            coverage = 0.0
            try:
                bm = bmesh.new()
                try:
                    bm.from_mesh(mesh)
                    bm.faces.ensure_lookup_table()
                    uv_layer_bm = bm.loops.layers.uv.get(layer.name)

                    if uv_layer_bm:
                        total_area = 0.0
                        for face in bm.faces:
                            # Compute UV face area using the shoelace formula
                            uvs = [loop[uv_layer_bm].uv for loop in face.loops]
                            loop_count += len(uvs)
                            n = len(uvs)
                            area = 0.0
                            for i in range(n):
                                j = (i + 1) % n
                                area += uvs[i].x * uvs[j].y
                                area -= uvs[j].x * uvs[i].y
                            total_area += abs(area) * 0.5
                        coverage = round(min(total_area, 1.0), 6)
                finally:
                    bm.free()
            except Exception:
                pass

            layer_info.append({
                "name": layer.name,
                "active": layer.name == active_layer,
                "loop_count": loop_count,
                "uv_coverage": coverage,
            })

        return ok_response({
            "object_name": obj.name,
            "has_uvs": has_uvs,
            "layer_count": len(uv_layers),
            "active_layer": active_layer,
            "layers": layer_info,
        })

    except Exception as e:
        return error_response(f"Failed to get UV info for '{object_name}': {e}")


def _handle_uv_mark_seam(params):
    """
    Mark or clear UV seams on a mesh object.
    Route: POST /api/uv/mark-seam
    """
    object_name = params.get("object_name")
    mode = params.get("mode", "MARK_BY_ANGLE").upper()
    angle_threshold = params.get("angle_threshold", 30.0)

    if not object_name:
        return error_response("Parameter 'object_name' is required.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    valid_modes = ("MARK_SHARP", "MARK_BY_ANGLE", "CLEAR_ALL")
    if mode not in valid_modes:
        return error_response(
            f"Invalid mode '{mode}'. Valid values: {', '.join(valid_modes)}."
        )

    try:
        bm = bmesh.new()
        try:
            bm.from_mesh(obj.data)
            bm.edges.ensure_lookup_table()

            affected = 0

            if mode == "CLEAR_ALL":
                for edge in bm.edges:
                    if edge.seam:
                        edge.seam = False
                        affected += 1

            elif mode == "MARK_SHARP":
                for edge in bm.edges:
                    if not edge.smooth:  # sharp edges have smooth=False
                        if not edge.seam:
                            edge.seam = True
                            affected += 1

            elif mode == "MARK_BY_ANGLE":
                angle_rad = math.radians(angle_threshold)
                for edge in bm.edges:
                    if len(edge.link_faces) == 2:
                        angle = edge.calc_face_angle(0)
                        if angle > angle_rad:
                            if not edge.seam:
                                edge.seam = True
                                affected += 1

            bm.to_mesh(obj.data)
        finally:
            bm.free()

        obj.data.update()

        return ok_response({
            "object_name": obj.name,
            "mode": mode,
            "edges_affected": affected,
            "total_edges": len(obj.data.edges),
        })

    except Exception as e:
        return error_response(f"UV seam marking failed: {e}")


# ─── Register routes ────────────────────────────────────────────────────────────

register_handler("uv", "unwrap", _handle_uv_unwrap)
register_handler("uv", "pack-islands", _handle_uv_pack_islands)
register_handler("uv", "info", _handle_uv_info)
register_handler("uv", "mark-seam", _handle_uv_mark_seam)

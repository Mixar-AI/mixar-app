"""
Advanced vertex group handlers for Blender MCP Bridge.
Provides: vgroup/create, vgroup/assign, vgroup/remove, vgroup/list,
          vgroup/paint, vgroup/normalize
"""

import bpy
from mathutils import Vector
from ...utils.response import ok_response, error_response, not_found
from ...utils.context_helpers import ensure_context_for_object, temp_override, safe_operator_call
from .. import register_handler


# ─── Helpers ────────────────────────────────────────────────────────────────────

def _get_mesh_object(name):
    """Return (obj, None) or (None, error_response) for a MESH object."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, not_found(name)
    if obj.type != "MESH":
        return None, error_response(
            f"Object '{name}' is type '{obj.type}', not 'MESH'."
        )
    return obj, None


def _exit_to_object_mode():
    """Switch back to Object Mode if not already there."""
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")


# ─── Handlers ───────────────────────────────────────────────────────────────────

def _handle_vgroup_create(params):
    """
    Create a new vertex group on a mesh object.
    Route: POST /api/vgroup/create
    """
    object_name = params.get("object_name")
    group_name = params.get("group_name")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not group_name:
        return error_response("Parameter 'group_name' is required.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    try:
        # Return existing group rather than creating a duplicate
        vg = obj.vertex_groups.get(group_name)
        if vg is None:
            vg = obj.vertex_groups.new(name=group_name)

        return ok_response({
            "object_name": obj.name,
            "group_name": vg.name,
            "group_index": vg.index,
        })
    except Exception as e:
        return error_response(f"Failed to create vertex group: {e}")


def _handle_vgroup_assign(params):
    """
    Assign a weight to vertices in a named vertex group.
    Route: POST /api/vgroup/assign
    """
    object_name = params.get("object_name")
    group_name = params.get("group_name")
    vertex_indices = params.get("vertex_indices")
    weight = params.get("weight")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not group_name:
        return error_response("Parameter 'group_name' is required.")
    if vertex_indices is None:
        return error_response("Parameter 'vertex_indices' is required.")
    if not isinstance(vertex_indices, list) or not all(isinstance(i, (int, float)) for i in vertex_indices):
        return error_response("Parameter 'vertex_indices' must be an array of numeric values.")
    if weight is None:
        return error_response("Parameter 'weight' is required.")

    weight = float(weight)
    if not (0.0 <= weight <= 1.0):
        return error_response("Parameter 'weight' must be between 0.0 and 1.0.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    try:
        vg = obj.vertex_groups.get(group_name)
        if vg is None:
            return error_response(
                f"Vertex group '{group_name}' not found on object '{object_name}'. "
                "Use blender_vgroup_create first."
            )

        indices = [int(i) for i in vertex_indices]
        vg.add(indices, weight, "REPLACE")

        return ok_response({
            "object_name": obj.name,
            "group_name": vg.name,
            "vertex_count": len(indices),
            "weight": weight,
        })
    except Exception as e:
        return error_response(f"Failed to assign vertex group weights: {e}")


def _handle_vgroup_remove(params):
    """
    Remove a vertex group from a mesh object.
    Route: POST /api/vgroup/remove
    """
    object_name = params.get("object_name")
    group_name = params.get("group_name")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not group_name:
        return error_response("Parameter 'group_name' is required.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    try:
        vg = obj.vertex_groups.get(group_name)
        if vg is None:
            return error_response(
                f"Vertex group '{group_name}' not found on object '{object_name}'."
            )

        obj.vertex_groups.remove(vg)

        return ok_response({
            "object_name": obj.name,
            "removed_group": group_name,
        })
    except Exception as e:
        return error_response(f"Failed to remove vertex group: {e}")


def _handle_vgroup_list(params):
    """
    List all vertex groups on a mesh object.
    Route: POST /api/vgroup/list
    """
    object_name = params.get("object_name")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    try:
        groups = [
            {
                "name": vg.name,
                "index": vg.index,
                "lock_weight": vg.lock_weight,
            }
            for vg in obj.vertex_groups
        ]

        return ok_response({
            "object_name": obj.name,
            "group_count": len(groups),
            "vertex_groups": groups,
        })
    except Exception as e:
        return error_response(f"Failed to list vertex groups: {e}")


def _handle_vgroup_paint(params):
    """
    Procedurally paint vertex weights using a gradient pattern.
    Route: POST /api/vgroup/paint
    """
    object_name = params.get("object_name")
    group_name = params.get("group_name")
    gradient = params.get("gradient", "TOP_BOTTOM").upper()

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not group_name:
        return error_response("Parameter 'group_name' is required.")

    valid_gradients = ("TOP_BOTTOM", "CENTER_OUT")
    if gradient not in valid_gradients:
        return error_response(
            f"Unknown gradient '{gradient}'. Valid: TOP_BOTTOM, CENTER_OUT."
        )

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    try:
        # Get or create the vertex group
        vg = obj.vertex_groups.get(group_name)
        if vg is None:
            vg = obj.vertex_groups.new(name=group_name)

        mesh = obj.data
        vertices = mesh.vertices

        if len(vertices) == 0:
            return error_response(f"Object '{object_name}' has no vertices.")

        if gradient == "TOP_BOTTOM":
            z_values = [v.co.z for v in vertices]
            min_z = min(z_values)
            max_z = max(z_values)
            z_range = max_z - min_z

            for vertex in vertices:
                if z_range < 1e-6:
                    weight = 0.5
                else:
                    weight = (vertex.co.z - min_z) / z_range
                vg.add([vertex.index], float(weight), "REPLACE")

        elif gradient == "CENTER_OUT":
            # Compute local-space centroid
            center = Vector((
                sum(v.co.x for v in vertices) / len(vertices),
                sum(v.co.y for v in vertices) / len(vertices),
                sum(v.co.z for v in vertices) / len(vertices),
            ))

            distances = [(v.co - center).length for v in vertices]
            max_distance = max(distances) if distances else 0.0

            for vertex in vertices:
                if max_distance < 1e-6:
                    weight = 1.0
                else:
                    dist = (vertex.co - center).length
                    weight = 1.0 - (dist / max_distance)
                vg.add([vertex.index], float(weight), "REPLACE")

        return ok_response({
            "object_name": obj.name,
            "group_name": vg.name,
            "gradient": gradient,
            "vertex_count": len(vertices),
        })
    except Exception as e:
        return error_response(f"Failed to paint vertex group: {e}")


def _handle_vgroup_normalize(params):
    """
    Normalize all vertex group weights on a mesh so they sum to 1.0 per vertex.
    Route: POST /api/vgroup/normalize
    """
    object_name = params.get("object_name")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    try:
        ensure_context_for_object(obj)

        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        with temp_override("VIEW_3D"):
            ok_result, res = safe_operator_call(
                bpy.ops.object.vertex_group_normalize_all
            )

        if not ok_result:
            return error_response(f"Normalize all vertex groups failed: {res}")

        return ok_response({
            "object_name": obj.name,
            "group_count": len(obj.vertex_groups),
        })
    except Exception as e:
        return error_response(f"Failed to normalize vertex groups: {e}")
    finally:
        _exit_to_object_mode()


# ─── Register routes ─────────────────────────────────────────────────────────────

register_handler("vgroup", "create",    _handle_vgroup_create)
register_handler("vgroup", "assign",    _handle_vgroup_assign)
register_handler("vgroup", "remove",    _handle_vgroup_remove)
register_handler("vgroup", "list",      _handle_vgroup_list)
register_handler("vgroup", "paint",     _handle_vgroup_paint)
register_handler("vgroup", "normalize", _handle_vgroup_normalize)

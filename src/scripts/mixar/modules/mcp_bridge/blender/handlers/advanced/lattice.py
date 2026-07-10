"""
Advanced lattice handlers for Blender MCP Bridge.
Provides: lattice/create, lattice/assign, lattice/edit-point, lattice/fit-to-object
"""

import bpy
from mathutils import Vector
from ...utils.response import ok_response, error_response, not_found
from ...utils.context_helpers import ensure_context_for_object
from .. import register_handler


# ─── Helpers ────────────────────────────────────────────────────────────────────

def _get_lattice_object(name):
    """Return (obj, None) or (None, error_response) for a LATTICE object."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, not_found(name, "Lattice")
    if obj.type != "LATTICE":
        return None, error_response(
            f"Object '{name}' is type '{obj.type}', not 'LATTICE'."
        )
    return obj, None


def _get_any_object(name):
    """Return (obj, None) or (None, error_response) for any object."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, not_found(name, "Lattice")
    return obj, None


def _world_bounding_box(obj):
    """Return the 8 world-space corners of obj's bounding box."""
    mat = obj.matrix_world
    return [mat @ Vector(corner) for corner in obj.bound_box]


# ─── Handlers ───────────────────────────────────────────────────────────────────

def _handle_lattice_create(params):
    """
    Create a new lattice object.
    Route: POST /api/lattice/create
    """
    try:
        name = params.get("name")
        if not name:
            return error_response("Parameter 'name' is required.")

        location = params.get("location", [0.0, 0.0, 0.0])
        if len(location) != 3:
            return error_response("Parameter 'location' must be a [x, y, z] array.")

        resolution = params.get("resolution") or {}
        points_u = max(2, int(resolution.get("u", 2)))
        points_v = max(2, int(resolution.get("v", 2)))
        points_w = max(2, int(resolution.get("w", 2)))

        lat_data = bpy.data.lattices.new(name)
        lat_data.points_u = points_u
        lat_data.points_v = points_v
        lat_data.points_w = points_w

        obj = bpy.data.objects.new(name, lat_data)
        bpy.context.collection.objects.link(obj)
        obj.location = tuple(location)

        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        return ok_response({
            "lattice_name": obj.name,
            "location": [round(v, 6) for v in obj.location],
            "resolution": {
                "u": lat_data.points_u,
                "v": lat_data.points_v,
                "w": lat_data.points_w,
            },
        })
    except Exception as e:
        return error_response(f"Failed to create lattice: {e}")


def _handle_lattice_assign(params):
    """
    Assign a lattice deformer to a target object via a Lattice modifier.
    Route: POST /api/lattice/assign
    """
    lattice_name = params.get("lattice_name")
    object_name = params.get("object_name")

    if not lattice_name:
        return error_response("Parameter 'lattice_name' is required.")
    if not object_name:
        return error_response("Parameter 'object_name' is required.")

    lattice_obj, err = _get_lattice_object(lattice_name)
    if err:
        return err

    target_obj, err = _get_any_object(object_name)
    if err:
        return err

    try:
        mod = target_obj.modifiers.new("Lattice", "LATTICE")
        mod.object = lattice_obj

        return ok_response({
            "lattice_name": lattice_obj.name,
            "object_name": target_obj.name,
            "modifier_name": mod.name,
        })
    except Exception as e:
        return error_response(f"Failed to assign lattice modifier: {e}")


def _handle_lattice_edit_point(params):
    """
    Move a single lattice control point to a new position.
    Route: POST /api/lattice/edit-point
    """
    lattice_name = params.get("lattice_name")
    index = params.get("index")
    position = params.get("position")

    if not lattice_name:
        return error_response("Parameter 'lattice_name' is required.")
    if index is None:
        return error_response("Parameter 'index' is required.")
    if position is None or len(position) != 3:
        return error_response("Parameter 'position' must be a [x, y, z] array.")
    if not all(isinstance(v, (int, float)) for v in position):
        return error_response("All elements of 'position' must be numeric (int or float).")

    lattice_obj, err = _get_lattice_object(lattice_name)
    if err:
        return err

    try:
        lat_data = lattice_obj.data
        point_count = len(lat_data.points)
        idx = int(index)

        if idx < 0 or idx >= point_count:
            return error_response(
                f"Index {idx} is out of range. Lattice has {point_count} control points (0–{point_count - 1})."
            )

        lat_data.points[idx].co_deform = Vector(position)

        return ok_response({
            "lattice_name": lattice_obj.name,
            "index": idx,
            "position": [round(v, 6) for v in position],
        })
    except Exception as e:
        return error_response(f"Failed to edit lattice point: {e}")


def _handle_lattice_fit_to_object(params):
    """
    Resize and reposition a lattice to enclose a target object's bounding box.
    Route: POST /api/lattice/fit-to-object
    """
    lattice_name = params.get("lattice_name")
    object_name = params.get("object_name")
    margin = float(params.get("margin", 0.0))

    if not lattice_name:
        return error_response("Parameter 'lattice_name' is required.")
    if not object_name:
        return error_response("Parameter 'object_name' is required.")

    lattice_obj, err = _get_lattice_object(lattice_name)
    if err:
        return err

    target_obj, err = _get_any_object(object_name)
    if err:
        return err

    try:
        # Compute world-space bounding box of the target object
        world_corners = _world_bounding_box(target_obj)

        xs = [v.x for v in world_corners]
        ys = [v.y for v in world_corners]
        zs = [v.z for v in world_corners]

        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        min_z, max_z = min(zs), max(zs)

        center_x = (min_x + max_x) / 2.0
        center_y = (min_y + max_y) / 2.0
        center_z = (min_z + max_z) / 2.0

        dim_x = (max_x - min_x) + margin * 2.0
        dim_y = (max_y - min_y) + margin * 2.0
        dim_z = (max_z - min_z) + margin * 2.0

        # Ensure minimum dimension to avoid zero-scale degeneracy
        dim_x = max(dim_x, 0.001)
        dim_y = max(dim_y, 0.001)
        dim_z = max(dim_z, 0.001)

        lattice_obj.location = (center_x, center_y, center_z)
        lattice_obj.scale = (dim_x, dim_y, dim_z)

        return ok_response({
            "lattice_name": lattice_obj.name,
            "object_name": target_obj.name,
            "center": [round(center_x, 6), round(center_y, 6), round(center_z, 6)],
            "scale": [round(dim_x, 6), round(dim_y, 6), round(dim_z, 6)],
            "margin": margin,
        })
    except Exception as e:
        return error_response(f"Failed to fit lattice to object: {e}")


# ─── Register routes ─────────────────────────────────────────────────────────────

register_handler("lattice", "create",         _handle_lattice_create)
register_handler("lattice", "assign",         _handle_lattice_assign)
register_handler("lattice", "edit-point",     _handle_lattice_edit_point)
register_handler("lattice", "fit-to-object",  _handle_lattice_fit_to_object)

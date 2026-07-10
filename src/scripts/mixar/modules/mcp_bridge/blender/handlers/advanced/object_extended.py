"""
Object extended handlers for Blender MCP Bridge.
Provides: object/rename, object/set-origin
"""

import bpy
from mathutils import Vector
from ...utils.response import ok_response, error_response, not_found
from ...utils.context_helpers import ensure_context_for_object, temp_override, safe_operator_call
from .. import register_handler


# ─── Helpers ────────────────────────────────────────────────────────────────────

def _get_object(name):
    """Return (obj, None) or (None, error_response) for any object."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, not_found(name)
    return obj, None


# ─── Handlers ───────────────────────────────────────────────────────────────────

def _handle_object_rename(params):
    """
    Rename an existing object.
    Route: POST /api/object/rename
    """
    old_name = params.get("old_name")
    new_name = params.get("new_name")

    if not old_name:
        return error_response("Parameter 'old_name' is required.")
    if not new_name:
        return error_response("Parameter 'new_name' is required.")

    obj = bpy.data.objects.get(old_name)
    if obj is None:
        return not_found(old_name)

    try:
        obj.name = new_name
        # Blender may suffix '.001' etc. on name collision — report the actual name
        return ok_response({
            "old_name": old_name,
            "new_name": obj.name,
            "object_name": obj.name,
        })
    except Exception as e:
        return error_response(f"Failed to rename object '{old_name}' to '{new_name}': {e}")


def _handle_object_set_origin(params):
    """
    Set the origin point of an object.
    Route: POST /api/object/set-origin
    """
    name        = params.get("object_name") or params.get("name")
    origin_type = params.get("type", "CENTER").upper()

    if not name:
        return error_response("Parameter 'object_name' (or 'name') is required.")

    valid_types = ("CENTER", "BOTTOM", "CURSOR", "GEOMETRY")
    if origin_type not in valid_types:
        return error_response(
            f"Invalid type '{origin_type}'. Valid values: {', '.join(valid_types)}."
        )

    obj, err = _get_object(name)
    if err:
        return err

    try:
        ensure_context_for_object(obj)

        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        if origin_type == "BOTTOM":
            # BOTTOM is not a native Blender origin type.
            # Calculate the bottom-center of the world-space bounding box,
            # temporarily move the 3D cursor there, then use ORIGIN_CURSOR.
            bbox_corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
            min_z    = min(c.z for c in bbox_corners)
            center_x = sum(c.x for c in bbox_corners) / 8.0
            center_y = sum(c.y for c in bbox_corners) / 8.0

            saved_cursor = bpy.context.scene.cursor.location.copy()
            bpy.context.scene.cursor.location = (center_x, center_y, min_z)

            with temp_override("VIEW_3D"):
                ok, res = safe_operator_call(
                    bpy.ops.object.origin_set, type="ORIGIN_CURSOR"
                )
            # Always restore cursor regardless of success
            bpy.context.scene.cursor.location = saved_cursor

            if not ok:
                return error_response(f"origin_set ORIGIN_CURSOR failed: {res}")

        elif origin_type == "GEOMETRY":
            with temp_override("VIEW_3D"):
                ok, res = safe_operator_call(
                    bpy.ops.object.origin_set, type="ORIGIN_GEOMETRY"
                )
            if not ok:
                return error_response(f"origin_set ORIGIN_GEOMETRY failed: {res}")

        elif origin_type == "CURSOR":
            with temp_override("VIEW_3D"):
                ok, res = safe_operator_call(
                    bpy.ops.object.origin_set, type="ORIGIN_CURSOR"
                )
            if not ok:
                return error_response(f"origin_set ORIGIN_CURSOR failed: {res}")

        else:
            # CENTER — center of mass
            with temp_override("VIEW_3D"):
                ok, res = safe_operator_call(
                    bpy.ops.object.origin_set, type="ORIGIN_CENTER_OF_MASS"
                )
            if not ok:
                return error_response(f"origin_set ORIGIN_CENTER_OF_MASS failed: {res}")

        return ok_response({
            "name":        obj.name,
            "object_name": obj.name,
            "origin_type": origin_type,
        })
    except Exception as e:
        return error_response(f"Failed to set origin on '{name}': {e}")


def _handle_object_set_visibility(params):
    """
    Set visibility properties of an object.
    Route: POST /api/object/set-visibility
    """
    name = params.get("object_name") or params.get("name")
    if not name:
        return error_response("Parameter 'object_name' is required.")

    obj, err = _get_object(name)
    if err:
        return err

    try:
        if "hide_viewport" in params:
            obj.hide_viewport = bool(params["hide_viewport"])
        if "hide_render" in params:
            obj.hide_render = bool(params["hide_render"])
        if "hide_select" in params:
            obj.hide_select = bool(params["hide_select"])

        return ok_response({
            "object_name": obj.name,
            "hide_viewport": obj.hide_viewport,
            "hide_render": obj.hide_render,
            "hide_select": obj.hide_select,
        })
    except Exception as e:
        return error_response(f"Failed to set visibility on '{name}': {e}")


# ─── Register routes ─────────────────────────────────────────────────────────────

register_handler("object", "rename",         _handle_object_rename)
register_handler("object", "set-origin",     _handle_object_set_origin)
register_handler("object", "set-visibility", _handle_object_set_visibility)

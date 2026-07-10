"""
Advanced curve handlers for Blender MCP Bridge.
Provides: curve/create, curve/add-point, curve/edit-point, curve/set-properties,
          curve/to-mesh, curve/from-points, curve/set-bevel-object, curve/set-taper-object
"""

import bpy
from ...utils.response import ok_response, error_response, not_found
from ...utils.context_helpers import ensure_context_for_object, temp_override
from .. import register_handler


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _get_curve_object(name):
    """Return (obj, None) or (None, error_response) for a CURVE object."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, not_found(name, "Curve")
    if obj.type != "CURVE":
        return None, error_response(
            f"Object '{name}' is of type '{obj.type}', not 'CURVE'."
        )
    return obj, None


# ─── Handlers ──────────────────────────────────────────────────────────────────

def _handle_curve_create(params):
    """
    Create a new curve object.
    Route: POST /api/curve/create
    """
    try:
        spline_type = params.get("type", "BEZIER").upper()
        name = params.get("name", "Curve")
        points = params.get("points") or []

        valid_types = ("BEZIER", "NURBS", "PATH")
        if spline_type not in valid_types:
            return error_response(
                f"Unknown curve type '{spline_type}'. Valid: {', '.join(valid_types)}."
            )

        # PATH is internally a NURBS spline in Blender
        internal_type = "NURBS" if spline_type == "PATH" else spline_type

        curve_data = bpy.data.curves.new(name, type="CURVE")
        curve_data.dimensions = "3D"

        spline = curve_data.splines.new(internal_type)

        if points:
            count = len(points)
            if spline_type == "BEZIER":
                spline.bezier_points.add(count - 1)
                for i, pt in enumerate(points):
                    bp = spline.bezier_points[i]
                    bp.co = (pt[0], pt[1], pt[2])
                    bp.handle_left = (pt[0], pt[1], pt[2])
                    bp.handle_right = (pt[0], pt[1], pt[2])
            else:
                spline.points.add(count - 1)
                for i, pt in enumerate(points):
                    spline.points[i].co = (pt[0], pt[1], pt[2], 1.0)

        obj = bpy.data.objects.new(name, curve_data)
        bpy.context.collection.objects.link(obj)

        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        point_count = (
            len(spline.bezier_points) if spline_type == "BEZIER" else len(spline.points)
        )
        return ok_response({
            "object_name": obj.name,
            "spline_type": spline_type,
            "point_count": point_count,
        })
    except Exception as e:
        return error_response(f"Failed to create curve: {e}")


def _handle_curve_add_point(params):
    """
    Append a new control point to the first spline of a curve object.
    Route: POST /api/curve/add-point
    """
    curve_name = params.get("curve_name")
    position = params.get("position")
    handle_left = params.get("handle_left")
    handle_right = params.get("handle_right")

    if not curve_name:
        return error_response("Parameter 'curve_name' is required.")
    if not position:
        return error_response("Parameter 'position' is required.")

    obj, err = _get_curve_object(curve_name)
    if err:
        return err

    try:
        curve_data = obj.data
        if not curve_data.splines:
            return error_response(f"Curve '{curve_name}' has no splines.")

        spline = curve_data.splines[0]

        if spline.type == "BEZIER":
            spline.bezier_points.add(1)
            bp = spline.bezier_points[-1]
            bp.co = (position[0], position[1], position[2])
            if handle_left:
                bp.handle_left = (handle_left[0], handle_left[1], handle_left[2])
            else:
                bp.handle_left = (position[0], position[1], position[2])
            if handle_right:
                bp.handle_right = (handle_right[0], handle_right[1], handle_right[2])
            else:
                bp.handle_right = (position[0], position[1], position[2])
            point_count = len(spline.bezier_points)
        else:
            spline.points.add(1)
            spline.points[-1].co = (position[0], position[1], position[2], 1.0)
            point_count = len(spline.points)

        return ok_response({
            "object_name": obj.name,
            "spline_type": spline.type,
            "point_count": point_count,
        })
    except Exception as e:
        return error_response(f"Failed to add point to curve '{curve_name}': {e}")


def _handle_curve_edit_point(params):
    """
    Edit an existing control point on the first spline of a curve object by index.
    Route: POST /api/curve/edit-point
    """
    curve_name = params.get("curve_name")
    index = params.get("index")
    position = params.get("position")
    handle_left = params.get("handle_left")
    handle_right = params.get("handle_right")
    tilt = params.get("tilt")

    if not curve_name:
        return error_response("Parameter 'curve_name' is required.")
    if index is None:
        return error_response("Parameter 'index' is required.")

    obj, err = _get_curve_object(curve_name)
    if err:
        return err

    try:
        curve_data = obj.data
        if not curve_data.splines:
            return error_response(f"Curve '{curve_name}' has no splines.")

        spline = curve_data.splines[0]

        if spline.type == "BEZIER":
            pts = spline.bezier_points
            if index < 0 or index >= len(pts):
                return error_response(
                    f"Index {index} out of range for BEZIER spline with {len(pts)} points."
                )
            bp = pts[index]
            if position:
                bp.co = (position[0], position[1], position[2])
            if handle_left:
                bp.handle_left = (handle_left[0], handle_left[1], handle_left[2])
            if handle_right:
                bp.handle_right = (handle_right[0], handle_right[1], handle_right[2])
            if tilt is not None:
                bp.tilt = tilt
            updated = {
                "co": list(bp.co),
                "handle_left": list(bp.handle_left),
                "handle_right": list(bp.handle_right),
                "tilt": bp.tilt,
            }
        else:
            pts = spline.points
            if index < 0 or index >= len(pts):
                return error_response(
                    f"Index {index} out of range for {spline.type} spline with {len(pts)} points."
                )
            p = pts[index]
            if position:
                p.co = (position[0], position[1], position[2], 1.0)
            updated = {"co": list(p.co[:3])}

        return ok_response({
            "object_name": obj.name,
            "spline_type": spline.type,
            "index": index,
            "updated": updated,
        })
    except Exception as e:
        return error_response(f"Failed to edit point {index} on curve '{curve_name}': {e}")


def _handle_curve_set_properties(params):
    """
    Set geometry/render properties on a curve object.
    Route: POST /api/curve/set-properties
    """
    curve_name = params.get("curve_name")

    if not curve_name:
        return error_response("Parameter 'curve_name' is required.")

    obj, err = _get_curve_object(curve_name)
    if err:
        return err

    try:
        curve_data = obj.data
        changed = {}

        if "resolution" in params:
            curve_data.resolution_u = int(params["resolution"])
            changed["resolution_u"] = curve_data.resolution_u

        if "bevel_depth" in params:
            curve_data.bevel_depth = float(params["bevel_depth"])
            changed["bevel_depth"] = curve_data.bevel_depth

        if "bevel_resolution" in params:
            curve_data.bevel_resolution = int(params["bevel_resolution"])
            changed["bevel_resolution"] = curve_data.bevel_resolution

        if "extrude" in params:
            curve_data.extrude = float(params["extrude"])
            changed["extrude"] = curve_data.extrude

        if "twist_mode" in params:
            valid_twist = ("Z_UP", "MINIMUM", "TANGENT")
            twist = params["twist_mode"].upper()
            if twist not in valid_twist:
                return error_response(
                    f"Unknown twist_mode '{twist}'. Valid: {', '.join(valid_twist)}."
                )
            curve_data.twist_mode = twist
            changed["twist_mode"] = curve_data.twist_mode

        return ok_response({
            "object_name": obj.name,
            "properties_set": changed,
        })
    except Exception as e:
        return error_response(f"Failed to set properties on curve '{curve_name}': {e}")


def _handle_curve_to_mesh(params):
    """
    Convert a curve object to a mesh object in-place.
    Route: POST /api/curve/to-mesh
    """
    curve_name = params.get("curve_name")
    profile_curve = params.get("profile_curve")

    if not curve_name:
        return error_response("Parameter 'curve_name' is required.")

    obj, err = _get_curve_object(curve_name)
    if err:
        return err

    try:
        # Optionally set a profile/bevel curve before conversion
        if profile_curve:
            profile_obj = bpy.data.objects.get(profile_curve)
            if profile_obj is None:
                return error_response(f"Profile curve object '{profile_curve}' not found.")
            if profile_obj.type != "CURVE":
                return error_response(
                    f"Profile object '{profile_curve}' is of type '{profile_obj.type}', not 'CURVE'."
                )
            obj.data.bevel_object = profile_obj

        ensure_context_for_object(obj)

        with temp_override("VIEW_3D"):
            bpy.ops.object.convert(target="MESH")

        # After conversion obj still references the same object, now a MESH
        mesh_obj = bpy.context.view_layer.objects.active
        mesh = mesh_obj.data

        return ok_response({
            "object_name": mesh_obj.name,
            "vertex_count": len(mesh.vertices),
            "face_count": len(mesh.polygons),
            "edge_count": len(mesh.edges),
        })
    except Exception as e:
        return error_response(f"Failed to convert curve '{curve_name}' to mesh: {e}")


def _handle_curve_from_points(params):
    """
    Create a curve object from a complete list of points in one pass.
    Route: POST /api/curve/from-points
    """
    try:
        name = params.get("name", "Curve")
        points = params.get("points") or []
        spline_type = params.get("type", "BEZIER").upper()
        cyclic = params.get("cyclic", False)

        if not points:
            return error_response("Parameter 'points' must be a non-empty list.")

        valid_types = ("BEZIER", "NURBS", "POLY")
        if spline_type not in valid_types:
            return error_response(
                f"Unknown spline type '{spline_type}'. Valid: {', '.join(valid_types)}."
            )

        curve_data = bpy.data.curves.new(name, type="CURVE")
        curve_data.dimensions = "3D"

        spline = curve_data.splines.new(spline_type)
        count = len(points)

        if spline_type == "BEZIER":
            spline.bezier_points.add(count - 1)
            for i, pt in enumerate(points):
                bp = spline.bezier_points[i]
                bp.co = (pt[0], pt[1], pt[2])
                bp.handle_left = (pt[0], pt[1], pt[2])
                bp.handle_right = (pt[0], pt[1], pt[2])
        else:
            spline.points.add(count - 1)
            for i, pt in enumerate(points):
                spline.points[i].co = (pt[0], pt[1], pt[2], 1.0)

        if cyclic:
            spline.use_cyclic_u = True

        obj = bpy.data.objects.new(name, curve_data)
        bpy.context.collection.objects.link(obj)

        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        point_count = (
            len(spline.bezier_points) if spline_type == "BEZIER" else len(spline.points)
        )
        return ok_response({
            "object_name": obj.name,
            "spline_type": spline_type,
            "point_count": point_count,
            "cyclic": cyclic,
        })
    except Exception as e:
        return error_response(f"Failed to create curve from points: {e}")


def _handle_curve_set_bevel_object(params):
    """
    Assign a bevel object to a curve.
    Route: POST /api/curve/set-bevel-object
    """
    curve_name = params.get("curve_name")
    bevel_object_name = params.get("bevel_object_name")

    if not curve_name:
        return error_response("Parameter 'curve_name' is required.")
    if not bevel_object_name:
        return error_response("Parameter 'bevel_object_name' is required.")

    obj, err = _get_curve_object(curve_name)
    if err:
        return err

    try:
        bevel_obj = bpy.data.objects.get(bevel_object_name)
        if bevel_obj is None:
            return error_response(f"Bevel object '{bevel_object_name}' not found.")
        if bevel_obj.type != "CURVE":
            return error_response(
                f"Bevel object '{bevel_object_name}' is of type '{bevel_obj.type}', not 'CURVE'."
            )

        obj.data.bevel_object = bevel_obj

        return ok_response({
            "object_name": obj.name,
            "bevel_object": bevel_obj.name,
        })
    except Exception as e:
        return error_response(f"Failed to set bevel object on curve '{curve_name}': {e}")


def _handle_curve_set_taper_object(params):
    """
    Assign a taper object to a curve.
    Route: POST /api/curve/set-taper-object
    """
    curve_name = params.get("curve_name")
    taper_object_name = params.get("taper_object_name")

    if not curve_name:
        return error_response("Parameter 'curve_name' is required.")
    if not taper_object_name:
        return error_response("Parameter 'taper_object_name' is required.")

    obj, err = _get_curve_object(curve_name)
    if err:
        return err

    try:
        taper_obj = bpy.data.objects.get(taper_object_name)
        if taper_obj is None:
            return error_response(f"Taper object '{taper_object_name}' not found.")
        if taper_obj.type != "CURVE":
            return error_response(
                f"Taper object '{taper_object_name}' is of type '{taper_obj.type}', not 'CURVE'."
            )

        obj.data.taper_object = taper_obj

        return ok_response({
            "object_name": obj.name,
            "taper_object": taper_obj.name,
        })
    except Exception as e:
        return error_response(f"Failed to set taper object on curve '{curve_name}': {e}")


# ─── Register routes ────────────────────────────────────────────────────────────

register_handler("curve", "create", _handle_curve_create)
register_handler("curve", "add-point", _handle_curve_add_point)
register_handler("curve", "edit-point", _handle_curve_edit_point)
register_handler("curve", "set-properties", _handle_curve_set_properties)
register_handler("curve", "to-mesh", _handle_curve_to_mesh)
register_handler("curve", "from-points", _handle_curve_from_points)
register_handler("curve", "set-bevel-object", _handle_curve_set_bevel_object)
register_handler("curve", "set-taper-object", _handle_curve_set_taper_object)

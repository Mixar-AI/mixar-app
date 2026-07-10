"""
Mesh handlers for Blender MCP Bridge.
Provides mesh operations: create_primitive, get_data, set_data.
"""

import math
import bpy
from ..utils.response import ok_response, error_response, not_found
from ..utils.compat import get_auto_smooth_method, is_blender_4  # noqa: F401
from ..utils.context_helpers import (
    ensure_context_for_object,
    temp_override,
    safe_operator_call,
)
from . import register_handler


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

def _handle_create_primitive(params):
    """
    Create a mesh primitive object in the active scene.

    Route: POST /api/mesh/create-primitive

    Params:
        type (str): CUBE | UV_SPHERE | ICO_SPHERE | CYLINDER | CONE | TORUS | PLANE | GRID | MONKEY
        name (str, optional): Name for the created object.
        location ([x,y,z], optional)
        size (float, optional): Overall size for CUBE, PLANE, GRID, MONKEY.
        radius (float, optional): Radius for sphere/cylinder/cone/torus.
        segments (int, optional): Longitude segments (UV_SPHERE, CYLINDER, CONE, TORUS major).
        rings (int, optional): Latitude rings (UV_SPHERE) / minor segments (TORUS).
        vertices (int, optional): Grid x/y resolution; alias for segments on some types.
        depth (float, optional): Height/depth for CYLINDER and CONE.
        subdivisions (int, optional): Subdivision count for ICO_SPHERE.
    """
    try:
        prim_type = params.get("type")
        if not prim_type:
            return error_response("Parameter 'type' is required.")

        name = params.get("name")
        location = params.get("location", [0.0, 0.0, 0.0])
        size = params.get("size")
        radius = params.get("radius")
        segments = params.get("segments")
        rings = params.get("rings")
        vertices = params.get("vertices")
        depth = params.get("depth")
        subdivisions = params.get("subdivisions")

        loc = tuple(location) if location else (0.0, 0.0, 0.0)

        # Build kwargs for each operator; only pass params that were explicitly provided
        def _k(**kw):
            """Strip None values so we fall back to Blender defaults."""
            return {k: v for k, v in kw.items() if v is not None}

        prim_type_upper = prim_type.upper()

        with temp_override("VIEW_3D"):
            if prim_type_upper == "CUBE":
                kw = _k(size=size, location=loc)
                success, res = safe_operator_call(bpy.ops.mesh.primitive_cube_add, **kw)

            elif prim_type_upper == "UV_SPHERE":
                kw = _k(
                    segments=segments,
                    ring_count=rings,
                    radius=radius,
                    location=loc,
                )
                success, res = safe_operator_call(bpy.ops.mesh.primitive_uv_sphere_add, **kw)

            elif prim_type_upper == "ICO_SPHERE":
                kw = _k(subdivisions=subdivisions, radius=radius, location=loc)
                success, res = safe_operator_call(bpy.ops.mesh.primitive_ico_sphere_add, **kw)

            elif prim_type_upper == "CYLINDER":
                kw = _k(
                    vertices=vertices or segments,
                    radius=radius,
                    depth=depth,
                    location=loc,
                )
                success, res = safe_operator_call(bpy.ops.mesh.primitive_cylinder_add, **kw)

            elif prim_type_upper == "CONE":
                kw = _k(
                    vertices=vertices or segments,
                    radius1=radius,
                    depth=depth,
                    location=loc,
                )
                success, res = safe_operator_call(bpy.ops.mesh.primitive_cone_add, **kw)

            elif prim_type_upper == "TORUS":
                kw = _k(
                    major_segments=segments,
                    minor_segments=rings,
                    major_radius=radius,
                    location=loc,
                )
                success, res = safe_operator_call(bpy.ops.mesh.primitive_torus_add, **kw)

            elif prim_type_upper == "PLANE":
                kw = _k(size=size, location=loc)
                success, res = safe_operator_call(bpy.ops.mesh.primitive_plane_add, **kw)

            elif prim_type_upper == "GRID":
                kw = _k(
                    x_subdivisions=vertices or segments,
                    y_subdivisions=vertices or segments,
                    size=size,
                    location=loc,
                )
                success, res = safe_operator_call(bpy.ops.mesh.primitive_grid_add, **kw)

            elif prim_type_upper == "MONKEY":
                kw = _k(size=size, location=loc)
                success, res = safe_operator_call(bpy.ops.mesh.primitive_monkey_add, **kw)

            else:
                return error_response(
                    f"Unknown primitive type '{prim_type}'. "
                    "Valid types: CUBE, UV_SPHERE, ICO_SPHERE, CYLINDER, CONE, TORUS, PLANE, GRID, MONKEY."
                )

        if not success:
            return error_response(f"Failed to create primitive '{prim_type}': {res}")

        # Blender activates the newly created object automatically
        obj = bpy.context.active_object
        if obj is None:
            return error_response("Primitive was created but no active object found afterwards.")

        # Rename if requested
        if name:
            obj.name = name
            if obj.data:
                obj.data.name = name

        mesh = obj.data
        return ok_response({
            "name": obj.name,
            "object_name": obj.name,
            "type": prim_type_upper,
            "location": list(obj.location),
            "vertex_count": len(mesh.vertices) if mesh else 0,
            "face_count": len(mesh.polygons) if mesh else 0,
        })
    except Exception as e:
        return error_response(f"Failed to create primitive: {e}")


def _handle_get_data(params):
    """
    Get mesh data for a mesh object.

    Route: POST /api/mesh/get-data

    Params:
        name (str)

    Returns:
        {object, vertices, edges, faces, bounding_box, has_custom_normals, uv_layers, vertex_groups}
    """
    try:
        object_name = params.get("name")
        if not object_name:
            return error_response("Parameter 'name' is required.")

        obj, err = _get_mesh_object(object_name)
        if err:
            return err

        mesh = obj.data

        # Bounding box (local space corners, 8 points)
        if obj.bound_box:
            xs = [v[0] for v in obj.bound_box]
            ys = [v[1] for v in obj.bound_box]
            zs = [v[2] for v in obj.bound_box]
            bounding_box = {
                "min": [min(xs), min(ys), min(zs)],
                "max": [max(xs), max(ys), max(zs)],
            }
        else:
            bounding_box = None

        return ok_response({
            "name": obj.name,
            "object_name": obj.name,
            "vertex_count": len(mesh.vertices),
            "edge_count": len(mesh.edges),
            "face_count": len(mesh.polygons),
            "bounding_box": bounding_box,
            "has_custom_normals": mesh.has_custom_normals,
            "uv_layers": [uv.name for uv in mesh.uv_layers],
            "vertex_groups": [vg.name for vg in obj.vertex_groups],
        })
    except Exception as e:
        return error_response(f"Failed to get mesh data: {e}")


def _handle_set_data(params):
    """
    Set shading/smoothing properties on a mesh object.

    Route: POST /api/mesh/set-data

    Params:
        name (str)
        shade_smooth (bool, optional): True → smooth shading, False → flat.
        auto_smooth_angle (float, optional): Threshold in degrees.
            Blender 3.x: sets mesh.use_auto_smooth + mesh.auto_smooth_angle
            Blender 4.x: adds/configures the Auto Smooth modifier (geometry nodes)
    """
    try:
        object_name = params.get("name")
        shade_smooth = params.get("shade_smooth")
        auto_smooth_angle = params.get("auto_smooth_angle")

        if not object_name:
            return error_response("Parameter 'name' is required.")

        obj, err = _get_mesh_object(object_name)
        if err:
            return err

        result = {"object": obj.name, "object_name": obj.name}

        # ── Shade smooth / flat ──────────────────────────────────────────────
        if shade_smooth is not None:
            ensure_context_for_object(obj)
            if shade_smooth:
                with temp_override("VIEW_3D"):
                    ok, res = safe_operator_call(bpy.ops.object.shade_smooth)
                if not ok:
                    return error_response(f"shade_smooth operator failed: {res}")
            else:
                with temp_override("VIEW_3D"):
                    ok, res = safe_operator_call(bpy.ops.object.shade_flat)
                if not ok:
                    return error_response(f"shade_flat operator failed: {res}")
            result["shade_smooth"] = shade_smooth

        # ── Auto smooth angle ────────────────────────────────────────────────
        if auto_smooth_angle is not None:
            try:
                angle_deg = float(auto_smooth_angle)
            except (TypeError, ValueError):
                return error_response(
                    f"Parameter 'auto_smooth_angle' must be a number, got: {auto_smooth_angle!r}"
                )

            angle_rad = math.radians(angle_deg)

            if bpy.app.version >= (4, 1, 0):
                # Blender 4.1+ / 5.0 — use the operator approach.
                # The operator applies smooth shading by angle in one step
                # (adds/updates the "Smooth by Angle" modifier internally).
                # Select and activate the target BEFORE mode_set so we switch
                # the correct object out of edit mode (MCPB-199).
                ensure_context_for_object(obj)
                if obj.mode != "OBJECT":
                    bpy.ops.object.mode_set(mode="OBJECT")

                with temp_override("VIEW_3D"):
                    ok, res = safe_operator_call(
                        bpy.ops.object.shade_smooth_by_angle,
                        angle=angle_rad,
                    )
                if not ok:
                    return error_response(
                        f"shade_smooth_by_angle failed on Blender "
                        f"{'.'.join(str(v) for v in bpy.app.version[:2])}+: {res}"
                    )

                smooth_method = "operator"
            else:
                # Blender 3.x — legacy mesh property
                mesh = obj.data
                mesh.use_auto_smooth = True
                mesh.auto_smooth_angle = angle_rad
                smooth_method = "mesh_property"

            result["auto_smooth_angle"] = angle_deg
            result["method"] = smooth_method

        return ok_response(result)
    except Exception as e:
        return error_response(f"Failed to set mesh data: {e}")


# ─── Register routes ────────────────────────────────────────────────────────────

register_handler("mesh", "create-primitive", _handle_create_primitive)
register_handler("mesh", "get-data", _handle_get_data)
register_handler("mesh", "set-data", _handle_set_data)

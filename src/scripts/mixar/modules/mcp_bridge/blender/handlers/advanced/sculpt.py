"""
Advanced sculpt handlers for Blender MCP Bridge.
Provides: sculpt/enter, sculpt/exit, sculpt/set-brush, sculpt/configure-brush,
          sculpt/stroke, sculpt/symmetry, sculpt/dyntopo-enable, sculpt/dyntopo-disable,
          sculpt/voxel-remesh, sculpt/mask-fill, sculpt/face-sets-init,
          sculpt/multires-add, sculpt/multires-set-level, sculpt/remesh-quadriflow,
          sculpt/detail-flood-fill
"""

import bpy
from ...utils.response import ok_response, error_response, not_found
from ...utils.context_helpers import ensure_context_for_object, temp_override, safe_operator_call
from .. import register_handler


# ─── Helpers ────────────────────────────────────────────────────────────────────

def _get_mesh_object(name):
    """Return (obj, None) or (None, error_response) for a MESH object."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, not_found(name, "Mesh object")
    if obj.type != "MESH":
        return None, error_response(
            f"Object '{name}' is of type '{obj.type}', not 'MESH'."
        )
    return obj, None


def _exit_sculpt_mode():
    """Switch back to Object Mode from any mode."""
    try:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass


def _is_dyntopo_active():
    """Return True if dynamic topology is currently enabled."""
    obj = bpy.context.object
    if obj is None or obj.type != "MESH":
        return False
    return getattr(obj.data, "use_dynamic_topology_sculpting", False)


# ─── Handlers ───────────────────────────────────────────────────────────────────

def _handle_sculpt_enter(params):
    """
    Select a mesh object and enter Sculpt Mode.
    Route: POST /api/sculpt/enter
    """
    object_name = params.get("object_name")
    if not object_name:
        return error_response("Parameter 'object_name' is required.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    try:
        ensure_context_for_object(obj)
        # Exit any current mode first
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.mode_set(mode="SCULPT")
        return ok_response({
            "object_name": obj.name,
            "mode": "SCULPT",
        })
    except Exception as e:
        try:
            _exit_sculpt_mode()
        except Exception:
            pass
        return error_response(f"Failed to enter sculpt mode on '{object_name}': {e}")


def _handle_sculpt_exit(params):
    """
    Exit Sculpt Mode back to Object Mode.
    Route: POST /api/sculpt/exit
    """
    try:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        return ok_response({"mode": "OBJECT"})
    except Exception as e:
        return error_response(f"Failed to exit sculpt mode: {e}")


def _handle_sculpt_set_brush(params):
    """
    Set the active sculpt brush by type identifier.
    Route: POST /api/sculpt/set-brush
    """
    brush_type = params.get("brush_type", "").upper()
    if not brush_type:
        return error_response("Parameter 'brush_type' is required.")

    valid_types = {
        "DRAW", "CLAY_STRIPS", "GRAB", "SNAKE_HOOK", "SMOOTH", "CREASE",
        "INFLATE", "BLOB", "FLATTEN", "FILL", "SCRAPE", "PINCH", "LAYER",
        "NUDGE", "ROTATE", "THUMB", "ELASTIC_DEFORM", "CLOTH_BRUSH",
        "MASK", "DRAW_FACE_SETS",
    }
    if brush_type not in valid_types:
        return error_response(
            f"Unknown brush_type '{brush_type}'. "
            f"Valid: {', '.join(sorted(valid_types))}."
        )

    if bpy.context.mode != "SCULPT":
        return error_response("Must be in Sculpt Mode to set the sculpt brush.")

    try:
        # Attempt to activate via the tool system (Blender 4.x preferred)
        tool_id = f"builtin_brush.{brush_type}"
        with temp_override("VIEW_3D"):
            ok, res = safe_operator_call(bpy.ops.wm.tool_set_by_id, name=tool_id)

        if not ok:
            # Fallback: use paint.brush_select operator
            with temp_override("VIEW_3D"):
                ok, res = safe_operator_call(
                    bpy.ops.paint.brush_select,
                    sculpt_tool=brush_type,
                    toggle=False,
                )
            if not ok:
                return error_response(
                    f"Failed to set brush '{brush_type}': {res}"
                )

        # Confirm active brush name
        sculpt = bpy.context.tool_settings.sculpt
        active_brush_name = sculpt.brush.name if sculpt and sculpt.brush else brush_type

        return ok_response({
            "brush_type": brush_type,
            "active_brush": active_brush_name,
        })
    except Exception as e:
        return error_response(f"Failed to set sculpt brush '{brush_type}': {e}")


def _handle_sculpt_configure_brush(params):
    """
    Configure properties of the active sculpt brush.
    Route: POST /api/sculpt/configure-brush
    """
    if bpy.context.mode != "SCULPT":
        return error_response("Must be in Sculpt Mode to configure the sculpt brush.")

    sculpt = bpy.context.tool_settings.sculpt
    if sculpt is None or sculpt.brush is None:
        return error_response("No active sculpt brush found.")

    brush = sculpt.brush
    applied = {}

    try:
        radius = params.get("radius")
        strength = params.get("strength")
        auto_smooth = params.get("auto_smooth")
        direction = params.get("direction", "").upper() if params.get("direction") else None

        if radius is not None:
            brush.size = int(radius)
            applied["radius"] = brush.size

        if strength is not None:
            brush.strength = float(strength)
            applied["strength"] = brush.strength

        if auto_smooth is not None:
            brush.auto_smooth_factor = float(auto_smooth)
            applied["auto_smooth"] = brush.auto_smooth_factor

        if direction is not None:
            valid_directions = ("ADD", "SUBTRACT")
            if direction not in valid_directions:
                return error_response(
                    f"Unknown direction '{direction}'. Valid: ADD, SUBTRACT."
                )
            brush.direction = direction
            applied["direction"] = brush.direction

        return ok_response({
            "brush_name": brush.name,
            "configured": applied,
            "current": {
                "radius": brush.size,
                "strength": brush.strength,
                "auto_smooth": brush.auto_smooth_factor,
                "direction": brush.direction,
            },
        })
    except Exception as e:
        return error_response(f"Failed to configure sculpt brush: {e}")


def _handle_sculpt_stroke(params):
    """
    Execute a sculpt brush stroke through a list of 3D world-space points.
    Route: POST /api/sculpt/stroke
    """
    points = params.get("points")
    pressure_list = params.get("pressure")

    if not points or not isinstance(points, list):
        return error_response("Parameter 'points' must be a non-empty list of [x, y, z] arrays.")

    if bpy.context.mode != "SCULPT":
        return error_response("Must be in Sculpt Mode to execute a sculpt stroke.")

    sculpt = bpy.context.tool_settings.sculpt
    if sculpt is None or sculpt.brush is None:
        return error_response("No active sculpt brush found.")

    brush = sculpt.brush
    brush_name = brush.name

    try:
        stroke = []
        for i, pt in enumerate(points):
            if len(pt) < 3:
                return error_response(
                    f"Point at index {i} must have 3 coordinates [x, y, z]."
                )
            pressure = 1.0
            if pressure_list and i < len(pressure_list):
                pressure = float(pressure_list[i])

            stroke.append({
                "name": "",
                "mouse": (float(pt[0]), float(pt[1])),
                "mouse_event": (float(pt[0]), float(pt[1])),
                "pen_flip": False,
                "is_start": (i == 0),
                "location": (float(pt[0]), float(pt[1]), float(pt[2])),
                "pressure": pressure,
                "size": float(brush.size),
                "x_tilt": 0.0,
                "y_tilt": 0.0,
            })

        with temp_override("VIEW_3D"):
            ok, res = safe_operator_call(
                bpy.ops.sculpt.brush_stroke,
                stroke=stroke,
                mode="NORMAL",
            )

        if not ok:
            return error_response(f"Sculpt stroke failed: {res}")

        return ok_response({
            "points_count": len(points),
            "brush": brush_name,
        })
    except Exception as e:
        return error_response(f"Failed to execute sculpt stroke: {e}")


def _handle_sculpt_symmetry(params):
    """
    Configure sculpt symmetry mirroring axes.
    Route: POST /api/sculpt/symmetry
    """
    if bpy.context.mode != "SCULPT":
        return error_response("Must be in Sculpt Mode to configure symmetry.")

    obj = bpy.context.object
    if obj is None or obj.type != "MESH":
        return error_response("No active mesh object found in sculpt mode.")

    try:
        use_symmetry = params.get("use_symmetry")
        x = params.get("x")
        y = params.get("y")
        z = params.get("z")

        # When use_symmetry is explicitly False, disable all axes
        if use_symmetry is False:
            obj.use_mesh_symmetry_x = False
            obj.use_mesh_symmetry_y = False
            obj.use_mesh_symmetry_z = False
        else:
            # Apply individual axis toggles if provided
            if x is not None:
                obj.use_mesh_symmetry_x = bool(x)
            if y is not None:
                obj.use_mesh_symmetry_y = bool(y)
            if z is not None:
                obj.use_mesh_symmetry_z = bool(z)

        return ok_response({
            "object_name": obj.name,
            "symmetry_x": obj.use_mesh_symmetry_x,
            "symmetry_y": obj.use_mesh_symmetry_y,
            "symmetry_z": obj.use_mesh_symmetry_z,
        })
    except Exception as e:
        return error_response(f"Failed to configure sculpt symmetry: {e}")


def _handle_sculpt_dyntopo_enable(params):
    """
    Enable Dynamic Topology on the active sculpt object.
    Route: POST /api/sculpt/dyntopo-enable
    """
    if bpy.context.mode != "SCULPT":
        return error_response("Must be in Sculpt Mode to enable Dyntopo.")

    obj = bpy.context.object
    if obj is None or obj.type != "MESH":
        return error_response("No active mesh object found in sculpt mode.")

    # Shape keys are incompatible with dyntopo
    if obj.data.shape_keys and len(obj.data.shape_keys.key_blocks) > 0:
        return error_response(
            f"Object '{obj.name}' has shape keys. "
            "Dynamic topology is not supported on meshes with shape keys."
        )

    detail_size = params.get("detail_size")
    detail_method = params.get("detail_method", "").upper() if params.get("detail_method") else None

    valid_methods = ("CONSTANT", "RELATIVE", "BRUSH")
    if detail_method and detail_method not in valid_methods:
        return error_response(
            f"Unknown detail_method '{detail_method}'. "
            f"Valid: {', '.join(valid_methods)}."
        )

    try:
        sculpt_settings = bpy.context.scene.tool_settings.sculpt

        # Toggle dyntopo on only if not already active
        if not _is_dyntopo_active():
            with temp_override("VIEW_3D"):
                ok, res = safe_operator_call(bpy.ops.sculpt.dynamic_topology_toggle)
            if not ok:
                return error_response(f"Failed to enable dynamic topology: {res}")

        if detail_size is not None:
            sculpt_settings.constant_detail_resolution = float(detail_size)

        if detail_method is not None:
            sculpt_settings.detail_type_method = detail_method

        return ok_response({
            "enabled": True,
            "detail_size": sculpt_settings.constant_detail_resolution,
            "detail_method": sculpt_settings.detail_type_method,
        })
    except Exception as e:
        return error_response(f"Failed to enable dynamic topology: {e}")


def _handle_sculpt_dyntopo_disable(params):
    """
    Disable Dynamic Topology on the active sculpt object.
    Route: POST /api/sculpt/dyntopo-disable
    """
    if bpy.context.mode != "SCULPT":
        return error_response("Must be in Sculpt Mode to disable Dyntopo.")

    try:
        if not _is_dyntopo_active():
            return ok_response({"disabled": True, "was_active": False})

        with temp_override("VIEW_3D"):
            ok, res = safe_operator_call(bpy.ops.sculpt.dynamic_topology_toggle)
        if not ok:
            return error_response(f"Failed to disable dynamic topology: {res}")

        return ok_response({"disabled": True, "was_active": True})
    except Exception as e:
        return error_response(f"Failed to disable dynamic topology: {e}")


def _handle_sculpt_voxel_remesh(params):
    """
    Perform a voxel-based remesh on the specified mesh object.
    Route: POST /api/sculpt/voxel-remesh
    """
    object_name = params.get("object_name")
    voxel_size = params.get("voxel_size")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if voxel_size is None:
        return error_response("Parameter 'voxel_size' is required.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    prev_mode = bpy.context.mode

    try:
        # Must be in OBJECT mode for voxel remesh
        ensure_context_for_object(obj)
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        obj.data.remesh_voxel_size = float(voxel_size)

        with temp_override("VIEW_3D"):
            ok, res = safe_operator_call(bpy.ops.object.voxel_remesh)
        if not ok:
            return error_response(f"Voxel remesh failed: {res}")

        vertex_count = len(obj.data.vertices)

        return ok_response({
            "object_name": obj.name,
            "voxel_size": float(voxel_size),
            "vertex_count": vertex_count,
        })
    except Exception as e:
        return error_response(f"Voxel remesh on '{object_name}' failed: {e}")
    finally:
        try:
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass


def _handle_sculpt_mask_fill(params):
    """
    Flood-fill the sculpt mask.
    Route: POST /api/sculpt/mask-fill
    """
    action = params.get("action", "").upper()
    if not action:
        return error_response("Parameter 'action' is required.")

    valid_actions = ("FILL", "CLEAR", "INVERT", "SMOOTH")
    if action not in valid_actions:
        return error_response(
            f"Unknown action '{action}'. Valid: {', '.join(valid_actions)}."
        )

    if bpy.context.mode != "SCULPT":
        return error_response("Must be in Sculpt Mode to operate on the sculpt mask.")

    try:
        with temp_override("VIEW_3D"):
            if action == "FILL":
                ok, res = safe_operator_call(
                    bpy.ops.paint.mask_flood_fill, mode="VALUE", value=1.0
                )
            elif action == "CLEAR":
                ok, res = safe_operator_call(
                    bpy.ops.paint.mask_flood_fill, mode="VALUE", value=0.0
                )
            elif action == "INVERT":
                ok, res = safe_operator_call(
                    bpy.ops.paint.mask_flood_fill, mode="INVERT"
                )
            elif action == "SMOOTH":
                ok, res = safe_operator_call(
                    bpy.ops.sculpt.mask_filter, filter_type="SMOOTH"
                )

        if not ok:
            return error_response(f"Mask action '{action}' failed: {res}")

        return ok_response({"action": action})
    except Exception as e:
        return error_response(f"Mask fill action '{action}' failed: {e}")


def _handle_sculpt_face_sets_init(params):
    """
    Initialize face sets from a geometry feature.
    Route: POST /api/sculpt/face-sets-init
    """
    mode = params.get("mode", "").upper()
    if not mode:
        return error_response("Parameter 'mode' is required.")

    # Map friendly names to Blender operator enum values
    mode_map = {
        "NORMALS": "NORMALS",
        "UV_SEAMS": "UV",
        "SHARP_EDGES": "SHARP_EDGES",
        "MATERIALS": "MATERIALS",
    }
    if mode not in mode_map:
        return error_response(
            f"Unknown mode '{mode}'. Valid: {', '.join(mode_map.keys())}."
        )

    if bpy.context.mode != "SCULPT":
        return error_response("Must be in Sculpt Mode to initialize face sets.")

    try:
        blender_mode = mode_map[mode]
        with temp_override("VIEW_3D"):
            ok, res = safe_operator_call(
                bpy.ops.sculpt.face_sets_init, mode=blender_mode
            )
        if not ok:
            return error_response(f"face_sets_init (mode={blender_mode}) failed: {res}")

        return ok_response({"mode": mode, "blender_mode": blender_mode})
    except Exception as e:
        return error_response(f"Face sets init (mode={mode}) failed: {e}")


def _handle_sculpt_multires_add(params):
    """
    Add a Multiresolution modifier and subdivide by the requested number of levels.
    Route: POST /api/sculpt/multires-add
    """
    object_name = params.get("object_name")
    subdivisions = int(params.get("subdivisions", 1))

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if subdivisions < 1:
        return error_response("Parameter 'subdivisions' must be at least 1.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    try:
        ensure_context_for_object(obj)
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        # Add the Multiresolution modifier
        with temp_override("VIEW_3D"):
            ok, res = safe_operator_call(
                bpy.ops.object.modifier_add, type="MULTIRES"
            )
        if not ok:
            return error_response(f"Failed to add Multiresolution modifier: {res}")

        # Find the newly added modifier (named "Multires" by default)
        multires_mod = None
        for mod in obj.modifiers:
            if mod.type == "MULTIRES":
                multires_mod = mod
                break
        if multires_mod is None:
            return error_response("Multiresolution modifier was not found after adding.")

        # Subdivide the requested number of times
        for _ in range(subdivisions):
            with temp_override("VIEW_3D"):
                ok, res = safe_operator_call(
                    bpy.ops.object.multires_subdivide,
                    modifier=multires_mod.name,
                    mode="CATMULL_CLARK",
                )
            if not ok:
                return error_response(f"multires_subdivide failed: {res}")

        vertex_count = len(obj.data.vertices)
        sculpt_level = multires_mod.sculpt_levels

        return ok_response({
            "object_name": obj.name,
            "modifier_name": multires_mod.name,
            "subdivisions_added": subdivisions,
            "sculpt_levels": sculpt_level,
            "vertex_count": vertex_count,
        })
    except Exception as e:
        return error_response(f"Adding Multiresolution to '{object_name}' failed: {e}")
    finally:
        try:
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass


def _handle_sculpt_multires_set_level(params):
    """
    Set the sculpt level on an existing Multiresolution modifier.
    Route: POST /api/sculpt/multires-set-level
    """
    object_name = params.get("object_name")
    level = params.get("level")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if level is None:
        return error_response("Parameter 'level' is required.")
    level = int(level)

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    try:
        ensure_context_for_object(obj)

        multires_mod = None
        for mod in obj.modifiers:
            if mod.type == "MULTIRES":
                multires_mod = mod
                break

        if multires_mod is None:
            return error_response(
                f"Object '{object_name}' does not have a Multiresolution modifier."
            )

        max_level = multires_mod.total_levels
        if level < 0 or level > max_level:
            return error_response(
                f"Level {level} is out of range. "
                f"Object has {max_level} total subdivision level(s) (0–{max_level})."
            )

        multires_mod.sculpt_levels = level

        return ok_response({
            "object_name": obj.name,
            "modifier_name": multires_mod.name,
            "level": multires_mod.sculpt_levels,
            "total_levels": max_level,
        })
    except Exception as e:
        return error_response(
            f"Failed to set multires level on '{object_name}': {e}"
        )


def _handle_sculpt_remesh_quadriflow(params):
    """
    Perform QuadriFlow retopology on the specified mesh object.
    Route: POST /api/sculpt/remesh-quadriflow
    """
    object_name = params.get("object_name")
    target_faces = params.get("target_faces")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if target_faces is None:
        return error_response("Parameter 'target_faces' is required.")
    target_faces = int(target_faces)
    if target_faces < 4:
        return error_response("Parameter 'target_faces' must be at least 4.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    try:
        ensure_context_for_object(obj)
        # Must be in OBJECT mode
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        with temp_override("VIEW_3D"):
            ok, res = safe_operator_call(
                bpy.ops.object.quadriflow_remesh,
                target_faces=target_faces,
            )
        if not ok:
            return error_response(f"QuadriFlow remesh failed: {res}")

        actual_faces = len(obj.data.polygons)

        return ok_response({
            "object_name": obj.name,
            "target_faces": target_faces,
            "actual_faces": actual_faces,
        })
    except Exception as e:
        return error_response(f"QuadriFlow remesh on '{object_name}' failed: {e}")
    finally:
        try:
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass


def _handle_sculpt_detail_flood_fill(params):
    """
    Uniformize mesh tessellation based on the current Dyntopo detail size.
    Route: POST /api/sculpt/detail-flood-fill
    """
    if bpy.context.mode != "SCULPT":
        return error_response("Must be in Sculpt Mode to perform detail flood fill.")

    if not _is_dyntopo_active():
        return error_response(
            "Dynamic Topology must be active to perform detail flood fill."
        )

    try:
        with temp_override("VIEW_3D"):
            ok, res = safe_operator_call(bpy.ops.sculpt.detail_flood_fill)
        if not ok:
            return error_response(f"Detail flood fill failed: {res}")

        return ok_response({"success": True})
    except Exception as e:
        return error_response(f"Detail flood fill failed: {e}")


# ─── Register routes ─────────────────────────────────────────────────────────────

register_handler("sculpt", "enter",              _handle_sculpt_enter)
register_handler("sculpt", "exit",               _handle_sculpt_exit)
register_handler("sculpt", "set-brush",          _handle_sculpt_set_brush)
register_handler("sculpt", "configure-brush",    _handle_sculpt_configure_brush)
register_handler("sculpt", "stroke",             _handle_sculpt_stroke)
register_handler("sculpt", "symmetry",           _handle_sculpt_symmetry)
register_handler("sculpt", "dyntopo-enable",     _handle_sculpt_dyntopo_enable)
register_handler("sculpt", "dyntopo-disable",    _handle_sculpt_dyntopo_disable)
register_handler("sculpt", "voxel-remesh",       _handle_sculpt_voxel_remesh)
register_handler("sculpt", "mask-fill",          _handle_sculpt_mask_fill)
register_handler("sculpt", "face-sets-init",     _handle_sculpt_face_sets_init)
register_handler("sculpt", "multires-add",       _handle_sculpt_multires_add)
register_handler("sculpt", "multires-set-level", _handle_sculpt_multires_set_level)
register_handler("sculpt", "remesh-quadriflow",  _handle_sculpt_remesh_quadriflow)
register_handler("sculpt", "detail-flood-fill",  _handle_sculpt_detail_flood_fill)

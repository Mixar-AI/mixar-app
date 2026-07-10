"""
Advanced Grease Pencil handlers for Blender MCP Bridge.
Provides: gp/create, gp/add-layer, gp/draw-stroke, gp/set-material,
          gp/modifier-add, gp/to-curve, gp/to-mesh, gp/sculpt-stroke
"""

import bpy
from ...utils.response import ok_response, error_response, not_found
from ...utils.context_helpers import ensure_context_for_object, temp_override, safe_operator_call
from .. import register_handler


# ─── Helpers ───────────────────────────────────────────────────────────────────

# Grease Pencil modifier type mapping: friendly name → Blender internal name
_GP_MODIFIER_MAP = {
    "SMOOTH":    "GP_SMOOTH",
    "NOISE":     "GP_NOISE",
    "THICKNESS": "GP_THICK",
    "TINT":      "GP_TINT",
    "OFFSET":    "GP_OFFSET",
    "BUILD":     "GP_BUILD",
    "SIMPLIFY":  "GP_SIMPLIFY",
}

# GP sculpt brush type mapping: friendly name → Blender internal name
_GP_SCULPT_BRUSH_MAP = {
    "SMOOTH":    "SMOOTH",
    "THICKNESS": "THICKNESS",
    "STRENGTH":  "STRENGTH",
    "GRAB":      "GRAB",
    "PUSH":      "PUSH",
    "TWIST":     "TWIST",
    "PINCH":     "PINCH",
    "RANDOMIZE": "RANDOMIZE",
    "CLONE":     "CLONE",
}


def _get_gp_object(name):
    """Return (obj, None) or (None, error_response) for a GPENCIL object."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, not_found(name, "Grease Pencil object")
    if obj.type != "GPENCIL":
        return None, error_response(
            f"Object '{name}' is of type '{obj.type}', not 'GPENCIL'."
        )
    return obj, None


def _new_grease_pencil_data(name):
    """
    Create a new Grease Pencil data-block, handling Blender 3.x / 4.x API differences.
    Returns the grease pencil data-block.
    """
    # Blender 3.x uses bpy.data.grease_pencils
    if hasattr(bpy.data, "grease_pencils"):
        try:
            return bpy.data.grease_pencils.new(name)
        except Exception:
            pass
    # Blender 4.3+ may use grease_pencils_v3 for legacy GP objects
    if hasattr(bpy.data, "grease_pencils_v3"):
        try:
            return bpy.data.grease_pencils_v3.new(name)
        except Exception:
            pass
    raise RuntimeError(
        "Cannot create Grease Pencil data-block: "
        "bpy.data.grease_pencils not available in this Blender version."
    )


def _get_or_create_frame(layer, frame_number):
    """Return existing frame at frame_number or create a new one."""
    for frame in layer.frames:
        if frame.frame_number == frame_number:
            return frame
    return layer.frames.new(frame_number)


# ─── Handlers ──────────────────────────────────────────────────────────────────

def _handle_gp_create(params):
    """
    Create a new Grease Pencil object in the active collection.
    Route: POST /api/gp/create
    """
    name = params.get("name", "GPencil")
    location = params.get("location", [0.0, 0.0, 0.0])

    if not isinstance(location, (list, tuple)) or len(location) != 3:
        return error_response("Parameter 'location' must be a list of 3 numbers [x, y, z].")

    try:
        gp_data = _new_grease_pencil_data(name)
        obj = bpy.data.objects.new(name, gp_data)
        bpy.context.collection.objects.link(obj)

        obj.location = (float(location[0]), float(location[1]), float(location[2]))

        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        return ok_response({
            "object_name": obj.name,
            "gp_data_name": gp_data.name,
            "location": list(obj.location),
        })
    except Exception as e:
        return error_response(f"Failed to create Grease Pencil object: {e}")


def _handle_gp_add_layer(params):
    """
    Add a new layer to an existing Grease Pencil object.
    Route: POST /api/gp/add-layer
    """
    gp_name = params.get("gp_name")
    layer_name = params.get("layer_name")

    if not gp_name:
        return error_response("Parameter 'gp_name' is required.")
    if not layer_name:
        return error_response("Parameter 'layer_name' is required.")

    obj, err = _get_gp_object(gp_name)
    if err:
        return err

    try:
        gp_data = obj.data
        layer = gp_data.layers.new(layer_name)
        layer_index = list(gp_data.layers).index(layer)

        return ok_response({
            "object_name": obj.name,
            "layer_name": layer.info,
            "layer_index": layer_index,
        })
    except Exception as e:
        return error_response(f"Failed to add layer '{layer_name}' to '{gp_name}': {e}")


def _handle_gp_draw_stroke(params):
    """
    Draw a stroke on the specified Grease Pencil layer.
    Route: POST /api/gp/draw-stroke
    """
    gp_name = params.get("gp_name")
    layer_name = params.get("layer_name")
    points = params.get("points")
    pressure_list = params.get("pressure")
    material_index = int(params.get("material_index", 0))

    if not gp_name:
        return error_response("Parameter 'gp_name' is required.")
    if not layer_name:
        return error_response("Parameter 'layer_name' is required.")
    if not points or not isinstance(points, list):
        return error_response("Parameter 'points' must be a non-empty list of [x, y, z] arrays.")

    # Validate each point
    for i, pt in enumerate(points):
        if not isinstance(pt, (list, tuple)) or len(pt) < 3:
            return error_response(
                f"Point at index {i} must have 3 coordinates [x, y, z]."
            )

    obj, err = _get_gp_object(gp_name)
    if err:
        return err

    try:
        gp_data = obj.data

        # Find the layer
        layer = gp_data.layers.get(layer_name)
        if layer is None:
            return error_response(
                f"Layer '{layer_name}' not found in GP object '{gp_name}'. "
                f"Available layers: {[l.info for l in gp_data.layers]}."
            )

        frame_number = bpy.context.scene.frame_current
        frame = _get_or_create_frame(layer, frame_number)

        stroke = frame.strokes.new()
        stroke.display_mode = "3DSPACE"
        stroke.material_index = material_index

        point_count = len(points)
        stroke.points.add(point_count)

        for i, pt in enumerate(points):
            p = stroke.points[i]
            p.co = (float(pt[0]), float(pt[1]), float(pt[2]))
            pressure_val = 1.0
            if pressure_list and i < len(pressure_list):
                pressure_val = float(pressure_list[i])
            p.pressure = pressure_val
            p.strength = pressure_val

        stroke_index = list(frame.strokes).index(stroke)

        return ok_response({
            "object_name": obj.name,
            "layer_name": layer_name,
            "frame_number": frame_number,
            "stroke_index": stroke_index,
            "point_count": point_count,
            "material_index": material_index,
        })
    except Exception as e:
        return error_response(f"Failed to draw stroke on '{gp_name}/{layer_name}': {e}")


def _handle_gp_set_material(params):
    """
    Create or update a Grease Pencil material on the specified GP object.
    Route: POST /api/gp/set-material
    """
    gp_name = params.get("gp_name")
    index = params.get("index")

    if not gp_name:
        return error_response("Parameter 'gp_name' is required.")
    if index is None:
        return error_response("Parameter 'index' is required.")
    index = int(index)

    obj, err = _get_gp_object(gp_name)
    if err:
        return err

    try:
        color = params.get("color")
        fill_color = params.get("fill_color")
        stroke_width = params.get("stroke_width")

        # Ensure material slots exist up to the requested index
        while len(obj.material_slots) <= index:
            bpy.ops.object.material_slot_add()

        # Retrieve or create material at this slot
        slot = obj.material_slots[index]
        if slot.material is None:
            mat = bpy.data.materials.new(f"{gp_name}_GP_Mat_{index}")
            bpy.data.materials.create_gpencil_data(mat)
            slot.material = mat
        else:
            mat = slot.material
            # Ensure it has GP data
            if not mat.is_grease_pencil:
                bpy.data.materials.create_gpencil_data(mat)

        gp_mat = mat.grease_pencil

        if color is not None:
            if len(color) == 3:
                gp_mat.color = (float(color[0]), float(color[1]), float(color[2]), 1.0)
            elif len(color) == 4:
                gp_mat.color = (float(color[0]), float(color[1]), float(color[2]), float(color[3]))
            else:
                return error_response("'color' must be [r, g, b] or [r, g, b, a].")
            gp_mat.show_stroke = True

        if fill_color is not None:
            if len(fill_color) == 3:
                gp_mat.fill_color = (
                    float(fill_color[0]), float(fill_color[1]), float(fill_color[2]), 1.0
                )
            elif len(fill_color) == 4:
                gp_mat.fill_color = (
                    float(fill_color[0]), float(fill_color[1]),
                    float(fill_color[2]), float(fill_color[3])
                )
            else:
                return error_response("'fill_color' must be [r, g, b] or [r, g, b, a].")
            gp_mat.show_fill = True

        if stroke_width is not None:
            # stroke_width is stored as a thickness in pixels on the GP settings, not the material
            # We set it as linewidth on the material if available, otherwise skip gracefully
            if hasattr(gp_mat, "stroke_style"):
                pass  # line width is per-stroke in Blender GP; record as metadata
            # Some Blender versions expose thickness via pen_width; try best-effort
            if hasattr(gp_mat, "pixel_size"):
                gp_mat.pixel_size = float(stroke_width)

        return ok_response({
            "object_name": obj.name,
            "material_name": mat.name,
            "slot_index": index,
            "is_grease_pencil": mat.is_grease_pencil,
        })
    except Exception as e:
        return error_response(f"Failed to set GP material on '{gp_name}' at index {index}: {e}")


def _handle_gp_modifier_add(params):
    """
    Add a Grease Pencil modifier to the specified GP object.
    Route: POST /api/gp/modifier-add
    """
    gp_name = params.get("gp_name")
    mod_type = params.get("type", "").upper()

    if not gp_name:
        return error_response("Parameter 'gp_name' is required.")
    if not mod_type:
        return error_response("Parameter 'type' is required.")

    valid_types = list(_GP_MODIFIER_MAP.keys())
    if mod_type not in _GP_MODIFIER_MAP:
        return error_response(
            f"Unknown GP modifier type '{mod_type}'. "
            f"Valid: {', '.join(valid_types)}."
        )

    obj, err = _get_gp_object(gp_name)
    if err:
        return err

    try:
        blender_type = _GP_MODIFIER_MAP[mod_type]
        mod = obj.grease_pencil_modifiers.new(
            name=f"{mod_type.capitalize()}",
            type=blender_type,
        )
        return ok_response({
            "object_name": obj.name,
            "modifier_name": mod.name,
            "modifier_type": mod.type,
            "friendly_type": mod_type,
        })
    except Exception as e:
        return error_response(
            f"Failed to add GP modifier '{mod_type}' to '{gp_name}': {e}"
        )


def _handle_gp_to_curve(params):
    """
    Convert a Grease Pencil object to a Curve object.
    Route: POST /api/gp/to-curve
    """
    gp_name = params.get("gp_name")
    if not gp_name:
        return error_response("Parameter 'gp_name' is required.")

    obj, err = _get_gp_object(gp_name)
    if err:
        return err

    try:
        ensure_context_for_object(obj)
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        # Deselect all, then select only the target object
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        with temp_override("VIEW_3D"):
            ok, res = safe_operator_call(bpy.ops.object.convert, target="CURVE")
        if not ok:
            return error_response(f"Convert GP to Curve failed: {res}")

        # After conversion the active object is the new curve
        new_obj = bpy.context.view_layer.objects.active
        new_name = new_obj.name if new_obj else gp_name

        return ok_response({
            "original_name": gp_name,
            "result_name": new_name,
            "result_type": new_obj.type if new_obj else "CURVE",
        })
    except Exception as e:
        return error_response(f"Failed to convert GP '{gp_name}' to Curve: {e}")


def _handle_gp_to_mesh(params):
    """
    Convert a Grease Pencil object to a Mesh object.
    Route: POST /api/gp/to-mesh
    """
    gp_name = params.get("gp_name")
    if not gp_name:
        return error_response("Parameter 'gp_name' is required.")

    obj, err = _get_gp_object(gp_name)
    if err:
        return err

    try:
        ensure_context_for_object(obj)
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        with temp_override("VIEW_3D"):
            ok, res = safe_operator_call(bpy.ops.object.convert, target="MESH")
        if not ok:
            return error_response(f"Convert GP to Mesh failed: {res}")

        new_obj = bpy.context.view_layer.objects.active
        new_name = new_obj.name if new_obj else gp_name

        vertex_count = 0
        if new_obj and new_obj.type == "MESH":
            vertex_count = len(new_obj.data.vertices)

        return ok_response({
            "original_name": gp_name,
            "result_name": new_name,
            "result_type": new_obj.type if new_obj else "MESH",
            "vertex_count": vertex_count,
        })
    except Exception as e:
        return error_response(f"Failed to convert GP '{gp_name}' to Mesh: {e}")


def _handle_gp_sculpt_stroke(params):
    """
    Configure and apply GP sculpt brush settings on a Grease Pencil object.
    Route: POST /api/gp/sculpt-stroke
    """
    gp_name = params.get("gp_name")
    layer_name = params.get("layer_name")
    brush_type = params.get("brush_type", "").upper()
    brush_params = params.get("params") or {}

    if not gp_name:
        return error_response("Parameter 'gp_name' is required.")
    if not layer_name:
        return error_response("Parameter 'layer_name' is required.")
    if not brush_type:
        return error_response("Parameter 'brush_type' is required.")

    valid_types = list(_GP_SCULPT_BRUSH_MAP.keys())
    if brush_type not in _GP_SCULPT_BRUSH_MAP:
        return error_response(
            f"Unknown GP sculpt brush type '{brush_type}'. "
            f"Valid: {', '.join(valid_types)}."
        )

    obj, err = _get_gp_object(gp_name)
    if err:
        return err

    try:
        ensure_context_for_object(obj)
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        # Enter GP Sculpt mode
        bpy.ops.object.mode_set(mode="SCULPT_GPENCIL")

        # Set the active sculpt brush type
        blender_brush_type = _GP_SCULPT_BRUSH_MAP[brush_type]
        sculpt_settings = bpy.context.tool_settings.gpencil_sculpt_paint
        if sculpt_settings and hasattr(sculpt_settings, "brush"):
            brush = sculpt_settings.brush
            if brush is not None:
                if hasattr(brush, "gpencil_sculpt_tool"):
                    brush.gpencil_sculpt_tool = blender_brush_type
                # Apply optional brush params
                radius = brush_params.get("radius")
                strength = brush_params.get("strength")
                use_pressure = brush_params.get("use_pressure")

                if radius is not None and hasattr(brush, "size"):
                    brush.size = int(radius)
                if strength is not None and hasattr(brush, "strength"):
                    brush.strength = float(strength)
                if use_pressure is not None and hasattr(brush, "use_pressure_strength"):
                    brush.use_pressure_strength = bool(use_pressure)

        # Return to object mode
        bpy.ops.object.mode_set(mode="OBJECT")

        return ok_response({
            "object_name": obj.name,
            "layer_name": layer_name,
            "brush_type": brush_type,
            "params_applied": brush_params,
        })
    except Exception as e:
        return error_response(
            f"Failed to apply GP sculpt stroke on '{gp_name}': {e}"
        )
    finally:
        try:
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass


# ─── Register routes ────────────────────────────────────────────────────────────

register_handler("gp", "create",        _handle_gp_create)
register_handler("gp", "add-layer",     _handle_gp_add_layer)
register_handler("gp", "draw-stroke",   _handle_gp_draw_stroke)
register_handler("gp", "set-material",  _handle_gp_set_material)
register_handler("gp", "modifier-add",  _handle_gp_modifier_add)
register_handler("gp", "to-curve",      _handle_gp_to_curve)
register_handler("gp", "to-mesh",       _handle_gp_to_mesh)
register_handler("gp", "sculpt-stroke", _handle_gp_sculpt_stroke)

"""
Advanced Text object handlers for Blender MCP Bridge.
Provides: text/create, text/edit, text/set-font, text/to-mesh, text/to-curve
"""

import bpy
import os
from ...utils.response import ok_response, error_response, not_found
from ...utils.context_helpers import ensure_context_for_object, temp_override, safe_operator_call
from .. import register_handler


# ─── Helpers ───────────────────────────────────────────────────────────────────

# Valid horizontal alignment values for Blender font curve data
_VALID_ALIGN = {"LEFT", "CENTER", "RIGHT", "JUSTIFY", "FLUSH"}


def _get_text_object(name):
    """Return (obj, None) or (None, error_response) for a FONT object."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, not_found(name, "Text object")
    if obj.type != "FONT":
        return None, error_response(
            f"Object '{name}' is of type '{obj.type}', not 'FONT'."
        )
    return obj, None


def _load_font(font_path):
    """
    Load a font from disk, returning the bpy.types.VectorFont data-block.
    Raises ValueError if the file does not exist or fails to load.
    """
    if not os.path.isfile(font_path):
        raise ValueError(f"Font file not found: '{font_path}'")
    # Check if already loaded (avoids duplicate data-blocks)
    abs_path = os.path.abspath(font_path)
    for existing_font in bpy.data.fonts:
        if existing_font.filepath and os.path.abspath(existing_font.filepath) == abs_path:
            return existing_font
    font = bpy.data.fonts.load(font_path)
    return font


# ─── Handlers ──────────────────────────────────────────────────────────────────

def _handle_text_create(params):
    """
    Create a new Text (FONT) object in the active collection.
    Route: POST /api/text/create
    """
    text_body = params.get("text")
    if text_body is None:
        return error_response("Parameter 'text' is required.")

    name = params.get("name", "Text")
    location = params.get("location", [0.0, 0.0, 0.0])
    font_path = params.get("font")
    size = params.get("size")

    if not isinstance(location, (list, tuple)) or len(location) != 3:
        return error_response("Parameter 'location' must be a list of 3 numbers [x, y, z].")

    try:
        text_data = bpy.data.curves.new(name=name, type="FONT")
        text_data.body = str(text_body)

        if size is not None:
            text_data.size = float(size)

        if font_path:
            try:
                font = _load_font(font_path)
                text_data.font = font
            except ValueError as fe:
                return error_response(str(fe))

        obj = bpy.data.objects.new(name, text_data)
        bpy.context.collection.objects.link(obj)

        obj.location = (float(location[0]), float(location[1]), float(location[2]))

        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        return ok_response({
            "object_name": obj.name,
            "text_body": text_data.body,
            "size": text_data.size,
            "font": text_data.font.name if text_data.font else "Bfont",
            "location": list(obj.location),
        })
    except Exception as e:
        return error_response(f"Failed to create Text object: {e}")


def _handle_text_edit(params):
    """
    Edit properties of an existing Text object.
    Route: POST /api/text/edit
    """
    name = params.get("name")
    if not name:
        return error_response("Parameter 'name' is required.")

    obj, err = _get_text_object(name)
    if err:
        return err

    try:
        text_data = obj.data
        applied = {}

        text_body = params.get("text")
        font_path = params.get("font")
        size = params.get("size")
        extrude = params.get("extrude")
        bevel_depth = params.get("bevel_depth")
        align = params.get("align", "").upper() if params.get("align") else None

        if text_body is not None:
            text_data.body = str(text_body)
            applied["text"] = text_data.body

        if size is not None:
            text_data.size = float(size)
            applied["size"] = text_data.size

        if extrude is not None:
            text_data.extrude = float(extrude)
            applied["extrude"] = text_data.extrude

        if bevel_depth is not None:
            text_data.bevel_depth = float(bevel_depth)
            applied["bevel_depth"] = text_data.bevel_depth

        if align is not None:
            if align not in _VALID_ALIGN:
                return error_response(
                    f"Unknown align value '{align}'. "
                    f"Valid: {', '.join(sorted(_VALID_ALIGN))}."
                )
            text_data.align_x = align
            applied["align"] = text_data.align_x

        if font_path is not None:
            try:
                font = _load_font(font_path)
                text_data.font = font
                applied["font"] = font.name
            except ValueError as fe:
                return error_response(str(fe))

        return ok_response({
            "object_name": obj.name,
            "applied": applied,
            "current": {
                "text": text_data.body,
                "size": text_data.size,
                "extrude": text_data.extrude,
                "bevel_depth": text_data.bevel_depth,
                "align": text_data.align_x,
                "font": text_data.font.name if text_data.font else "Bfont",
            },
        })
    except Exception as e:
        return error_response(f"Failed to edit Text object '{name}': {e}")


def _handle_text_set_font(params):
    """
    Load a font file and assign it to the specified Text object.
    Route: POST /api/text/set-font
    """
    text_name = params.get("text_name")
    font_path = params.get("font_path")

    if not text_name:
        return error_response("Parameter 'text_name' is required.")
    if not font_path:
        return error_response("Parameter 'font_path' is required.")

    obj, err = _get_text_object(text_name)
    if err:
        return err

    try:
        font = _load_font(font_path)
        obj.data.font = font

        return ok_response({
            "object_name": obj.name,
            "font_name": font.name,
            "font_filepath": font.filepath,
        })
    except ValueError as ve:
        return error_response(str(ve))
    except Exception as e:
        return error_response(f"Failed to set font on '{text_name}': {e}")


def _handle_text_to_mesh(params):
    """
    Convert a Text object to a Mesh object.
    Route: POST /api/text/to-mesh
    """
    text_name = params.get("text_name")
    if not text_name:
        return error_response("Parameter 'text_name' is required.")

    obj, err = _get_text_object(text_name)
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
            return error_response(f"Convert Text to Mesh failed: {res}")

        new_obj = bpy.context.view_layer.objects.active
        new_name = new_obj.name if new_obj else text_name

        vertex_count = 0
        if new_obj and new_obj.type == "MESH":
            vertex_count = len(new_obj.data.vertices)

        return ok_response({
            "original_name": text_name,
            "result_name": new_name,
            "result_type": new_obj.type if new_obj else "MESH",
            "vertex_count": vertex_count,
        })
    except Exception as e:
        return error_response(f"Failed to convert Text '{text_name}' to Mesh: {e}")
    finally:
        try:
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass


def _handle_text_to_curve(params):
    """
    Convert a Text object to a Curve object.
    Route: POST /api/text/to-curve
    """
    text_name = params.get("text_name")
    if not text_name:
        return error_response("Parameter 'text_name' is required.")

    obj, err = _get_text_object(text_name)
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
            ok, res = safe_operator_call(bpy.ops.object.convert, target="CURVE")
        if not ok:
            return error_response(f"Convert Text to Curve failed: {res}")

        new_obj = bpy.context.view_layer.objects.active
        new_name = new_obj.name if new_obj else text_name

        spline_count = 0
        if new_obj and new_obj.type == "CURVE":
            spline_count = len(new_obj.data.splines)

        return ok_response({
            "original_name": text_name,
            "result_name": new_name,
            "result_type": new_obj.type if new_obj else "CURVE",
            "spline_count": spline_count,
        })
    except Exception as e:
        return error_response(f"Failed to convert Text '{text_name}' to Curve: {e}")
    finally:
        try:
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass


# ─── Register routes ────────────────────────────────────────────────────────────

register_handler("text", "create",   _handle_text_create)
register_handler("text", "edit",     _handle_text_edit)
register_handler("text", "set-font", _handle_text_set_font)
register_handler("text", "to-mesh",  _handle_text_to_mesh)
register_handler("text", "to-curve", _handle_text_to_curve)

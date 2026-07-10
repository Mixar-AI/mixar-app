"""
File extended handlers for Blender MCP Bridge.
Provides: file/append, file/link
"""

import os
import bpy
from ...utils.response import ok_response, error_response, validate_filepath
from ...utils.context_helpers import safe_operator_call
from .. import register_handler


# ─── Allowed data types for append/link ──────────────────────────────────────

_VALID_DATA_TYPES = frozenset({
    "Action", "Armature", "Brush", "Camera", "Collection",
    "Curve", "FreestyleLineStyle", "GreasePencil", "Image",
    "Key", "Lattice", "Light", "Library", "Mask", "Material",
    "Mesh", "MetaBall", "MovieClip", "NodeTree", "Object",
    "PaintCurve", "Palette", "ParticleSettings", "Scene",
    "Screen", "Sound", "Speaker", "Text", "Texture",
    "VectorFont", "Volume", "WindowManager", "WorkSpace", "World",
})


def _sanitize_blend_name(value, param_name):
    """
    Validate that a data_type or name parameter does not contain
    path separators or traversal sequences.
    Returns (sanitized_value, error_response_or_None).
    """
    if os.sep in value or "/" in value or "\\" in value or ".." in value:
        return None, error_response(
            f"Parameter '{param_name}' contains invalid path characters: {value!r}"
        )
    return value, None


# ─── Handlers ───────────────────────────────────────────────────────────────────

def _handle_file_append(params):
    """
    Append a data-block from an external .blend file.
    Route: POST /api/file/append
    """
    filepath  = params.get("filepath")
    data_type = params.get("data_type")
    name      = params.get("name")

    if not filepath:
        return error_response("Parameter 'filepath' is required.")
    if not data_type:
        return error_response("Parameter 'data_type' is required.")
    if not name:
        return error_response("Parameter 'name' is required.")

    # Validate filepath
    filepath, path_err = validate_filepath(filepath, must_exist=True)
    if path_err:
        return error_response(path_err)

    # Validate data_type against known Blender data-block categories
    if data_type not in _VALID_DATA_TYPES:
        return error_response(
            f"Invalid data_type '{data_type}'. "
            f"Must be one of: {', '.join(sorted(_VALID_DATA_TYPES))}."
        )

    # Reject path traversal in name
    name, err = _sanitize_blend_name(name, "name")
    if err:
        return err

    try:
        directory = filepath + "/" + data_type + "/"
        full_path = directory + name

        # bpy.ops.wm.append is required here: there is no bpy.data equivalent
        # that can import a data-block from an external .blend file into the
        # current scene. bpy.data.libraries.load() can read data but does not
        # perform the full append (scene integration, ID remapping, etc.) that
        # bpy.ops.wm.append provides. This is a justified exception to the
        # bpy.data > bpy.ops convention.
        success, result = safe_operator_call(
            bpy.ops.wm.append,
            filepath=full_path,
            directory=directory,
            filename=name,
        )
        if not success:
            return error_response(f"Failed to append '{data_type}/{name}' from '{filepath}': {result}")

        return ok_response({
            "filepath":  filepath,
            "data_type": data_type,
            "name":      name,
        })
    except Exception as e:
        return error_response(f"Failed to append '{data_type}/{name}' from '{filepath}': {e}")


def _handle_file_link(params):
    """
    Link a data-block from an external .blend file.
    Route: POST /api/file/link
    """
    filepath  = params.get("filepath")
    data_type = params.get("data_type")
    name      = params.get("name")

    if not filepath:
        return error_response("Parameter 'filepath' is required.")
    if not data_type:
        return error_response("Parameter 'data_type' is required.")
    if not name:
        return error_response("Parameter 'name' is required.")

    # Validate filepath
    filepath, path_err = validate_filepath(filepath, must_exist=True)
    if path_err:
        return error_response(path_err)

    # Validate data_type against known Blender data-block categories
    if data_type not in _VALID_DATA_TYPES:
        return error_response(
            f"Invalid data_type '{data_type}'. "
            f"Must be one of: {', '.join(sorted(_VALID_DATA_TYPES))}."
        )

    # Reject path traversal in name
    name, err = _sanitize_blend_name(name, "name")
    if err:
        return err

    try:
        directory = filepath + "/" + data_type + "/"
        full_path = directory + name

        # bpy.ops.wm.link is required here: there is no bpy.data equivalent
        # that can link a data-block from an external .blend file with proper
        # library reference tracking. bpy.data.libraries.load() can read data
        # but does not establish the library link (ID ownership, override
        # support, etc.) that bpy.ops.wm.link provides. This is a justified
        # exception to the bpy.data > bpy.ops convention.
        success, result = safe_operator_call(
            bpy.ops.wm.link,
            filepath=full_path,
            directory=directory,
            filename=name,
        )
        if not success:
            return error_response(f"Failed to link '{data_type}/{name}' from '{filepath}': {result}")

        return ok_response({
            "filepath":  filepath,
            "data_type": data_type,
            "name":      name,
        })
    except Exception as e:
        return error_response(f"Failed to link '{data_type}/{name}' from '{filepath}': {e}")


# ─── Register routes ─────────────────────────────────────────────────────────────

register_handler("file", "append", _handle_file_append)
register_handler("file", "link",   _handle_file_link)

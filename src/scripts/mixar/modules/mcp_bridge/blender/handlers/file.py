"""
File handlers for Blender MCP Bridge.
Provides file-related operations: info, save, open.
"""

import bpy
from ..utils.response import ok_response, error_response, validate_filepath
from ..utils.context_helpers import safe_operator_call
from . import register_handler


def _file_info(params):
    """
    Get information about the current Blender file.

    Route: POST /api/file/info

    Returns:
        filepath, is_saved, is_dirty, blender_version, active_scene
    """
    try:
        filepath = bpy.data.filepath
        return ok_response({
            "filepath": filepath if filepath else "",
            "is_saved": bool(filepath),
            "is_dirty": bpy.data.is_dirty,
            "blender_version": ".".join(str(v) for v in bpy.app.version),
            "active_scene": bpy.context.scene.name,
            "object_count": len(bpy.data.objects),
            "mesh_count": len(bpy.data.meshes),
            "material_count": len(bpy.data.materials),
        })
    except Exception as e:
        return error_response(f"Failed to get file info: {e}")


def _file_save(params):
    """
    Save the current Blender file.

    Route: POST /api/file/save

    Optional params:
        filepath (str): Destination path (Save As). Omit to save in-place.
        compress (bool): Write a compressed .blend file. Defaults to False.

    Returns:
        {filepath, compressed}
    """
    try:
        filepath = params.get("filepath", "").strip()
        compress = bool(params.get("compress", False))

        if filepath:
            filepath, path_err = validate_filepath(filepath)
            if path_err:
                return error_response(path_err)

        if filepath:
            success, result = safe_operator_call(
                bpy.ops.wm.save_as_mainfile,
                filepath=filepath,
                compress=compress,
            )
            if not success:
                return error_response(f"Save As failed: {result}")
            saved_path = filepath
        else:
            current_path = bpy.data.filepath
            if not current_path:
                return error_response(
                    "The file has never been saved. "
                    "Provide a 'filepath' parameter to save it for the first time."
                )
            success, result = safe_operator_call(
                bpy.ops.wm.save_mainfile,
                compress=compress,
            )
            if not success:
                return error_response(f"Save failed: {result}")
            saved_path = current_path

        return ok_response({"filepath": saved_path, "compressed": compress})
    except Exception as e:
        return error_response(f"Failed to save file: {e}")


def _file_open(params):
    """
    Open a .blend file in Blender.

    Route: POST /api/file/open

    WARNING: This reloads the entire Blender session — unsaved changes are lost.

    Required params:
        filepath (str): Absolute path to the .blend file to open.

    Returns:
        {filepath, active_scene, object_count}
    """
    filepath = params.get("filepath", "").strip()
    if not filepath:
        return error_response("Parameter 'filepath' is required.")

    filepath, path_err = validate_filepath(filepath, must_exist=True)
    if path_err:
        return error_response(path_err)

    try:
        success, result = safe_operator_call(
            bpy.ops.wm.open_mainfile,
            filepath=filepath,
        )
        if not success:
            return error_response(f"Open failed: {result}")

        return ok_response({
            "filepath": filepath,
            "active_scene": bpy.context.scene.name,
            "object_count": len(bpy.data.objects),
        })
    except Exception as e:
        return error_response(f"Failed to open file: {e}")


# ─── Register routes ───
register_handler("file", "info", _file_info)
register_handler("file", "save", _file_save)
register_handler("file", "open", _file_open)

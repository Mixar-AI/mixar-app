"""
Advanced export/import handlers for Blender MCP Bridge.
Provides OBJ, STL, USD exports and reference image import.
"""

import os
import bpy
from ...utils.response import ok_response, error_response, validate_filepath
from ...utils.compat import is_blender_4
from .. import register_handler


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _file_size_info(filepath):
    """Return (size_bytes, size_readable) for an existing file."""
    try:
        size_bytes = os.path.getsize(filepath)
        if size_bytes < 1024:
            readable = f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            readable = f"{size_bytes / 1024:.1f} KB"
        else:
            readable = f"{size_bytes / (1024 * 1024):.2f} MB"
        return size_bytes, readable
    except OSError:
        return 0, "unknown"


# ─── Handlers ──────────────────────────────────────────────────────────────────

def _handle_export_obj(params):
    """
    Export scene or selection as Wavefront OBJ.

    Route: POST /api/export/obj

    Required params:
        filepath (str): Absolute path for the output .obj file.

    Optional params:
        selected_only (bool): Export only selected objects. Default False.
        apply_modifiers (bool): Apply mesh modifiers. Default True.
        export_materials (bool): Export companion .mtl file. Default True.

    Returns:
        {filepath, size_bytes, size_readable, blender_version}
    """
    filepath = params.get("filepath", "").strip()
    if not filepath:
        return error_response("Parameter 'filepath' is required.")

    filepath, path_err = validate_filepath(filepath)
    if path_err:
        return error_response(path_err)

    selected_only = bool(params.get("selected_only", False))
    apply_modifiers = bool(params.get("apply_modifiers", True))
    export_materials = bool(params.get("export_materials", True))

    try:
        if is_blender_4():
            # Blender 4.x new OBJ exporter
            result = bpy.ops.wm.obj_export(
                filepath=filepath,
                export_selected_objects=selected_only,
                apply_modifiers=apply_modifiers,
                export_materials=export_materials,
            )
        else:
            # Blender 3.x legacy OBJ exporter
            result = bpy.ops.export_scene.obj(
                filepath=filepath,
                use_selection=selected_only,
                use_mesh_modifiers=apply_modifiers,
                use_materials=export_materials,
            )

        if result != {"FINISHED"}:
            return error_response(f"OBJ export operator returned: {result}")

    except Exception as e:
        return error_response(f"Failed to export OBJ: {e}")

    size_bytes, size_readable = _file_size_info(filepath)
    return ok_response({
        "filepath": filepath,
        "size_bytes": size_bytes,
        "size_readable": size_readable,
        "blender_version": ".".join(str(v) for v in bpy.app.version[:3]),
    })


def _handle_export_stl(params):
    """
    Export scene or selection as STL.

    Route: POST /api/export/stl

    Required params:
        filepath (str): Absolute path for the output .stl file.

    Optional params:
        selected_only (bool): Export only selected objects. Default False.
        ascii (bool): Write ASCII STL instead of binary. Default False.

    Returns:
        {filepath, ascii, size_bytes, size_readable}
    """
    filepath = params.get("filepath", "").strip()
    if not filepath:
        return error_response("Parameter 'filepath' is required.")

    filepath, path_err = validate_filepath(filepath)
    if path_err:
        return error_response(path_err)

    selected_only = bool(params.get("selected_only", False))
    ascii_mode = bool(params.get("ascii", False))

    try:
        if is_blender_4():
            # Blender 4.x new STL exporter
            result = bpy.ops.wm.stl_export(
                filepath=filepath,
                export_selected_objects=selected_only,
                ascii_format=ascii_mode,
            )
        else:
            # Blender 3.x legacy STL exporter
            result = bpy.ops.export_mesh.stl(
                filepath=filepath,
                use_selection=selected_only,
                ascii=ascii_mode,
            )

        if result != {"FINISHED"}:
            return error_response(f"STL export operator returned: {result}")

    except Exception as e:
        return error_response(f"Failed to export STL: {e}")

    size_bytes, size_readable = _file_size_info(filepath)
    return ok_response({
        "filepath": filepath,
        "ascii": ascii_mode,
        "size_bytes": size_bytes,
        "size_readable": size_readable,
    })


def _handle_export_usd(params):
    """
    Export scene or selection in Universal Scene Description (USD) format.

    Route: POST /api/export/usd

    Required params:
        filepath (str): Absolute path for the output USD file (.usd, .usda, .usdc).

    Optional params:
        format (str): 'USD' | 'USDA' | 'USDC'. Typically inferred from extension.
        selected_only (bool): Export only selected objects. Default False.
        export_materials (bool): Include material data. Default True.
        export_animation (bool): Include animation data. Default False.

    Returns:
        {filepath, size_bytes, size_readable}
    """
    filepath = params.get("filepath", "").strip()
    if not filepath:
        return error_response("Parameter 'filepath' is required.")

    filepath, path_err = validate_filepath(filepath)
    if path_err:
        return error_response(path_err)

    selected_only = bool(params.get("selected_only", False))
    export_materials = bool(params.get("export_materials", True))
    export_animation = bool(params.get("export_animation", False))

    try:
        kwargs = dict(
            filepath=filepath,
            selected_objects_only=selected_only,
            export_materials=export_materials,
            export_animation=export_animation,
        )

        # Optional explicit format override
        fmt = params.get("format")
        if fmt:
            kwargs["export_format"] = fmt.upper()

        result = bpy.ops.wm.usd_export(**kwargs)
        if result != {"FINISHED"}:
            return error_response(f"USD export operator returned: {result}")

    except Exception as e:
        return error_response(f"Failed to export USD: {e}")

    size_bytes, size_readable = _file_size_info(filepath)
    return ok_response({
        "filepath": filepath,
        "size_bytes": size_bytes,
        "size_readable": size_readable,
        "export_animation": export_animation,
    })


def _handle_import_reference_image(params):
    """
    Import an image as a reference empty in the scene.

    Route: POST /api/import/reference-image

    Required params:
        filepath (str): Absolute path to the image file.

    Optional params:
        location ([x, y, z]): World-space position. Default [0, 0, 0].
        size (float): Display size of the empty. Default 1.0.

    Returns:
        {name, type, filepath, location, size}
    """
    filepath = params.get("filepath", "").strip()
    if not filepath:
        return error_response("Parameter 'filepath' is required.")

    filepath, path_err = validate_filepath(filepath, must_exist=True)
    if path_err:
        return error_response(path_err)

    if not os.path.isfile(filepath):
        return error_response(f"Image file not found: {filepath}")

    location = params.get("location", [0.0, 0.0, 0.0])
    size = float(params.get("size", 1.0))

    # Snapshot existing objects
    snapshot = set(bpy.data.objects.keys())

    try:
        bpy.ops.object.empty_image_add(filepath=filepath)
    except Exception as e:
        return error_response(f"Failed to import reference image: {e}")

    # Find newly created empty
    new_keys = set(bpy.data.objects.keys()) - snapshot
    if not new_keys:
        # Fallback: use active object
        obj = bpy.context.active_object
        if obj is None or obj.type != "EMPTY":
            return error_response("Reference image empty was not created.")
    else:
        # Prefer the newly created object
        obj_name = next(iter(new_keys))
        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            return error_response("Reference image empty was created but cannot be found.")

    # Apply location and size
    try:
        obj.location = (
            float(location[0]),
            float(location[1]),
            float(location[2]),
        )
        obj.empty_display_size = size
    except Exception as e:
        return error_response(f"Reference image created but failed to set location/size: {e}")

    return ok_response({
        "name": obj.name,
        "object_name": obj.name,
        "type": obj.type,
        "filepath": filepath,
        "location": list(obj.location),
        "size": obj.empty_display_size,
    })


# ─── Register routes ────────────────────────────────────────────────────────────

register_handler("export", "obj", _handle_export_obj)
register_handler("export", "stl", _handle_export_stl)
register_handler("export", "usd", _handle_export_usd)
register_handler("import", "reference-image", _handle_import_reference_image)

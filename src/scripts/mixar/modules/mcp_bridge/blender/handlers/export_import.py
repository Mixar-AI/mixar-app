"""
Export/Import handlers for Blender MCP Bridge.
Provides FBX export, glTF/GLB export, and auto-detected file import.
"""

import os
import bpy
from ..utils.response import ok_response, error_response, validate_filepath
from ..utils.compat import is_blender_5, is_cast_shadow_supported
from . import register_handler


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _file_size_info(filepath):
    """Return file size in bytes and a human-readable string."""
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

def _handle_export_fbx(params):
    """
    Export scene or selection as FBX.

    Route: POST /api/export/fbx

    Required params:
        filepath (str): Absolute path for the output .fbx file.

    Optional params:
        selected_only (bool): Export only selected objects. Default False.
        apply_modifiers (bool): Apply mesh modifiers. Default True.
        forward_axis (str): Forward axis override (e.g. '-Z', 'Y').
        up_axis (str): Up axis override (e.g. 'Y', 'Z').
        global_scale (float): Scale multiplier. Default 1.0.
        embed_textures (bool): Embed textures in the FBX. Default False.
        target_engine (str): 'UNITY' | 'UNREAL' | 'GENERIC' — applies axis/scale presets.

    Returns:
        {filepath, file_size_bytes, size_readable, target_engine}
    """
    filepath = params.get("filepath", "").strip()
    if not filepath:
        return error_response("Parameter 'filepath' is required.")

    filepath, path_err = validate_filepath(filepath)
    if path_err:
        return error_response(path_err)

    selected_only = bool(params.get("selected_only", False))
    apply_modifiers = bool(params.get("apply_modifiers", True))
    global_scale = float(params.get("global_scale", 1.0))
    embed_textures = bool(params.get("embed_textures", False))
    target_engine = (params.get("target_engine") or "GENERIC").upper()

    # Axis defaults — may be overridden by engine preset
    forward_axis = params.get("forward_axis", "-Z")
    up_axis = params.get("up_axis", "Y")

    # Engine preset overrides
    apply_unit_scale = False
    bake_space_transform = False

    if target_engine == "UNITY":
        forward_axis = "-Z"
        up_axis = "Y"
        global_scale = 1.0
        apply_unit_scale = True
        bake_space_transform = True
    elif target_engine == "UNREAL":
        forward_axis = "X"
        up_axis = "Z"

    # Path mode for texture embedding
    path_mode = "COPY" if embed_textures else "AUTO"

    # Exclude specific object types by temporarily adjusting selection
    exclude_types = params.get("exclude_types")
    saved_selection = None

    if exclude_types:
        exclude_types = set(t.upper() for t in exclude_types)
        # Save current selection state
        saved_selection = {obj.name: obj.select_get() for obj in bpy.data.objects}
        # Deselect all, then select only non-excluded objects
        bpy.ops.object.select_all(action='DESELECT')
        for obj in bpy.data.objects:
            if obj.type not in exclude_types:
                obj.select_set(True)
        # Force selection-only export
        selected_only = True

    try:
        # Blender 3.x / 4.x / 5.x all use the same FBX export parameter names.
        # Note: Blender 5.0.1 did NOT rename the FBX operator parameters despite
        # earlier release notes suggesting otherwise. The legacy names remain valid.
        kwargs = dict(
            filepath=filepath,
            use_selection=selected_only,
            use_mesh_modifiers=apply_modifiers,
            axis_forward=forward_axis,
            axis_up=up_axis,
            global_scale=global_scale,
            path_mode=path_mode,
            embed_textures=embed_textures,
            apply_unit_scale=apply_unit_scale,
            bake_space_transform=bake_space_transform,
        )
        result = bpy.ops.export_scene.fbx(**kwargs)
        if result != {"FINISHED"}:
            return error_response(f"FBX export operator returned: {result}")
    except AttributeError as e:
        return error_response(
            f"FBX export operator not available in this Blender version "
            f"({bpy.app.version[0]}.{bpy.app.version[1]}): {e}. "
            f"Ensure the FBX add-on is enabled (File > Preferences > Add-ons > Import-Export: FBX format)."
        )
    except TypeError as e:
        return error_response(
            f"FBX export failed due to an unexpected parameter change in Blender "
            f"{bpy.app.version[0]}.{bpy.app.version[1]}: {e}. "
            f"Please report this as a compatibility issue."
        )
    except Exception as e:
        return error_response(f"Failed to export FBX: {e}")
    finally:
        # Restore original selection state if we modified it
        if saved_selection is not None:
            for obj in bpy.data.objects:
                if obj.name in saved_selection:
                    obj.select_set(saved_selection[obj.name])

    size_bytes, size_readable = _file_size_info(filepath)
    return ok_response({
        "filepath": filepath,
        "file_size_bytes": size_bytes,
        "size_readable": size_readable,
        "target_engine": target_engine,
    })


def _handle_export_gltf(params):
    """
    Export scene or selection as glTF/GLB.

    Route: POST /api/export/gltf

    Required params:
        filepath (str): Absolute path for the output file.

    Optional params:
        format (str): 'GLB' | 'GLTF_SEPARATE' | 'GLTF_EMBEDDED'. Default 'GLB'.
        selected_only (bool): Export only selected objects. Default False.
        apply_modifiers (bool): Apply mesh modifiers. Default True.
        export_draco (bool): Enable Draco mesh compression. Default False.
        draco_compression_level (int): 0–10. Default 6.

    Returns:
        {filepath, format, draco_compression, file_size_bytes, size_readable}
    """
    filepath = params.get("filepath", "").strip()
    if not filepath:
        return error_response("Parameter 'filepath' is required.")

    filepath, path_err = validate_filepath(filepath)
    if path_err:
        return error_response(path_err)

    fmt = (params.get("format") or "GLB").upper()
    valid_formats = ("GLB", "GLTF_SEPARATE", "GLTF_EMBEDDED")
    if fmt not in valid_formats:
        return error_response(f"Invalid format '{fmt}'. Must be one of: {', '.join(valid_formats)}.")

    selected_only = bool(params.get("selected_only", False))
    apply_modifiers = bool(params.get("apply_modifiers", True))
    export_draco = bool(params.get("export_draco", False))
    draco_level = int(params.get("draco_compression_level", 6))

    try:
        kwargs = dict(
            filepath=filepath,
            export_format=fmt,
            use_selection=selected_only,
            export_apply=apply_modifiers,
        )

        if export_draco:
            kwargs["export_draco_mesh_compression_enable"] = True
            kwargs["export_draco_mesh_compression_level"] = max(0, min(10, draco_level))

        result = bpy.ops.export_scene.gltf(**kwargs)
        if result != {"FINISHED"}:
            return error_response(f"glTF export operator returned: {result}")
    except Exception as e:
        return error_response(f"Failed to export glTF: {e}")

    size_bytes, size_readable = _file_size_info(filepath)
    return ok_response({
        "filepath": filepath,
        "format": fmt,
        "draco_compression": export_draco,
        "file_size_bytes": size_bytes,
        "size_readable": size_readable,
    })


def _handle_import_file(params):
    """
    Import a 3D file (FBX, glTF/GLB, OBJ, STL) into the current scene.

    Route: POST /api/import/file

    Required params:
        filepath (str): Absolute path to the file to import.

    Optional params:
        format (str): Force import format ('fbx', 'gltf', 'obj', 'stl').
                      Auto-detected from extension if omitted.

    Returns:
        {filepath, format, imported_objects: [{name, type}]}
    """
    filepath = params.get("filepath", "").strip()
    if not filepath:
        return error_response("Parameter 'filepath' is required.")

    filepath, path_err = validate_filepath(filepath, must_exist=True)
    if path_err:
        return error_response(path_err)

    if not os.path.isfile(filepath):
        return error_response(f"File not found: {filepath}")

    # Determine format
    forced_format = (params.get("format") or "").lower().strip()
    if forced_format:
        fmt = forced_format
    else:
        ext = os.path.splitext(filepath)[1].lower()
        ext_map = {
            ".fbx": "fbx",
            ".gltf": "gltf",
            ".glb": "gltf",
            ".obj": "obj",
            ".stl": "stl",
        }
        fmt = ext_map.get(ext)
        if not fmt:
            return error_response(
                f"Cannot auto-detect import format for extension '{ext}'. "
                "Supported: .fbx, .gltf, .glb, .obj, .stl. "
                "Use the 'format' parameter to specify explicitly."
            )

    # Snapshot of existing objects before import
    snapshot = set(bpy.data.objects.keys())

    try:
        if fmt == "fbx":
            try:
                result = bpy.ops.import_scene.fbx(filepath=filepath)
            except AttributeError as e:
                if not is_cast_shadow_supported() and "cast_shadow" in str(e):
                    return error_response(
                        f"FBX import failed due to Blender 5.0 API change: {e}. "
                        f"The FBX file contains light data using the removed "
                        f"'CyclesLightSettings.cast_shadow' property. "
                        f"Workaround: re-export the FBX without lights, or use Blender 4.x for this import."
                    )
                raise
        elif fmt == "gltf":
            result = bpy.ops.import_scene.gltf(filepath=filepath)
        elif fmt == "obj":
            # Blender 4.x uses wm.obj_import, 3.x uses import_scene.obj
            try:
                result = bpy.ops.wm.obj_import(filepath=filepath)
            except AttributeError:
                result = bpy.ops.import_scene.obj(filepath=filepath)
        elif fmt == "stl":
            # Blender 4.x uses wm.stl_import, 3.x uses import_mesh.stl
            try:
                result = bpy.ops.wm.stl_import(filepath=filepath)
            except AttributeError:
                result = bpy.ops.import_mesh.stl(filepath=filepath)
        else:
            return error_response(
                f"Unsupported format '{fmt}'. Valid values: fbx, gltf, obj, stl."
            )

        if result != {"FINISHED"}:
            return error_response(f"Import operator returned: {result}")

    except Exception as e:
        return error_response(f"Failed to import file: {e}")

    # Find newly added objects
    new_keys = set(bpy.data.objects.keys()) - snapshot
    imported_objects = [
        {"name": name, "object_name": name, "type": bpy.data.objects[name].type}
        for name in sorted(new_keys)
        if name in bpy.data.objects
    ]

    return ok_response({
        "filepath": filepath,
        "format": fmt,
        "imported_objects": imported_objects,
        "imported_count": len(imported_objects),
    })


# ─── Register routes ────────────────────────────────────────────────────────────

register_handler("export", "fbx", _handle_export_fbx)
register_handler("export", "gltf", _handle_export_gltf)
register_handler("import", "file", _handle_import_file)

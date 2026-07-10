"""
Render handlers for Blender MCP Bridge.
Provides render operations: current, get-settings, set-settings.
"""

import bpy
import time
from ..utils.response import ok_response, error_response
from ..utils.context_helpers import safe_operator_call
from ..utils.compat import get_eevee_engine_name
from . import register_handler


def _get_render_samples(scene):
    """
    Read the sample count from the appropriate engine sub-settings.
    Returns an integer, or None if the engine is not recognised.
    """
    engine = scene.render.engine
    if engine == "CYCLES":
        return scene.cycles.samples
    if engine == get_eevee_engine_name() or engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        return scene.eevee.taa_render_samples
    return None


def _build_settings_dict(scene):
    """Return a dict containing all current render settings."""
    render = scene.render
    cm = scene.view_settings  # color management lives here

    return {
        "engine": render.engine,
        "resolution_x": render.resolution_x,
        "resolution_y": render.resolution_y,
        "resolution_percentage": render.resolution_percentage,
        "samples": _get_render_samples(scene),
        "output_path": render.filepath,
        "file_format": render.image_settings.file_format,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "frame_current": scene.frame_current,
        "color_management": {
            "view_transform": cm.view_transform,
            "look": cm.look,
        },
    }


def _handle_render_current(params):
    """
    Render the current frame and write it to disk.

    Route: POST /api/render/current

    Optional params:
        output_path (str): Override the output file path.
        file_format (str): Override the file format (PNG, JPEG, EXR, OPEN_EXR, TIFF, BMP).

    Returns:
        {output_path, file_format, resolution: [x, y]}
    """
    try:
        scene = bpy.context.scene
        render = scene.render

        if "output_path" in params and params["output_path"]:
            render.filepath = params["output_path"]

        if "file_format" in params and params["file_format"]:
            render.image_settings.file_format = params["file_format"]

        # bpy.ops.render.render is blocking — it returns only when the frame is done.
        start_time = time.time()
        success, result = safe_operator_call(bpy.ops.render.render, write_still=True)
        if not success:
            return error_response(f"Render operator failed: {result}")

        render_time_seconds = round(time.time() - start_time, 3)

        return ok_response({
            "output_path": render.filepath,
            "file_format": render.image_settings.file_format,
            "resolution": [render.resolution_x, render.resolution_y],
            "render_time_seconds": render_time_seconds,
        })
    except Exception as e:
        return error_response(f"Failed to render current frame: {e}")


def _handle_render_get_settings(params):
    """
    Read the current render settings from the active scene.

    Route: POST /api/render/get-settings

    Returns:
        engine, resolution_x/y, resolution_percentage, samples, output_path,
        file_format, frame_start/end/current, color_management.
    """
    try:
        scene = bpy.context.scene
        return ok_response(_build_settings_dict(scene))
    except Exception as e:
        return error_response(f"Failed to get render settings: {e}")


def _handle_render_set_settings(params):
    """
    Update render settings on the active scene.

    Route: POST /api/render/set-settings

    Optional params:
        engine (str), resolution_x (int), resolution_y (int),
        resolution_percentage (int), samples (int),
        output_path (str), file_format (str),
        frame_start (int), frame_end (int).

    Returns:
        Confirmation with all current settings after the update.
    """
    try:
        scene = bpy.context.scene
        render = scene.render

        if "engine" in params:
            engine = params["engine"]
            eevee_name = get_eevee_engine_name()
            ENGINE_ALIASES = {
                "EEVEE": eevee_name,
                "BLENDER_EEVEE": eevee_name,
                "BLENDER_EEVEE_NEXT": eevee_name,
                "WORKBENCH": "BLENDER_WORKBENCH",
            }
            engine = ENGINE_ALIASES.get(engine, engine)
            render.engine = engine

        if "resolution_x" in params:
            render.resolution_x = int(params["resolution_x"])

        if "resolution_y" in params:
            render.resolution_y = int(params["resolution_y"])

        if "resolution_percentage" in params:
            render.resolution_percentage = int(params["resolution_percentage"])

        if "output_path" in params:
            render.filepath = params["output_path"]

        if "file_format" in params:
            render.image_settings.file_format = params["file_format"]

        if "frame_start" in params:
            scene.frame_start = int(params["frame_start"])

        if "frame_end" in params:
            scene.frame_end = int(params["frame_end"])

        if "samples" in params:
            samples = int(params["samples"])
            engine = render.engine
            if engine == "CYCLES":
                scene.cycles.samples = samples
            elif engine == get_eevee_engine_name() or engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
                scene.eevee.taa_render_samples = samples
            # For other engines, silently ignore — no standard samples property.

        return ok_response(_build_settings_dict(scene))
    except Exception as e:
        return error_response(f"Failed to set render settings: {e}")


# ─── Register routes ───
register_handler("render", "current", _handle_render_current)
register_handler("render", "get-settings", _handle_render_get_settings)
register_handler("render", "set-settings", _handle_render_set_settings)

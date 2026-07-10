"""
Scene handlers for Blender MCP Bridge.
Provides scene-level operations: info, list, set-active.
"""

import bpy
from ..utils.response import ok_response, error_response, not_found
from . import register_handler


def _handle_scene_info(params):
    """
    Get information about the currently active scene.

    Route: POST /api/scene/info

    Returns:
        name, object_count, frame_start, frame_end, frame_current,
        render_engine, unit system, unit scale, length unit.
    """
    try:
        scene = bpy.context.scene
        unit = scene.unit_settings

        return ok_response({
            "name": scene.name,
            "object_count": len(scene.objects),
            "frame_start": scene.frame_start,
            "frame_end": scene.frame_end,
            "frame_current": scene.frame_current,
            "render_engine": scene.render.engine,
            "unit_settings": {
                "system": unit.system,
                "scale": unit.scale_length,
                "length_unit": unit.length_unit,
            },
        })
    except Exception as e:
        return error_response(f"Failed to get scene info: {e}")


def _handle_scene_list(params):
    """
    List all scenes in the current Blender file.

    Route: POST /api/scene/list

    Returns:
        Array of {name, object_count, is_active}.
    """
    try:
        active_scene = bpy.context.scene
        scenes = []

        for scene in bpy.data.scenes:
            scenes.append({
                "name": scene.name,
                "object_count": len(scene.objects),
                "is_active": scene.name == active_scene.name,
            })

        return ok_response(scenes)
    except Exception as e:
        return error_response(f"Failed to list scenes: {e}")


def _handle_scene_set_active(params):
    """
    Switch the active scene to the named scene.

    Route: POST /api/scene/set-active

    Params:
        name (str): The name of the scene to activate.

    Returns:
        Confirmation with the scene name.
    """
    name = params.get("name")
    if not name:
        return error_response("Parameter 'name' is required.")

    try:
        scene = bpy.data.scenes.get(name)
        if scene is None:
            return not_found(name, "Scene")

        bpy.context.window.scene = scene

        return ok_response({
            "name": scene.name,
            "message": f"Active scene set to '{scene.name}'.",
        })
    except Exception as e:
        return error_response(f"Failed to set active scene: {e}")


# ─── Register routes ───
register_handler("scene", "info", _handle_scene_info)
register_handler("scene", "list", _handle_scene_list)
register_handler("scene", "set-active", _handle_scene_set_active)

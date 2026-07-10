"""
Animation handlers for Blender MCP Bridge.
Provides animation operations: insert-keyframe, get-keyframes, set-frame.
"""

import bpy
from ..utils.response import ok_response, error_response, not_found
from ..utils.compat import get_action_fcurves
from . import register_handler


def _handle_anim_get_keyframes(params):
    """
    Get all keyframe data from an object's action.

    Route: POST /api/anim/get-keyframes

    Required params:
        name (str): Name of the target object.

    Optional params:
        data_path (str): If provided, only return F-Curves matching this path.

    Returns:
        {
            object: str,
            fcurves: [
                {
                    data_path: str,
                    array_index: int,
                    keyframes: [{frame: float, value: float, interpolation: str}, ...]
                },
                ...
            ]
        }
    """
    object_name = params.get("name")
    if not object_name:
        return error_response("Parameter 'name' is required.")

    try:
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return not_found(object_name)

        filter_path = params.get("data_path")

        if obj.animation_data is None or obj.animation_data.action is None:
            return ok_response({"object": object_name, "object_name": object_name, "fcurves": []})

        action = obj.animation_data.action
        fcurves_data = []

        for fcurve in get_action_fcurves(action, obj):
            if filter_path is not None and fcurve.data_path != filter_path:
                continue

            keyframes = []
            for kp in fcurve.keyframe_points:
                keyframes.append({
                    "frame": kp.co[0],
                    "value": kp.co[1],
                    "interpolation": kp.interpolation,
                })

            fcurves_data.append({
                "data_path": fcurve.data_path,
                "array_index": fcurve.array_index,
                "keyframes": keyframes,
            })

        return ok_response({"object": object_name, "object_name": object_name, "fcurves": fcurves_data})
    except Exception as e:
        return error_response(f"Failed to get keyframes: {e}")


def _handle_anim_set_frame(params):
    """
    Set the current frame of the active scene.

    Route: POST /api/anim/set-frame

    Required params:
        frame (int): The frame number to jump to.

    Returns:
        {frame}
    """
    if "frame" not in params:
        return error_response("Parameter 'frame' is required.")

    try:
        frame = int(params["frame"])
        bpy.context.scene.frame_set(frame)
        return ok_response({"frame": bpy.context.scene.frame_current})
    except Exception as e:
        return error_response(f"Failed to set frame: {e}")


# ─── Register routes ───
register_handler("anim", "get-keyframes", _handle_anim_get_keyframes)
register_handler("anim", "set-frame", _handle_anim_set_frame)

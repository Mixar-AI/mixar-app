"""
Modifier extended handlers for Blender MCP Bridge.
Provides: modifier/reorder
"""

import bpy
from ...utils.response import ok_response, error_response, not_found
from ...utils.compat import is_blender_4
from ...utils.context_helpers import ensure_context_for_object, temp_override, safe_operator_call
from .. import register_handler


# ─── Helpers ────────────────────────────────────────────────────────────────────

def _get_object(name):
    """Return (obj, None) or (None, error_response) for any object."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, not_found(name)
    return obj, None


# ─── Handlers ───────────────────────────────────────────────────────────────────

def _handle_modifier_reorder(params):
    """
    Reorder a modifier in an object's modifier stack.
    Route: POST /api/modifier/reorder
    """
    object_name   = params.get("object_name")
    modifier_name = params.get("modifier_name")
    direction     = params.get("direction")      # "UP" or "DOWN"
    index         = params.get("index")          # int target position

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not modifier_name:
        return error_response("Parameter 'modifier_name' is required.")
    if direction is not None and index is not None:
        return error_response("Cannot specify both 'direction' and 'index'")
    if direction is None and index is None:
        return error_response("Either 'direction' or 'index' must be provided.")

    if direction is not None:
        direction = direction.upper()
        if direction not in ("UP", "DOWN"):
            return error_response("Parameter 'direction' must be 'UP' or 'DOWN'.")

    obj, err = _get_object(object_name)
    if err:
        return err

    if obj.modifiers.get(modifier_name) is None:
        return error_response(
            f"Modifier '{modifier_name}' not found on object '{object_name}'."
        )

    try:
        ensure_context_for_object(obj)

        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        if index is not None:
            target_index = int(index)
            stack = list(obj.modifiers)
            mod_names = [m.name for m in stack]
            if modifier_name not in mod_names:
                return error_response(
                    f"Modifier '{modifier_name}' not found on object '{object_name}'."
                )
            from_index = mod_names.index(modifier_name)
            num_mods   = len(stack)
            # Clamp target index to valid range
            target_index = max(0, min(target_index, num_mods - 1))

            if is_blender_4():
                # Blender 4.x — native move API
                obj.modifiers.move(from_index, target_index)
            else:
                # Blender 3.x — use move_up / move_down operators repeatedly
                steps = from_index - target_index
                if steps > 0:
                    for _ in range(steps):
                        with temp_override("VIEW_3D"):
                            safe_operator_call(
                                bpy.ops.object.modifier_move_up,
                                modifier=modifier_name,
                            )
                elif steps < 0:
                    for _ in range(abs(steps)):
                        with temp_override("VIEW_3D"):
                            safe_operator_call(
                                bpy.ops.object.modifier_move_down,
                                modifier=modifier_name,
                            )
        else:
            # direction-based (UP or DOWN)
            if direction == "UP":
                with temp_override("VIEW_3D"):
                    ok, res = safe_operator_call(
                        bpy.ops.object.modifier_move_up, modifier=modifier_name
                    )
                if not ok:
                    return error_response(f"modifier_move_up failed: {res}")
            else:
                with temp_override("VIEW_3D"):
                    ok, res = safe_operator_call(
                        bpy.ops.object.modifier_move_down, modifier=modifier_name
                    )
                if not ok:
                    return error_response(f"modifier_move_down failed: {res}")

        # Report the final index of the modifier
        final_stack = list(obj.modifiers)
        final_names = [m.name for m in final_stack]
        final_index = final_names.index(modifier_name) if modifier_name in final_names else -1

        return ok_response({
            "object_name":   obj.name,
            "modifier_name": modifier_name,
            "index":         final_index,
        })
    except Exception as e:
        return error_response(
            f"Failed to reorder modifier '{modifier_name}' on '{object_name}': {e}"
        )


# ─── Register routes ─────────────────────────────────────────────────────────────

register_handler("modifier", "reorder", _handle_modifier_reorder)

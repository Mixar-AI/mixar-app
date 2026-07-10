"""
Advanced animation extended handlers for Blender MCP Bridge.
Provides: anim/insert-keyframe, anim/delete-keyframe, anim/set-frame-range,
          anim/set-current-frame, anim/set-interpolation, anim/create-action,
          anim/assign-action, anim/list-actions, anim/bake, anim/nla-push,
          anim/shape-key-add, anim/shape-key-set, anim/shape-key-keyframe,
          anim/driver-add
"""

import bpy
from ...utils.response import ok_response, error_response, not_found, coerce_value
from ...utils.context_helpers import ensure_context_for_object, temp_override, safe_operator_call
from .. import register_handler


# â”€â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _get_object(name):
    """Return (obj, None) or (None, error_response) for any object type."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, not_found(name)
    return obj, None


def _get_mesh_object(name):
    """Return (obj, None) or (None, error_response) for a MESH object."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, not_found(name)
    if obj.type != "MESH":
        return None, error_response(
            f"Object '{name}' is of type '{obj.type}', not 'MESH'."
        )
    return obj, None


def _ensure_animation_data(obj):
    """Create animation_data on obj if it does not already exist."""
    if obj.animation_data is None:
        obj.animation_data_create()


# â”€â”€â”€ Handlers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _handle_anim_insert_keyframe(params):
    """
    Insert a keyframe on a specific data_path at the given frame.
    Route: anim/insert-keyframe
    """
    object_name = params.get("name")
    data_path   = params.get("data_path")
    frame       = params.get("frame")
    value       = params.get("value")
    # Coerce value: if string that looks like array, parse it; ensure numeric elements
    if value is not None:
        import json as _json
        if isinstance(value, str):
            try:
                value = _json.loads(value)
            except (ValueError, TypeError):
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    pass
        if isinstance(value, (list, tuple)):
            value = [float(x) for x in value]
    index       = params.get("index")

    if not object_name:
        return error_response("Parameter 'name' is required.")
    if not data_path:
        return error_response("Parameter 'data_path' is required.")
    if frame is None:
        frame = bpy.context.scene.frame_current

    obj, err = _get_object(object_name)
    if err:
        return err

    try:
        # Optionally set the value before inserting the keyframe
        if value is not None:
            try:
                # Handle indexed path like "location[0]"
                if "[" in data_path and data_path.rstrip().endswith("]"):
                    # Parse "attr[index]" to avoid creating a custom property
                    bracket_pos = data_path.index("[")
                    attr_name = data_path[:bracket_pos]
                    idx = int(data_path[bracket_pos + 1:data_path.index("]")])
                    getattr(obj, attr_name)[idx] = value
                else:
                    # Try direct attribute set; for vectors accept list/tuple
                    attr = data_path
                    current = obj.path_resolve(attr)
                    if hasattr(current, "__len__"):
                        # compound property (Vector, Euler, etc.)
                        for i, v in enumerate(value):
                            current[i] = v
                    else:
                        obj.path_resolve(attr)  # validate path
                        # Walk to the parent and set
                        parts = attr.rsplit(".", 1)
                        if len(parts) == 2:
                            parent = obj.path_resolve(parts[0])
                            coerced = coerce_value(current, value)
                            setattr(parent, parts[1], coerced)
                        else:
                            coerced = coerce_value(current, value)
                            setattr(obj, attr, coerced)
            except Exception as ve:
                return error_response(
                    f"Failed to set value on '{data_path}' before keyframe insert: {ve}"
                )

        _ensure_animation_data(obj)

        # If data_path contains a bracket index (e.g. "location[0]"), split it
        # into the base path and the numeric index so that keyframe_insert
        # receives a valid RNA path.  An explicit `index` parameter passed by
        # the caller takes precedence over any bracket-encoded index.
        kf_data_path = data_path
        kf_index = index
        if kf_index is None and "[" in data_path and data_path.rstrip().endswith("]"):
            try:
                bracket_pos = data_path.index("[")
                kf_index = int(data_path[bracket_pos + 1:data_path.index("]")])
                kf_data_path = data_path[:bracket_pos]
            except (ValueError, IndexError):
                pass  # Leave data_path as-is if parsing fails

        kf_kwargs = {"data_path": kf_data_path, "frame": float(frame)}
        if kf_index is not None:
            kf_kwargs["index"] = int(kf_index)
        obj.keyframe_insert(**kf_kwargs)

        response_data = {
            "object_name": obj.name,
            "data_path": data_path,
            "frame": float(frame),
        }
        if kf_index is not None:
            response_data["index"] = int(kf_index)
        return ok_response(response_data)
    except Exception as e:
        return error_response(
            f"Failed to insert keyframe on '{object_name}' path '{data_path}' at frame {frame}: {e}"
        )


def _handle_anim_delete_keyframe(params):
    """
    Delete a keyframe on a specific data_path at the given frame.
    Route: anim/delete-keyframe
    """
    object_name = params.get("object_name")
    data_path   = params.get("data_path")
    frame       = params.get("frame")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not data_path:
        return error_response("Parameter 'data_path' is required.")
    if frame is None:
        return error_response("Parameter 'frame' is required.")

    obj, err = _get_object(object_name)
    if err:
        return err

    try:
        obj.keyframe_delete(data_path=data_path, frame=float(frame))
        return ok_response({
            "object_name": obj.name,
            "data_path": data_path,
            "frame": float(frame),
        })
    except Exception as e:
        return error_response(
            f"Failed to delete keyframe on '{object_name}' path '{data_path}' at frame {frame}: {e}"
        )


def _handle_anim_set_frame_range(params):
    """
    Set the scene's animation frame range and optionally the fps.
    Route: anim/set-frame-range
    """
    start = params.get("start")
    end   = params.get("end")
    fps   = params.get("fps")

    if start is None:
        return error_response("Parameter 'start' is required.")
    if end is None:
        return error_response("Parameter 'end' is required.")

    start = int(start)
    end   = int(end)

    if end < start:
        return error_response(
            f"'end' ({end}) must be greater than or equal to 'start' ({start})."
        )

    try:
        scene = bpy.context.scene
        scene.frame_start = start
        scene.frame_end   = end
        if fps is not None:
            scene.render.fps = int(fps)

        return ok_response({
            "frame_start": scene.frame_start,
            "frame_end":   scene.frame_end,
            "fps":         scene.render.fps,
        })
    except Exception as e:
        return error_response(f"Failed to set frame range: {e}")


def _handle_anim_set_current_frame(params):
    """
    Set the scene's current frame.
    Route: anim/set-current-frame
    """
    frame = params.get("frame")
    if frame is None:
        return error_response("Parameter 'frame' is required.")

    try:
        bpy.context.scene.frame_set(int(frame))
        return ok_response({"frame": bpy.context.scene.frame_current})
    except Exception as e:
        return error_response(f"Failed to set current frame to {frame}: {e}")


def _handle_anim_set_interpolation(params):
    """
    Set keyframe interpolation for all keyframe points in the object's active action.
    Route: anim/set-interpolation
    """
    object_name   = params.get("object_name")
    interpolation = params.get("interpolation", "").upper() if params.get("interpolation") else ""

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not interpolation:
        return error_response("Parameter 'interpolation' is required.")

    valid = ("LINEAR", "BEZIER", "CONSTANT")
    if interpolation not in valid:
        return error_response(
            f"Unknown interpolation '{interpolation}'. Valid: {', '.join(valid)}."
        )

    obj, err = _get_object(object_name)
    if err:
        return err

    if obj.animation_data is None or obj.animation_data.action is None:
        return error_response(
            f"Object '{object_name}' has no animation data or no active action."
        )

    try:
        count = 0
        for fcurve in obj.animation_data.action.fcurves:
            for kp in fcurve.keyframe_points:
                kp.interpolation = interpolation
                count += 1

        return ok_response({
            "object_name": obj.name,
            "interpolation": interpolation,
            "keyframe_points_modified": count,
        })
    except Exception as e:
        return error_response(
            f"Failed to set interpolation on '{object_name}': {e}"
        )


def _handle_anim_create_action(params):
    """
    Create a new Action and assign it to the specified object.
    Route: anim/create-action
    """
    name        = params.get("name")
    object_name = params.get("object_name")

    if not name:
        return error_response("Parameter 'name' is required.")
    if not object_name:
        return error_response("Parameter 'object_name' is required.")

    obj, err = _get_object(object_name)
    if err:
        return err

    try:
        action = bpy.data.actions.new(name)
        _ensure_animation_data(obj)
        obj.animation_data.action = action

        return ok_response({
            "object_name": obj.name,
            "action_name": action.name,
        })
    except Exception as e:
        return error_response(
            f"Failed to create action '{name}' on '{object_name}': {e}"
        )


def _handle_anim_assign_action(params):
    """
    Assign an existing Action to the specified object.
    Route: anim/assign-action
    """
    object_name = params.get("object_name")
    action_name = params.get("action_name")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not action_name:
        return error_response("Parameter 'action_name' is required.")

    obj, err = _get_object(object_name)
    if err:
        return err

    action = bpy.data.actions.get(action_name)
    if action is None:
        return error_response(
            f"Action '{action_name}' not found in bpy.data.actions."
        )

    try:
        _ensure_animation_data(obj)
        obj.animation_data.action = action

        return ok_response({
            "object_name": obj.name,
            "action_name": action.name,
        })
    except Exception as e:
        return error_response(
            f"Failed to assign action '{action_name}' to '{object_name}': {e}"
        )


def _handle_anim_list_actions(params):
    """
    Return a list of all Action data-blocks in the file.
    Route: anim/list-actions
    """
    try:
        actions = []
        for action in bpy.data.actions:
            frame_range = None
            if action.frame_range:
                frame_range = [action.frame_range[0], action.frame_range[1]]
            actions.append({
                "name":        action.name,
                "frame_range": frame_range,
                "users":       action.users,
            })

        return ok_response({"actions": actions, "count": len(actions)})
    except Exception as e:
        return error_response(f"Failed to list actions: {e}")


def _handle_anim_bake(params):
    """
    Bake the animation of the specified object into explicit keyframes.
    Route: anim/bake
    """
    object_name = params.get("object_name")
    start_frame = params.get("start_frame")
    end_frame   = params.get("end_frame")
    step        = int(params.get("step", 1))

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if start_frame is None:
        return error_response("Parameter 'start_frame' is required.")
    if end_frame is None:
        return error_response("Parameter 'end_frame' is required.")

    start_frame = int(start_frame)
    end_frame   = int(end_frame)

    if end_frame < start_frame:
        return error_response(
            f"'end_frame' ({end_frame}) must be >= 'start_frame' ({start_frame})."
        )
    if step < 1:
        return error_response("Parameter 'step' must be at least 1.")

    obj, err = _get_object(object_name)
    if err:
        return err

    try:
        ensure_context_for_object(obj)
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        with temp_override("VIEW_3D"):
            ok, res = safe_operator_call(
                bpy.ops.nla.bake,
                frame_start=start_frame,
                frame_end=end_frame,
                step=step,
                only_selected=True,
                visual_keying=True,
                clear_constraints=False,
                bake_types={"OBJECT"},
            )
        if not ok:
            return error_response(f"Animation bake failed: {res}")

        return ok_response({
            "object_name": obj.name,
            "start_frame": start_frame,
            "end_frame":   end_frame,
            "step":        step,
        })
    except Exception as e:
        return error_response(
            f"Failed to bake animation on '{object_name}': {e}"
        )


def _handle_anim_nla_push(params):
    """
    Push the object's active action down into the NLA editor.
    Route: anim/nla-push
    """
    object_name = params.get("object_name")
    strip_name  = params.get("strip_name")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")

    obj, err = _get_object(object_name)
    if err:
        return err

    if obj.animation_data is None or obj.animation_data.action is None:
        return error_response(
            f"Object '{object_name}' has no active action to push to the NLA."
        )

    try:
        ensure_context_for_object(obj)

        with temp_override("VIEW_3D"):
            ok, res = safe_operator_call(bpy.ops.nla.action_pushdown)
        if not ok:
            return error_response(f"NLA action pushdown failed: {res}")

        # Retrieve the last NLA track/strip and rename if requested
        result_strip_name = None
        if obj.animation_data and obj.animation_data.nla_tracks:
            last_track = obj.animation_data.nla_tracks[-1]
            if last_track.strips:
                strip = last_track.strips[-1]
                if strip_name:
                    strip.name = strip_name
                result_strip_name = strip.name

        return ok_response({
            "object_name": obj.name,
            "strip_name":  result_strip_name,
        })
    except Exception as e:
        return error_response(
            f"Failed to push action to NLA for '{object_name}': {e}"
        )


def _handle_anim_shape_key_add(params):
    """
    Add a new shape key to a mesh object.
    Route: anim/shape-key-add
    """
    object_name = params.get("object_name")
    name        = params.get("name")
    from_mix    = bool(params.get("from_mix", False))

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not name:
        return error_response("Parameter 'name' is required.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    try:
        ensure_context_for_object(obj)
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        with temp_override("VIEW_3D"):
            ok, res = safe_operator_call(
                bpy.ops.object.shape_key_add, from_mix=from_mix
            )
        if not ok:
            return error_response(f"Failed to add shape key: {res}")

        # Rename the last key block to the requested name
        key_blocks = obj.data.shape_keys.key_blocks
        new_key = key_blocks[-1]
        new_key.name = name

        return ok_response({
            "object_name":    obj.name,
            "shape_key_name": new_key.name,
            "total_keys":     len(key_blocks),
        })
    except Exception as e:
        return error_response(
            f"Failed to add shape key '{name}' to '{object_name}': {e}"
        )


def _handle_anim_shape_key_set(params):
    """
    Set the influence value of a named shape key on a mesh object.
    Route: anim/shape-key-set
    """
    object_name = params.get("object_name")
    key_name    = params.get("key_name")
    value       = params.get("value")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not key_name:
        return error_response("Parameter 'key_name' is required.")
    if value is None:
        return error_response("Parameter 'value' is required.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    if obj.data.shape_keys is None:
        return error_response(
            f"Object '{object_name}' has no shape keys."
        )

    key_block = obj.data.shape_keys.key_blocks.get(key_name)
    if key_block is None:
        return error_response(
            f"Shape key '{key_name}' not found on object '{object_name}'."
        )

    try:
        key_block.value = float(value)
        return ok_response({
            "object_name": obj.name,
            "key_name":    key_block.name,
            "value":       key_block.value,
        })
    except Exception as e:
        return error_response(
            f"Failed to set shape key value on '{object_name}'/'{key_name}': {e}"
        )


def _handle_anim_shape_key_keyframe(params):
    """
    Set a shape key's value and insert a keyframe for it at the given frame.
    Route: anim/shape-key-keyframe
    """
    object_name = params.get("object_name")
    key_name    = params.get("key_name")
    frame       = params.get("frame")
    value       = params.get("value")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not key_name:
        return error_response("Parameter 'key_name' is required.")
    if frame is None:
        return error_response("Parameter 'frame' is required.")
    if value is None:
        return error_response("Parameter 'value' is required.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    if obj.data.shape_keys is None:
        return error_response(
            f"Object '{object_name}' has no shape keys."
        )

    key_block = obj.data.shape_keys.key_blocks.get(key_name)
    if key_block is None:
        return error_response(
            f"Shape key '{key_name}' not found on object '{object_name}'."
        )

    try:
        key_block.value = float(value)
        key_block.keyframe_insert(data_path="value", frame=float(frame))

        return ok_response({
            "object_name": obj.name,
            "key_name":    key_block.name,
            "value":       key_block.value,
            "frame":       float(frame),
        })
    except Exception as e:
        return error_response(
            f"Failed to insert shape key keyframe on '{object_name}'/'{key_name}': {e}"
        )


def _handle_anim_driver_add(params):
    """
    Add a driver with a Python expression to a data path on an object.
    Route: anim/driver-add
    """
    object_name = params.get("object_name")
    data_path   = params.get("data_path")
    expression  = params.get("expression")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not data_path:
        return error_response("Parameter 'data_path' is required.")
    if expression is None:
        return error_response("Parameter 'expression' is required.")

    obj, err = _get_object(object_name)
    if err:
        return err

    try:
        fcurve = obj.driver_add(data_path)
        # driver_add may return a list for vector properties; handle both cases
        if isinstance(fcurve, (list, tuple)):
            for fc in fcurve:
                fc.driver.type = "SCRIPTED"
                fc.driver.expression = str(expression)
            result_expression = str(expression)
        else:
            fcurve.driver.type = "SCRIPTED"
            fcurve.driver.expression = str(expression)
            result_expression = fcurve.driver.expression

        return ok_response({
            "object_name": obj.name,
            "data_path":   data_path,
            "expression":  result_expression,
        })
    except Exception as e:
        return error_response(
            f"Failed to add driver on '{object_name}' path '{data_path}': {e}"
        )


# â”€â”€â”€ Register routes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

register_handler("anim", "insert-keyframe",   _handle_anim_insert_keyframe)
register_handler("anim", "delete-keyframe",   _handle_anim_delete_keyframe)
register_handler("anim", "set-frame-range",   _handle_anim_set_frame_range)
register_handler("anim", "set-current-frame", _handle_anim_set_current_frame)
register_handler("anim", "set-interpolation", _handle_anim_set_interpolation)
register_handler("anim", "create-action",     _handle_anim_create_action)
register_handler("anim", "assign-action",     _handle_anim_assign_action)
register_handler("anim", "list-actions",      _handle_anim_list_actions)
register_handler("anim", "bake",              _handle_anim_bake)
register_handler("anim", "nla-push",          _handle_anim_nla_push)
register_handler("anim", "shape-key-add",     _handle_anim_shape_key_add)
register_handler("anim", "shape-key-set",     _handle_anim_shape_key_set)
register_handler("anim", "shape-key-keyframe",_handle_anim_shape_key_keyframe)
register_handler("anim", "driver-add",        _handle_anim_driver_add)

"""
Advanced constraint handlers for Blender MCP Bridge.
Provides: constraint/add, constraint/remove, constraint/configure,
          constraint/set-target, constraint/set-influence, constraint/list
"""

import bpy
from ...utils.response import ok_response, error_response, not_found, coerce_value
from ...utils.context_helpers import ensure_context_for_object, is_valid_rna_property
from .. import register_handler


# ─── Supported constraint types ─────────────────────────────────────────────────

_SUPPORTED_TYPES = {
    "COPY_LOCATION",
    "COPY_ROTATION",
    "COPY_SCALE",
    "TRACK_TO",
    "DAMPED_TRACK",
    "LIMIT_LOCATION",
    "LIMIT_ROTATION",
    "LIMIT_SCALE",
    "FOLLOW_PATH",
    "CLAMP_TO",
    "CHILD_OF",
    "FLOOR",
}


# ─── Helpers ─────────────────────────────────────────────────────────────────────

def _get_object(name):
    """Return (obj, None) or (None, error_response) for any object."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, not_found(name)
    return obj, None


def _get_constraint(obj, constraint_name):
    """Return (constraint, None) or (None, error_response)."""
    constraint = obj.constraints.get(constraint_name)
    if constraint is None:
        return None, error_response(
            f"Constraint '{constraint_name}' not found on '{obj.name}'."
        )
    return constraint, None


# ─── Handlers ────────────────────────────────────────────────────────────────────

def _handle_constraint_add(params):
    """
    Add a constraint to an object.
    Route: constraint/add
    """
    object_name = params.get("object_name")
    constraint_type = params.get("type")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not constraint_type:
        return error_response("Parameter 'type' is required.")
    if constraint_type not in _SUPPORTED_TYPES:
        return error_response(
            f"Unsupported constraint type '{constraint_type}'. "
            f"Valid types: {', '.join(sorted(_SUPPORTED_TYPES))}."
        )

    try:
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return not_found(object_name)

        constraint = obj.constraints.new(type=constraint_type)

        return ok_response({
            "object_name": obj.name,
            "constraint_name": constraint.name,
            "type": constraint_type,
        })
    except Exception as e:
        return error_response(f"Failed to add constraint: {e}")


def _handle_constraint_remove(params):
    """
    Remove a named constraint from an object.
    Route: constraint/remove
    """
    object_name = params.get("object_name")
    constraint_name = params.get("constraint_name")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not constraint_name:
        return error_response("Parameter 'constraint_name' is required.")

    try:
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return not_found(object_name)

        constraint = obj.constraints.get(constraint_name)
        if constraint is None:
            return error_response(
                f"Constraint '{constraint_name}' not found on '{object_name}'."
            )

        obj.constraints.remove(constraint)

        return ok_response({
            "object_name": object_name,
            "removed_constraint": constraint_name,
        })
    except Exception as e:
        return error_response(f"Failed to remove constraint: {e}")


def _handle_constraint_configure(params):
    """
    Set properties on an existing constraint via a params dictionary.
    Route: constraint/configure
    """
    object_name = params.get("object_name")
    constraint_name = params.get("constraint_name")
    configure_params = params.get("params")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not constraint_name:
        return error_response("Parameter 'constraint_name' is required.")
    if configure_params is None or not isinstance(configure_params, dict):
        return error_response("Parameter 'params' must be a non-empty object.")

    try:
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return not_found(object_name)

        constraint, err = _get_constraint(obj, constraint_name)
        if err:
            return err

        applied = []
        skipped = []

        for key, value in configure_params.items():
            if is_valid_rna_property(constraint, key):
                try:
                    current = getattr(constraint, key)
                    coerced = coerce_value(current, value)
                    setattr(constraint, key, coerced)
                    applied.append(key)
                except (AttributeError, TypeError, ValueError) as set_err:
                    skipped.append(f"{key} (set error: {set_err})")
            else:
                skipped.append(f"{key} (not a valid RNA property)")

        return ok_response({
            "object_name": object_name,
            "constraint_name": constraint_name,
            "type": constraint.type,
            "applied": applied,
            "skipped": skipped,
        })
    except Exception as e:
        return error_response(f"Failed to configure constraint: {e}")


def _handle_constraint_set_target(params):
    """
    Assign a target object (and optional target bone) to a constraint.
    Route: constraint/set-target
    """
    object_name = params.get("object_name")
    constraint_name = params.get("constraint_name")
    target_object = params.get("target_object")
    target_bone = params.get("target_bone")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not constraint_name:
        return error_response("Parameter 'constraint_name' is required.")
    if not target_object:
        return error_response("Parameter 'target_object' is required.")

    try:
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return not_found(object_name)

        constraint, err = _get_constraint(obj, constraint_name)
        if err:
            return err

        if not hasattr(constraint, "target"):
            return error_response(
                f"Constraint '{constraint_name}' (type: {constraint.type}) "
                "does not support a target object."
            )

        target = bpy.data.objects.get(target_object)
        if target is None:
            return not_found(target_object)

        constraint.target = target

        resolved_bone = None
        if target_bone:
            if hasattr(constraint, "subtarget"):
                constraint.subtarget = target_bone
                resolved_bone = target_bone
            else:
                # Not an error — just report it was skipped
                resolved_bone = None

        return ok_response({
            "object_name": object_name,
            "constraint_name": constraint_name,
            "type": constraint.type,
            "target_object": target.name,
            "target_bone": resolved_bone,
        })
    except Exception as e:
        return error_response(f"Failed to set constraint target: {e}")


def _handle_constraint_set_influence(params):
    """
    Set the influence value of a constraint (clamped to 0.0–1.0).
    Route: constraint/set-influence
    """
    object_name = params.get("object_name")
    constraint_name = params.get("constraint_name")
    influence = params.get("influence")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not constraint_name:
        return error_response("Parameter 'constraint_name' is required.")
    if influence is None:
        return error_response("Parameter 'influence' is required.")

    try:
        influence = float(influence)
    except (TypeError, ValueError):
        return error_response("Parameter 'influence' must be a number.")

    try:
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return not_found(object_name)

        constraint, err = _get_constraint(obj, constraint_name)
        if err:
            return err

        clamped = max(0.0, min(1.0, influence))
        constraint.influence = clamped

        return ok_response({
            "object_name": object_name,
            "constraint_name": constraint_name,
            "type": constraint.type,
            "influence": clamped,
        })
    except Exception as e:
        return error_response(f"Failed to set constraint influence: {e}")


def _handle_constraint_list(params):
    """
    List all constraints on an object.
    Route: constraint/list
    """
    object_name = params.get("object_name")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")

    try:
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return not_found(object_name)

        constraints = []
        for c in obj.constraints:
            info = {
                "name": c.name,
                "type": c.type,
                "influence": round(c.influence, 6),
                "mute": c.mute,
                "target": c.target.name if hasattr(c, "target") and c.target else None,
            }
            # Include subtarget (bone) if present and set
            if hasattr(c, "subtarget") and c.subtarget:
                info["target_bone"] = c.subtarget
            constraints.append(info)

        return ok_response({
            "object_name": obj.name,
            "constraints": constraints,
            "count": len(constraints),
        })
    except Exception as e:
        return error_response(f"Failed to list constraints: {e}")


# ─── Register routes ─────────────────────────────────────────────────────────────

register_handler("constraint", "add",           _handle_constraint_add)
register_handler("constraint", "remove",         _handle_constraint_remove)
register_handler("constraint", "configure",      _handle_constraint_configure)
register_handler("constraint", "set-target",     _handle_constraint_set_target)
register_handler("constraint", "set-influence",  _handle_constraint_set_influence)
register_handler("constraint", "list",           _handle_constraint_list)

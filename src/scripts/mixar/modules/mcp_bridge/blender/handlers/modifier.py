"""
Modifier handlers for Blender MCP Bridge.
Provides modifier operations: list, add, remove, set_property, apply.
"""

import bpy
from ..utils.response import ok_response, error_response, not_found, coerce_value
from ..utils.context_helpers import (
    ensure_context_for_object,
    temp_override,
    safe_operator_call,
    is_valid_rna_property,
)
from . import register_handler


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _get_object(name):
    """Return (obj, None) or (None, error_response) for the named object."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, not_found(name)
    return obj, None


def _get_modifier(obj, modifier_name):
    """Return (mod, None) or (None, error_response) for the named modifier."""
    mod = obj.modifiers.get(modifier_name)
    if mod is None:
        return None, error_response(
            f"Object '{obj.name}' has no modifier named '{modifier_name}'."
        )
    return mod, None


# ─── Handlers ──────────────────────────────────────────────────────────────────

def _handle_list(params):
    """
    List all modifiers on an object.

    Route: POST /api/modifier/list

    Params:
        object_name (str)

    Returns:
        Array of {name, type, show_viewport, show_render}.
    """
    try:
        object_name = params.get("object_name")
        if not object_name:
            return error_response("Parameter 'object_name' is required.")

        obj, err = _get_object(object_name)
        if err:
            return err

        modifiers = [
            {
                "name": mod.name,
                "type": mod.type,
                "show_viewport": mod.show_viewport,
                "show_render": mod.show_render,
            }
            for mod in obj.modifiers
        ]
        return ok_response(modifiers)
    except Exception as e:
        return error_response(f"Failed to list modifiers: {e}")


def _handle_add(params):
    """
    Add a modifier to an object.

    Route: POST /api/modifier/add

    Params:
        object_name (str)
        type (str): Modifier type (e.g. 'SUBSURF', 'MIRROR').
        name (str, optional): Custom modifier name.
        properties (dict, optional): Modifier attribute key/value pairs to set after creation.
    """
    try:
        object_name = params.get("object_name")
        mod_type = params.get("type")
        mod_name = params.get("name") or mod_type
        properties = params.get("properties") or {}

        if not object_name:
            return error_response("Parameter 'object_name' is required.")
        if not mod_type:
            return error_response("Parameter 'type' is required.")

        obj, err = _get_object(object_name)
        if err:
            return err

        mod = obj.modifiers.new(name=mod_name, type=mod_type)
        if mod is None:
            return error_response(
                f"Failed to add modifier of type '{mod_type}' to '{object_name}'. "
                "Check that the type name is valid."
            )

        # Apply any extra properties and track results
        applied_properties = {}
        failed_properties = {}
        for attr, value in properties.items():
            if not is_valid_rna_property(mod, attr):
                failed_properties[attr] = f"'{attr}' is not a valid RNA property for {mod_type}"
                continue
            try:
                current = getattr(mod, attr, None)
                if current is not None:
                    value = coerce_value(current, value)
                setattr(mod, attr, value)
                # Read back the actual value after assignment
                applied_properties[attr] = getattr(mod, attr)
            except AttributeError:
                failed_properties[attr] = f"'{attr}' is not a valid attribute for {mod_type}"
            except Exception as exc:
                failed_properties[attr] = f"Could not set '{attr}': {exc}"

        result = {
            "object_name": obj.name,
            "modifier_name": mod.name,
            "type": mod.type,
            "applied_properties": applied_properties,
            "failed_properties": failed_properties,
        }

        return ok_response(result)
    except Exception as e:
        return error_response(f"Failed to add modifier: {e}")


def _handle_remove(params):
    """
    Remove a modifier from an object.

    Route: POST /api/modifier/remove

    Params:
        object_name (str)
        modifier_name (str)
    """
    try:
        object_name = params.get("object_name")
        modifier_name = params.get("modifier_name")

        if not object_name:
            return error_response("Parameter 'object_name' is required.")
        if not modifier_name:
            return error_response("Parameter 'modifier_name' is required.")

        obj, err = _get_object(object_name)
        if err:
            return err

        mod, err = _get_modifier(obj, modifier_name)
        if err:
            return err

        obj.modifiers.remove(mod)
        return ok_response({"object": obj.name, "object_name": obj.name, "removed": modifier_name})
    except Exception as e:
        return error_response(f"Failed to remove modifier: {e}")


def _handle_set_property(params):
    """
    Set a single property on an existing modifier.

    Route: POST /api/modifier/set-property

    Params:
        object_name (str)
        modifier_name (str)
        property (str): Python attribute name on the modifier.
        value: New attribute value.
    """
    try:
        object_name = params.get("object_name")
        modifier_name = params.get("modifier_name")
        prop = params.get("property")
        value = params.get("value")

        if not object_name:
            return error_response("Parameter 'object_name' is required.")
        if not modifier_name:
            return error_response("Parameter 'modifier_name' is required.")
        if not prop:
            return error_response("Parameter 'property' is required.")
        if value is None:
            return error_response("Parameter 'value' is required.")

        obj, err = _get_object(object_name)
        if err:
            return err

        mod, err = _get_modifier(obj, modifier_name)
        if err:
            return err

        if not is_valid_rna_property(mod, prop):
            return error_response(
                f"Modifier '{modifier_name}' (type {mod.type}) has no RNA property '{prop}'."
            )

        current = getattr(mod, prop)
        value = coerce_value(current, value)
        setattr(mod, prop, value)
        return ok_response({
            "object": obj.name,
            "object_name": obj.name,
            "modifier": mod.name,
            "property": prop,
            "value": value,
        })
    except Exception as e:
        return error_response(f"Failed to set modifier property: {e}")


def _handle_apply(params):
    """
    Apply (collapse) a modifier onto the mesh.

    Route: POST /api/modifier/apply

    Params:
        object_name (str)
        modifier_name (str)

    Notes:
        Requires a context override to execute bpy.ops.object.modifier_apply.
        The object is selected and activated before the call.
    """
    try:
        object_name = params.get("object_name")
        modifier_name = params.get("modifier_name")

        if not object_name:
            return error_response("Parameter 'object_name' is required.")
        if not modifier_name:
            return error_response("Parameter 'modifier_name' is required.")

        obj, err = _get_object(object_name)
        if err:
            return err

        # Verify the modifier exists before attempting to apply
        _, err = _get_modifier(obj, modifier_name)
        if err:
            return err

        if obj.type != "MESH":
            return error_response(
                f"Object '{object_name}' is of type '{obj.type}'. "
                "modifier_apply is only supported on MESH objects."
            )

        # Select/activate the object so the operator has the right context
        ensure_context_for_object(obj)

        with temp_override("VIEW_3D"):
            success, result = safe_operator_call(
                bpy.ops.object.modifier_apply,
                modifier=modifier_name,
            )

        if not success:
            return error_response(f"modifier_apply operator failed: {result}")

        return ok_response({"object": obj.name, "object_name": obj.name, "applied": modifier_name})
    except Exception as e:
        return error_response(f"Failed to apply modifier: {e}")


# ─── Register routes ────────────────────────────────────────────────────────────

register_handler("modifier", "list", _handle_list)
register_handler("modifier", "add", _handle_add)
register_handler("modifier", "remove", _handle_remove)
register_handler("modifier", "set-property", _handle_set_property)
register_handler("modifier", "apply", _handle_apply)

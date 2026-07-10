"""
Material handlers for Blender MCP Bridge.
Provides material operations: list, create, assign, get_properties, set_property.
"""

import bpy
from ..utils.response import ok_response, error_response, not_found, coerce_value
from ..utils.compat import get_principled_input_name
from . import register_handler


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _find_principled(mat):
    """Return the first Principled BSDF node in a material's node tree, or None."""
    if not mat.use_nodes or mat.node_tree is None:
        return None
    for node in mat.node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            return node
    return None


def _input_value(inp):
    """Serialize a node socket default_value to a JSON-safe type."""
    val = inp.default_value
    # Color / vector sockets expose a sequence-like object
    try:
        return list(val)
    except TypeError:
        return val


def _set_input(principled, canonical_name, value):
    """
    Set the default_value of a Principled BSDF input by canonical (4.x) name.
    Translates to 3.x name automatically via get_principled_input_name().
    """
    actual_name = get_principled_input_name(canonical_name)
    inp = principled.inputs.get(actual_name)
    if inp is None:
        raise KeyError(f"Principled BSDF has no input '{actual_name}' (requested '{canonical_name}')")
    try:
        # Color inputs: assign element-by-element so Blender's colour type is preserved
        if isinstance(value, (list, tuple)):
            for i, v in enumerate(value):
                inp.default_value[i] = float(v)
        else:
            value = coerce_value(inp.default_value, value)
            inp.default_value = value
    except Exception as e:
        raise ValueError(f"Could not set input '{actual_name}' to {value!r}: {e}") from e


# ─── Handlers ──────────────────────────────────────────────────────────────────

def _handle_list(params):
    """
    List all materials in the current file.

    Route: POST /api/material/list

    Returns:
        Array of {name, users, use_nodes, base_color (if Principled BSDF present)}.
    """
    try:
        materials = []
        for mat in bpy.data.materials:
            entry = {
                "name": mat.name,
                "users": mat.users,
                "use_nodes": mat.use_nodes,
            }
            principled = _find_principled(mat)
            if principled is not None:
                base_color_input = principled.inputs.get(
                    get_principled_input_name("Base Color")
                )
                if base_color_input is not None:
                    entry["base_color"] = list(base_color_input.default_value)
            materials.append(entry)
        return ok_response(materials)
    except Exception as e:
        return error_response(f"Failed to list materials: {e}")


def _handle_create(params):
    """
    Create a new material with optional Principled BSDF properties.

    Route: POST /api/material/create

    Params:
        name (str): Material name.
        base_color (list, optional): [r, g, b, a]
        metallic (float, optional)
        roughness (float, optional)
        specular (float, optional): Maps to Specular IOR Level.
        emission_color (list, optional): [r, g, b, a]
        emission_strength (float, optional)
        alpha (float, optional)
    """
    try:
        name = params.get("name")
        if not name:
            return error_response("Parameter 'name' is required.")

        mat = bpy.data.materials.new(name=name)
        mat.use_nodes = True

        principled = _find_principled(mat)
        if principled is None:
            return error_response(f"Failed to find Principled BSDF node in newly created material '{name}'.")

        # Property map: param key → canonical 4.x Principled BSDF input name
        prop_map = {
            "base_color": "Base Color",
            "metallic": "Metallic",
            "roughness": "Roughness",
            "specular": "Specular IOR Level",
            "emission_color": "Emission Color",
            "emission_strength": "Emission Strength",
            "alpha": "Alpha",
        }

        for param_key, canonical_name in prop_map.items():
            value = params.get(param_key)
            if value is not None:
                _set_input(principled, canonical_name, value)

        # Read back actual values for confirmation
        base_color_input = principled.inputs.get(get_principled_input_name("Base Color"))
        metallic_input = principled.inputs.get(get_principled_input_name("Metallic"))
        roughness_input = principled.inputs.get(get_principled_input_name("Roughness"))

        return ok_response({
            "name": mat.name,
            "use_nodes": mat.use_nodes,
            "base_color": _input_value(base_color_input) if base_color_input else None,
            "metallic": _input_value(metallic_input) if metallic_input else None,
            "roughness": _input_value(roughness_input) if roughness_input else None,
        })
    except Exception as e:
        return error_response(f"Failed to create material: {e}")


def _handle_assign(params):
    """
    Assign a material to an object.

    Route: POST /api/material/assign

    Params:
        object_name (str)
        material_name (str)
        slot (int, optional): 0-based slot index. Appends if omitted.
    """
    try:
        object_name = params.get("object_name")
        material_name = params.get("material_name")
        slot = params.get("slot")

        if not object_name:
            return error_response("Parameter 'object_name' is required.")
        if not material_name:
            return error_response("Parameter 'material_name' is required.")

        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return not_found(object_name)

        mat = bpy.data.materials.get(material_name)
        if mat is None:
            return not_found(material_name, "Material")

        if slot is not None:
            # Ensure enough slots exist
            while len(obj.material_slots) <= slot:
                obj.data.materials.append(None)
            obj.material_slots[slot].material = mat
            assigned_slot = slot
        else:
            # Append as a new slot
            obj.data.materials.append(mat)
            assigned_slot = len(obj.material_slots) - 1

        return ok_response({
            "object_name": obj.name,
            "material_name": mat.name,
            "slot": assigned_slot,
        })
    except Exception as e:
        return error_response(f"Failed to assign material: {e}")


def _handle_get_properties(params):
    """
    Get all Principled BSDF input values for a named material.

    Route: POST /api/material/get-properties

    Params:
        name (str): Material name.

    Returns:
        {name, properties: {input_name: value, ...}}
    """
    try:
        name = params.get("name")
        if not name:
            return error_response("Parameter 'name' is required.")

        mat = bpy.data.materials.get(name)
        if mat is None:
            return not_found(name, "Material")

        principled = _find_principled(mat)
        if principled is None:
            return error_response(
                f"Material '{name}' has no Principled BSDF node. "
                "Enable node shading and add a Principled BSDF first."
            )

        properties = {}
        for inp in principled.inputs:
            properties[inp.name] = _input_value(inp)

        return ok_response({"name": mat.name, "properties": properties})
    except Exception as e:
        return error_response(f"Failed to get material properties: {e}")


def _handle_set_property(params):
    """
    Set a single Principled BSDF input on a named material.

    Route: POST /api/material/set-property

    Params:
        name (str): Material name.
        property (str): Canonical 4.x Principled BSDF input name.
        value: Color array [r, g, b, a] or scalar float.
    """
    try:
        name = params.get("name")
        prop = params.get("property")
        value = params.get("value")

        if not name:
            return error_response("Parameter 'name' is required.")
        if not prop:
            return error_response("Parameter 'property' is required.")
        if value is None:
            return error_response("Parameter 'value' is required.")

        mat = bpy.data.materials.get(name)
        if mat is None:
            return not_found(name, "Material")

        principled = _find_principled(mat)
        if principled is None:
            return error_response(
                f"Material '{name}' has no Principled BSDF node. "
                "Enable node shading and add a Principled BSDF first."
            )

        _set_input(principled, prop, value)

        return ok_response({"name": mat.name, "property": prop, "value": value})
    except KeyError as e:
        return error_response(str(e))
    except Exception as e:
        return error_response(f"Failed to set material property: {e}")


# ─── Register routes ────────────────────────────────────────────────────────────

register_handler("material", "list", _handle_list)
register_handler("material", "create", _handle_create)
register_handler("material", "assign", _handle_assign)
register_handler("material", "get-properties", _handle_get_properties)
register_handler("material", "set-property", _handle_set_property)

"""
Material extended handlers for Blender MCP Bridge.
Provides: material/edit, material/add-texture, material/remove
"""

import bpy
from ...utils.response import ok_response, error_response, not_found, coerce_value
from ...utils.compat import get_principled_input_name
from .. import register_handler


# ─── Helpers ────────────────────────────────────────────────────────────────────

def _find_principled(mat):
    """Return the first Principled BSDF node in mat, or None."""
    if not mat.use_nodes or not mat.node_tree:
        return None
    for node in mat.node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            return node
    return None


# ─── Handlers ───────────────────────────────────────────────────────────────────

def _handle_material_edit(params):
    """
    Edit Principled BSDF shader inputs on an existing material.
    Route: POST /api/material/edit
    """
    name       = params.get("name")
    properties = params.get("properties", {})

    if not name:
        return error_response("Parameter 'name' is required.")
    if not isinstance(properties, dict):
        return error_response("Parameter 'properties' must be an object (key-value pairs).")

    mat = bpy.data.materials.get(name)
    if mat is None:
        return not_found(name, "Material")

    if not mat.use_nodes or not mat.node_tree:
        return error_response(f"Material '{name}' does not use nodes.")

    principled = _find_principled(mat)
    if principled is None:
        return error_response(
            f"Material '{name}' has no Principled BSDF node."
        )

    try:
        changed  = []
        skipped  = []
        errors   = []

        # Suggestions for common unsupported property paths
        _ALTERNATIVES = {
            "color_ramp": "Use blender_node_colorramp_set instead.",
            "node_tree":  "Use blender_node_set_value or blender_node_connect to manipulate nodes directly.",
            "mapping":    "Use blender_node_set_value to set Mapping node inputs.",
        }

        for key, value in properties.items():
            # Detect unsupported dot-notation or bracket-notation paths
            if "." in key or "[" in key:
                # Try to find a helpful suggestion based on the path prefix
                prefix = key.split(".")[0].split("[")[0]
                suggestion = _ALTERNATIVES.get(prefix, "Use the node tools (blender_node_*) to manipulate complex node properties.")
                errors.append(
                    f"Property '{key}' uses dot/bracket-notation which is not supported "
                    f"by material/edit. {suggestion}"
                )
                skipped.append(key)
                continue

            input_name = get_principled_input_name(key)
            inp = principled.inputs.get(input_name)
            if inp is None:
                errors.append(
                    f"Property '{key}' (resolved to '{input_name}') is not a recognised "
                    f"Principled BSDF input. Available inputs: "
                    f"{', '.join(i.name for i in principled.inputs)}."
                )
                skipped.append(key)
                continue
            try:
                if isinstance(value, (list, tuple)):
                    inp.default_value = tuple(value)
                else:
                    inp.default_value = coerce_value(inp.default_value, value)
                changed.append(input_name)
            except Exception as set_err:
                errors.append(
                    f"Failed to set '{key}' (input '{input_name}'): {set_err}"
                )
                skipped.append(f"{key} ({set_err})")

        if not changed and errors:
            return error_response(
                f"All properties failed for material '{mat.name}': "
                + "; ".join(errors)
            )

        return ok_response({
            "material": mat.name,
            "changed":  changed,
            "skipped":  skipped,
            "errors":   errors,
        })
    except Exception as e:
        return error_response(f"Failed to edit material '{name}': {e}")


def _handle_material_add_texture(params):
    """
    Load an image and connect it as a texture to a Principled BSDF channel.
    Route: POST /api/material/add-texture
    """
    material_name = params.get("material_name")
    channel       = params.get("channel")
    image_path    = params.get("image_path")

    if not material_name:
        return error_response("Parameter 'material_name' is required.")
    if not channel:
        return error_response("Parameter 'channel' is required.")
    if not image_path:
        return error_response("Parameter 'image_path' is required.")

    mat = bpy.data.materials.get(material_name)
    if mat is None:
        return not_found(material_name, "Material")

    # Ensure nodes are enabled
    if not mat.use_nodes:
        mat.use_nodes = True

    principled = _find_principled(mat)
    if principled is None:
        return error_response(
            f"Material '{material_name}' has no Principled BSDF node."
        )

    # Resolve the correct input name for the current Blender version
    input_name = get_principled_input_name(channel)
    target_input = principled.inputs.get(input_name)
    if target_input is None:
        return error_response(
            f"Principled BSDF has no input '{input_name}' (requested channel: '{channel}')."
        )

    try:
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links

        # Create and configure the Image Texture node
        tex_node = nodes.new("ShaderNodeTexImage")

        # Load (or reuse) the image
        img = bpy.data.images.get(image_path)
        if img is None:
            img = bpy.data.images.load(image_path)
        tex_node.image = img

        is_normal = channel.lower() == "normal"

        if is_normal:
            # For normal maps: texture → Normal Map node → Principled Normal input
            tex_node.image.colorspace_settings.name = "Non-Color"
            normal_node = nodes.new("ShaderNodeNormalMap")
            links.new(tex_node.outputs["Color"], normal_node.inputs["Color"])
            links.new(normal_node.outputs["Normal"], target_input)
        else:
            links.new(tex_node.outputs["Color"], target_input)

        return ok_response({
            "material":    mat.name,
            "channel":     channel,
            "input_name":  input_name,
            "image":       img.name,
            "is_normal":   is_normal,
        })
    except Exception as e:
        return error_response(
            f"Failed to add texture to material '{material_name}' channel '{channel}': {e}"
        )


def _handle_material_remove(params):
    """
    Remove a material data-block from the Blender file.
    Route: POST /api/material/remove
    """
    name = params.get("name")

    if not name:
        return error_response("Parameter 'name' is required.")

    mat = bpy.data.materials.get(name)
    if mat is None:
        return not_found(name, "Material")

    try:
        bpy.data.materials.remove(mat)
        return ok_response({"removed": name})
    except Exception as e:
        return error_response(f"Failed to remove material '{name}': {e}")


# ─── Register routes ─────────────────────────────────────────────────────────────

register_handler("material", "edit",        _handle_material_edit)
register_handler("material", "add-texture", _handle_material_add_texture)
register_handler("material", "remove",      _handle_material_remove)

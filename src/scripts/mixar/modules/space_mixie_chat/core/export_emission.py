# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Export-time bake of a MASKED emission strength for glTF.

glTF has an emissive colour texture and one emissive strength, never a
strength texture. A material whose Emission Strength is driven by a mask
(``mask`` or ``mask × k`` through a Math Multiply) and whose Emission Color
is one colour image therefore exported as ``colour × k`` everywhere: the
boss's whole armour glowed instead of its lava cracks.

``baked_emission_masks`` fixes that for the duration of one glTF export.
For each such material it builds a temporary image ``colour × mask`` (in
linear light, stored sRGB), feeds it to Emission Color through a temporary
Image Texture node on the mask's own UV input, unlinks Emission Strength
and sets it to ``k``. On exit the links, the strength value and the node
are restored and the image is removed from ``bpy.data``.

Conservative by design: a material is skipped (and named in the returned
notes) unless the mask and the colour each resolve to exactly one image,
the mask's UVs are the mesh's only UV map or the one the colour reads, and
both images hold pixels. Main thread only.
"""

from __future__ import annotations

from contextlib import contextmanager

import bpy

LUMA = (0.2126, 0.7152, 0.0722)
TEMP_PREFIX = "mixar_export_emission_"


def _linked_from(socket):
    links = getattr(socket, "links", ()) or ()
    return (links[0].from_node, links[0].from_socket) if links else (None, None)


def _bsdf(material):
    tree = getattr(material, "node_tree", None)
    for node in getattr(tree, "nodes", ()) or ():
        if node.type == 'OUTPUT_MATERIAL' and getattr(node, "is_active_output", True):
            node, _socket = _linked_from(node.inputs.get("Surface"))
            return node if getattr(node, "type", "") == 'BSDF_PRINCIPLED' else None
    return None


def strength_mask(bsdf):
    """``(mask_node, mask_socket, k)`` when Emission Strength = mask (× k)."""
    node, socket = _linked_from(bsdf.inputs.get("Emission Strength"))
    if getattr(node, "type", "") == 'TEX_IMAGE':
        return node, socket, 1.0
    if getattr(node, "type", "") != 'MATH' or node.operation != 'MULTIPLY' or node.use_clamp:
        return None
    first, second = node.inputs[0], node.inputs[1]
    for linked, constant in ((first, second), (second, first)):
        source, source_socket = _linked_from(linked)
        if getattr(source, "type", "") == 'TEX_IMAGE' and not constant.is_linked:
            return source, source_socket, float(constant.default_value)
    return None


def _upstream_images(socket, stack=(), seen=None):
    """Images reaching ``socket``, following group outputs/inputs exactly."""
    seen = set() if seen is None else seen
    node, from_socket = _linked_from(socket)
    if node is None or (id(node), from_socket.identifier) in seen:
        return []
    seen.add((id(node), from_socket.identifier))
    if node.type == 'TEX_IMAGE':
        return [node] if node.image is not None else []
    if node.type == 'GROUP' and node.node_tree is not None:
        outputs = [n for n in node.node_tree.nodes if n.type == 'GROUP_OUTPUT']
        inner = [s for n in outputs for s in n.inputs if s.identifier == from_socket.identifier]
        return [img for s in inner for img in _upstream_images(s, stack + (node,), seen)]
    if node.type == 'GROUP_INPUT':
        if not stack:
            return []
        outer = [s for s in stack[-1].inputs if s.identifier == from_socket.identifier]
        return [img for s in outer for img in _upstream_images(s, stack[:-1], seen)]
    return [img for s in node.inputs for img in _upstream_images(s, stack, seen)]


def _uv_name(image_node):
    node, _socket = _linked_from(image_node.inputs.get("Vector"))
    return getattr(node, "uv_map", "") if getattr(node, "type", "") == 'UVMAP' else ""


def _pixels(image):
    import numpy as np
    w, h = image.size
    if not w or not h:
        return None
    data = np.empty(w * h * 4, np.float32)
    image.pixels.foreach_get(data)
    return data.reshape(h, w, 4)


def _to_linear(rgb):
    import numpy as np
    return np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)


def _to_srgb(rgb):
    import numpy as np
    rgb = np.clip(rgb, 0.0, 1.0)
    return np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * rgb ** (1 / 2.4) - 0.055)


def baked_pixels(colour, colour_srgb: bool, mask, mask_socket: str, mask_srgb: bool):
    """``colour × mask`` as sRGB RGBA pixels (numpy, h × w × 4)."""
    import numpy as np
    if mask.shape[:2] != colour.shape[:2]:  # nearest resample onto the colour grid
        ys = (np.arange(colour.shape[0]) * mask.shape[0] // colour.shape[0])
        xs = (np.arange(colour.shape[1]) * mask.shape[1] // colour.shape[1])
        mask = mask[ys][:, xs]
    rgb = colour[..., :3]
    rgb = _to_linear(rgb) if colour_srgb else rgb
    if mask_socket == "Alpha":
        weight = mask[..., 3]
    else:
        m = _to_linear(mask[..., :3]) if mask_srgb else mask[..., :3]
        weight = m @ np.asarray(LUMA, np.float32)
    out = np.empty_like(colour)
    out[..., :3] = _to_srgb(rgb * weight[..., None])
    out[..., 3] = 1.0
    return out


def _uv_ok(meshes, mask_node, colour_node) -> bool:
    mask_uv, colour_uv = _uv_name(mask_node), _uv_name(colour_node)
    for mesh in meshes:
        layers = [uv.name for uv in getattr(mesh.data, "uv_layers", ())]
        if len(layers) > 1 and mask_uv != colour_uv:
            return False
    return True


def _plan(material, meshes):
    """``(bsdf, mask_node, mask_socket, k, colour_node)`` or a skip reason."""
    bsdf = _bsdf(material)
    if bsdf is None or not bsdf.inputs["Emission Strength"].is_linked:
        return None
    found = strength_mask(bsdf)
    if found is None:
        return "emission strength is not an image mask (× constant)"
    mask_node, mask_socket, k = found
    colours = {id(n.image): n for n in _upstream_images(bsdf.inputs["Emission Color"])
               if n.image.colorspace_settings.name != 'Non-Color'}
    if len(colours) != 1:
        return "emission colour is not one colour image"
    colour_node = next(iter(colours.values()))
    if not _uv_ok(meshes, mask_node, colour_node):
        return "the mask and the colour use different UV maps"
    return bsdf, mask_node, mask_socket.name, k, colour_node


def _srgb(image) -> bool:
    return image.colorspace_settings.name == 'sRGB' and not image.is_float


@contextmanager
def baked_emission_masks(meshes):
    """Bake masked emission for every material of ``meshes``; yields
    ``(baked_material_names, notes)``."""
    by_material = {}
    for obj in meshes:
        for material in getattr(obj.data, "materials", ()) or ():
            if material is not None:
                by_material.setdefault(material.name, (material, []))[1].append(obj)
    restores, images, baked, notes = [], [], [], []
    try:
        for name, (material, users) in by_material.items():
            plan = _plan(material, users)
            if plan is None:
                continue
            if isinstance(plan, str):
                notes.append(f"{name}: masked emission not baked ({plan})")
                continue
            bsdf, mask_node, mask_socket, k, colour_node = plan
            colour, mask = _pixels(colour_node.image), _pixels(mask_node.image)
            if colour is None or mask is None:
                notes.append(f"{name}: masked emission not baked (an image has no pixels)")
                continue
            pixels = baked_pixels(colour, _srgb(colour_node.image), mask, mask_socket,
                                  _srgb(mask_node.image))
            h, w = pixels.shape[:2]
            image = bpy.data.images.new(f"{TEMP_PREFIX}{name}", w, h, alpha=False)
            images.append(image)
            image.colorspace_settings.name = 'sRGB'
            image.pixels.foreach_set(pixels.ravel())
            tree = material.node_tree
            colour_in, strength_in = bsdf.inputs["Emission Color"], bsdf.inputs["Emission Strength"]
            old_colour = [link.from_socket for link in colour_in.links]
            old_strength = [link.from_socket for link in strength_in.links]
            old_value = strength_in.default_value
            node = tree.nodes.new("ShaderNodeTexImage")
            node.image, node.interpolation, node.extension = image, mask_node.interpolation, mask_node.extension
            vector, _socket = _linked_from(mask_node.inputs.get("Vector"))
            if vector is not None:
                tree.links.new(_socket, node.inputs["Vector"])
            restores.append((tree, node, colour_in, old_colour, strength_in, old_strength, old_value))
            tree.links.new(node.outputs["Color"], colour_in)
            for link in list(strength_in.links):
                tree.links.remove(link)
            strength_in.default_value = k
            baked.append(name)
        yield baked, notes
    finally:
        for tree, node, colour_in, old_colour, strength_in, old_strength, old_value in reversed(restores):
            try:
                tree.nodes.remove(node)
                for socket in old_colour:
                    tree.links.new(socket, colour_in)
                for socket in old_strength:
                    tree.links.new(socket, strength_in)
                strength_in.default_value = old_value
            except Exception:
                pass
        for image in images:
            try:
                bpy.data.images.remove(image)
            except Exception:
                pass

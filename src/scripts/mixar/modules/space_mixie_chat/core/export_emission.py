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

The colour may be one colour image (followed exactly through group
sockets) or a constant (an unlinked Emission Color, or an RGB node): the
temporary image is then ``constant × mask`` on the mask's grid. Anything
else whose strength is texture-driven — another strength graph, several
colour images, mask and colour on different UV maps on a multi-UV mesh, an
image without pixels — is exported WITHOUT emission for that material
(strength 0 for the export, named in the notes): glTF would otherwise make
the whole surface glow (a lava floor exported blown-out white). Main thread
only.
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
    if colour_node is None:  # a constant colour has no UVs
        return True
    mask_uv, colour_uv = _uv_name(mask_node), _uv_name(colour_node)
    for mesh in meshes:
        layers = [uv.name for uv in getattr(mesh.data, "uv_layers", ())]
        if len(layers) > 1 and mask_uv != colour_uv:
            return False
    return True


def _texture_driven(socket) -> bool:
    return bool(_upstream_images(socket))


def _constant_colour(colour_in):
    """The linear RGB an Emission Color holds without an image: its own
    value when unlinked, or an RGB node's. None otherwise."""
    node, socket = _linked_from(colour_in)
    if node is None:
        return tuple(colour_in.default_value)[:3]
    if node.type == 'RGB':
        return tuple(socket.default_value)[:3]
    return None


def _plan(material, meshes):
    """``None`` (nothing masked), ``("bake", bsdf, mask_node, mask_socket, k,
    colour_node | None, constant | None)`` or ``("off", bsdf, reason)``.

    ``off``: the strength is texture-driven but cannot be baked. glTF would
    then make the WHOLE surface glow, so emission is left out instead."""
    bsdf = _bsdf(material)
    if bsdf is None or not bsdf.inputs["Emission Strength"].is_linked:
        return None
    strength_in, colour_in = bsdf.inputs["Emission Strength"], bsdf.inputs["Emission Color"]
    found = strength_mask(bsdf)
    if found is None:
        if _texture_driven(strength_in):
            return "off", bsdf, "emission strength is not an image mask (× constant)"
        return None
    mask_node, mask_socket, k = found
    constant = _constant_colour(colour_in)
    colour_node = None
    if constant is None:
        colours = {id(n.image): n for n in _upstream_images(colour_in)
                   if n.image.colorspace_settings.name != 'Non-Color'}
        if len(colours) != 1:
            return "off", bsdf, "emission colour is not one colour image or a constant"
        colour_node = next(iter(colours.values()))
    if not _uv_ok(meshes, mask_node, colour_node):
        return "off", bsdf, "the mask and the colour use different UV maps"
    return "bake", bsdf, mask_node, mask_socket.name, k, colour_node, constant


def _srgb(image) -> bool:
    return image.colorspace_settings.name == 'sRGB' and not image.is_float


def _bake_image(name, colour_node, constant, mask_node, mask_socket):
    import numpy as np
    mask = _pixels(mask_node.image)
    if mask is None:
        return None
    if colour_node is not None:
        colour = _pixels(colour_node.image)
        if colour is None:
            return None
        colour_srgb = _srgb(colour_node.image)
    else:  # a constant (linear) colour on the mask's grid
        colour = np.empty(mask.shape, np.float32)
        colour[..., :3], colour[..., 3] = constant, 1.0
        colour_srgb = False
    pixels = baked_pixels(colour, colour_srgb, mask, mask_socket, _srgb(mask_node.image))
    h, w = pixels.shape[:2]
    image = bpy.data.images.new(f"{TEMP_PREFIX}{name}", w, h, alpha=False)
    image.colorspace_settings.name = 'sRGB'
    image.pixels.foreach_set(pixels.ravel())
    return image


@contextmanager
def baked_emission_masks(meshes):
    """Bake masked emission for every material of ``meshes``; yields
    ``(baked_material_names, notes)``. A masked emission that cannot be
    baked is switched OFF for the export (a missing glow is far less wrong
    than a whole surface glowing) and named in ``notes``."""
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
            tree, bsdf = material.node_tree, plan[1]
            colour_in, strength_in = bsdf.inputs["Emission Color"], bsdf.inputs["Emission Strength"]
            image = None
            if plan[0] == "bake":
                _kind, _bsdf_node, mask_node, mask_socket, k, colour_node, constant = plan
                image = _bake_image(name, colour_node, constant, mask_node, mask_socket)
                if image is None:
                    plan = ("off", bsdf, "an image has no pixels")
            restore = [tree, None, colour_in, None, strength_in,
                       [link.from_socket for link in strength_in.links], strength_in.default_value]
            restores.append(restore)
            for link in list(strength_in.links):
                tree.links.remove(link)
            if plan[0] == "off":
                strength_in.default_value = 0.0
                notes.append(f"{name}: exported without emission ({plan[2]}); glTF cannot mask its strength")
                continue
            images.append(image)
            restore[3] = [link.from_socket for link in colour_in.links]
            node = tree.nodes.new("ShaderNodeTexImage")
            restore[1] = node
            node.image, node.interpolation, node.extension = image, mask_node.interpolation, mask_node.extension
            vector, socket = _linked_from(mask_node.inputs.get("Vector"))
            if vector is not None:
                tree.links.new(socket, node.inputs["Vector"])
            tree.links.new(node.outputs["Color"], colour_in)
            strength_in.default_value = k
            baked.append(name)
        yield baked, notes
    finally:
        for tree, node, colour_in, old_colour, strength_in, old_strength, old_value in reversed(restores):
            try:
                if node is not None:
                    tree.nodes.remove(node)
                for socket in old_colour or ():
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


# Shared with game_studio's material checks (procedural base colours).
upstream_images = _upstream_images

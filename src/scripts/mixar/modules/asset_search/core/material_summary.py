# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Plain-text description of a material's node graph, for its embedding.

A material preview image says what the surface looks like; this summary says
what it IS (metallic, rough, glass, emissive, which textures drive it), so a
text query such as "brushed metal" or "glowing" lands on the right asset.
The text half of the material embedding is built from it by the indexation
service (``mixar-asset-processing``).

DELIBERATELY self-contained (stdlib only, duck-typed over the bpy material):
the headless preview worker imports it from this directory under
``--factory-startup``, where no ``mixar`` package exists, and the unit tests
drive it with plain stand-in objects.
"""

import colorsys

_PROCEDURAL = {
    "TEX_NOISE": "noise",
    "TEX_VORONOI": "voronoi",
    "TEX_WAVE": "wave",
    "TEX_BRICK": "brick",
    "TEX_CHECKER": "checker",
    "TEX_GRADIENT": "gradient",
    "TEX_MAGIC": "magic",
    "TEX_WHITE_NOISE": "white noise",
    "TEX_GABOR": "gabor",
}
_IMAGE_ROLES = (
    ("normal", ("normal", "nrm", "_nor", "-nor")),
    ("roughness", ("rough",)),
    ("metallic", ("metal",)),
    ("height", ("height", "disp", "bump")),
    ("ambient occlusion", ("_ao", "-ao", "occlusion")),
    ("opacity", ("opacity", "alpha", "mask")),
    ("emission", ("emiss", "emit")),
    ("colour", ("albedo", "diffuse", "basecolor", "base_color", "color", "colour", "_col", "-col")),
)
_MAX_GROUP_DEPTH = 3


def _input(node, *names):
    for socket in getattr(node, "inputs", ()) or ():
        if getattr(socket, "name", "") in names:
            return socket
    return None


def _value(socket):
    """(is_linked, default_value) of a socket, (False, None) when absent."""
    if socket is None:
        return False, None
    return bool(getattr(socket, "is_linked", False)), getattr(socket, "default_value", None)


def colour_name(rgb):
    """Rough human name for a linear-RGB colour ("dark orange-brown", "light gray")."""
    r, g, b = (max(0.0, min(1.0, float(c))) ** (1 / 2.2) for c in list(rgb)[:3])
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if v < 0.08:
        return "black"
    if s < 0.12:
        if v > 0.9:
            return "white"
        return "dark gray" if v < 0.35 else ("light gray" if v > 0.7 else "gray")
    deg = h * 360.0
    if deg < 15 or deg >= 345:
        hue = "red"
    elif deg < 40:
        hue = "orange"
    elif deg < 65:
        hue = "yellow"
    elif deg < 160:
        hue = "green"
    elif deg < 200:
        hue = "teal"
    elif deg < 255:
        hue = "blue"
    elif deg < 290:
        hue = "purple"
    else:
        hue = "pink"
    if hue in ("orange", "red", "yellow") and v < 0.6 and s > 0.25:
        hue = "brown" if hue != "red" else "red-brown"
    if v < 0.35:
        return f"dark {hue}"
    if v > 0.8 and s < 0.45:
        return f"pale {hue}"
    return hue


def _walk(tree, depth=0):
    """Every node of ``tree``, descending into node groups."""
    for node in getattr(tree, "nodes", ()) or ():
        yield node
        group = getattr(node, "node_tree", None)
        if group is not None and depth < _MAX_GROUP_DEPTH and getattr(node, "type", "") == "GROUP":
            yield from _walk(group, depth + 1)


def _image_role(image):
    text = (getattr(image, "name", "") + " " + getattr(image, "filepath", "")).lower()
    for role, tokens in _IMAGE_ROLES:
        if any(t in text for t in tokens):
            return role
    return "image"


def _principled_traits(node):
    traits = []
    linked, base = _value(_input(node, "Base Color"))
    if not linked and base is not None:
        traits.append(f"{colour_name(base)} base colour")
    elif linked:
        traits.append("textured base colour")
    linked, metallic = _value(_input(node, "Metallic"))
    if linked:
        traits.append("textured metalness")
    elif metallic is not None and metallic >= 0.5:
        traits.append("metallic")
    linked, rough = _value(_input(node, "Roughness"))
    if linked:
        traits.append("textured roughness")
    elif rough is not None:
        traits.append("glossy" if rough < 0.25 else ("rough" if rough > 0.65 else "semi-gloss"))
    linked, transmission = _value(_input(node, "Transmission Weight", "Transmission"))
    if linked or (transmission is not None and transmission >= 0.5):
        traits.append("transparent glass-like")
    linked, alpha = _value(_input(node, "Alpha"))
    if linked or (alpha is not None and alpha < 0.95):
        traits.append("partly transparent")
    linked, emission = _value(_input(node, "Emission Strength"))
    if linked or (emission is not None and emission > 0.0):
        _, emission_colour = _value(_input(node, "Emission Color", "Emission"))
        has_colour = emission_colour is not None and max(list(emission_colour)[:3]) > 0.01
        if linked or has_colour:
            traits.append("emissive glowing")
    linked, sss = _value(_input(node, "Subsurface Weight", "Subsurface"))
    if linked or (sss is not None and sss >= 0.3):
        traits.append("subsurface scattering")
    linked, coat = _value(_input(node, "Coat Weight", "Clearcoat"))
    if linked or (coat is not None and coat >= 0.3):
        traits.append("clear coat")
    linked, sheen = _value(_input(node, "Sheen Weight", "Sheen"))
    if linked or (sheen is not None and sheen >= 0.3):
        traits.append("fabric sheen")
    return traits


_SHADER_TRAITS = {
    "BSDF_GLASS": "glass",
    "BSDF_TRANSPARENT": "transparent",
    "EMISSION": "emissive glowing",
    "BSDF_GLOSSY": "glossy reflective",
    "BSDF_ANISOTROPIC": "glossy reflective",
    "SUBSURFACE_SCATTERING": "subsurface scattering",
    "BSDF_HAIR": "hair",
    "BSDF_HAIR_PRINCIPLED": "hair",
    "BSDF_TOON": "toon shaded",
    "VOLUME_PRINCIPLED": "volumetric",
}


def material_summary(material):
    """One sentence-ish description of ``material``'s look; "" when it has no graph."""
    tree = getattr(material, "node_tree", None)
    if tree is None or not getattr(material, "use_nodes", True):
        colour = getattr(material, "diffuse_color", None)
        return f"Plain {colour_name(colour)} surface" if colour is not None else ""

    traits, roles, procedural = [], [], []
    for node in _walk(tree):
        kind = getattr(node, "type", "")
        if kind == "BSDF_PRINCIPLED":
            traits.extend(_principled_traits(node))
        elif kind in _SHADER_TRAITS:
            traits.append(_SHADER_TRAITS[kind])
        elif kind == "TEX_IMAGE" and getattr(node, "image", None) is not None:
            roles.append(_image_role(node.image))
        elif kind in _PROCEDURAL:
            procedural.append(_PROCEDURAL[kind])
        elif kind in ("DISPLACEMENT", "BUMP"):
            roles.append("height")
        elif kind == "NORMAL_MAP":
            roles.append("normal")

    parts = []
    if traits:
        parts.append(", ".join(_unique(traits)).capitalize())
    if roles:
        parts.append("Image textures: " + ", ".join(_unique(roles)))
    if procedural:
        parts.append("Procedural: " + ", ".join(_unique(procedural)))
    return ". ".join(parts)


def missing_texture_count(material):
    """Image textures whose pixels could not be loaded (render as pink)."""
    count = 0
    for node in _walk(getattr(material, "node_tree", None)):
        image = getattr(node, "image", None) if getattr(node, "type", "") == "TEX_IMAGE" else None
        if image is None or getattr(image, "packed_file", None) is not None:
            continue
        if getattr(image, "source", "FILE") == "FILE" and not getattr(image, "has_data", True):
            size = tuple(getattr(image, "size", (0, 0)) or (0, 0))
            if size == (0, 0):
                count += 1
    return count


def _unique(items):
    seen, out = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out

# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Which materials a game GLB must get baked, and which meshes carry them.

glTF reproduces a Principled BSDF 1:1 only when each of its PBR inputs is
unlinked, or is an image texture reached through plain plumbing (an image,
optionally through Normal Map / Separate Color / reroutes / UV Map / group
sockets). A material NEEDS A BAKE when a PBR input (Base Color, Roughness,
Metallic, Normal, Emission Color) reaches anything else: a procedural
texture, a Mix / Math / Color Ramp chain, AO, pointiness, a Bump from a
procedural, or a Mixar layer stack. Emission Strength alone is not a
reason, because the lane already bakes an image mask × k
(``export_emission``).

Only Principled surfaces are baked. A Mix Shader or another BSDF is
reported as ``unsupported``. Meshes inside a character subtree (a player,
boss or enemy role node and everything under it) are never baked: their
materials are image-based, and a bake would freeze a bone-parented weapon
in its current pose.

The upstream walk follows group outputs and inputs exactly (the same walk as
``export_emission``). Verdicts are cached on each material graph's shape
(``visuals._cached``). Attribute reads only, so agent scripts may reach it.
"""

from __future__ import annotations

from ..constants import CHARACTER_ROLES
from . import roles, visuals

PBR_INPUTS = ("Base Color", "Roughness", "Metallic", "Normal", "Emission Color")
# Plumbing glTF follows from a socket to an image texture.
PLAIN = {"TEX_IMAGE", "NORMAL_MAP", "SEPARATE_COLOR", "SEPRGB", "SEPARATE_RGB", "REROUTE", "UVMAP",
         "GROUP", "GROUP_INPUT", "GROUP_OUTPUT", "FRAME"}
# Coordinates that change when meshes are joined into one bake proxy.
OBJECT_RELATIVE_OUTPUTS = {("TEX_COORD", "Generated"), ("TEX_COORD", "Object"), ("TEX_COORD", "Camera"),
                           ("TEX_COORD", "Window"), ("TEX_COORD", "Reflection")}
OBJECT_RELATIVE_NODES = {"OBJECT_INFO"}


def _links(socket):
    return getattr(socket, "links", ()) or ()


def upstream_nodes(socket, stack=(), seen=None):
    """``[(node, from_socket_name)]`` reaching ``socket``, through groups."""
    seen = set() if seen is None else seen
    found = []
    for link in _links(socket):
        node, from_socket = link.from_node, link.from_socket
        key = (id(node), getattr(from_socket, "identifier", ""), len(stack))
        if key in seen:
            continue
        seen.add(key)
        found.append((node, getattr(from_socket, "name", "")))
        if node.type == 'GROUP' and getattr(node, "node_tree", None) is not None:
            outputs = [n for n in node.node_tree.nodes if n.type == 'GROUP_OUTPUT']
            for inner in (s for n in outputs for s in n.inputs
                          if s.identifier == getattr(from_socket, "identifier", None)):
                found += upstream_nodes(inner, stack + (node,), seen)
        elif node.type == 'GROUP_INPUT':
            if stack:
                for outer in (s for s in stack[-1].inputs
                              if s.identifier == getattr(from_socket, "identifier", None)):
                    found += upstream_nodes(outer, stack[:-1], seen)
        else:
            for inner in getattr(node, "inputs", ()) or ():
                found += upstream_nodes(inner, stack, seen)
    return found


def _principled(material):
    output = visuals._output(material)
    surface = visuals._from(output.inputs.get("Surface")) if output is not None else None
    return output, surface


def _verdict(material) -> dict:
    output, surface = _principled(material)
    verdict = {"needs": False, "reasons": [], "object_relative": False, "unsupported": False}
    if output is None or surface is None:
        return verdict
    if surface.type != 'BSDF_PRINCIPLED':
        if surface.type not in ('BSDF_TRANSPARENT', 'HOLDOUT', 'EMISSION'):
            verdict["unsupported"] = True
        return verdict
    for name in PBR_INPUTS:
        socket = surface.inputs.get(name)
        if socket is None or not getattr(socket, "is_linked", False):
            continue
        nodes = upstream_nodes(socket)
        kinds = {node.type for node, _out in nodes}
        if kinds - PLAIN or "TEX_IMAGE" not in kinds:
            verdict["reasons"].append(name)
        if any((node.type, out) in OBJECT_RELATIVE_OUTPUTS or node.type in OBJECT_RELATIVE_NODES
               for node, out in nodes):
            verdict["object_relative"] = True
    verdict["needs"] = bool(verdict["reasons"])
    return verdict


def material_verdict(material) -> dict:
    """``{needs, reasons: [input], object_relative, unsupported}`` (cached)."""
    return visuals._cached("bake", material, _verdict)


def in_character(obj) -> bool:
    node = obj
    while node is not None:
        if roles.get_role(node) in CHARACTER_ROLES:
            return True
        node = getattr(node, "parent", None)
    return False


def _materials(obj):
    return [m for m in getattr(getattr(obj, "data", None), "materials", ()) or () if m is not None]


def plan(objects) -> dict:
    """What a build would bake for the in-game ``objects``:
    ``{"materials": [name], "meshes": [object], "unsupported": [name],
    "character_materials": [name]}``. ``meshes`` holds one object per mesh
    data (instances share one bake), name order."""
    materials, unsupported, character, meshes, seen = set(), set(), set(), [], set()
    for obj in sorted(objects, key=lambda o: o.name):
        if getattr(obj, "type", "") != 'MESH':
            continue
        mats = _materials(obj)
        verdicts = [(m, material_verdict(m)) for m in mats]
        unsupported |= {m.name for m, v in verdicts if v["unsupported"]}
        needing = [m.name for m, v in verdicts if v["needs"]]
        if not needing:
            continue
        if in_character(obj):
            character.update(needing)
            continue
        materials.update(needing)
        data = getattr(obj, "data", None)
        key = getattr(data, "name", None) or obj.name
        if key not in seen:
            seen.add(key)
            meshes.append(obj)
    return {"materials": sorted(materials), "meshes": meshes, "unsupported": sorted(unsupported),
            "character_materials": sorted(character - materials)}

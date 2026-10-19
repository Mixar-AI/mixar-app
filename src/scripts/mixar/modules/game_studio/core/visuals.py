# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""What a game GLB cannot show the way Blender does.

``non_visual_reason`` names a mesh the game leaves out. Every material on it
is one of these:

- **volume-only**: the active Material Output's Surface is unlinked and its
  Volume is linked (fog cards, smoke plumes);
- **fully transparent**: the surface is a Transparent BSDF or Holdout, or a
  Principled BSDF with Alpha unlinked at 0.

A mesh is also left out when it is a particle or hair emitter whose own
mesh is hidden in renders (Show Emitter off).

glTF has no volumes, and the game would give such a mesh an opaque box with
collision: an arena's haze became grey walls the player bumped into. A mesh
the user tagged itself (not through an ancestor) is kept, because the user
decided.

``procedural_materials`` lists materials whose Principled Base Color is
linked but reaches no image. A procedural texture has no glTF equivalent,
so they export as flat colour; this is reported, not baked.

Attribute reads only.
"""

from __future__ import annotations

from . import roles


def _output(material):
    tree = getattr(material, "node_tree", None)
    for node in getattr(tree, "nodes", ()) or ():
        if node.type == 'OUTPUT_MATERIAL' and getattr(node, "is_active_output", True):
            return node
    return None


def _from(socket):
    links = getattr(socket, "links", ()) or ()
    return links[0].from_node if links else None


def material_kind(material) -> str | None:
    """``"volume"``, ``"transparent"`` or None (a visible surface)."""
    output = _output(material)
    if output is None:
        return None
    surface = _from(output.inputs.get("Surface"))
    if surface is None:
        return "volume" if _from(output.inputs.get("Volume")) is not None else None
    if surface.type in ('BSDF_TRANSPARENT', 'HOLDOUT'):
        return "transparent"
    if surface.type == 'BSDF_PRINCIPLED':
        alpha = surface.inputs.get("Alpha")
        if alpha is not None and not alpha.is_linked and float(alpha.default_value) <= 0.001:
            return "transparent"
    return None


REASONS = {"volume": "volume-only material", "transparent": "fully transparent material",
           "particles": "particle emitter shown only as its particles"}


def non_visual_reason(obj) -> str | None:
    if getattr(obj, "type", "") != 'MESH':
        return None
    own = roles.get_role(obj)
    if own and own != "ignore":
        return None
    if getattr(obj, "particle_systems", None) and len(obj.particle_systems) \
            and not getattr(obj, "show_instancer_for_render", True):
        return REASONS["particles"]
    materials = [m for m in getattr(getattr(obj, "data", None), "materials", ()) or () if m is not None]
    kinds = {material_kind(m) for m in materials}
    if materials and None not in kinds:
        return REASONS["volume" if kinds == {"volume"} else "transparent"]
    return None


def split_visible(objects) -> tuple[list, list[dict]]:
    """``(kept, excluded)``; ``excluded`` is ``[{object, reason}]``."""
    kept, excluded = [], []
    for obj in objects:
        reason = non_visual_reason(obj)
        if reason:
            excluded.append({"object": obj.name, "reason": reason})
        else:
            kept.append(obj)
    return kept, excluded


def procedural_materials(objects) -> list[str]:
    """Materials of ``objects`` whose base colour is procedural (sorted)."""
    from mixar.modules.space_mixie_chat.core.export_emission import upstream_images
    found, seen = set(), set()
    for obj in objects:
        if getattr(obj, "type", "") != 'MESH':
            continue
        for material in getattr(getattr(obj, "data", None), "materials", ()) or ():
            if material is None or material.name in seen:
                continue
            seen.add(material.name)
            output = _output(material)
            surface = _from(output.inputs.get("Surface")) if output is not None else None
            if getattr(surface, "type", "") != 'BSDF_PRINCIPLED':
                continue
            base = surface.inputs.get("Base Color")
            if base is not None and base.is_linked and not upstream_images(base):
                found.add(material.name)
    return sorted(found)

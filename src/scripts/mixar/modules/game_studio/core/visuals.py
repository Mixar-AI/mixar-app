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

``particle_fields`` names untagged meshes that are fields of tiny scattered
parts (an ash or ember field made as one mesh). They default to ``decor``
(no collision) rather than static.

``procedural_materials`` lists materials whose Principled Base Color is
linked but reaches no image. A procedural texture has no glTF equivalent,
so they export as flat colour; this is reported, not baked.

Attribute reads only (numpy for the particle-field test).
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


_material_cache: dict = {}


def _material_key(material):
    """Changes when the material's node graph changes shape (nodes/links
    added or removed) or a value the checks read is edited."""
    tree = getattr(material, "node_tree", None)
    try:
        pointer = material.as_pointer()
    except Exception:
        pointer = id(material)
    nodes = getattr(tree, "nodes", ()) or ()
    links = getattr(tree, "links", ()) or ()
    alpha = None
    for node in nodes:
        if getattr(node, "type", "") == 'BSDF_PRINCIPLED':
            socket = node.inputs.get("Alpha") if hasattr(node.inputs, "get") else None
            alpha = getattr(socket, "default_value", None)
            break
    return pointer, len(nodes), len(links), alpha


def _cached(kind, material, compute):
    key = (kind,) + _material_key(material)
    if key not in _material_cache:
        if len(_material_cache) > 8192:
            _material_cache.clear()
        _material_cache[key] = compute(material)
    return _material_cache[key]


def material_kind(material) -> str | None:
    """``"volume"``, ``"transparent"`` or None (a visible surface); cached
    per material graph."""
    return _cached("kind", material, _material_kind)


def _material_kind(material) -> str | None:
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
            if _cached("procedural", material, lambda m: _procedural(m, upstream_images)):
                found.add(material.name)
    return sorted(found)


def _procedural(material, upstream_images) -> bool:
    output = _output(material)
    surface = _from(output.inputs.get("Surface")) if output is not None else None
    if getattr(surface, "type", "") != 'BSDF_PRINCIPLED':
        return False
    base = surface.inputs.get("Base Color")
    return bool(base is not None and base.is_linked and not upstream_images(base))


# --- particle fields (scattered ash, embers, sparks) --------------------------
# A mesh of at least FIELD_ISLANDS loose parts, each smaller than
# FIELD_PART_SHARE of the mesh's span, with a surface area under
# FIELD_AREA_SHARE of its bounding box's: drawn as particles, never solid.
FIELD_ISLANDS = 20
FIELD_PART_SHARE = 0.03
FIELD_AREA_SHARE = 0.02
FIELD_MAX_VERTS = 50000
_field_cache: dict = {}


def _mesh_key(mesh):
    try:
        pointer = mesh.as_pointer()
    except Exception:
        pointer = id(mesh)
    return pointer, len(mesh.vertices), len(mesh.edges), len(mesh.polygons)


def is_particle_field(mesh) -> bool:
    """True for a mesh that is a field of tiny scattered parts. Vectorized,
    cached per mesh data; the island walk runs only for meshes that are
    already sparse by area."""
    key = _mesh_key(mesh)
    if key in _field_cache:
        return _field_cache[key]
    _field_cache[key] = result = _particle_field(mesh, key[1])
    if len(_field_cache) > 4096:
        _field_cache.clear()
    return result


def _particle_field(mesh, count) -> bool:
    import numpy as np
    if count < FIELD_ISLANDS * 3 or count > FIELD_MAX_VERTS or not len(mesh.polygons):
        return False
    co = np.empty(count * 3, np.float32)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    size = co.max(0) - co.min(0)
    span = float(size.max())
    box = 2.0 * float(size[0] * size[1] + size[1] * size[2] + size[0] * size[2])
    if span <= 0.0 or box <= 0.0:
        return False
    areas = np.empty(len(mesh.polygons), np.float32)
    mesh.polygons.foreach_get("area", areas)
    if float(areas.sum()) >= FIELD_AREA_SHARE * box:
        return False
    edges = np.empty(len(mesh.edges) * 2, np.int64)
    mesh.edges.foreach_get("vertices", edges)
    roots = _islands(count, edges.reshape(-1, 2))
    labels, index = np.unique(roots, return_inverse=True)
    if len(labels) < FIELD_ISLANDS:
        return False
    low = np.full((len(labels), 3), np.inf, np.float32)
    high = np.full((len(labels), 3), -np.inf, np.float32)
    np.minimum.at(low, index, co)
    np.maximum.at(high, index, co)
    return float((high - low).max()) < FIELD_PART_SHARE * span


def _islands(count, edges):
    """Connected-component label per vertex (min-label propagation)."""
    import numpy as np
    labels = np.arange(count)
    if not len(edges):
        return labels
    a, b = edges[:, 0], edges[:, 1]
    while True:
        low = np.minimum(labels[a], labels[b])
        before = labels.copy()
        np.minimum.at(labels, a, low)
        np.minimum.at(labels, b, low)
        labels = labels[labels]  # pointer jumping
        if np.array_equal(labels, before):
            return labels


COLLIDING = ("static", "prop")


def particle_fields(objects) -> list[dict]:
    """``[{object, reason}]`` for meshes that default to ``decor``: a
    particle field whose role (its own default, or an ancestor's) would give
    it collision. A mesh the user tagged itself keeps its tag."""
    found = []
    for obj in objects:
        if getattr(obj, "type", "") != 'MESH' or roles.get_role(obj):
            continue
        if roles.effective_role(obj) not in COLLIDING:
            continue
        mesh = getattr(obj, "data", None)
        if mesh is not None and hasattr(mesh, "vertices") and is_particle_field(mesh):
            found.append({"object": obj.name, "reason": "particle field (many tiny loose parts)"})
    return found


def clear_caches() -> None:
    """Forget the per-material and per-mesh verdicts (a build re-reads all)."""
    _material_cache.clear()
    _field_cache.clear()

# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-object shader inputs that survive joining meshes into a bake proxy.

Joining meshes into one world-space proxy makes a bake pass one Cycles
session instead of one per mesh. But it would change what Object
coordinates, Generated coordinates and Object Info (Random / Location /
Color) return, because the proxy is a different object. Mixie's grime pass
seeds its noise from Object Info Random on every temple stone.

So, on the temporary copy:

- ``add_attributes`` stores those inputs on each mesh as point attributes:
  ``mixar_obj_co`` (object-space position), ``mixar_gen_co`` (Generated: the
  position in the mesh's texture space), ``mixar_obj_random``,
  ``mixar_obj_loc`` and ``mixar_obj_color``.
- ``carry_inputs`` rewires the materials to read those attributes instead.

Random is Cycles' own value, ``hash_uint2(hash_string(name), 0) /
0xFFFFFFFF`` (``util/hash.h``), checked against Cycles bakes of four
temple walls to 1e-7.
"""

from __future__ import annotations

import numpy as np

ATTRS = {("TEX_COORD", "Object"): ("mixar_obj_co", "Vector"),
         ("TEX_COORD", "Generated"): ("mixar_gen_co", "Vector"),
         ("OBJECT_INFO", "Random"): ("mixar_obj_random", "Fac"),
         ("OBJECT_INFO", "Location"): ("mixar_obj_loc", "Vector"),
         ("OBJECT_INFO", "Color"): ("mixar_obj_color", "Color")}
_M = 0xFFFFFFFF


def _rot(x, k):
    return ((x << k) | (x >> (32 - k))) & _M


def hash_uint2(kx: int, ky: int) -> int:
    """Cycles ``hash_uint2`` (Bob Jenkins' lookup3 final mix)."""
    a = b = c = (0xDEADBEEF + (2 << 2) + 13) & _M
    b = (b + ky) & _M
    a = (a + kx) & _M
    c ^= b; c = (c - _rot(b, 14)) & _M  # noqa: E702
    a ^= c; a = (a - _rot(c, 11)) & _M  # noqa: E702
    b ^= a; b = (b - _rot(a, 25)) & _M  # noqa: E702
    c ^= b; c = (c - _rot(b, 16)) & _M  # noqa: E702
    a ^= c; a = (a - _rot(c, 4)) & _M  # noqa: E702
    b ^= a; b = (b - _rot(a, 14)) & _M  # noqa: E702
    c ^= b; c = (c - _rot(b, 24)) & _M  # noqa: E702
    return c


def hash_string(text: str) -> int:
    value = 0
    for char in text.encode("utf-8"):
        value = (value * 37 + char) & _M
    return value


def object_random(name: str) -> float:
    """Object Info Random for a non-instanced object, as Cycles computes it."""
    return hash_uint2(hash_string(name), 0) / _M


def _set(mesh, name, kind, values):
    attribute = mesh.attributes.get(name)
    if attribute is not None:
        mesh.attributes.remove(attribute)
    attribute = mesh.attributes.new(name, kind, 'POINT')
    field = "value" if kind == 'FLOAT' else "color" if kind == 'FLOAT_COLOR' else "vector"
    attribute.data.foreach_set(field, np.ascontiguousarray(values, np.float32).ravel())


def add_attributes(obj, mesh, texspace=None) -> None:
    """Write the per-object attributes of ``obj`` onto ``mesh``, whose
    vertices are in ``obj``'s object space (the original data, or an
    evaluated copy before it is moved to world space)."""
    count = len(mesh.vertices)
    co = np.empty(count * 3, np.float32)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    data = texspace or obj.data
    location = np.asarray(tuple(getattr(data, "texspace_location", (0, 0, 0))), np.float32)
    size = np.asarray(tuple(getattr(data, "texspace_size", (1, 1, 1))), np.float32)
    size = np.where(np.abs(size) < 1e-8, 1.0, size)
    _set(mesh, "mixar_obj_co", 'FLOAT_VECTOR', co)
    _set(mesh, "mixar_gen_co", 'FLOAT_VECTOR', (co - (location - size)) / (2.0 * size))
    _set(mesh, "mixar_obj_random", 'FLOAT', np.full(count, object_random(obj.name), np.float32))
    _set(mesh, "mixar_obj_loc", 'FLOAT_VECTOR', np.tile(np.asarray(obj.matrix_world.translation, np.float32),
                                                       (count, 1)))
    _set(mesh, "mixar_obj_color", 'FLOAT_COLOR', np.tile(np.asarray(tuple(obj.color), np.float32), (count, 1)))


def _trees(tree, seen):
    if tree is None or id(tree) in seen:
        return
    seen.add(id(tree))
    yield tree
    for node in tree.nodes:
        if getattr(node, "node_tree", None) is not None:
            yield from _trees(node.node_tree, seen)


def carry_inputs(materials) -> int:
    """Rewire every carried per-object output (``ATTRS``) in ``materials``
    and the groups they use to an Attribute node. Returns links rewired."""
    rewired, seen = 0, set()
    for material in materials:
        for tree in _trees(getattr(material, "node_tree", None), seen):
            for link in list(tree.links):
                key = (link.from_node.type, link.from_socket.name)
                if key not in ATTRS:
                    continue
                name, output = ATTRS[key]
                node = tree.nodes.new("ShaderNodeAttribute")
                node.attribute_type = 'GEOMETRY'
                node.attribute_name = name
                node.location = link.from_node.location
                tree.links.new(node.outputs[output], link.to_socket)
                rewired += 1
    return rewired

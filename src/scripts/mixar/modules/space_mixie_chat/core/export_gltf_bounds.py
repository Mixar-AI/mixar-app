# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""World-space bounds of a glTF document (export contract §5).

Walks ``scenes[0].nodes`` recursively, composes each node's ``matrix`` or
TRS (glTF: column-major, quaternion ``[x, y, z, w]``) into a world matrix,
transforms the 8 corners of every mesh primitive's POSITION min/max box and
unions them — so a multi-part asset whose parts are placed by node
transforms reports its real extent, not the largest single part. Pure
Python, no ``bpy``, so the verifier stays testable outside Blender.
"""

from __future__ import annotations

IDENTITY = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]


def _matmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _from_column_major(values) -> list:
    """glTF ``matrix`` is 16 floats column-major → row-major 4x4."""
    return [[float(values[col * 4 + row]) for col in range(4)] for row in range(4)]


def _trs_matrix(node: dict) -> list:
    t = node.get("translation") or [0.0, 0.0, 0.0]
    q = node.get("rotation") or [0.0, 0.0, 0.0, 1.0]
    s = node.get("scale") or [1.0, 1.0, 1.0]
    x, y, z, w = (float(v) for v in q)
    rot = [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]
    m = [[0.0] * 4 for _ in range(4)]
    for i in range(3):
        for j in range(3):
            m[i][j] = rot[i][j] * float(s[j])
        m[i][3] = float(t[i])
    m[3][3] = 1.0
    return m


def node_matrix(node: dict) -> list:
    matrix = node.get("matrix")
    if matrix and len(matrix) == 16:
        return _from_column_major(matrix)
    return _trs_matrix(node)


def _transform(m, point):
    return [sum(m[i][k] * point[k] for k in range(3)) + m[i][3] for i in range(3)]


def _mesh_box(mesh: dict, accessors) -> list | None:
    lo, hi = [None] * 3, [None] * 3
    for prim in mesh.get("primitives") or []:
        position = (prim.get("attributes") or {}).get("POSITION")
        if position is None or position >= len(accessors):
            continue
        acc = accessors[position]
        a_min, a_max = acc.get("min"), acc.get("max")
        if not (a_min and a_max and len(a_min) == 3 and len(a_max) == 3):
            continue
        for axis in range(3):
            lo[axis] = a_min[axis] if lo[axis] is None else min(lo[axis], a_min[axis])
            hi[axis] = a_max[axis] if hi[axis] is None else max(hi[axis], a_max[axis])
    if None in lo or None in hi:
        return None
    return [lo, hi]


def gltf_world_bounds(doc: dict) -> list | None:
    """``[[min_x, min_y, min_z], [max_x, max_y, max_z]]`` in world space, or
    None when no node carries a mesh with POSITION bounds."""
    nodes = doc.get("nodes") or []
    meshes = doc.get("meshes") or []
    accessors = doc.get("accessors") or []
    scenes = doc.get("scenes") or []
    if scenes:
        roots = list(scenes[0].get("nodes") or [])
    else:  # no scene: every node that is nobody's child is a root
        children = {c for n in nodes for c in (n.get("children") or [])}
        roots = [i for i in range(len(nodes)) if i not in children]
    boxes: dict = {}
    lo, hi = [None] * 3, [None] * 3
    seen: set = set()

    def visit(index, parent):
        if index in seen or index >= len(nodes):
            return
        seen.add(index)
        node = nodes[index]
        world = _matmul(parent, node_matrix(node))
        mesh_index = node.get("mesh")
        if mesh_index is not None and mesh_index < len(meshes):
            if mesh_index not in boxes:
                boxes[mesh_index] = _mesh_box(meshes[mesh_index], accessors)
            box = boxes[mesh_index]
            if box is not None:
                for cx in (box[0][0], box[1][0]):
                    for cy in (box[0][1], box[1][1]):
                        for cz in (box[0][2], box[1][2]):
                            point = _transform(world, (float(cx), float(cy), float(cz)))
                            for axis in range(3):
                                lo[axis] = point[axis] if lo[axis] is None else min(lo[axis], point[axis])
                                hi[axis] = point[axis] if hi[axis] is None else max(hi[axis], point[axis])
        for child in node.get("children") or []:
            visit(child, world)

    for root in roots:
        visit(root, IDENTITY)
    if None in lo or None in hi:
        return None
    return [lo, hi]

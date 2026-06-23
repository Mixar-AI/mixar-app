# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Shared node registry: one scene walk, geometry reused by every relation layer.

The registry is the single source of node identity. Each node carries the
geometry primitives (world-axis AABB enclosing the evaluated oriented box) that
every relation layer reuses, so the scene is walked once and nothing is
recomputed per layer.
"""

import bpy
from mathutils import Vector


def round_vec(v, ndigits=4):
    return [round(float(v[0]), ndigits), round(float(v[1]), ndigits), round(float(v[2]), ndigits)]


def world_box(obj, depsgraph):
    """World-axis AABB enclosing the evaluated (modifiers-applied) oriented box."""
    obj_eval = obj.evaluated_get(depsgraph)
    mat = obj_eval.matrix_world
    corners = [mat @ Vector(c) for c in obj_eval.bound_box]
    mins = Vector((min(c[i] for c in corners) for i in range(3)))
    maxs = Vector((max(c[i] for c in corners) for i in range(3)))
    return {"min": mins, "max": maxs, "centroid": (mins + maxs) * 0.5, "size": maxs - mins}


def aabb_gap(a, b):
    """Shortest distance between two world AABBs (0.0 if they overlap)."""
    sep_sq = 0.0
    for i in range(3):
        sep = max(0.0, a["min"][i] - b["max"][i], b["min"][i] - a["max"][i])
        sep_sq += sep * sep
    return sep_sq ** 0.5


def axis_overlap(a, b, i):
    """Overlap length of two AABBs along axis i (negative if separated)."""
    return min(a["max"][i], b["max"][i]) - max(a["min"][i], b["min"][i])


class SceneNode:
    """One object: stable index + id, shared geometry, collection membership."""

    __slots__ = ("idx", "id", "obj", "box", "collection", "type")

    def __init__(self, idx, obj, box, collection):
        self.idx = idx
        self.id = obj.name
        self.obj = obj
        self.box = box
        self.collection = collection
        self.type = obj.type

    def to_dict(self):
        return {
            "id": self.id,
            "c": round_vec(self.box["centroid"]),
            "d": round_vec(self.box["size"]),
            "coll": self.collection or "(none)",
        }


class NodeRegistry:
    """Index-stable list of scene nodes + scene-scale reference for thresholds."""

    def __init__(self, nodes, scene_min, scene_max):
        self.nodes = nodes
        self.by_name = {n.id: n.idx for n in nodes}
        self.scene_min = scene_min
        self.scene_max = scene_max
        self.scene_diagonal = (scene_max - scene_min).length if nodes else 0.0

    @classmethod
    def from_scene(cls, scene=None, object_types=("MESH",)):
        scene = scene or bpy.context.scene
        depsgraph = bpy.context.evaluated_depsgraph_get()
        coll_of = cls._collection_map()

        nodes = []
        for obj in scene.objects:
            if obj.type not in object_types:
                continue
            box = world_box(obj, depsgraph)
            nodes.append(SceneNode(len(nodes), obj, box, coll_of.get(obj.name, "")))

        if nodes:
            scene_min = Vector((min(n.box["min"][i] for n in nodes) for i in range(3)))
            scene_max = Vector((max(n.box["max"][i] for n in nodes) for i in range(3)))
        else:
            scene_min = scene_max = Vector((0.0, 0.0, 0.0))
        return cls(nodes, scene_min, scene_max)

    @staticmethod
    def _collection_map():
        """First collection each object belongs to (for hierarchy / collapse views)."""
        mapping = {}
        for coll in bpy.data.collections:
            for obj in coll.objects:
                mapping.setdefault(obj.name, coll.name)
        return mapping

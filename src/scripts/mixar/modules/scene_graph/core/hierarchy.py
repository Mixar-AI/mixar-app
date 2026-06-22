# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Extract the Outliner hierarchy (parenting) into plain dicts.

This is the structural backbone of the scene graph: every object is a node and
the only relationships are parent/child. The spatial layer is added on top of
these same nodes later.
"""

import bpy


def collection_map():
    """name -> first collection it belongs to."""
    mapping = {}
    for coll in bpy.data.collections:
        for obj in coll.objects:
            mapping.setdefault(obj.name, coll.name)
    return mapping


def build_hierarchy(scene):
    """Return (parent, meta).

    parent : child name -> parent name (or None for top-level)
    meta   : name -> {"type", "coll", "root"}  (root = top-level ancestor name)
    """
    objs = list(scene.objects)
    names = {o.name for o in objs}

    parent = {}
    for obj in objs:
        p = obj.parent
        parent[obj.name] = p.name if (p is not None and p.name in names) else None

    def root_of(name):
        cur, guard = name, 0
        while parent.get(cur) and guard < 100000:
            cur, guard = parent[cur], guard + 1
        return cur

    coll = collection_map()
    meta = {
        obj.name: {
            "type": obj.type,
            "coll": coll.get(obj.name, ""),
            "root": root_of(obj.name),
        }
        for obj in objs
    }
    return parent, meta

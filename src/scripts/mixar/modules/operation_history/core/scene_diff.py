# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shallow scene snapshot + diff.

Two layers, both standalone and pure:
- objects: per-object (type + transform + material-slot count) — detects add/delete/move/scale.
- materials: per-material node-tree node count — detects material edits (e.g. a node group
  added) that don't change any object signature and would otherwise be invisible.

Operates on any object with .name/.type/.location/.rotation_euler/.scale/.material_slots and
materials with .name/.node_tree.nodes.
"""


def _obj_sig(o):
    try:
        loc = tuple(round(float(v), 5) for v in o.location)
        rot = tuple(round(float(v), 5) for v in o.rotation_euler)
        scl = tuple(round(float(v), 5) for v in o.scale)
        mats = len(getattr(o, "material_slots", []) or [])
        return (o.type, loc, rot, scl, mats)
    except Exception:
        return None


def _mat_node_count(m):
    try:
        nt = getattr(m, "node_tree", None)
        return len(nt.nodes) if nt is not None else 0
    except Exception:
        return 0


def snapshot_scene(scene) -> dict:
    objs = {}
    mats = {}
    try:
        for o in getattr(scene, "objects", []) or []:
            objs[o.name] = _obj_sig(o)
            for slot in getattr(o, "material_slots", []) or []:
                m = getattr(slot, "material", None)
                if m is not None and getattr(m, "name", None):
                    mats[m.name] = _mat_node_count(m)
    except Exception:
        pass
    return {"objects": objs, "materials": mats}


def _diff_maps(before: dict, after: dict):
    bset, aset = set(before), set(after)
    created = sorted(aset - bset)
    deleted = sorted(bset - aset)
    modified = sorted(n for n in (aset & bset) if before.get(n) != after.get(n))
    return created, modified, deleted


def diff_snapshots(before: dict, after: dict) -> dict:
    created, modified, deleted = _diff_maps(
        (before or {}).get("objects", {}), (after or {}).get("objects", {}))
    mat_created, mat_modified, mat_deleted = _diff_maps(
        (before or {}).get("materials", {}), (after or {}).get("materials", {}))
    return {"created": created, "modified": modified, "deleted": deleted,
            "materials_created": mat_created, "materials_modified": mat_modified,
            "materials_deleted": mat_deleted}

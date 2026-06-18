# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shallow object-level scene snapshot + diff (object set + transforms + material count).

Mirrors space_mixie_chat.core.executor's change-detection shape but is standalone and
pure (operates on any object with .name/.type/.location/.rotation_euler/.scale/.material_slots).
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


def snapshot_scene(scene) -> dict:
    objs = {}
    try:
        for o in getattr(scene, "objects", []) or []:
            objs[o.name] = _obj_sig(o)
    except Exception:
        pass
    return {"objects": objs}


def diff_snapshots(before: dict, after: dict) -> dict:
    b = (before or {}).get("objects", {})
    a = (after or {}).get("objects", {})
    bset, aset = set(b), set(a)
    created = sorted(aset - bset)
    deleted = sorted(bset - aset)
    modified = sorted(n for n in (aset & bset) if b.get(n) != a.get(n))
    return {"created": created, "modified": modified, "deleted": deleted}

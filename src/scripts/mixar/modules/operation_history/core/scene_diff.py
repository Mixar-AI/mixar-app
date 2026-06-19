# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shallow scene snapshot + diff.

Two layers, both standalone and pure:
- objects: per-object (type + transform + material-slot count + mesh topology +
  modifiers) — detects add/delete/rename/move/scale, modifier changes, and edit-mode
  topology changes such as extrude.
- materials: per-material node-tree node count — detects material edits (e.g. a node group
  added) that don't change any object signature and would otherwise be invisible.

Operates on any object with .name/.type/.location/.rotation_euler/.scale/.material_slots,
optionally .modifiers/.data.vertices/.data.edges/.data.polygons, and materials with
.name/.node_tree.nodes. In Blender edit mode, it uses bmesh when available so live mesh
edits are not missed.
"""


def _safe_len(value):
    try:
        return len(value)
    except Exception:
        return 0


def _mesh_counts(o):
    if getattr(o, "type", None) != "MESH":
        return {}
    data = getattr(o, "data", None)
    if data is None:
        return {}
    if getattr(o, "mode", None) == "EDIT":
        try:
            import bmesh
            bm = bmesh.from_edit_mesh(data)
            return {"vertices": _safe_len(bm.verts), "edges": _safe_len(bm.edges),
                    "faces": _safe_len(bm.faces)}
        except Exception:
            pass
    return {
        "vertices": _safe_len(getattr(data, "vertices", [])),
        "edges": _safe_len(getattr(data, "edges", [])),
        "faces": _safe_len(getattr(data, "polygons", getattr(data, "faces", []))),
    }


def _stable_value(value):
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(float(value), 5)
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        out = []
        for item in value[:16]:
            stable = _stable_value(item)
            if stable is not None:
                out.append(stable)
        return tuple(out)
    return None


def _modifier_properties(mod):
    props = {}
    try:
        rna_props = getattr(getattr(mod, "bl_rna", None), "properties", None)
        if rna_props:
            names = [p.identifier for p in rna_props if not getattr(p, "is_readonly", False)]
        else:
            names = [n for n in vars(mod) if not n.startswith("_")]
    except Exception:
        names = []
    for name in sorted(set(names)):
        if name in {"name", "type", "rna_type", "id_data"}:
            continue
        try:
            stable = _stable_value(getattr(mod, name))
        except Exception:
            continue
        if stable is not None:
            props[name] = stable
        if len(props) >= 32:
            break
    return props


def _modifier_sig(mod):
    try:
        return {
            "name": getattr(mod, "name", ""),
            "type": getattr(mod, "type", ""),
            "properties": _modifier_properties(mod),
        }
    except Exception:
        return None


def _modifier_sigs(o):
    out = []
    try:
        for mod in getattr(o, "modifiers", []) or []:
            sig = _modifier_sig(mod)
            if sig is not None:
                out.append(sig)
    except Exception:
        pass
    return out


def _obj_sig(o):
    try:
        loc = tuple(round(float(v), 5) for v in o.location)
        rot = tuple(round(float(v), 5) for v in o.rotation_euler)
        scl = tuple(round(float(v), 5) for v in o.scale)
        mats = len(getattr(o, "material_slots", []) or [])
        return {"type": o.type, "loc": loc, "rot": rot, "scale": scl,
                "materials": mats, "mesh": _mesh_counts(o),
                "modifiers": _modifier_sigs(o)}
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


def _detect_renames(before: dict, after: dict, created: list, deleted: list):
    renamed = []
    remaining_created = list(created)
    remaining_deleted = list(deleted)
    for old_name in list(remaining_deleted):
        old_sig = before.get(old_name)
        for new_name in list(remaining_created):
            if old_sig == after.get(new_name):
                renamed.append({"from": old_name, "to": new_name})
                remaining_deleted.remove(old_name)
                remaining_created.remove(new_name)
                break
    return renamed, remaining_created, remaining_deleted


def _modifier_map(sig):
    return {m.get("name"): m for m in (sig or {}).get("modifiers", []) if m.get("name")}


def _object_change(before, after):
    changes = []
    detail = {}
    if not isinstance(before, dict) or not isinstance(after, dict):
        return {"fields": ["unknown"]}
    if (before.get("loc"), before.get("rot"), before.get("scale")) != (
            after.get("loc"), after.get("rot"), after.get("scale")):
        changes.append("transform")
    if before.get("materials") != after.get("materials"):
        changes.append("material_slots")
        detail["material_slots_delta"] = (after.get("materials") or 0) - (before.get("materials") or 0)
    before_mods = _modifier_map(before)
    after_mods = _modifier_map(after)
    mods_added = sorted(set(after_mods) - set(before_mods))
    mods_removed = sorted(set(before_mods) - set(after_mods))
    mods_modified = sorted(
        name for name in (set(before_mods) & set(after_mods))
        if before_mods.get(name) != after_mods.get(name)
    )
    if mods_added or mods_removed or mods_modified:
        changes.append("modifiers")
        detail["modifiers_added"] = mods_added
        detail["modifiers_removed"] = mods_removed
        detail["modifiers_modified"] = mods_modified
    before_mesh = before.get("mesh") or {}
    after_mesh = after.get("mesh") or {}
    mesh_delta = {}
    for key in ("vertices", "edges", "faces"):
        delta = (after_mesh.get(key) or 0) - (before_mesh.get(key) or 0)
        if delta:
            mesh_delta[key] = delta
    if mesh_delta:
        changes.append("mesh_topology")
        detail["mesh_delta"] = mesh_delta
        detail["mesh_before"] = before_mesh
        detail["mesh_after"] = after_mesh
    if not changes:
        changes.append("unknown")
    detail["fields"] = changes
    return detail


def _object_changes(before: dict, after: dict, modified: list, renamed: list) -> dict:
    out = {}
    renames_by_new = {r["to"]: r["from"] for r in renamed}
    for name in modified:
        old_name = renames_by_new.get(name)
        if old_name:
            change = _object_change(before.get(old_name), after.get(name))
            fields = change.setdefault("fields", [])
            if "rename" not in fields:
                fields.insert(0, "rename")
            change["previous_name"] = old_name
            out[name] = change
        else:
            out[name] = _object_change(before.get(name), after.get(name))
    return out


def _material_changes(before: dict, after: dict, modified: list) -> dict:
    out = {}
    for name in modified:
        b = before.get(name) or 0
        a = after.get(name) or 0
        out[name] = {"nodes_delta": a - b, "nodes_before": b, "nodes_after": a}
    return out


def diff_snapshots(before: dict, after: dict) -> dict:
    before_objects = (before or {}).get("objects", {})
    after_objects = (after or {}).get("objects", {})
    before_materials = (before or {}).get("materials", {})
    after_materials = (after or {}).get("materials", {})
    created, modified, deleted = _diff_maps(before_objects, after_objects)
    renamed, created, deleted = _detect_renames(before_objects, after_objects, created, deleted)
    for row in renamed:
        if row["to"] not in modified:
            modified.append(row["to"])
    modified = sorted(modified)
    mat_created, mat_modified, mat_deleted = _diff_maps(before_materials, after_materials)
    return {"created": created, "modified": modified, "deleted": deleted,
            "renamed": renamed,
            "object_changes": _object_changes(before_objects, after_objects, modified, renamed),
            "materials_created": mat_created, "materials_modified": mat_modified,
            "materials_deleted": mat_deleted,
            "material_changes": _material_changes(before_materials, after_materials, mat_modified)}

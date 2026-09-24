# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Run an Assemble Character card: attach its parts to the connected body.

The Blender side of the engine: measure the body and parts in the rig's REST
pose, ask the pure modules where each part goes, then bone-parent every part
ROOT keeping its world transform (no armature: OBJECT-parent to the body).
Only root transforms and parenting change -- never mesh data, the armature,
the body or an object name (upstream cards find objects by name). Each root
stores its pre-assembly matrix so a re-run starts from it; a failure restores
everything this run touched; success is one undo step.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import logging

import numpy as np

from .assemble_bones import BoneInfo, nearest_bone
from .assemble_constants import param_name
from .assemble_landmarks import crossings, outer_surface, ray_start, surface_query
from .assemble_math import (
    bone_key,
    measure_body,
    plan_part,
    resolve_settings,
    sorted_extents,
    transform_points,
)
from .assemble_rules import region_note
from .assemble_schema import body_link, part_label, part_links

STAMP_OWNER = "mixar_assembled_by"
STAMP_REST = "mixar_assemble_rest"
STAMP_ATTACH = "mixar_attach"
STAMP_HIDDEN = "mixar_hidden_by"
_STAMPS = (STAMP_OWNER, STAMP_REST, STAMP_ATTACH, STAMP_HIDDEN)
DRIFT_TOLERANCE = 1e-4
logger = logging.getLogger(__name__)


def _copy_value(value):
    return value.to_list() if hasattr(value, "to_list") else value


def _in_layer(view_layer, obj) -> bool:
    return view_layer.objects.get(obj.name) == obj


class _Snapshot:
    """Everything this run may change on an object, recorded before the first write."""

    def __init__(self, view_layer):
        self._view_layer = view_layer
        self._saved = {}

    def remember(self, obj) -> None:
        key = obj.as_pointer()
        if key in self._saved:
            return
        hidden = (obj.hide_get(view_layer=self._view_layer)
                  if _in_layer(self._view_layer, obj) else None)
        self._saved[key] = (obj, {
            "parent": obj.parent, "parent_type": obj.parent_type,
            "parent_bone": obj.parent_bone, "inverse": obj.matrix_parent_inverse.copy(),
            "matrix": obj.matrix_world.copy(),
            "hidden": hidden, "hide_render": obj.hide_render,
            "stamps": {name: _copy_value(obj.get(name)) for name in _STAMPS},
        })

    def restore(self) -> None:
        # Every parent setter resets the parent inverse (ED_object_parent): write
        # only a relation this run changed, then put the saved inverse back.
        for obj, saved in self._saved.values():
            for attr in ("parent", "parent_type", "parent_bone"):
                if getattr(obj, attr) != saved[attr]:
                    setattr(obj, attr, saved[attr])
            obj.matrix_parent_inverse = saved["inverse"]
        self._view_layer.update()
        for obj, saved in self._saved.values():
            obj.matrix_world = saved["matrix"]
            if saved["hidden"] is not None:
                obj.hide_set(saved["hidden"], view_layer=self._view_layer)
            obj.hide_render = saved["hide_render"]
            for key, value in saved["stamps"].items():
                if value is not None:
                    obj[key] = value
                elif key in obj:
                    del obj[key]
        self._view_layer.update()


def _matrix(rows):
    from mathutils import Matrix

    return Matrix([list(map(float, row)) for row in np.asarray(rows, dtype=float)])


def _scene_objects(scene, names) -> list:
    found = (scene.objects.get(name) for name in names)
    return list(dict.fromkeys(obj for obj in found if obj is not None))


def _root(obj):
    """Walk up through EMPTY parents; an armature or mesh parent ends the walk."""
    while obj.parent is not None and obj.parent.type == 'EMPTY':
        obj = obj.parent
    return obj


def _ancestors(obj):
    parent = obj.parent
    while parent is not None:
        yield parent
        parent = parent.parent


def _family(root) -> list:
    return [root, *root.children_recursive]


def _live_assemble(scene, node_id: str) -> bool:
    from .node_graph import action_node_by_id

    node = action_node_by_id(scene, str(node_id or ""))
    return node is not None and node.action_type == 'ASSEMBLE'


def _resolve_body(scene, node):
    from .node_graph import action_node_by_id, mesh_source_object_names

    link = body_link(scene, node)
    if link is None:
        raise ValueError("Connect a body to Assemble")
    source = action_node_by_id(scene, link.from_node_id)
    if source is not None and source.action_type == 'ASSEMBLE':
        raise ValueError("Connect the rigged body itself, not another Assemble card")
    objects = _scene_objects(scene, mesh_source_object_names(scene, link.from_node_id))
    meshes = [obj for obj in objects if obj.type == 'MESH' and STAMP_OWNER not in obj]
    if not meshes:
        label = part_label(scene, link.from_node_id) or "the body card"
        raise ValueError(f"Generate '{label}' first — Assemble uses its result")
    arm = next((obj for obj in objects if obj.type == 'ARMATURE'), None)
    if arm is None:
        arm = next((found for found in (m.find_armature() for m in meshes) if found), None)
    if arm is not None:
        rigged = [mesh for mesh in meshes if mesh.parent == arm or any(
            mod.type == 'ARMATURE' and mod.object == arm for mod in mesh.modifiers)]
        meshes = rigged or meshes
    return link, arm, meshes


def _resolve_parts(scene, node, body_set) -> list:
    """One entry per connected part input: its label and rigid root group."""
    from .node_graph import action_node_by_id, mesh_source_object_names

    parts, claimed = [], set()
    for link in part_links(scene, node):
        entry = {"link": link, "label": part_label(scene, link.from_node_id),
                 "roots": [], "skip": ""}
        parts.append(entry)
        source = action_node_by_id(scene, link.from_node_id)
        if source is not None and source.action_type == 'ASSEMBLE':
            entry["skip"] = "connect the part's own card, not an Assemble card"
            continue
        for obj in _scene_objects(scene, mesh_source_object_names(scene, link.from_node_id)):
            root = _root(obj)
            # A body's own child meshes stay; a part this card attached last time does not.
            if obj in body_set or root in body_set or (STAMP_OWNER not in root and any(
                    parent in body_set for parent in _ancestors(root))):
                continue
            if root.as_pointer() not in claimed and root not in entry["roots"]:
                entry["roots"].append(root)
        # A mesh under another root of the part (a gem on its sword, a prop's
        # own armature) moves with that root: never a second root of its own.
        entry["roots"] = [root for root in entry["roots"] if not any(
            parent in entry["roots"] or parent.as_pointer() in claimed
            for parent in _ancestors(root))]
        owner = next((root.get(STAMP_OWNER) for root in entry["roots"]
                      if root.get(STAMP_OWNER) not in (None, node.node_id)
                      and _live_assemble(scene, root.get(STAMP_OWNER))), None)
        if owner is not None:
            entry["roots"] = []
            entry["skip"] = "attached by another Assemble card; disconnect it there first"
        elif not entry["roots"]:
            entry["skip"] = "not generated yet"
        claimed.update(root.as_pointer() for root in entry["roots"])
    return parts


def _validate(context, objects) -> None:
    scene, view_layer = context.scene, context.view_layer
    for obj in objects:
        if scene.objects.get(obj.name) != obj or view_layer.objects.get(obj.name) != obj:
            raise ValueError(f"'{obj.name}' is not in this view layer")
        if obj.mode != 'OBJECT':
            raise ValueError("Leave Pose/Edit mode first")


def _restore_rest(scene, view_layer, node, roots, snapshot) -> None:
    """Undo this card's previous run: unparent at rest, unhide, clear stamps."""
    stale = [root for root in roots if STAMP_OWNER in root
             and not _live_assemble(scene, root.get(STAMP_OWNER))]
    owned = [obj for obj in scene.objects if obj.get(STAMP_OWNER) == node.node_id]
    for obj in dict.fromkeys(owned + stale):
        snapshot.remember(obj)
        rest = _copy_value(obj.get(STAMP_REST))
        target = (_matrix(np.reshape(rest, (4, 4))) if rest is not None and len(rest) == 16
                  else obj.matrix_world.copy())
        obj.parent = None
        obj.parent_type = 'OBJECT'
        obj.parent_bone = ""
        obj.matrix_world = target
        for key in (STAMP_OWNER, STAMP_REST, STAMP_ATTACH):
            obj.pop(key, None)
    for obj in scene.objects:
        if obj.get(STAMP_HIDDEN) == node.node_id:
            snapshot.remember(obj)
            if _in_layer(view_layer, obj):
                obj.hide_set(False, view_layer=view_layer)
            obj.hide_render = False
            del obj[STAMP_HIDDEN]


@contextmanager
def _rest_pose(armature, view_layer):
    if armature is None:
        view_layer.update()
        yield
        return
    previous = armature.data.pose_position
    armature.data.pose_position = 'REST'
    try:
        view_layer.update()
        yield
    finally:
        armature.data.pose_position = previous
        view_layer.update()


def _evaluated_verts(objects, depsgraph) -> np.ndarray:
    chunks = []
    for obj in objects:
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            co = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
            mesh.vertices.foreach_get("co", co)
            world = np.array(evaluated.matrix_world, dtype=float)
        finally:
            evaluated.to_mesh_clear()
        chunks.append(transform_points(world, co.reshape(-1, 3).astype(np.float64)))
    return np.concatenate(chunks) if chunks else np.zeros((0, 3))


def _bone_infos(armature) -> list:
    world = np.array(armature.matrix_world, dtype=float)
    return [
        BoneInfo(bone.name, transform_points(world, tuple(bone.head_local))[0],
                 transform_points(world, tuple(bone.tail_local))[0],
                 bone.parent.name if bone.parent else "", bool(bone.use_deform))
        for bone in armature.data.bones
    ]


def _mesh_cast(obj, depsgraph, direction):
    """``cast(origin)`` for ``crossings``: the next crossing of *obj*'s evaluated
    mesh, cast in its local space (BVH rays hit front and back faces alike)."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree

    tree = BVHTree.FromObject(obj, depsgraph)
    world = np.array(obj.evaluated_get(depsgraph).matrix_world, dtype=float)
    inverse = np.linalg.inv(world)
    local = Vector((inverse[:3, :3] @ direction).tolist())

    def cast(origin):
        found = tree.ray_cast(Vector(transform_points(inverse, origin)[0].tolist()), local)[0]
        return None if found is None else transform_points(world, tuple(found))[0]
    return cast


def _surface_hit(slot, body, env):
    """The body's surface point on a surface slot's side, cast from inside the body."""
    query = surface_query(slot, body["sockets"], body["top"], body["height"], body["yaw"])
    if query is None:
        return None
    start, outward = ray_start(slot, body["sockets"], query[0]), query[1]
    distance = outer_surface([hit for obj in env["meshes"] for hit in crossings(
        _mesh_cast(obj, env["depsgraph"], outward), start, outward, body["height"])],
        body["height"])
    return None if distance is None else start + outward * distance


def _row(rows, kind, index, attr, default):
    row = rows.get(param_name(kind, index))
    return getattr(row, attr, default) if row is not None else default


def _attach(root, delta, parent, bone, view_layer, height) -> list:
    """Move *root* by *delta* from rest, parent it, and keep it in place."""
    rest = np.array(root.matrix_world, dtype=float)
    root.matrix_world = _matrix(delta @ rest)
    view_layer.update()
    placed = root.matrix_world.copy()
    root.parent = parent
    root.parent_type = 'BONE' if bone else 'OBJECT'
    if bone:
        root.parent_bone = bone
    view_layer.update()
    root.matrix_world = placed
    view_layer.update()
    drift = np.abs(np.array(root.matrix_world, dtype=float) - np.array(placed, dtype=float))
    if float(drift.max()) >= DRIFT_TOLERANCE * max(1.0, height):
        raise ValueError(f"Could not keep '{root.name}' in place while parenting")
    return [float(value) for value in rest.reshape(16)]


def _hide_source_body(scene, view_layer, node, link, keep, snapshot) -> None:
    """Hide the unrigged mesh an Auto Rig card imported a rigged copy of."""
    from .node_graph import action_node_by_id, input_source_object_names

    rig = action_node_by_id(scene, link.from_node_id)
    if rig is None or rig.action_type != 'AUTO_RIG':
        return
    for obj in _scene_objects(scene, input_source_object_names(scene, rig)):
        for member in _family(_root(obj)):
            if member in keep:
                continue
            snapshot.remember(member)
            if _in_layer(view_layer, member):
                member.hide_set(True, view_layer=view_layer)
            member.hide_render = True
            member[STAMP_HIDDEN] = node.node_id


def _summary(attached: int, skipped: int, rigged: bool) -> str:
    noun = "part" if attached == 1 else "parts"
    text = (f"No parts connected — the {'rigged ' if rigged else ''}body is the character"
            if attached == skipped == 0 else f"{attached} {noun} on bones" if rigged
            else f"{attached} {noun} placed — not rigged")
    return f"{text}, {skipped} skipped" if skipped else text


def _result_names(names) -> str:
    from ..constants import GRAPH_OBJECT_NAMES_MAXLEN

    names = list(dict.fromkeys(names))
    while names and len(", ".join(names)) > GRAPH_OBJECT_NAMES_MAXLEN:
        names.pop()
    return ", ".join(names)


def _place(part, rows, body, env) -> dict:
    """Plan and attach one part; its report row for ``params_json``."""
    link, roots, arm = part["link"], part["roots"], env["arm"]
    index = int(link.to_socket.partition(":")[2] or 0)
    record = {"socket": link.to_socket, "label": part["label"],
              "objects": [root.name for root in roots]}
    members = [m for root in roots for m in _family(root) if m.type == 'MESH']
    region = _row(rows, "slot", index, "value_enum", "AUTO") == "AUTO" and region_note(part["label"])
    if part["skip"] or region or not members:
        return {**record, "status": "skipped",
                "notes": [part["skip"] or region or "no mesh in this part"]}
    verts = _evaluated_verts(members, env["depsgraph"])
    settings = resolve_settings(
        part["label"], sorted_extents(verts),
        _row(rows, "slot", index, "value_enum", "AUTO"),
        _row(rows, "hold", index, "value_enum", "AUTO"),
        _row(rows, "size", index, "value_float", 0.0),
        _row(rows, "flip", index, "value_boolean", False))
    plan = plan_part(verts, settings, body, _surface_hit(settings.slot, body, env))
    notes = [*settings.warnings, *plan.notes]
    key = bone_key(settings.slot)
    bone, how = body["resolved"].get(key, ("", "estimated"))
    if arm is not None and not bone:
        bone = nearest_bone(body["resolved"], body["bones"], body["sockets"][key])
        notes.append("does not follow the arm")
    for root in roots:
        env["snapshot"].remember(root)
        rest = _attach(root, plan.delta, arm if arm is not None else env["meshes"][0],
                       bone if arm is not None else "", env["view_layer"], body["height"])
        root[STAMP_OWNER] = env["node_id"]
        root[STAMP_REST] = rest
        root[STAMP_ATTACH] = json.dumps(
            {"slot": settings.slot, "hold": settings.hold, "bone": bone,
             "size_pct": settings.size_pct, "flip": settings.flip}, sort_keys=True)
    return {**record, "status": "attached", "slot": settings.slot,
            "slot_guessed": settings.slot_guessed, "hold": settings.hold, "bone": bone,
            "bone_how": how if arm is not None else "estimated",
            "size_m": round(plan.size_m, 4), "size_pct": round(settings.size_pct, 2),
            "notes": notes}


def _assemble(context, node, snapshot) -> None:
    scene, view_layer = context.scene, context.view_layer
    link, arm, meshes = _resolve_body(scene, node)
    body_set = set(meshes) | ({arm} if arm is not None else set())
    parts = _resolve_parts(scene, node, body_set)
    roots = [root for part in parts for root in part["roots"]]
    _validate(context, [*meshes, *([arm] if arm is not None else []), *roots])

    _restore_rest(scene, view_layer, node, roots, snapshot)
    env = {"arm": arm, "meshes": meshes, "depsgraph": context.evaluated_depsgraph_get(),
           "view_layer": view_layer, "snapshot": snapshot, "node_id": node.node_id}
    rows = {parameter.name: parameter for parameter in node.parameters}
    with _rest_pose(arm, view_layer):
        body = measure_body(_evaluated_verts(meshes, env["depsgraph"]),
                            _bone_infos(arm) if arm is not None else [])
        records = [_place(part, rows, body, env) for part in parts]
        keep = set(body_set).union(*(_family(root) for root in roots))
        _hide_source_body(scene, view_layer, node, link, keep, snapshot)

    from .node_graph import create_asset_result

    attached = sum(1 for record in records if record["status"] == "attached")
    body_names = [mesh.name for mesh in meshes]
    create_asset_result(scene, node, _result_names(
        body_names + ([arm.name] if arm is not None else []) + [root.name for root in roots]))
    node.params_json = json.dumps({
        "version": 1, "rigged": arm is not None, "armature": arm.name if arm is not None else "",
        "body": body_names, "height_m": round(body["height"], 4), "yaw_deg": round(body["yaw"], 2),
        "summary": _summary(attached, len(records) - attached, arm is not None),
        "parts": records,
    }, separators=(",", ":"))
    node.state = 'SUCCESS'
    node.edit_mode = False
    node.error = ""


def run_assemble_node(context, node) -> None:
    """Attach the connected parts; raise ValueError after undoing any change."""
    snapshot = _Snapshot(context.view_layer)
    try:
        _assemble(context, node, snapshot)
    except Exception as exc:
        try:
            snapshot.restore()
        except Exception:
            logger.exception("Assemble rollback failed")
        if isinstance(exc, ValueError):
            raise
        raise ValueError(str(exc) or type(exc).__name__) from exc
    from mixar.modules.common.utils.undo import push_undo_step

    push_undo_step("Assemble Character")

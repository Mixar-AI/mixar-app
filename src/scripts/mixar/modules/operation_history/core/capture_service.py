# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Manual user-operation capture: depsgraph -> dirty scene queue -> timer drain.

Follows the Mixar handler pattern (scene_graph/core/watcher.py + paint ui_handlers.py):
the depsgraph handler only marks dirty scenes; the timer does the diff + attribution + record.
Manual ops are recorded whenever the agent is NOT actively executing (so edits made before
any chat session — the common "I built this, now ask the agent" flow — are captured), and
keyed by the scene's persistent history id (not the chat session). Agent operations are
captured separately at the script executor, so the IDLE-vs-busy gate avoids double-counting.
"""

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger

from ...space_mixie_chat.constants import SessionState
from ...space_mixie_chat.core.session import get_session_manager
from ..constants import CAT_MATERIAL, CAT_OBJECT, CAT_UNDO
from . import store
from .record import build_manual_record, category_for_operator
from .scene_diff import diff_snapshots, snapshot_scene
from .scene_key import get_scene_history_id

logger = get_logger(__name__)

# Session states in which the agent itself is actively driving the scene; manual capture
# pauses only then. AWAITING_INPUT is a user-facing pause, so manual edits there are recorded.
_AGENT_ACTIVE = (SessionState.BUSY, SessionState.MODIFYING)

_dirty_scene_names = set()
_dirty_context_scene = False
_prev: dict = {}          # history_id -> last snapshot


def should_capture(state) -> bool:
    return state not in _AGENT_ACTIVE


@persistent
def _on_depsgraph(scene, depsgraph):
    try:
        if any(depsgraph.id_type_updated(t) for t in ('OBJECT', 'MESH', 'MATERIAL', 'NODETREE')):
            _mark_dirty_scene(scene)
    except Exception:
        _mark_dirty_scene(scene)


def _mark_dirty_scene(scene):
    global _dirty_context_scene
    if scene is None:
        try:
            scene = getattr(bpy.context, 'scene', None)
        except Exception:
            scene = None
    name = getattr(scene, 'name', None)
    if name:
        _dirty_scene_names.add(name)
    else:
        _dirty_context_scene = True


def _context_scene():
    try:
        return getattr(bpy.context, 'scene', None)
    except Exception:
        return None


def _resolve_dirty_scene(name):
    if not name:
        return _context_scene()
    try:
        scenes = getattr(getattr(bpy, 'data', None), 'scenes', None)
    except Exception:
        scenes = None
    if scenes is None:
        return _context_scene()
    try:
        get_scene = getattr(scenes, 'get', None)
        if callable(get_scene):
            return get_scene(name)
    except Exception:
        return _context_scene()
    try:
        for scene in scenes:
            if getattr(scene, 'name', None) == name:
                return scene
    except Exception:
        return _context_scene()
    return None


def _attribution():
    try:
        wm = getattr(bpy.context, 'window_manager', None)
        if wm and len(wm.operators):
            op = wm.operators[-1]
            return op.bl_idname, str(op.as_pointer())
    except Exception:
        pass
    return None, None


def _names(names):
    names = list(names or [])
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return "{} and {}".format(names[0], names[1])
    return "{}, and {} others".format(names[0], len(names) - 1)


def _format_mesh_delta(mesh_delta):
    labels = (("vertices", "vertex", "vertices"), ("edges", "edge", "edges"),
              ("faces", "face", "faces"))
    parts = []
    for key, singular, plural in labels:
        value = int(mesh_delta.get(key, 0) or 0)
        if value:
            noun = singular if abs(value) == 1 else plural
            parts.append("{:+d} {}".format(value, noun))
    return ", ".join(parts)


def _mesh_change_label(delta):
    changes = delta.get("object_changes") or {}
    mesh_rows = []
    for name, info in changes.items():
        mesh_delta = (info or {}).get("mesh_delta") or {}
        if mesh_delta:
            mesh_rows.append((name, mesh_delta))
    if not mesh_rows:
        return None
    name, mesh_delta = mesh_rows[0]
    values = [int(v or 0) for v in mesh_delta.values()]
    all_positive = values and all(v >= 0 for v in values) and any(v > 0 for v in values)
    all_negative = values and all(v <= 0 for v in values) and any(v < 0 for v in values)
    detail = _format_mesh_delta(mesh_delta)
    suffix = " ({})".format(detail) if detail else ""
    extra = "" if len(mesh_rows) == 1 else " and {} others".format(len(mesh_rows) - 1)
    if all_positive:
        return "extruded or added mesh geometry to {}{}{}".format(name, extra, suffix)
    if all_negative:
        return "removed mesh geometry from {}{}{}".format(name, extra, suffix)
    return "edited mesh topology on {}{}{}".format(name, extra, suffix)


def _material_label(delta, mats):
    changes = delta.get("material_changes") or {}
    if changes:
        name = sorted(changes)[0]
        node_delta = int((changes[name] or {}).get("nodes_delta", 0) or 0)
        suffix = " ({:+d} node{})".format(node_delta, "" if abs(node_delta) == 1 else "s") if node_delta else ""
        extra = "" if len(changes) == 1 else " and {} others".format(len(changes) - 1)
        return "edited material {}{}{}".format(name, extra, suffix)
    return "edited material {}".format(_names(mats))


def _operator_label(idname, affected_objects):
    name = (idname or "").lower()
    target = _names(affected_objects)
    if name.startswith("transform.translate"):
        return "moved {}".format(target) if target else "moved objects"
    if name.startswith("transform.resize"):
        return "scaled {}".format(target) if target else "scaled objects"
    if name.startswith("transform.rotate"):
        return "rotated {}".format(target) if target else "rotated objects"
    if "extrude" in name:
        return "extruded {}".format(target) if target else "extruded mesh geometry"
    if name.startswith("object.delete"):
        return "deleted {}".format(target) if target else "deleted objects"
    if name.startswith("object.") and affected_objects:
        return "{} {}".format(name.replace("_", " "), target)
    if idname:
        return "{} {}".format(idname, target).strip()
    return "manual edit {}".format(target).strip()


def _record_delta(delta):
    out = {"created": delta["created"], "modified": delta["modified"],
           "deleted": delta["deleted"]}
    if delta.get("object_changes"):
        out["object_changes"] = delta["object_changes"]
    for key in ("materials_created", "materials_modified", "materials_deleted",
                "material_changes"):
        if delta.get(key):
            out[key] = delta[key]
    return out


def _capture_scene(scene):
    sid = get_scene_history_id(scene)
    snap = snapshot_scene(scene)
    state = get_session_manager().get_state(scene)
    if not should_capture(state):
        _prev[sid] = snap            # keep baseline fresh without recording (agent is acting)
        return
    before = _prev.get(sid)
    _prev[sid] = snap
    if before is None:
        return
    delta = diff_snapshots(before, snap)
    obj_changed = bool(delta["created"] or delta["modified"] or delta["deleted"])
    mats = sorted(set(delta.get("materials_created", []))
                  | set(delta.get("materials_modified", []))
                  | set(delta.get("materials_deleted", [])))
    if not (obj_changed or mats):
        return
    idname, ptr = _attribution()
    del ptr  # attribution pointer is not stable enough to use for deduplication.
    affected = {
        "objects": sorted(set(delta["created"]) | set(delta["modified"]) | set(delta["deleted"])),
        "materials": mats, "layers": [],
    }
    mesh_label = _mesh_change_label(delta)
    if obj_changed:
        category = CAT_OBJECT if mesh_label else category_for_operator(idname)
        label = "User: {}".format(mesh_label or _operator_label(idname, affected["objects"]))
    else:
        category = CAT_MATERIAL
        label = "User: {}".format(_material_label(delta, mats))
    store.append_operation(build_manual_record(
        scene_delta=_record_delta(delta),
        op_idname=idname, label=label, category=category,
        affected=affected, session_id=sid,
    ))


def _capture_tick():
    global _dirty_context_scene
    if not _dirty_scene_names and not _dirty_context_scene:
        return 0.5
    dirty_names = sorted(_dirty_scene_names)
    capture_context = _dirty_context_scene
    _dirty_scene_names.clear()
    _dirty_context_scene = False

    scenes = []
    for name in dirty_names:
        scene = _resolve_dirty_scene(name)
        if scene is not None:
            scenes.append(scene)
    if capture_context:
        scene = _context_scene()
        if scene is not None:
            scenes.append(scene)

    seen = set()
    for scene in scenes:
        key = getattr(scene, 'name', None) or id(scene)
        if key in seen:
            continue
        seen.add(key)
        try:
            _capture_scene(scene)
        except Exception as e:
            logger.debug("operation_history capture tick failed: %s", e)
    return 0.5


def _record_undo(scene, idname, label):
    try:
        sid = get_scene_history_id(scene)
        if not should_capture(get_session_manager().get_state(scene)):
            return
        store.append_operation(build_manual_record(
            scene_delta=None, op_idname=idname, label=label, category=CAT_UNDO, session_id=sid))
        _prev[sid] = snapshot_scene(scene)   # reset baseline after undo/redo
    except Exception:
        pass


@persistent
def _on_undo(scene):
    _record_undo(scene, "ed.undo", "User: undo")


@persistent
def _on_redo(scene):
    _record_undo(scene, "ed.redo", "User: redo")


@persistent
def _on_load(*_args):
    global _dirty_context_scene
    _dirty_context_scene = False
    _dirty_scene_names.clear()
    _prev.clear()
    store.reset_cache()


_HANDLERS = (
    (lambda: bpy.app.handlers.depsgraph_update_post, _on_depsgraph),
    (lambda: bpy.app.handlers.undo_post, _on_undo),
    (lambda: bpy.app.handlers.redo_post, _on_redo),
    (lambda: bpy.app.handlers.load_post, _on_load),
)


def register():
    for getter, fn in _HANDLERS:
        hl = getter()
        if fn not in hl:
            hl.append(fn)
    if not bpy.app.timers.is_registered(_capture_tick):
        bpy.app.timers.register(_capture_tick, first_interval=1.0, persistent=True)


def unregister():
    for getter, fn in _HANDLERS:
        hl = getter()
        if fn in hl:
            hl.remove(fn)
    try:
        if bpy.app.timers.is_registered(_capture_tick):
            bpy.app.timers.unregister(_capture_tick)
    except Exception:
        pass

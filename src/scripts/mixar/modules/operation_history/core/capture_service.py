# SPDX-License-Identifier: GPL-3.0-or-later
"""Manual user-operation capture: depsgraph -> dirty flag -> timer drain.

Follows the Mixar handler pattern (scene_graph/core/watcher.py + paint ui_handlers.py):
the depsgraph handler only sets a flag; the timer does the diff + attribution + record.
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
from ..constants import CAT_MATERIAL, CAT_UNDO
from . import store
from .record import build_manual_record, category_for_operator
from .scene_diff import diff_snapshots, snapshot_scene
from .scene_key import get_scene_history_id

logger = get_logger(__name__)

# Session states in which the agent itself is driving the scene; manual capture pauses then.
_AGENT_ACTIVE = (SessionState.BUSY, SessionState.MODIFYING, SessionState.AWAITING_INPUT)

_dirty = False
_prev: dict = {}          # history_id -> last snapshot
_last_op: dict = {}       # history_id -> (bl_idname, pointer)


def should_capture(state) -> bool:
    return state not in _AGENT_ACTIVE


@persistent
def _on_depsgraph(scene, depsgraph):
    global _dirty
    try:
        if any(depsgraph.id_type_updated(t) for t in ('OBJECT', 'MATERIAL', 'NODETREE')):
            _dirty = True
    except Exception:
        _dirty = True


def _attribution():
    try:
        wm = getattr(bpy.context, 'window_manager', None)
        if wm and len(wm.operators):
            op = wm.operators[-1]
            return op.bl_idname, str(op.as_pointer())
    except Exception:
        pass
    return None, None


def _capture_tick():
    global _dirty
    if not _dirty:
        return 0.5
    _dirty = False
    try:
        scene = getattr(bpy.context, 'scene', None)
        if scene is None:
            return 0.5
        sid = get_scene_history_id(scene)
        snap = snapshot_scene(scene)
        state = get_session_manager().get_state(scene)
        if not should_capture(state):
            _prev[sid] = snap            # keep baseline fresh without recording (agent is acting)
            return 0.5
        before = _prev.get(sid)
        _prev[sid] = snap
        if before is None:
            return 0.5
        delta = diff_snapshots(before, snap)
        obj_changed = bool(delta["created"] or delta["modified"] or delta["deleted"])
        mats = sorted(set(delta.get("materials_created", []))
                      | set(delta.get("materials_modified", []))
                      | set(delta.get("materials_deleted", [])))
        if not (obj_changed or mats):
            return 0.5
        idname, ptr = _attribution()
        if idname and _last_op.get(sid) == (idname, ptr):
            return 0.5                    # same operator invocation already recorded
        _last_op[sid] = (idname, ptr)
        affected = {
            "objects": sorted(set(delta["created"]) | set(delta["modified"]) | set(delta["deleted"])),
            "materials": mats, "layers": [],
        }
        if obj_changed:
            category = category_for_operator(idname)
            label = "User: {}".format(idname or "manual edit")
        else:
            category = CAT_MATERIAL
            label = "User: {}".format(idname or "material edit")
        store.append_operation(build_manual_record(
            scene_delta={"created": delta["created"], "modified": delta["modified"],
                         "deleted": delta["deleted"]},
            op_idname=idname, label=label, category=category,
            affected=affected, session_id=sid,
        ))
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
    global _dirty
    _dirty = False
    _prev.clear()
    _last_op.clear()
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

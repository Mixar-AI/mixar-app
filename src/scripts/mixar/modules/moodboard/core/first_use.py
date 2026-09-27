# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Board-owned onboarding history. Rendering only reads this state."""

import bpy
from bpy.app.handlers import persistent

from .canvas_context import MOODBOARD_CONTENT_COLLECTIONS

_KEY = "_mixie_moodboard_started"
_seen = set()
_pending = {}


def started(scene):
    """Undo may restore older ID properties; session history remains monotonic."""
    return bool(scene.get(_KEY, False) or scene.session_uid in _seen)


def mark_started(scene):
    _seen.add(scene.session_uid)
    if not scene.get(_KEY, False) and scene.is_editable:
        scene[_KEY] = True


def begin_preview(scene, collection):
    """A modal preview is not a successful first edit until confirmed."""
    key = (scene.session_uid, collection)
    _pending[key] = _pending.get(key, 0) + 1


def end_preview(scene, collection, *, committed=False):
    key = (scene.session_uid, collection)
    remaining = _pending.get(key, 1) - 1
    if remaining:
        _pending[key] = remaining
    else:
        _pending.pop(key, None)
    if committed:
        mark_started(scene)


def observe_scene(scene):
    if started(scene) or any(
        len(getattr(scene, name, ())) > _pending.get((scene.session_uid, name), 0)
        for name in MOODBOARD_CONTENT_COLLECTIONS
    ):
        mark_started(scene)


def tick():
    # No RNA references retained across file loads or undo. Imported/agent
    # content and older projects are covered as well as explicit UI edits.
    live = set()
    for scene in bpy.data.scenes:
        live.add(scene.session_uid)
        observe_scene(scene)
    _seen.intersection_update(live)
    for key in list(_pending):
        if key[0] not in live:
            _pending.pop(key, None)
    return 0.2


@persistent
def reset_after_load(_dummy):
    _seen.clear()
    _pending.clear()


@persistent
def before_save(_dummy):
    # Persist monotonic history even if Save immediately follows Undo.
    tick()


def register():
    for handlers, callback in ((bpy.app.handlers.load_post, reset_after_load),
                               (bpy.app.handlers.save_pre, before_save)):
        if callback not in handlers:
            handlers.append(callback)
    if not bpy.app.timers.is_registered(tick):
        bpy.app.timers.register(tick, first_interval=0.2, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(tick):
        bpy.app.timers.unregister(tick)
    for handlers, callback in ((bpy.app.handlers.load_post, reset_after_load),
                               (bpy.app.handlers.save_pre, before_save)):
        if callback in handlers:
            handlers.remove(callback)
    _seen.clear()
    _pending.clear()

# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Toolbar browser lifetime and cached discovery, independent of drawing."""
import time

import bpy
from bpy.app.handlers import persistent

from ..constants import BASIC_WORKSPACE_NAME
from . import animation_catalog as catalog, animation_preview as preview

_host = None  # (window, area) pointers; RNA for either may be freed between ticks
_signature = None
_scan = None
_owner = object()


def invalidate(_owner=None, _context=None):
    global _signature
    _signature = None
    if not bpy.app.timers.is_registered(_watch):
        bpy.app.timers.register(_watch, first_interval=.05)


def open_browser(context):
    global _host
    _host = (context.window.as_pointer(), context.area.as_pointer())
    invalidate()
    _watch()
    if not bpy.app.timers.is_registered(_watch):
        bpy.app.timers.register(_watch, first_interval=.05)


def close():
    global _host, _scan
    preview.stop()
    _host = None
    _scan = None
    invalidate()


def _refresh(state, target):
    state.clips.clear()
    state.active_index = 0
    state.target_name = target.name if target else ''
    state.loading = True
    query = state.search.casefold().strip()
    for entry in catalog.entries(target, bpy.data.actions, state.scope == 'ALL'):
        if not query or query in entry['action_name'].casefold():
            row = state.clips.add()
            for key, value in entry.items():
                setattr(row, key, value)
            session = preview.current()
            if (session and session.action.name == row.action_name
                    and (session.slot.handle if session.slot else 0) == row.slot_handle):
                state.active_index = len(state.clips) - 1
        yield
    state.loading = False


def _watch():
    global _signature, _scan, _host
    if not _host:
        _host = next(((w.as_pointer(), a.as_pointer())
                      for w in bpy.context.window_manager.windows
                      if w.workspace.name == BASIC_WORKSPACE_NAME
                      for a in w.screen.areas if a.type == 'VIEW_3D'), None)
        if not _host:
            return None
    window, area = preview.find_host(*_host)
    try:
        if (window is None or window.workspace.name != BASIC_WORKSPACE_NAME
                or area.type != 'VIEW_3D'):
            close()
            return None
        state = bpy.context.window_manager.mixar_animations
        session = preview.current()
        with bpy.context.temp_override(window=window, area=area):
            target = session.target if session else catalog.selected_target(bpy.context)
        signature = (target.as_pointer() if target else 0, state.search, state.scope,
                     len(bpy.data.actions), tuple((b.action.name, b.action_slot_handle)
                                                 for b in catalog.bindings(target)))
        if signature != _signature:
            _signature = signature
            _scan = _refresh(state, target)
        if _scan:
            deadline = time.perf_counter() + .004
            while time.perf_counter() < deadline:
                try:
                    next(_scan)
                except StopIteration:
                    _scan = None
                    break
            area.tag_redraw()
            window.mixar_refresh_popover("MIXAR_PT_animations")
        return .02 if _scan else None
    except (ReferenceError, RuntimeError):
        close()
        return None


@persistent
def before_save(_unused):
    preview.stop(resume=False)


@persistent
def before_reset(_unused):
    close()


def _subscribe():
    bpy.msgbus.clear_by_owner(_owner)
    for key in ((bpy.types.LayerObjects, 'active'), (bpy.types.Window, 'scene'),
                (bpy.types.Window, 'workspace')):
        bpy.msgbus.subscribe_rna(key=key, owner=_owner, args=(), notify=invalidate,
                                options={'PERSISTENT'})
    invalidate()


@persistent
def after_load(_unused):
    _subscribe()


def register():
    _subscribe()
    for handlers, callback in (
        (bpy.app.handlers.save_pre, before_save),
        (bpy.app.handlers.load_pre, before_reset),
        (bpy.app.handlers.undo_pre, before_reset),
        (bpy.app.handlers.redo_pre, before_reset),
        (bpy.app.handlers.load_post, after_load),
    ):
        if callback not in handlers:
            handlers.append(callback)


def unregister():
    bpy.msgbus.clear_by_owner(_owner)
    close()
    if bpy.app.timers.is_registered(_watch):
        bpy.app.timers.unregister(_watch)
    for handlers, callback in (
        (bpy.app.handlers.save_pre, before_save),
        (bpy.app.handlers.load_pre, before_reset),
        (bpy.app.handlers.undo_pre, before_reset),
        (bpy.app.handlers.redo_pre, before_reset),
        (bpy.app.handlers.load_post, after_load),
    ):
        if callback in handlers:
            handlers.remove(callback)

# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Browser host binding and cached discovery, independent of drawing.

The host is the window/area the popover was last drawn in, kept as
``as_pointer()`` values and re-resolved on every use: freed wmWindow/ScrArea
RNA is not invalidated, so a held reference would be a use-after-free.
"""
import time

import bpy
from bpy.app.handlers import persistent

from ..constants import BASIC_WORKSPACE_NAME
from . import animation_catalog as catalog

_host = None  # (window, area) pointers
_signature = None
_scan = None
_owner = object()


def find_host(window_ptr, area_ptr):
    """(window, area) still open at these addresses, else (None, None)."""
    for window in bpy.context.window_manager.windows:
        if window.as_pointer() == window_ptr:
            area = next((a for a in window.screen.areas if a.as_pointer() == area_ptr), None)
            return (window, area) if area is not None else (None, None)
    return None, None


def host():
    return find_host(*_host) if _host else (None, None)


def bind(context):
    """Called by the popover's draw: discovery follows the popover's own host.

    Only module state changes here; the scan itself runs from a timer.
    """
    global _host
    if context.window is None or context.area is None:
        return
    pointers = (context.window.as_pointer(), context.area.as_pointer())
    if pointers != _host:
        _host = pointers
        invalidate()


def invalidate(_owner=None, _context=None):
    global _signature
    _signature = None
    if _host and not bpy.app.timers.is_registered(_watch):
        bpy.app.timers.register(_watch, first_interval=.05)


def close():
    global _host, _scan, _signature
    _host = None
    _scan = None
    _signature = None


def _key(row):
    return (row.action_name, row.slot_handle, row.track_name, row.strip_name)


def _refresh(state, target):
    clips = state.clips
    active = (_key(clips[state.active_index])
              if 0 <= state.active_index < len(clips) else None)
    clips.clear()
    state.active_index = 0
    state.target_name = target.name if target else ''
    state.loading = True
    query = state.search.casefold().strip()
    for entry in catalog.entries(target, bpy.data.actions, state.scope == 'ALL'):
        if not query or query in entry['action_name'].casefold():
            row = clips.add()
            for key, value in entry.items():
                setattr(row, key, value)
            if _key(row) == active:
                state.active_index = len(clips) - 1
        yield
    state.loading = False


def _nla_signature(target):
    anim = getattr(target, 'animation_data', None)
    if anim is None:
        return ()
    return ((anim.action.name if anim.action else '', anim.action_slot_handle),
            tuple((track.name, tuple(strip.name for strip in track.strips))
                  for track in anim.nla_tracks))


def _watch():
    global _signature, _scan
    window, area = host()
    try:
        if (window is None or window.workspace.name != BASIC_WORKSPACE_NAME
                or area.type != 'VIEW_3D'):
            close()
            return None
        state = bpy.context.window_manager.mixar_animations
        with bpy.context.temp_override(window=window, area=area):
            target = catalog.selected_target(bpy.context)
        signature = (target.as_pointer() if target else 0, state.search, state.scope,
                     len(bpy.data.actions), _nla_signature(target))
        if signature != _signature:
            _signature = signature
            _scan = _refresh(state, target)
        if _scan:
            # Tags only the popover; its count of 0 means the browser closed, so
            # stop scanning and unbind: the next popover draw binds and rescans.
            if not window.mixar_refresh_popover("MIXAR_PT_animations"):
                close()
                return None
            deadline = time.perf_counter() + .004
            while time.perf_counter() < deadline:
                try:
                    next(_scan)
                except StopIteration:
                    _scan = None
                    break
        return .02 if _scan else None
    except (ReferenceError, RuntimeError):
        close()
        return None


@persistent
def after_data_change(_unused):
    """Undo/redo can add or remove strips; rescan instead of drawing stale rows."""
    invalidate()


@persistent
def before_load(_unused):
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


_HANDLERS = (
    ('load_pre', before_load),
    ('load_post', after_load),
    ('undo_post', after_data_change),
    ('redo_post', after_data_change),
)


def register():
    _subscribe()
    for name, callback in _HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if callback not in handlers:
            handlers.append(callback)


def unregister():
    bpy.msgbus.clear_by_owner(_owner)
    close()
    if bpy.app.timers.is_registered(_watch):
        bpy.app.timers.unregister(_watch)
    for name, callback in _HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if callback in handlers:
            handlers.remove(callback)

# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""NLA-style preview: the clip temporarily drives the real target in its scene.

Like the NLA editor's preview, Play assigns the clip to the target (the rig of
a skinned mesh) without an undo push; Stop restores the snapshot taken first
(``animation_snapshot``), the frame/subframe, rig visibility and prior playback.
Switching clips keeps that original snapshot. Save, load, undo/redo, editing
keys and leaving Zen stop the preview. The browser may close while playback
continues; the toolbar always keeps Pause and Stop.

The session keeps ID references and window/area *pointers*: raw wmWindow and
ScrArea RNA is not invalidated when freed, so both are re-resolved on use.
"""
import time
from types import SimpleNamespace

import bpy
from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_

from . import animation_catalog as catalog
from . import animation_snapshot as snapshots

_session = None
_logger = get_logger(__name__)


def current():
    return _session


def find_host(window_ptr, area_ptr):
    """(window, area) still open at these addresses, else (None, None)."""
    for window in bpy.context.window_manager.windows:
        if window.as_pointer() == window_ptr:
            area = next((a for a in window.screen.areas if a.as_pointer() == area_ptr), None)
            return (window, area) if area is not None else (None, None)
    return None, None


def host(session=None):
    session = session or _session
    return find_host(session.window_ptr, session.area_ptr) if session else (None, None)


def is_host(context):
    session = _session
    return bool(session and context.window and context.area
                and session.window_ptr == context.window.as_pointer()
                and session.area_ptr == context.area.as_pointer())


def _alive(obj):
    try:
        return obj is not None and bool(obj.name)
    except ReferenceError:
        return False


def _playback(window, start):
    with bpy.context.temp_override(window=window):
        if window.screen.is_animation_playing:
            bpy.ops.screen.animation_cancel(restore_frame=False)
        if start:
            bpy.ops.screen.animation_play()


def _view_layer(session):
    return session.scene.view_layers.get(session.layer_name)


def start(context, action_name, slot_handle):
    global _session
    previous = _session
    window, area = context.window, context.area
    # A clip switch carries the session's snapshot only within its own view layer.
    if previous is not None and not (
            window is not None and _alive(previous.target)
            and previous.scene == window.scene
            and previous.layer_name == window.view_layer.name):
        stop()
        previous = None
    # Everything that can refuse runs before the first mutation.
    target = previous.target if previous else catalog.selected_target(context)
    action = bpy.data.actions.get(action_name)
    slot = catalog.resolve(action, slot_handle)
    fcurves = catalog.curves(action, slot)
    reason = catalog.compatibility(target, slot, fcurves)
    if reason:
        raise ValueError(reason)
    if target.animation_data is not None and target.animation_data.use_tweak_mode:
        raise ValueError(n_("Leave NLA tweak mode to preview animations"))
    if window is None or area is None or area.type != 'VIEW_3D':
        raise ValueError(n_("Open a 3D viewport to preview animations"))
    scene, layer = window.scene, window.view_layer
    first, last = catalog.clip_range(action, fcurves)
    state = context.window_manager.mixar_animations
    rig = target.type == 'ARMATURE'
    if previous is None:
        session = SimpleNamespace(
            snapshot=snapshots.capture(target, scene, fcurves),
            was_playing=window.screen.is_animation_playing,
            rig_hidden=rig and target.hide_get(view_layer=layer),
            rig_selected=rig and target.select_get(view_layer=layer),
            control_object=context.view_layer.objects.active)
    else:
        # Keep the original snapshot; only channels this clip adds are read.
        snapshots.extend(previous.snapshot, target, fcurves)
        session = SimpleNamespace(
            snapshot=previous.snapshot, was_playing=previous.was_playing,
            rig_hidden=previous.rig_hidden, rig_selected=previous.rig_selected,
            control_object=previous.control_object)
    # A new namespace per clip retires the previous transport modal.
    session.__dict__.update(
        target=target, scene=scene, layer_name=layer.name,
        workspace=window.workspace, window_ptr=window.as_pointer(),
        area_ptr=area.as_pointer(), action=action, slot=slot,
        first=first, last=max(first, last), paused=False,
        origin=time.monotonic(), offset=0.0, frame=None, last_refresh=0.0)
    try:
        _session = session
        if previous is None:
            _playback(window, False)
        snapshots.assign(target, action, slot)
        scene.frame_set(int(first), subframe=first % 1)
        session.frame = int(first)
        update_rig_visibility()
        state.error = False
        state.preview_name = action.name
        state.active_index = next((i for i, item in enumerate(state.clips)
                                   if item.action_name == action.name
                                   and item.slot_handle == slot_handle), 0)
        state.playing = True
        if not bpy.app.timers.is_registered(_tick):
            bpy.app.timers.register(_tick, first_interval=0.01)
        window.mixar_refresh_popover("MIXAR_PT_animations")
    except Exception:
        stop()
        raise


def update_rig_visibility(_owner=None, _context=None):
    """Hide Rig hides only the armature's display; deformation keeps evaluating."""
    session = _session
    try:
        if session is None or session.target.type != 'ARMATURE':
            return
        layer = _view_layer(session)
        hide = bpy.context.window_manager.mixar_animations.hide_rig or session.rig_hidden
        if layer is not None and session.target.hide_get(view_layer=layer) != hide:
            session.target.hide_set(hide, view_layer=layer)
    except ReferenceError:
        return
    _window, area = host()
    if area is not None:
        area.tag_redraw()


def _restore_rig(session):
    layer = _view_layer(session)
    target = session.target
    if layer is None or target.type != 'ARMATURE':
        return
    if target.hide_get(view_layer=layer) != session.rig_hidden:
        target.hide_set(session.rig_hidden, view_layer=layer)
        # Hidden objects lose selection; a selected rig comes back selected.
        if session.rig_selected and not session.rig_hidden:
            target.select_set(True, view_layer=layer)


def _tick():
    session = _session
    if session is None:
        return None
    try:
        window, area = host()
        if (window is None or window.workspace != session.workspace
                or window.scene != session.scene or area.type != 'VIEW_3D'
                or not _alive(session.target)
                or not (session.control_object is None or _alive(session.control_object))):
            stop()
            return None
        if session.paused:
            return .25
        state = bpy.context.window_manager.mixar_animations
        fps = session.scene.render.fps / session.scene.render.fps_base
        elapsed = (time.monotonic() - session.origin) * fps + session.offset
        span = session.last - session.first
        if elapsed > span and not state.loop:
            elapsed = span
            session.paused = True
            state.playing = False
        frame = session.first + (elapsed % (span + 1) if state.loop else elapsed)
        frame = min(session.last, frame)
        if int(frame) != session.frame:
            session.scene.frame_set(int(frame))
            session.frame = int(frame)
        if time.monotonic() - session.last_refresh >= .1:
            window.mixar_refresh_popover("MIXAR_PT_animations")
            session.last_refresh = time.monotonic()
        return min(1 / fps, 1 / 30)
    except Exception:
        _logger.exception('Animation preview failed')
        stop()
        bpy.context.window_manager.mixar_animations.error = True
        return None


def pause():
    session = _session
    if session is None:
        return
    session.paused = not session.paused
    session.offset = session.scene.frame_current - session.first
    if not session.paused and session.offset >= session.last - session.first:
        session.offset = 0
    session.origin = time.monotonic()
    bpy.context.window_manager.mixar_animations.playing = not session.paused
    window, _area = host()
    if window is not None:
        window.mixar_refresh_popover("MIXAR_PT_animations")


def position():
    session = _session
    if not session or session.last <= session.first:
        return 0.0
    try:
        return (session.scene.frame_current - session.first) / (session.last - session.first)
    except ReferenceError:
        return 0.0


def seek(value):
    session = _session
    if session:
        session.offset = value * (session.last - session.first)
        session.origin = time.monotonic()
        session.frame = round(session.first + session.offset)
        session.scene.frame_set(session.frame)


def stop(*, resume=True):
    """Restore everything the preview changed. Never raises; always clears."""
    global _session
    session, _session = _session, None
    if session is None:
        return
    window = None
    try:
        window, _area = host(session)
        if window is not None:
            _playback(window, False)
    except Exception:
        _logger.exception('Could not cancel animation preview playback')
    try:
        if not snapshots.restore(session.snapshot, session.target, session.scene):
            _logger.warning('Animation preview restored only part of the original state')
    except Exception:
        _logger.exception('Could not restore the original animation')
    try:
        _restore_rig(session)
    except ReferenceError:
        pass
    except Exception:
        _logger.exception('Could not restore rig visibility')
    try:
        if (resume and session.was_playing and window is not None
                and window.scene == session.scene):
            _playback(window, True)
    except Exception:
        _logger.exception('Could not resume playback after animation preview')
    state = getattr(bpy.context.window_manager, 'mixar_animations', None)
    if state:
        state.preview_name = ''
        state.playing = False
    try:
        if window is not None:
            window.mixar_refresh_popover("MIXAR_PT_animations")
    except ReferenceError:
        pass


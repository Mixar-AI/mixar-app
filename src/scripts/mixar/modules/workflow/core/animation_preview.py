# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Disposable, time-budgeted scene preview. Source animation is never assigned.

The original window scene/view layer and playback remain pinned until Stop.
Save, load, undo and workspace changes tear down the copy. The browser may
close while playback continues; the toolbar always keeps Pause and Stop.
All bpy work is on a timer/main thread; each copy pass yields after 4 ms.
"""
import time
from types import SimpleNamespace

import bpy
from mixar.config.logging_config import get_logger

from mixar.modules.common.render_coordinator.constants import INTERNAL_ANIMATION_SCENE_PROP
from . import animation_catalog as catalog
from . import animation_preview_data as preview_data

_session = None
_logger = get_logger(__name__)


def current():
    return _session


def _playback(window, start):
    with bpy.context.temp_override(window=window):
        if window.screen.is_animation_playing:
            bpy.ops.screen.animation_cancel(restore_frame=False)
        if start:
            bpy.ops.screen.animation_play()


def _remap(owner, copies):
    """Retarget only copied object references; mesh/material data stay linked."""
    for prop in owner.bl_rna.properties:
        if prop.type != 'POINTER' or prop.is_readonly:
            continue
        value = getattr(owner, prop.identifier, None)
        if isinstance(value, bpy.types.Object) and value in copies:
            setattr(owner, prop.identifier, copies[value])


def _copy_objects(session):
    for obj in session.source.objects:
        copy = obj.copy()
        session.objects.append(copy)
        session.copies[obj] = copy
        session.scene.collection.objects.link(copy)
        preview_data.isolate_object(obj, copy, session)
        # Preview is inspectable and navigable, never an editable project.
        copy.hide_select = True
        yield
    references = session.copies | session.data_copies
    for original, copy in session.copies.items():
        if original.parent in session.copies:
            copy.parent = session.copies[original.parent]
            # Blender's parent setter resets parent inverse to identity.
            # Restore the binding offset after remapping, including bone and
            # nested import-root parenting, so meshes stay aligned to the rig.
            copy.matrix_parent_inverse = original.matrix_parent_inverse.copy()
        for owner in (*copy.modifiers, *copy.constraints):
            _remap(owner, session.copies)
        if copy.pose:
            for bone in copy.pose.bones:
                for constraint in bone.constraints:
                    _remap(constraint, session.copies)
        preview_data.remap_drivers(copy, references)
        # Flattening into the preview's root collection loses collection and
        # layer exclusions. Preserve effective viewport visibility, not just
        # the object's own Hide flag (rig helpers often rely on collections).
        copy.hide_set(not original.visible_get(view_layer=session.layer,
                                              viewport=session.area.spaces.active),
                      view_layer=session.scene.view_layers[0])
        yield
    for data in session.data_copies.values():
        preview_data.remap_drivers(data, references)
        yield


def start(context, action_name, slot_handle):
    global _session
    previous = _session
    target = previous.target if previous else catalog.selected_target(context)
    action = bpy.data.actions.get(action_name)
    slot = catalog.resolve(action, slot_handle)
    reason = catalog.compatibility(target, slot, catalog.curves(action, slot))
    if reason:
        raise ValueError(reason)
    stop(resume=False)
    window = context.window
    source = window.scene
    playing = previous.was_playing if previous else window.screen.is_animation_playing
    _playback(window, False)
    first, last = catalog.clip_range(action, catalog.curves(action, slot))
    scene = bpy.data.scenes.new('~Animation preview')
    scene[INTERNAL_ANIMATION_SCENE_PROP] = True
    _session = session = SimpleNamespace(
        window=window, source=source, layer=window.view_layer, target=target,
        control_object=(previous.control_object if previous
                        else context.view_layer.objects.active),
        target_visible=target.visible_get(view_layer=window.view_layer,
                                          viewport=context.area.spaces.active),
        scene=scene, objects=[], copies={}, action=action, slot=slot,
        data=[], data_copies={}, static_data=set(),
        first=first, last=max(first, last), was_playing=playing,
        ready=False, paused=False, origin=time.monotonic(), offset=0.0,
        area=context.area, workspace=window.workspace, frame=None,
        last_refresh=0.0,
    )
    try:
        scene.render.engine = source.render.engine
        scene.render.fps = source.render.fps
        scene.render.fps_base = source.render.fps_base
        scene.world = preview_data.isolate(source.world, session)
        scene.frame_start = int(first)
        scene.frame_end = max(scene.frame_start, int(last))
        scene.tool_settings.use_keyframe_insert_auto = False
        session.builder = _copy_objects(session)
        state = context.window_manager.mixar_animations
        state.error = False
        state.preview_name = action.name
        state.active_index = next((i for i, item in enumerate(state.clips)
                                   if item.action_name == action.name
                                   and item.slot_handle == slot_handle), 0)
        state.preparing = True
        state.playing = True
        if not bpy.app.timers.is_registered(_tick):
            bpy.app.timers.register(_tick, first_interval=0.01)
    except Exception:
        stop()
        raise


def _finish_build(session):
    copy = session.copies[session.target]
    anim = copy.animation_data_create()
    anim.action = session.action
    if session.slot:
        anim.action_slot = session.slot
    anim.use_nla = False
    anim.action_blend_type = 'REPLACE'
    anim.action_influence = 1.0
    anim.action_extrapolation = 'HOLD'
    session.scene.camera = session.copies.get(session.source.camera)
    session.scene.frame_set(int(session.first), subframe=session.first % 1)
    session.window.scene = session.scene
    session.ready = True
    update_rig_visibility()
    session.origin = time.monotonic()
    bpy.context.window_manager.mixar_animations.preparing = False
    session.window.mixar_refresh_popover("MIXAR_PT_animations")


def update_rig_visibility(_owner=None, _context=None):
    """Only hide the copied rig's display; its deformation keeps evaluating."""
    session = _session
    if session is None or not session.ready or session.target.type != 'ARMATURE':
        return
    hide = bpy.context.window_manager.mixar_animations.hide_rig
    session.copies[session.target].hide_set(hide or not session.target_visible,
                                          view_layer=session.scene.view_layers[0])
    session.area.tag_redraw()


def _tick():
    session = _session
    if session is None:
        return None
    try:
        if (session.window.workspace != session.workspace
                or session.window.scene not in (session.source, session.scene)
                or session.area.type != 'VIEW_3D'):
            stop()
            return None
        if not session.ready:
            deadline = time.perf_counter() + .004
            while time.perf_counter() < deadline:
                try:
                    next(session.builder)
                except StopIteration:
                    _finish_build(session)
                    break
            return .01
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
            session.window.mixar_refresh_popover("MIXAR_PT_animations")
            session.last_refresh = time.monotonic()
        return min(1 / fps, 1 / 30)
    except Exception:
        _logger.exception('Animation preview failed')
        stop()
        bpy.context.window_manager.mixar_animations.error = True
        return None


def pause():
    session = _session
    if session is None or not session.ready:
        return
    session.paused = not session.paused
    session.offset = session.scene.frame_current - session.first
    if not session.paused and session.offset >= session.last - session.first:
        session.offset = 0
    session.origin = time.monotonic()
    bpy.context.window_manager.mixar_animations.playing = not session.paused
    session.window.mixar_refresh_popover("MIXAR_PT_animations")


def position():
    session = _session
    if not session or not session.ready or session.last <= session.first:
        return 0.0
    return (session.scene.frame_current - session.first) / (session.last - session.first)


def seek(value):
    session = _session
    if session and session.ready:
        session.offset = value * (session.last - session.first)
        session.origin = time.monotonic()
        session.scene.frame_set(round(session.first + session.offset))


def stop(*, resume=True):
    global _session
    session, _session = _session, None
    if session is None:
        return
    try:
        if session.window.scene == session.scene:
            _playback(session.window, False)
            session.window.scene = session.source
            session.window.view_layer = session.layer
        if resume and session.was_playing and session.window.scene == session.source:
            _playback(session.window, True)
    except (ReferenceError, RuntimeError):
        pass
    # Free the scene's evaluated depsgraph before its referenced object IDs.
    # Viewport cache maintenance can visit inactive scenes' depsgraphs too.
    try:
        bpy.data.scenes.remove(session.scene)
    except (ReferenceError, RuntimeError):
        pass
    # Free precisely our allocations. No global sweep of the user's IDs.
    for obj in session.objects:
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except (ReferenceError, RuntimeError):
            pass
    if session.data:
        bpy.data.batch_remove(ids=session.data)
    state = getattr(bpy.context.window_manager, 'mixar_animations', None)
    if state:
        state.preview_name = ''
        state.preparing = False
        state.playing = False
    try:
        session.window.mixar_refresh_popover("MIXAR_PT_animations")
    except ReferenceError:
        pass

# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Poll and update callbacks for the Director property groups.

Split from `ui/properties/director_properties.py`, which crossed the 500-line
rule: the declarations are a manifest and these are the behaviour behind them.
They live in `core/` because that is where they belong — every one of them is
logic, and several already reach into other `core` modules to do it.

Two rules hold throughout. A property update can fire during file load, before
the data it wants is reachable, so each one fails closed rather than raising
into the loader. And none of them calls an operator: an update that pushed an
operator onto the undo stack would make loading a file an editing action.
"""

from __future__ import annotations

import bpy

from .aspect import apply_camera_ratio
from .shot_api import release_preview_range, shot_scene
from .viewport import enter_camera_view, select_camera_object


def _camera_poll(_self, obj):
    return getattr(obj, "type", None) == 'CAMERA'


def _request_beat_reconcile() -> None:
    """Adopt/prune native camera keys for the newly watched shot right away.

    The beat_sync watcher only ticks on depsgraph updates, which entering
    Director or switching shots does not cause — without this, a camera
    keyed through the native timeline shows an empty Director strip until
    some unrelated edit happens to tick the handler.
    """
    from . import beat_sync

    try:
        beat_sync.request_reconcile()
    except Exception:
        # Never let a reconcile request break the camera-switch update.
        pass


def _activate_shot_camera(self, context):
    scene = shot_scene(self, getattr(context, "scene", None))
    camera = getattr(self, "camera", None)
    if scene is not None and camera is not None and camera.type == 'CAMERA':
        scene.camera = camera
        # A ratio belongs to the camera; the scene only ever mirrors the live
        # one (`core/aspect.py`). A camera with no ratio of its own leaves the
        # scene's shape alone.
        apply_camera_ratio(scene, camera)
        state = getattr(scene, "mixar_director", None)
        if state is not None and state.is_directing:
            select_camera_object(context or bpy.context, camera)
            try:
                enter_camera_view(context or bpy.context, camera, remember=False)
            except Exception:
                # RNA updates can run without a usable area during file loading.
                pass
        _request_beat_reconcile()


def _on_active_shot_change(self, context):
    """Follow the newly active shot: its camera, view, selection, and range.

    All shots share one scene timeline, so switching shots must re-point the
    scene camera and the playback range or the timeline shows one shot's beats
    while the view and playhead still belong to another. The selection follows
    while directing so gizmos and transform keys edit the new shot's camera.
    """
    scene = getattr(context, "scene", None) or bpy.context.scene
    shots = getattr(self, "shots", None)
    if scene is None or not shots:
        return
    index = min(max(0, self.active_shot_index), len(shots) - 1)
    shot = shots[index]
    camera = getattr(shot, "camera", None)
    if camera is not None and getattr(camera, "type", None) == 'CAMERA':
        scene.camera = camera
        apply_camera_ratio(scene, camera)
        if self.is_directing:
            select_camera_object(context or bpy.context, camera)
            try:
                enter_camera_view(context or bpy.context, camera, remember=False)
            except Exception:
                pass
    release_preview_range(scene)
    _request_beat_reconcile()


def _on_handheld_update(self, _context):
    from .handheld import refresh_handheld

    try:
        refresh_handheld(self)
    except Exception:
        # Property updates can fire during file load before the camera's
        # animation data is reachable; the next capture refreshes anyway.
        pass


def _on_interpolation_update(self, _context):
    from .interpolation import apply_interpolation

    try:
        apply_interpolation(self)
    except Exception:
        # Property updates can fire during file load before the camera's
        # animation data is reachable; the next capture re-applies anyway.
        pass


def _on_beat_interpolation_update(self, _context):
    """Re-apply the owning shot's easing after one beat overrode it.

    A beat has no pointer back to its shot, so the shot is the one whose
    `beats` collection this beat belongs to — found by identity, which is
    exact and does not depend on a name or an index.
    """
    from .interpolation import apply_interpolation

    try:
        state = getattr(getattr(self, "id_data", None), "mixar_director", None)
        me = self.as_pointer()
        for shot in getattr(state, "shots", ()):
            if any(beat.as_pointer() == me for beat in shot.beats):
                apply_interpolation(shot)
                return
    except Exception:
        # Property updates can fire during file load before the camera's
        # animation data is reachable; the next capture re-applies anyway.
        pass


def _on_speed_update(self, context):
    """Retime the shot to its new speed (``core/retime.py``).

    Locked shots return untouched (the surface disables their slider); the
    value is never fought over. Load-safe: no operators, and a shot whose
    animation is not reachable yet keeps its frames until the next edit.
    """
    from .retime import apply_shot_speed

    if self.state != 'DRAFT':
        return
    scene = shot_scene(self, getattr(context, "scene", None) or bpy.context.scene)
    if scene is None:
        return
    try:
        apply_shot_speed(scene, self)
    except Exception:
        pass


def _track_target_poll(self, obj):
    return getattr(obj, "type", None) != 'CAMERA'


def _on_track_target_update(self, _context):
    from .tracking import refresh_tracking

    try:
        refresh_tracking(self)
    except Exception:
        pass


def _on_directing_update(self, context):
    """Directing entry: refresh the surface and reconcile the watched shot.

    All four entry operators set ``is_directing = True``; none of them
    causes a depsgraph update, so without an explicit request the strip
    ignores natively keyed cameras until an unrelated edit ticks the
    beat_sync handler.
    """
    _redraw_director_surface(self, context)
    if self.is_directing:
        _request_beat_reconcile()


def _redraw_director_surface(_self, context):
    """Refresh native Director overlays and poll-driven regions."""
    window_manager = getattr(context, "window_manager", None)
    if window_manager is None:
        window_manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(window_manager, "windows", ()):
        screen = getattr(window, "screen", None)
        for area in getattr(screen, "areas", ()):
            if area.type in {'VIEW_3D', 'MIXIE'}:
                area.tag_redraw()
        # The topbar Director toggle lives in a global area, which screen
        # iteration misses; global_areas is a Mixar RNA addition.
        for area in getattr(window, "global_areas", ()):
            area.tag_redraw()


# ---------------------------------------------------------------------------
# The scene's frame range, read in the unit the dock's Ruler switch selects.


def _effective_fps(scene) -> float:
    """Frames per second, with the rate BASE applied (23.976, 29.97, ...)."""
    render = getattr(scene, "render", None)
    fps = float(getattr(render, "fps", 24) or 24)
    base = float(getattr(render, "fps_base", 1.0) or 1.0)
    return max(fps / base, 0.001)


def _range_seconds_get(state, attribute: str) -> float:
    """``scene.frame_start`` / ``frame_end`` as an ABSOLUTE time.

    Frame divided by the effective rate — what Blender's own "Show Seconds"
    means by a time, and what keeps both ends of the range editable. (The
    Director ruler's own labels measure ELAPSED time from the scene's start,
    so on a scene starting at frame 1 the two differ by that one frame.)
    """
    scene = state.id_data
    return float(getattr(scene, attribute, 0)) / _effective_fps(scene)


def _range_seconds_set(state, attribute: str, value: float) -> None:
    scene = state.id_data
    # Frames are integers, so a time lands on the nearest one; the scene's own
    # RNA setters keep start and end in order from there.
    setattr(scene, attribute, int(round(value * _effective_fps(scene))))


def _get_range_start_seconds(self) -> float:
    return _range_seconds_get(self, "frame_start")


def _set_range_start_seconds(self, value: float) -> None:
    _range_seconds_set(self, "frame_start", value)


def _get_range_end_seconds(self) -> float:
    return _range_seconds_get(self, "frame_end")


def _set_range_end_seconds(self, value: float) -> None:
    _range_seconds_set(self, "frame_end", value)


# ---------------------------------------------------------------------------
# Auto Key IS Blender's Auto Keying switch.
#
# It was a Director-only flag, so the Timeline's record button and the Cinema
# dock's chip were two switches for one idea — Cinema Mode could key while the
# Timeline said auto-keying was off, and Blender's own auto-keying never ran
# for a Cinema session. The property is a proxy now: reading and writing it
# reads and writes `tool_settings.use_keyframe_insert_auto`, and every Director
# reader (the recorder, the stillness debounce, the walk's exit capture) keeps
# asking `state.auto_key`.


def _tool_settings(state):
    try:
        return getattr(state.id_data, "tool_settings", None)
    except (AttributeError, ReferenceError):
        return None


def _get_auto_key(self) -> bool:
    return bool(getattr(_tool_settings(self), "use_keyframe_insert_auto", False))


def _set_auto_key(self, value: bool) -> None:
    tool_settings = _tool_settings(self)
    if tool_settings is None:
        return
    try:
        tool_settings.use_keyframe_insert_auto = bool(value)
    except (AttributeError, ReferenceError, TypeError):
        pass


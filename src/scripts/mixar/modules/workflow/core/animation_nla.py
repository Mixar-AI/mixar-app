# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""The browser's NLA actions as Blender's own NLA data API and screen operators.

Nothing here animates anything: there is no timer, snapshot or session. Each
function is what a user does in the NLA editor, expressed through the RNA the
editor's buttons drive (``NlaTrack.is_solo`` for the solo star, ``mute``,
``nla_tracks.new``/``strips.new`` for Add Action Strip, ``strips.remove`` /
``nla_tracks.remove`` for Delete) plus the scene's preview range and the
``screen.animation_play``/``animation_cancel``/``frame_jump`` operators.
The NLA editor's own operators poll on an NLA editor area, which Zen does not
have, and act on the editor's selection rather than on one object.

Every caller is a REGISTER|UNDO operator, so each click is one undo step.
The only runtime state is the preview range a Play replaced, kept on the
WindowManager browser state so Stop can put it back.
"""
import math

import bpy
from mixar.modules.common.i18n import n_

from . import animation_catalog as catalog


def check_editable(target):
    """Refuse before any mutation, like the NLA operators' tweak-mode poll."""
    if target is None:
        raise ValueError(n_("Select a character or animated object"))
    anim = target.animation_data
    if anim is not None and anim.use_tweak_mode:
        raise ValueError(n_("Leave NLA tweak mode to change animations"))


def check_clip(target, action, slot):
    check_editable(target)
    reason = catalog.compatibility(target, slot, catalog.curves(action, slot))
    if reason:
        raise ValueError(reason)


def strip_for(target, action, slot):
    """The first top-level strip on the target playing this clip, if any."""
    handle = slot.handle if slot else 0
    for track, strip, nested in catalog.track_strips(target):
        strip_slot = strip.action_slot
        if (not nested and strip.action == action
                and (strip_slot.handle if strip_slot else 0) == handle):
            return track, strip
    return None, None


def add_strip(target, action, slot):
    """Add Action Strip: a new track named after the clip, the strip starting
    at the clip's own first frame (not the current frame)."""
    track, strip = strip_for(target, action, slot)
    if strip is not None:
        return track, strip
    start, _end = catalog.clip_range(action, catalog.curves(action, slot))
    track = target.animation_data_create().nla_tracks.new()
    track.name = action.name
    strip = track.strips.new(action.name, int(math.floor(start)), action)
    if slot is not None and strip.action_slot != slot:
        strip.action_slot = slot
    return track, strip


def tag_relations(target):
    """Make the depsgraph pick up a solo or mute change.

    The depsgraph builder leaves every disabled track (muted, or not the
    solo) out of the graph (``deg_builder_relations.cc``,
    ``build_animdata_curves``), so a rig whose only time dependency is a
    stashed clip has no time relation until relations are rebuilt. The NLA
    editor's star and checkbox tag that rebuild
    (``anim_channels_defines.cc``); the ``is_solo`` and ``mute`` RNA setters
    only tag the animation (``rna_NlaStrip_update``), so a merged character
    with no active action kept its pose while the frame counter ran.
    Re-assigning a strip's own slot is the one strip RNA update that tags
    relations (``rna_NlaStrip_dependency_update``) without changing data.
    """
    for _track, strip, _nested in catalog.track_strips(target):
        strip.action_slot = strip.action_slot
        return


def _playback_running(window):
    return bool(window and window.screen and window.screen.is_animation_playing)


def _set_preview_range(scene, start, end):
    # Enable first: while disabled, Blender's setters reset the other end to
    # the scene range (rna_scene.cc, rna_Scene_preview_range_*_frame_set).
    scene.use_preview_range = True
    scene.frame_preview_start = start
    scene.frame_preview_end = end


def _remember_range(state, scene, window, target):
    """Keep the range Stop restores; a clip switch keeps the first one.

    Switching to another object's clip first clears the solo this browser set
    on the previous object, as its Stop would.
    """
    if is_playing(window, scene, state):
        previous = play_target(scene, state)
        soloed = catalog.soloed_track(previous) if previous != target else None
        if soloed is not None and not previous.animation_data.use_tweak_mode:
            soloed.is_solo = False
            tag_relations(previous)
        return
    state.range_saved = True
    state.range_scene = scene.session_uid
    state.range_use = scene.use_preview_range
    state.range_start = scene.frame_preview_start
    state.range_end = scene.frame_preview_end


def play(window, scene, state, target, action, slot, track_name='', strip_name=''):
    """Solo the clip's track, set the preview range to it, then play.

    A clip that is not on the target yet is added first. The active action is
    left assigned: Blender mutes the action line while a track is soloed
    (anim_sys.cc:3353-3358). Playing the active action itself clears the
    solo instead, so it evaluates again.
    """
    check_clip(target, action, slot)
    anim = target.animation_data
    is_active = (not track_name and anim is not None and anim.action == action
                 and anim.action_slot == slot)
    if track_name:
        track, strip, _nested = catalog.find_strip(target, track_name, strip_name)
        if strip is None:
            raise ValueError(n_("This animation is no longer on the object"))
    _remember_range(state, scene, window, target)
    if is_active:
        soloed = catalog.soloed_track(target)
        if soloed is not None:
            soloed.is_solo = False
        first, last = catalog.clip_range(action, catalog.curves(action, slot))
    else:
        if not track_name:
            track, strip = add_strip(target, action, slot)
        # With use_nla off Blender skips NLA evaluation entirely, solo
        # included (anim_sys.cc:4027), so the soloed clip would not show.
        target.animation_data.use_nla = True
        track.is_solo = True
        first, last = strip.frame_start, strip.frame_end
    tag_relations(target)
    _set_preview_range(scene, int(math.floor(first)), int(math.ceil(last)))
    state.play_target = target.name
    with bpy.context.temp_override(window=window):
        # Start before jumping: playback then remembers the user's frame,
        # which Stop's animation_cancel returns to.
        if not _playback_running(window):
            bpy.ops.screen.animation_play()
        bpy.ops.screen.frame_jump(end=False)


def pause(window):
    with bpy.context.temp_override(window=window):
        if _playback_running(window):
            bpy.ops.screen.animation_cancel(restore_frame=False)
        else:
            bpy.ops.screen.animation_play()


def play_target(scene, state):
    """The object a browser Play is running on, if it still exists."""
    if not state.range_saved or state.range_scene != scene.session_uid:
        return None
    return scene.objects.get(state.play_target) if state.play_target else None


def is_playing(window, scene, state):
    """A browser Play is in progress: its clip is soloed or playback runs."""
    target = play_target(scene, state)
    return target is not None and (catalog.soloed_track(target) is not None
                                   or _playback_running(window))


def stop(window, scene, state):
    """Cancel playback, clear the clip's solo and restore the preview range."""
    target = play_target(scene, state)
    with bpy.context.temp_override(window=window):
        if _playback_running(window):
            bpy.ops.screen.animation_cancel()
    soloed = catalog.soloed_track(target) if target is not None else None
    # Stop always ends playback; in NLA tweak mode the solo is the editor's
    # to manage, so it stays.
    if soloed is not None and not target.animation_data.use_tweak_mode:
        soloed.is_solo = False
        tag_relations(target)
    if state.range_saved and state.range_scene == scene.session_uid:
        _set_preview_range(scene, state.range_start, state.range_end)
        scene.use_preview_range = state.range_use
    state.range_saved = False
    state.play_target = ''


def toggle_solo(target, track_name, strip_name):
    check_editable(target)
    track = _track(target, track_name, strip_name, allow_nested=True)[0]
    track.is_solo = not track.is_solo
    tag_relations(target)


def toggle_mute(target, track_name, strip_name):
    check_editable(target)
    track = _track(target, track_name, strip_name, allow_nested=True)[0]
    track.mute = not track.mute
    tag_relations(target)


def delete(target, track_name, strip_name):
    """Delete the strip, and its track when that leaves the track empty."""
    check_editable(target)
    track, strip = _track(target, track_name, strip_name)
    if len(track.strips) == 1:
        # nla_tracks.remove() keeps the AnimData's solo flag (unlike the NLA
        # editor's Delete Tracks), which would disable every other track.
        if track.is_solo:
            track.is_solo = False
        target.animation_data.nla_tracks.remove(track)
    else:
        track.strips.remove(strip)


def add(target, action, slot):
    check_clip(target, action, slot)
    return add_strip(target, action, slot)


def toggle_rig_visibility(rig, view_layer):
    """Hide Rig is the outliner eye: the armature's view-layer hide flag."""
    rig.hide_set(not rig.hide_get(view_layer=view_layer), view_layer=view_layer)


def _track(target, track_name, strip_name, allow_nested=False):
    track, strip, nested = catalog.find_strip(target, track_name, strip_name)
    if strip is None:
        raise ValueError(n_("This animation is no longer on the object"))
    if nested and not allow_nested:
        raise ValueError(n_("This clip is inside a meta strip"))
    return track, strip

# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Slot-aware, read-only animation discovery. Never run scans from draw().

A row is one of three kinds: ``ACTION`` (the target's active action),
``STRIP`` (an NLA strip on the target; its track carries Solo/Mute) or
``FILE`` (a clip from All in file that is not on the target yet).
"""
from types import SimpleNamespace
from collections import deque

from mixar.modules.common.utils.animation import bound_fcurves
from mixar.modules.common.i18n import n_


def selected_target(context):
    obj = context.view_layer.objects.active
    if obj is None or not obj.select_get(view_layer=context.view_layer):
        return None
    if obj.type == 'MESH':
        rig = obj.find_armature()
        if rig is not None and rig.name in context.scene.objects:
            return rig
    return obj


def hidable_rig(context):
    """The rig of a selected skinned mesh; a selected rig itself is not hidden
    (hiding deselects it, which would empty the browser)."""
    target = selected_target(context)
    if (target is None or target.type != 'ARMATURE'
            or target == context.view_layer.objects.active):
        return None
    return target


def track_strips(target):
    """(track, strip, nested) for every clip strip, including meta contents."""
    anim = getattr(target, 'animation_data', None)
    if anim is None:
        return
    for track in anim.nla_tracks:
        pending = deque((strip, False) for strip in track.strips)
        while pending:
            strip, nested = pending.popleft()
            if strip.type == 'META':
                pending.extend((child, True) for child in strip.strips)
            elif strip.action:
                yield track, strip, nested


def bindings(target):
    """Active and NLA bindings: everything that can make a row 'used'."""
    anim = getattr(target, 'animation_data', None)
    if anim is not None and anim.action:
        yield anim
    for _track, strip, _nested in track_strips(target):
        yield strip


def find_strip(target, track_name, strip_name):
    """(track, strip, nested) by name, or (None, None, False)."""
    for track, strip, nested in track_strips(target):
        if track.name == track_name and strip.name == strip_name:
            return track, strip, nested
    return None, None, False


def soloed_track(target):
    anim = getattr(target, 'animation_data', None)
    if anim is None:
        return None
    return next((track for track in anim.nla_tracks if track.is_solo), None)


def curves(action, slot):
    return bound_fcurves(SimpleNamespace(action=action, action_slot=slot))


def compatibility(target, slot, fcurves):
    if target is None:
        return n_("Select a character or animated object")
    if slot is not None and slot.target_id_type != target.id_type:
        return n_("This animation is for a different data type")
    if not fcurves:
        return n_("This animation has no keyframes")
    # Matching OBJECT slot types alone do not prove rig compatibility. Every
    # bone/custom property path and array component must resolve on this ID.
    for curve in fcurves:
        try:
            value = target.path_resolve(curve.data_path)
            if hasattr(value, '__len__') and curve.array_index >= len(value):
                return n_("This animation does not match the selected object")
        except (ValueError, KeyError, AttributeError):
            return n_("This animation does not match the selected object")
    return ''


def clip_range(action, fcurves):
    if action.use_frame_range:
        return float(action.frame_start), float(action.frame_end)
    ranges = [curve.range() for curve in fcurves
              if len(curve.keyframe_points) or len(curve.sampled_points)]
    if not ranges:
        return tuple(float(v) for v in action.frame_range)
    return min(r[0] for r in ranges), max(r[1] for r in ranges)


def _row(target, action, slot, kind, **extra):
    fcurves = curves(action, slot)
    start, end = clip_range(action, fcurves)
    row = dict(action_name=action.name, slot_handle=slot.handle if slot else 0,
               slot_name=slot.name_display if slot and len(action.slots) > 1 else '',
               start=start, end=end, used=kind != 'FILE', kind=kind,
               track_name='', strip_name='', nested=False,
               reason=compatibility(target, slot, fcurves))
    row.update(extra)
    return row


def _strip_row(target, track, strip, nested):
    return _row(target, strip.action, strip.action_slot, 'STRIP',
                track_name=track.name, strip_name=strip.name, nested=nested,
                start=float(strip.frame_start), end=float(strip.frame_end))


def entries(target, actions, all_in_file=False):
    """Selected scope: the active action, then every strip on the target.

    All in file lists each action/slot once: as its first strip on the target
    when there is one, else as the active action, else as a FILE row that Add
    or Play puts on the target. Incompatible slots stay visible but disabled.
    """
    anim = getattr(target, 'animation_data', None)
    active = None
    if anim is not None and anim.action:
        active = (anim.action.name, anim.action_slot.handle if anim.action_slot else 0)
    strips = list(track_strips(target))
    if not all_in_file:
        if active:
            yield _row(target, anim.action, anim.action_slot, 'ACTION')
        for track, strip, nested in strips:
            yield _strip_row(target, track, strip, nested)
        return
    first = {}
    for track, strip, nested in strips:
        slot = strip.action_slot
        first.setdefault((strip.action.name, slot.handle if slot else 0),
                         (track, strip, nested))
    for action in actions:
        for slot in (list(action.slots) or [None]):
            key = (action.name, slot.handle if slot else 0)
            if key in first:
                yield _strip_row(target, *first[key])
            elif key == active:
                yield _row(target, action, slot, 'ACTION')
            else:
                yield _row(target, action, slot, 'FILE')


def resolve(action, handle):
    if action is None:
        raise ValueError(n_("The animation is no longer available"))
    slot = next((s for s in action.slots if s.handle == handle), None)
    if len(action.slots) and slot is None:
        raise ValueError(n_("The animation slot is no longer available"))
    return slot

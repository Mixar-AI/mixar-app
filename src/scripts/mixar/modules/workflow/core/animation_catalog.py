# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Slot-aware, read-only animation discovery. Never run scans from draw()."""
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


def bindings(target):
    """Active and stashed/NLA bindings, including strips inside meta strips."""
    anim = getattr(target, 'animation_data', None)
    if anim is None:
        return
    if anim.action:
        yield anim
    pending = deque(strip for track in anim.nla_tracks for strip in track.strips)
    while pending:
        strip = pending.popleft()
        if strip.type == 'META':
            pending.extend(strip.strips)
        elif strip.action:
            yield strip


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


def entries(target, actions, all_in_file=False):
    """One row per action/slot; repeated strips don't duplicate the source clip.

    Selected scope means proven ownership (active or NLA). All in file is
    explicit discovery, with incompatible slots visible but unplayable.
    """
    owned = {}
    for binding in bindings(target):
        slot = binding.action_slot
        owned[(binding.action.name, slot.handle if slot else 0)] = (binding.action, slot)
    candidates = (((a, s) for a in actions for s in (list(a.slots) or [None]))
                  if all_in_file else list(owned.values()))
    for action, slot in candidates:
        key = (action.name, slot.handle if slot else 0)
        fcurves = curves(action, slot)
        start, end = clip_range(action, fcurves)
        yield dict(action_name=action.name, slot_handle=key[1],
                   slot_name=slot.name_display if slot and len(action.slots) > 1 else '',
                   start=start, end=end, used=key in owned,
                   reason=compatibility(target, slot, fcurves))


def resolve(action, handle):
    if action is None:
        raise ValueError(n_("The animation is no longer available"))
    slot = next((s for s in action.slots if s.handle == handle), None)
    if len(action.slots) and slot is None:
        raise ValueError(n_("The animation slot is no longer available"))
    return slot

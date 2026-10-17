# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""What an NLA-style preview changes on its target, and how to put it back.

Plain functions over the target object and scene, so the round trip is testable
without Blender. Restore order matters: animation-data settings first (the clip
stops writing), then the channel values the clip wrote, then the frame, whose
re-evaluation lets the user's own animation drive its channels again.
"""
import ast
from types import SimpleNamespace

ANIM_FIELDS = ('action', 'action_slot', 'use_nla', 'action_blend_type',
               'action_influence', 'action_extrapolation')
_RESTORE_ERRORS = (ReferenceError, RuntimeError, AttributeError, TypeError,
                   ValueError, KeyError, IndexError, SyntaxError)


def split_path(path):
    """``'pose.bones["A.L"].location'`` -> (owner path, key, is custom property)."""
    quote, escaped, last_dot, last_open = None, False, -1, -1
    for i, char in enumerate(path):
        if quote:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == quote:
                quote = None
        elif char in '"\'':
            quote = char
        elif char == '.':
            last_dot = i
        elif char == '[':
            last_open = i
    if path.endswith(']') and last_open > last_dot:
        return path[:last_open], ast.literal_eval(path[last_open + 1:-1]), True
    return path[:max(last_dot, 0)], path[last_dot + 1:], False


def _is_array(value):
    return hasattr(value, '__len__') and not isinstance(value, str)


def read(target, path, index):
    value = target.path_resolve(path)
    return value[index] if _is_array(value) else value


def write(target, path, index, value):
    owner_path, key, custom = split_path(path)
    owner = target.path_resolve(owner_path) if owner_path else target
    current = owner[key] if custom else getattr(owner, key)
    if _is_array(current):
        current[index] = value
    elif custom:
        owner[key] = value
    else:
        setattr(owner, key, value)


def capture(target, scene, fcurves):
    """Snapshot before the first clip is assigned."""
    anim = target.animation_data
    snapshot = SimpleNamespace(
        had_animation_data=anim is not None,
        settings={name: getattr(anim, name) for name in ANIM_FIELDS} if anim else {},
        last_slot=getattr(anim, 'last_slot_identifier', '') if anim else '',
        values={}, frame=scene.frame_current, subframe=scene.frame_subframe)
    extend(snapshot, target, fcurves)
    return snapshot


def extend(snapshot, target, fcurves):
    """Add channels a newly chosen clip writes; earlier (original) values are kept.

    Channels no previous preview clip wrote still hold the user's values, so
    reading them on a clip switch is still the original state.
    """
    for curve in fcurves:
        key = (curve.data_path, curve.array_index)
        if key in snapshot.values:
            continue
        try:
            snapshot.values[key] = read(target, *key)
        except (ValueError, KeyError, AttributeError, IndexError, TypeError):
            continue  # compatibility() already refuses clips that don't resolve


def assign(target, action, slot):
    anim = target.animation_data_create()
    anim.action = action
    if slot is not None:
        anim.action_slot = slot
    anim.use_nla = False
    anim.action_blend_type = 'REPLACE'
    anim.action_influence = 1.0
    anim.action_extrapolation = 'HOLD'


def _restore_settings(snapshot, target):
    if not snapshot.had_animation_data:
        if target.animation_data is not None:
            target.animation_data_clear()
        return
    anim = target.animation_data or target.animation_data_create()
    settings = snapshot.settings
    anim.action = settings['action']
    if settings['action'] is not None:
        anim.action_slot = settings['action_slot']
    for name in ANIM_FIELDS[2:]:
        setattr(anim, name, settings[name])
    anim.last_slot_identifier = snapshot.last_slot


def restore(snapshot, target, scene):
    """Idempotent. Each stage runs even if an earlier one fails (e.g. the
    target was deleted); returns False when anything could not be restored."""
    complete = True
    try:
        _restore_settings(snapshot, target)
    except _RESTORE_ERRORS:
        complete = False
    for (path, index), value in snapshot.values.items():
        try:
            write(target, path, index, value)
        except _RESTORE_ERRORS:
            complete = False
    try:
        scene.frame_set(snapshot.frame, subframe=snapshot.subframe)
    except _RESTORE_ERRORS:
        complete = False
    return complete

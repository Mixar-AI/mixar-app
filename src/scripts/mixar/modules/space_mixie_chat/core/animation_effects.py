# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Local animation fingerprints for the script executor's before/after diff.

Inspect authored data, never source-code keywords or model-supplied object names.
Only the owning object's name leaves the client. Shared action/slot digests are
cached within ONE snapshot; reusing them across calls would miss key edits.
"""
import hashlib
from array import array

from ...common.utils.animation import bound_fcurves


def _identity(value):
    if value is None:
        return None
    return (value.as_pointer(), getattr(value, "name", ""))


def _rna(value, depth=0):
    """Writable settings, including constraint targets and F-curve modifiers.

    Do not traverse ID pointers (targets may form cycles). Read-only evaluated
    fields such as constraint errors/validity are deliberately excluded.
    """
    rows = []
    for prop in value.bl_rna.properties:
        key = prop.identifier
        if key == "rna_type":
            continue
        if prop.type == 'COLLECTION':
            if depth < 2 and key in {'targets', 'control_points'}:
                rows.append((key, tuple(_rna(v, depth + 1) for v in getattr(value, key))))
            continue
        if prop.is_readonly:
            continue
        item = getattr(value, key)
        if prop.type == 'POINTER':
            item = _identity(item)
        elif getattr(prop, "is_array", False):
            item = tuple(item)
        elif isinstance(item, set):
            item = tuple(sorted(item))
        rows.append((key, item))
    return tuple(rows)


def _digest(value):
    return hashlib.sha256(repr(value).encode()).hexdigest()


def _custom(owner):
    def value(v):
        if hasattr(v, "as_pointer"):
            return _identity(v)
        if hasattr(v, "to_dict"):
            return tuple(sorted((k, value(x)) for k, x in v.to_dict().items()))
        if hasattr(v, "to_list"):
            return tuple(v.to_list())
        return v
    return tuple(sorted((k, value(v)) for k, v in owner.items())) if owner else ()


def _curve(curve):
    digest = hashlib.sha256()
    digest.update(repr((curve.data_path, curve.array_index, _rna(curve))).encode())
    # foreach_get avoids a Python float/tuple allocation for every key coordinate.
    for collection, fields in ((curve.keyframe_points, ("co", "handle_left", "handle_right")),
                               (curve.sampled_points, ("co",))):
        for field in fields:
            values = array('f', [0.0]) * (len(collection) * 2)
            collection.foreach_get(field, values)
            digest.update(values.tobytes())
    digest.update(repr(tuple((k.interpolation, k.easing, k.handle_left_type,
                              k.handle_right_type, k.amplitude, k.back, k.period)
                             for k in curve.keyframe_points)).encode())
    digest.update(repr(tuple(_rna(m) for m in curve.modifiers)).encode())
    if curve.driver:
        digest.update(repr((_rna(curve.driver), tuple(
            (v.name, v.type, tuple(_rna(t) for t in v.targets))
            for v in curve.driver.variables))).encode())
    return digest.hexdigest()


def _action(binding, cache):
    action = binding.action
    if action is None:
        return None
    slot = getattr(binding, "action_slot", None)
    handle = slot.handle if slot else None
    key = (action.as_pointer(), handle)
    if key not in cache:
        curves = [_curve(curve) for curve in bound_fcurves(binding)]
        layers = [(_rna(layer), tuple(_rna(s) for s in layer.strips))
                  for layer in getattr(action, "layers", ())]
        cache[key] = _digest((_identity(action), _rna(action), _custom(action),
                              handle, layers, curves))
    return cache[key]


def _strip(strip, cache):
    # Strip control curves are separate from its bound action's curves.
    return (_rna(strip), _action(strip, cache), tuple(_curve(c) for c in strip.fcurves),
            tuple(_strip(s, cache) for s in getattr(strip, "strips", ())))


def _animation(owner, cache):
    ad = getattr(owner, "animation_data", None)
    if not ad:
        return None
    return (_action(ad, cache), _rna(ad), tuple(_curve(c) for c in ad.drivers),
            tuple((t.name, t.mute, t.is_solo, tuple(_strip(s, cache) for s in t.strips))
                  for t in ad.nla_tracks))


def animation_fingerprint(obj, cache):
    """Changes to assigned actions, NLA, drivers, constraints and pose channels.

    Includes object-data/shape-key animation and pose-bone constraints. Hashes
    stay in the local snapshot and are never part of the execution response.
    """
    data = getattr(obj, "data", None)
    pose = getattr(obj, "pose", None)
    bones = tuple((b.name, tuple(b.location), b.rotation_mode,
                   tuple(b.rotation_euler), tuple(b.rotation_quaternion),
                   tuple(b.rotation_axis_angle), tuple(b.scale),
                   _custom(b), tuple(_rna(c) for c in b.constraints)) for b in pose.bones) if pose else ()
    return _digest((_animation(obj, cache), _animation(data, cache),
                    _animation(getattr(data, "shape_keys", None), cache),
                    tuple(_rna(c) for c in obj.constraints), bones,
                    _custom(obj), getattr(data, "pose_position", None)))


def snapshot_properties_changed(before, after):
    """An unreadable animation fingerprint is unknown, not a detected edit."""
    if any(before.get(k) != after.get(k) for k in before.keys() | after.keys()
           if k != "animation"):
        return True
    old, new = before.get("animation"), after.get("animation")
    return old is not None and new is not None and old != new

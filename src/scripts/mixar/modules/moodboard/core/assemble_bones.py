# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Find the hand, forearm, head, chest and hip bones of an unknown rig.

Pure: bones arrive as ``BoneInfo`` with WORLD rest positions (character frame:
front -Y, up +Z, the character's left +X), so every rule here runs outside
Blender. Names are tried first (Mixamo ``mixamorig:RightHand``, Rigify
``DEF-hand.R``, Unreal ``hand_r``, generic ``Hand_R``); a key no name resolves
falls back to the skeleton's geometry, and the caller reports which one won.
"""

from collections import Counter, namedtuple
import math
import re

import numpy as np

BoneInfo = namedtuple("BoneInfo", "name head tail parent deform")

HAND_NAMES = frozenset({"hand"})
FOREARM_NAMES = frozenset({"forearm", "lowerarm", "lowarm"})
# Rigify's head deform bone is DEF-spine.006.
HEAD_NAMES = frozenset({"head", "spine6"})
# Spine digits lose their leading zeros, so Rigify's DEF-spine.003 and
# Unreal's spine_03 both read "spine3".
CHEST_NAMES = frozenset({"spine2", "spine3", "chest", "upperchest"})
HIPS_NAMES = frozenset({"hips", "pelvis"})
# A hand is where three or more finger chains (thumb included) meet.
FINGER_BRANCH = 3
KEYS = ("hand_r", "hand_l", "forearm_r", "forearm_l", "head", "chest", "hips")

_PREFIXES = ("mixamorig", "def-", "def_", "org-")
_SEPARATORS = "._- "
_SIDE_PREFIX = re.compile(r"^(left|right)(?=.)")
_SHORT_PREFIX = re.compile(r"^([lr])[._]")
_SIDE_SUFFIX = re.compile(r"[._\- ](left|right|l|r)((?:[._]\d+)?)$")
# Auto-Rig Pro marks centre bones ".x".
_CENTRE_SUFFIX = re.compile(r"[._]x((?:[._]\d+)?)$")


def normalize_bone_name(name: str) -> tuple:
    """``(base, side)`` of a bone name, side in 'L' / 'R' / ''.

    The text after the last ':' is lower-cased; the Mixamo / Rigify prefixes
    and one side token (a ``left``/``right``/``l_``/``r.`` prefix or a
    ``.l``/``_l``/``-l``/`` l`` suffix, a Blender ``.001`` after it allowed)
    are removed; separators are dropped; trailing digits are dropped except on
    spine names, which keep them without leading zeros. So finger and end
    bones ("RightHandThumb1", "HeadTop_End") never read as a hand or a head.
    """
    text = str(name or "").rsplit(":", 1)[-1].strip().lower()
    for prefix in _PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    text = text.strip(_SEPARATORS)
    side = ""
    match = _SIDE_PREFIX.match(text) or _SHORT_PREFIX.match(text)
    if match is not None:
        side = match.group(1)[0].upper()
        text = text[match.end():]
    else:
        match = _SIDE_SUFFIX.search(text)
        if match is not None:
            side = match.group(1)[0].upper()
            text = text[:match.start()] + match.group(2)
        else:
            match = _CENTRE_SUFFIX.search(text)
            if match is not None:
                text = text[:match.start()] + match.group(1)
    base = re.sub(r"[._\-\s]+", "", text)
    if base.startswith("spine"):
        base = re.sub(r"0+(\d)", r"\1", base)
    else:
        base = base.rstrip("0123456789")
    return base, side


def _vec(point) -> np.ndarray:
    return np.asarray(point, dtype=float).reshape(3)


def _prefer(bone):
    # Deform bones first, then the plain name over a ".001" duplicate.
    return (not bone.deform, len(bone.name), bone.name)


def _named(bones, parsed, names, side):
    pool = [bone for bone in bones if parsed[bone.name] in {(n, side) for n in names}]
    return min(pool, key=_prefer) if pool else None


def _depth(bone, by_name) -> int:
    depth, seen = 0, {bone.name}
    while bone.parent and bone.parent in by_name and bone.parent not in seen:
        bone = by_name[bone.parent]
        seen.add(bone.name)
        depth += 1
    return depth


def _geometric_hand(deform, by_name, side, zmin, height):
    band = [bone for bone in deform
            if zmin + 0.3 * height <= _vec(bone.head)[2] <= zmin + 0.8 * height]
    if not band:
        return None
    centre = float(np.mean([_vec(bone.head)[0] for bone in deform]))
    sign = 1.0 if side == "L" else -1.0
    start = max(band, key=lambda bone: (sign * _vec(bone.head)[0], bone.name))
    if sign * (_vec(start.head)[0] - centre) < 0.05 * height:
        return None
    # Walk up from the outermost joint (a fingertip) while each step is a
    # finger or palm segment (< 0.12H; the wrist-to-elbow step is longer), and
    # stop at the bone the fingers branch from, so a short cartoon forearm
    # is not mistaken for one more hand segment.
    fanout = Counter(bone.parent for bone in by_name.values() if bone.parent)
    bone, seen = start, {start.name}
    while (fanout[bone.name] < FINGER_BRANCH and bone.parent in by_name
           and bone.parent not in seen):
        parent = by_name[bone.parent]
        if np.linalg.norm(_vec(parent.head) - _vec(bone.head)) >= 0.12 * height:
            break
        bone = parent
        seen.add(bone.name)
    return bone


def _geometric_head(deform, by_name, height):
    head = max(deform, key=lambda bone: (_vec(bone.head)[2], bone.name))
    children = {bone.parent for bone in by_name.values() if bone.parent}
    parent = by_name.get(head.parent) if head.parent else None
    # An end marker at the crown (Mixamo HeadTop_End) sits on the real head.
    if (head.name not in children and parent is not None
            and np.linalg.norm(_vec(head.head) - _vec(parent.head)) < 0.15 * height):
        return parent
    return head


def resolve_bones(bones, height: float, zmin=None) -> dict:
    """``{key: (bone_name, 'name'|'geometry')}`` for the keys in ``KEYS`` found.

    By name: hand, forearm/lowerarm, head (never headtop/headend), chest = the
    highest chest-named bone below the head, hips/pelvis (Rigify: the root
    DEF-spine), deform bones first.
    Geometry for what names missed: per side, the outermost deform joint in the
    arm band (``zmin`` + 0.3H..0.8H) walked up while each step is under 0.12H,
    stopping at a finger branch (the hand), its parent as forearm; the highest
    deform head (an end marker's parent) as head; the head's grandparent as
    chest; the root-most deform bone as hips. ``zmin`` defaults to the lowest
    bone point.
    """
    bones = list(bones)
    if not bones:
        return {}
    height = max(float(height), 1e-6)
    if zmin is None:
        zmin = min(min(_vec(b.head)[2], _vec(b.tail)[2]) for b in bones)
    by_name = {bone.name: bone for bone in bones}
    parsed = {bone.name: normalize_bone_name(bone.name) for bone in bones}
    deform = [bone for bone in bones if bone.deform] or bones
    out = {}

    def put(key, bone, how):
        if bone is not None:
            out[key] = (bone.name, how)

    for side in ("R", "L"):
        suffix = side.lower()
        hand = _named(bones, parsed, HAND_NAMES, side)
        put(f"hand_{suffix}", hand, "name")
        if hand is None:
            hand = _geometric_hand(deform, by_name, side, zmin, height)
            put(f"hand_{suffix}", hand, "geometry")
        forearm = _named(bones, parsed, FOREARM_NAMES, side)
        put(f"forearm_{suffix}", forearm, "name")
        if forearm is None and hand is not None:
            put(f"forearm_{suffix}", by_name.get(hand.parent or ""), "geometry")

    head = _named(bones, parsed, HEAD_NAMES, "")
    put("head", head, "name")
    if head is None:
        head = _geometric_head(deform, by_name, height)
        put("head", head, "geometry")

    ceiling = _vec(head.head)[2] if head is not None else math.inf
    chests = [bone for bone in bones
              if parsed[bone.name] in {(n, "") for n in CHEST_NAMES}
              and _vec(bone.head)[2] < ceiling]
    # A Rigify "chest" control must not outrank the DEF spine bone under it.
    chests = [bone for bone in chests if bone.deform] or chests
    if chests:
        top = max(_vec(bone.head)[2] for bone in chests)
        put("chest", min((b for b in chests if _vec(b.head)[2] == top), key=_prefer), "name")
    elif head is not None:
        parent = by_name.get(head.parent or "")
        grand = by_name.get(parent.parent or "") if parent is not None else None
        put("chest", grand or parent, "geometry")

    # Rigify's hip deform bone is the root DEF-spine; its "hips" is a control.
    hips = (_named(deform, parsed, HIPS_NAMES, "")
            or _named(deform, parsed, {"spine"}, "")
            or _named(bones, parsed, HIPS_NAMES, ""))
    put("hips", hips, "name")
    if hips is None:
        root = min(deform, key=lambda bone: (
            _depth(bone, by_name), abs(_vec(bone.head)[0]), _vec(bone.head)[2], bone.name))
        put("hips", root, "geometry")
    return out


def bone_sockets(resolved: dict, bones, height: float) -> dict:
    """World points the parts attach to, per resolved key.

    A hand's palm lies half a clamped hand length along the bone:
    ``head + unit(tail - head) * 0.5 * clamp(|tail - head|, 0.04H, 0.09H)``,
    so a stub or an over-long hand bone still lands in the palm. A forearm
    uses its midpoint; head, chest and hips their bone head.
    """
    by_name = {bone.name: bone for bone in bones}
    height = max(float(height), 1e-6)
    out = {}
    for key, (name, _how) in resolved.items():
        bone = by_name.get(name)
        if bone is None:
            continue
        head, tail = _vec(bone.head), _vec(bone.tail)
        if key.startswith("hand"):
            span = tail - head
            length = float(np.linalg.norm(span))
            unit = span / length if length > 1e-9 else np.zeros(3)
            reach = 0.5 * min(max(length, 0.04 * height), 0.09 * height)
            out[key] = head + unit * reach
        elif key.startswith("forearm"):
            out[key] = (head + tail) / 2.0
        else:
            out[key] = head
    return out


def facing_yaw(sockets: dict) -> float:
    """Degrees the character is turned about +Z from facing -Y.

    ``atan2`` of the right-to-left hand vector in the ground plane; 0 when a
    hand is missing or the turn is under 20 degrees (an A-pose is rarely
    perfectly square, and every import is already normalised to face -Y).
    """
    right, left = sockets.get("hand_r"), sockets.get("hand_l")
    if right is None or left is None:
        return 0.0
    dx, dy = float(left[0] - right[0]), float(left[1] - right[1])
    if math.hypot(dx, dy) < 1e-9:
        return 0.0
    yaw = math.degrees(math.atan2(dy, dx))
    return 0.0 if abs(yaw) < 20.0 else yaw


def nearest_bone(resolved: dict, bones, point) -> str:
    """The resolved bone (any bone when none resolved) whose head is nearest *point*."""
    by_name = {bone.name: bone for bone in bones}
    pool = [by_name[name] for name, _how in resolved.values() if name in by_name] or list(bones)
    if not pool:
        return ""
    point = _vec(point)
    return min(pool, key=lambda bone: (float(np.linalg.norm(_vec(bone.head) - point)),
                                       bone.name)).name

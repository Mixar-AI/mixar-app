# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Where an Assemble part goes: settings resolution and the placement matrix.

Pure numpy, deterministic, no mathutils (a MagicMock in the unit tests); the
adapter converts with ``np.array(matrix)`` and ``Matrix(rows)``.

Frames. The body is in the character frame (front -Y, up +Z, the character's
left +X). A part is first brought into the normalised part frame -- long axis
+Z with the grip end at the bottom, the side that faced the camera -Y,
image-right +X -- then turned by its slot's rest rotation (column vectors,
``R_final = Rz(yaw) @ R_slot``), scaled uniformly and moved onto its socket::

    delta = T(socket) @ R @ S(s) @ T(-grip) @ N

``delta`` is applied to the part root's stored rest matrix, so planning from
the same rest vertices always yields the same answer (idempotent re-runs).
"""

from dataclasses import dataclass, field
import math

import numpy as np

from .assemble_bones import bone_sockets, facing_yaw, resolve_bones
from .assemble_constants import FLOAT_SLOTS, FOREARM_SLOTS, HAND_SLOTS, HEAD_SLOTS
from .assemble_landmarks import body_extent, estimate_landmarks, head_width, surface_query
from .assemble_rules import body_word, match_rule, side_override

LONG_RATIO = 2.5
FLAT_RATIO = 0.35
GRIP_SLAB = 0.15
# A slab whose sides differ by less than this is a handle-like round section.
ROUND_RATIO = 2.0
FLOAT_LIFT = 0.05
SURFACE_GAP = 0.004
MISSED_RAY_OFFSET = 0.1
HEAD_TOP_SINK = 0.1
PLANT_SIZE = 80.0

_FALLBACK_SLOT = {'long': 'HAND_R', 'flat': 'HAND_L', 'compact': 'HAND_L'}
# Grip fraction for a long hand item no keyword describes: near the end for a
# pointed item, lower third for an upright pole. Everything else: bbox centre.
_FALLBACK_GRIP = {'POINT': 0.12, 'UPRIGHT': 0.4}


def rot_x(deg) -> np.ndarray:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])


def rot_y(deg) -> np.ndarray:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])


def rot_z(deg) -> np.ndarray:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def translation(offset) -> np.ndarray:
    out = np.eye(4)
    out[:3, 3] = np.asarray(offset, dtype=float).reshape(3)
    return out


def linear(rot3) -> np.ndarray:
    out = np.eye(4)
    out[:3, :3] = rot3
    return out


def transform_points(matrix, points) -> np.ndarray:
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    matrix = np.asarray(matrix, dtype=float)
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def _points(verts) -> np.ndarray:
    points = np.asarray(verts, dtype=float).reshape(-1, 3)
    if not len(points):
        raise ValueError("This part has no vertices")
    return points


def sorted_extents(verts) -> tuple:
    """Axis-aligned bounding-box sides, longest first."""
    points = _points(verts)
    return tuple(sorted((float(v) for v in np.ptp(points, axis=0)), reverse=True))


def extents_class(extents_sorted_desc) -> str:
    """'long' (a blade, pole, bow), 'flat' (a shield) or 'compact'."""
    e0, e1, e2 = (float(v) for v in extents_sorted_desc)
    if e1 <= 1e-9:
        return 'long' if e0 > 1e-9 else 'compact'
    if e0 / e1 >= LONG_RATIO:
        return 'long'
    if e2 / e1 <= FLAT_RATIO:
        return 'flat'
    return 'compact'


@dataclass
class PartSettings:
    slot: str
    hold: str
    size_pct: float
    basis: str
    grip: object
    keep_axis: bool
    flip: bool
    slot_guessed: bool
    hold_guessed: bool
    warnings: list = field(default_factory=list)
    cls: str = 'compact'


def _sided(slot: str) -> bool:
    return slot[-2:] in {'_R', '_L'}


def _other_side(slot: str) -> str:
    return slot[:-1] + ('L' if slot.endswith('R') else 'R')


def _auto_slot(label, rule, cls) -> str:
    words = side_override(label)
    slot = words['slot'] or (rule.slot if rule else _FALLBACK_SLOT[cls])
    if words['side'] and _sided(slot):
        slot = slot[:-1] + words['side']
    elif words['swap_hands'] and _sided(slot):
        slot = _other_side(slot)
    return slot


def _auto_hold(slot, rule, cls, explicit_size) -> str:
    if rule and rule.hold:
        return rule.hold
    if cls == 'flat':
        return 'FACE_OUT'
    if cls != 'long':
        return 'AS_IS'
    if slot.endswith('_L'):
        return 'UPRIGHT'
    return 'UPRIGHT' if explicit_size >= PLANT_SIZE else 'POINT'


def _auto_size(slot, hold, cls) -> float:
    if slot in HAND_SLOTS | FOREARM_SLOTS:
        if hold == 'POINT':
            return 50.0
        if hold == 'UPRIGHT':
            return 90.0
        if hold == 'FACE_OUT':
            return 30.0 if slot in HAND_SLOTS else 45.0
        return 17.0
    if slot == 'BACK':
        return 45.0
    if slot in {'HIP_L', 'HIP_R'}:
        return 45.0 if cls == 'long' else 10.0
    if slot == 'HEAD_FRONT':
        return 95.0
    if slot == 'HEAD_TOP':
        return 100.0
    return 11.0


def resolve_settings(label, extents_sorted_desc, slot='AUTO', hold='AUTO',
                     size_pct=0.0, flip=False) -> PartSettings:
    """Settle every AUTO row of one part.

    Explicit values win, then the label's side words, then its keyword rule,
    then the fallbacks by slot and shape class. Hold only means something on
    a hand or forearm; elsewhere it resolves to ''. Flip ("Flip edge", drawn
    for hand slots only) is dropped elsewhere, so a stale hidden row never
    turns goggles or a forearm shield around. A size a keyword gives in head
    widths is not reused on a body slot (or the reverse).
    """
    rule = match_rule(label)
    cls = rule.cls if rule else extents_class(extents_sorted_desc)
    warnings = []
    word = body_word(label)
    if word:
        warnings.append(f"'{word}' usually stays on the body mesh")
    explicit_size = max(float(size_pct or 0.0), 0.0)

    slot_guessed = slot in ('', 'AUTO')
    if slot_guessed:
        slot = _auto_slot(label, rule, cls)
    hold_guessed = False
    if slot in HAND_SLOTS | FOREARM_SLOTS:
        hold_guessed = hold in ('', 'AUTO')
        if hold_guessed:
            hold = _auto_hold(slot, rule, cls, explicit_size)
    else:
        hold = ''

    if explicit_size > 0.0:
        size = explicit_size
    elif rule and (rule.slot in HEAD_SLOTS) == (slot in HEAD_SLOTS):
        size = rule.size_pct
    else:
        size = _auto_size(slot, hold, cls)

    grip = rule.grip if rule else None
    if grip is None and not rule and cls == 'long' and slot in HAND_SLOTS:
        grip = _FALLBACK_GRIP.get(hold)
    return PartSettings(
        slot=slot, hold=hold, size_pct=float(size),
        basis='head' if slot in HEAD_SLOTS else 'height',
        grip=grip, keep_axis=bool(rule.keep_axis) if rule else False,
        flip=bool(flip) and slot in HAND_SLOTS, slot_guessed=slot_guessed,
        hold_guessed=hold_guessed,
        warnings=warnings, cls=cls,
    )


def _slab_shape(points) -> tuple:
    """(xy bbox area, is it round) of one end slab."""
    ex, ey = (float(v) for v in np.ptp(points[:, :2], axis=0))
    wide, narrow = max(ex, ey), min(ex, ey)
    return ex * ey, wide <= ROUND_RATIO * max(narrow, 1e-9)


def _grip_on_top(points, trust_upright: bool) -> bool:
    """Whether the grip end of a +Z-long part is at the top.

    A handle is a small, round section; a blade tip or an axe head is flat.
    One round end against one flat end decides it. Otherwise the smaller
    slab is the grip end -- but only for a part whose long axis had to be
    inferred: an upright part keeps the grip-at-bottom orientation its
    reference asked for, since a thin blade tip is smaller than a hilt.
    """
    z = points[:, 2]
    zmin, zmax = float(z.min()), float(z.max())
    slab = GRIP_SLAB * (zmax - zmin)
    bottom_area, bottom_round = _slab_shape(points[z <= zmin + slab])
    top_area, top_round = _slab_shape(points[z >= zmax - slab])
    if top_round != bottom_round:
        return top_round
    if trust_upright:
        return False
    return top_area < bottom_area


def normalize_part(verts_world, settings) -> tuple:
    """``(N, notes)``: the 4x4 that brings a part into the normalised frame.

    Only a long part without ``keep_axis`` is touched: its longest bbox axis
    is turned onto +Z about the bbox centre (X by Ry(-90), Y by Rx(+90), so
    the other axes move least), then it is turned end over end (Rx(180)) when
    the grip end is on top. AS_IS parts are left exactly as generated.
    """
    notes = []
    if settings.hold == 'AS_IS' or settings.cls != 'long' or settings.keep_axis:
        return np.eye(4), notes
    points = _points(verts_world)
    lo, hi = points.min(axis=0), points.max(axis=0)
    centre = (lo + hi) / 2.0
    axis = int(np.argmax(hi - lo))
    rot = {0: rot_y(-90), 1: rot_x(90), 2: np.eye(3)}[axis]
    local = (points - centre) @ rot.T
    if _grip_on_top(local, trust_upright=axis == 2):
        rot = rot_x(180) @ rot
    if axis != 2 or not np.allclose(rot, np.eye(3)):
        notes.append("orientation inferred")
    return translation(centre) @ linear(rot) @ translation(-centre), notes


def rest_rotation(slot, hold, is_long, flip, yaw) -> np.ndarray:
    """The 3x3 that turns a normalised part into its slot pose (DESIGN §2.3)."""
    side = slot[-1] if _sided(slot) else ''
    if hold == 'AS_IS' or slot in HEAD_SLOTS | FLOAT_SLOTS:
        rot = np.eye(3)
    elif slot in HAND_SLOTS | FOREARM_SLOTS:
        if hold == 'POINT':
            rot = rot_x(90) @ rot_z(90)
        elif hold == 'UPRIGHT':
            rot = np.eye(3) if side == 'R' else rot_z(180)
        elif hold == 'FACE_OUT':
            rot = rot_z(90) if side == 'L' else rot_z(-90)
        else:
            rot = np.eye(3)
    elif slot == 'BACK':
        rot = rot_y(-25) @ rot_z(180) if is_long else rot_z(180)
    elif slot in {'HIP_L', 'HIP_R'}:
        turn = rot_z(90) if slot == 'HIP_L' else rot_z(-90)
        rot = rot_x(40) @ turn if is_long else turn
    else:
        rot = np.eye(3)
    if flip:
        rot = rot @ rot_z(180)
    return rot_z(yaw) @ rot


def _bbox_centre(points) -> np.ndarray:
    return (points.min(axis=0) + points.max(axis=0)) / 2.0


def grip_point(verts_norm, settings) -> np.ndarray:
    """Where the hand closes, in normalised coordinates: a fraction up the
    long axis from the grip end on the bbox centre line, or the bbox centre."""
    points = _points(verts_norm)
    centre = _bbox_centre(points)
    if settings.grip is None:
        return centre
    zmin, zmax = float(points[:, 2].min()), float(points[:, 2].max())
    return np.array([centre[0], centre[1], zmin + float(settings.grip) * (zmax - zmin)])


def compose(socket, rot3, scale, grip) -> np.ndarray:
    """``T(socket) @ R @ S(scale) @ T(-grip)`` as one 4x4."""
    return (translation(socket) @ linear(np.asarray(rot3, dtype=float) * float(scale))
            @ translation(-np.asarray(grip, dtype=float)))


def bone_key(slot: str) -> str:
    """The resolved-bone key a slot follows."""
    side = slot[-1].lower() if _sided(slot) else ''
    if slot in HAND_SLOTS | FLOAT_SLOTS:
        return f"hand_{side}"
    if slot in FOREARM_SLOTS:
        return f"forearm_{side}"
    if slot == 'BACK':
        return "chest"
    if slot in {'HIP_L', 'HIP_R'}:
        return "hips"
    return "head"


def measure_body(verts, bones) -> dict:
    """The body dict ``plan_part`` reads, from REST-pose world vertices and
    bones (none: static landmarks). Bone sockets win over estimated ones."""
    zmin, top, height = body_extent(verts)
    sockets = estimate_landmarks(verts)
    resolved = resolve_bones(bones, height, zmin) if bones else {}
    sockets.update(bone_sockets(resolved, bones, height))
    yaw = facing_yaw(sockets)
    return {"height": height, "zmin": zmin, "top": top, "yaw": yaw, "sockets": sockets,
            "head_width": head_width(verts, sockets["head"], top, height, yaw),
            "bones": list(bones), "resolved": resolved}


@dataclass
class PartPlan:
    delta: np.ndarray
    size_m: float
    size_pct: float
    notes: list = field(default_factory=list)


def _socket(body, key) -> np.ndarray:
    point = body['sockets'].get(key)
    if point is None:
        raise ValueError(f"The body has no {key.replace('_', ' ')} to attach to")
    return np.asarray(point, dtype=float).reshape(3)


def plan_part(verts_world, settings, body: dict, hit=None) -> PartPlan:
    """The world-space delta for one part (or rigid group) at rest.

    ``body`` = {'height', 'zmin', 'top', 'yaw', 'head_width', 'sockets'}.
    ``hit`` is the surface point the adapter's raycast found for a surface
    slot (None: missed, or not a surface slot). Hands hold the grip point at
    the palm; a float hovers above its palm; a surface part sits on the hit,
    its bbox centre pushed out by half its depth plus a small gap, and a
    HEAD_TOP part sinks 10% of its height into the crown.
    """
    points = _points(verts_world)
    norm_matrix, notes = normalize_part(points, settings)
    notes = list(notes)
    norm = transform_points(norm_matrix, points)
    longest = float(np.ptp(norm, axis=0).max())
    if longest <= 1e-9:
        raise ValueError("This part has no size")
    height = float(body['height'])
    basis = float(body['head_width']) if settings.basis == 'head' else height
    target = settings.size_pct / 100.0 * basis
    scale = target / longest
    rot = rest_rotation(settings.slot, settings.hold, settings.cls == 'long',
                        settings.flip, body.get('yaw', 0.0))
    slot = settings.slot

    if slot in HAND_SLOTS:
        socket = _socket(body, bone_key(slot))
        grip = grip_point(norm, settings)
    elif slot in FLOAT_SLOTS:
        palm = _socket(body, bone_key(slot))
        socket = palm + np.array([0.0, 0.0, FLOAT_LIFT * height + 0.5 * target])
        grip = _bbox_centre(norm)
    else:
        query = surface_query(slot, body['sockets'], float(body['top']), height,
                              body.get('yaw', 0.0))
        if query is None:
            raise ValueError(f"The body has no {bone_key(slot)} to attach to")
        anchor, outward = query
        placed = norm @ (rot * scale).T
        centre = _bbox_centre(placed)
        if hit is None:
            point = anchor + outward * MISSED_RAY_OFFSET * height
            notes.append("surface not found")
        else:
            point = np.asarray(hit, dtype=float).reshape(3)
        if slot == 'HEAD_TOP':
            tall = float(np.ptp(placed[:, 2]))
            socket = np.array([point[0], point[1],
                               point[2] - HEAD_TOP_SINK * tall + 0.5 * tall])
        else:
            half = float(np.ptp(placed @ outward)) / 2.0
            socket = point + outward * (SURFACE_GAP * height + half)
        # The bbox centre after R and S, expressed back in normalised space.
        grip = rot.T @ centre / scale

    delta = compose(socket, rot, scale, grip) @ norm_matrix
    if settings.hold == 'UPRIGHT' and settings.size_pct >= PLANT_SIZE:
        lowest = float(transform_points(delta, points)[:, 2].min())
        if lowest < float(body['zmin']):
            delta = translation((0.0, 0.0, float(body['zmin']) - lowest)) @ delta
            notes.append("planted on the ground")
    return PartPlan(delta=delta, size_m=target, size_pct=settings.size_pct, notes=notes)

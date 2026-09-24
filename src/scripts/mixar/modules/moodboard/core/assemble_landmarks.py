# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Body measurements the Assemble engine reads from vertices alone.

Pure numpy. Every Mixar 3D import is normalised to the character frame
(front -Y, up +Z, the character's left +X), so a body with no armature can
still be measured: its hands are the outermost vertices of the arm band, its
chest, hips and head sit on the torso's centre line. The same module finds
the head width the head slots size by, and the (anchor, outward) ray the
adapter casts from inside the body to find a surface slot's contact point.
"""

import math

import numpy as np

# Arm band: where A-pose hands hang, as fractions of the body height.
ARM_BAND = (0.3, 0.8)
TORSO_BAND = (0.45, 0.75)
HAND_SLAB = 0.03
FOREARM_REACH = 0.12
HEAD_DROP = 0.12
EYE_FRACTION = 0.45
EYE_SLAB = 0.01
# A head is never wider than this around its own centre line, so a raised
# arm or a held staff at eye height does not count as head.
HEAD_RADIUS = 0.15
FALLBACK_HEAD_WIDTH = 0.1
BACK_DROP = 0.03
FOREHEAD_RISE = 0.1
# Surface crossings closer together than this are one surface (skin, then
# clothing, a belt, hair); a wider gap is something else in the ray's path.
LAYER_GAP = 0.03
RAY_NUDGE = 1e-4


def _points(verts) -> np.ndarray:
    points = np.asarray(verts, dtype=float).reshape(-1, 3)
    if not len(points):
        raise ValueError("The body has no vertices to measure")
    return points


def body_extent(verts) -> tuple:
    """``(zmin, top, height)`` of a vertex cloud; height is never zero."""
    points = _points(verts)
    zmin, top = float(points[:, 2].min()), float(points[:, 2].max())
    return zmin, top, max(top - zmin, 1e-6)


def yaw_axes(yaw: float) -> tuple:
    """The character's (left, forward) ground-plane axes after a turn of *yaw* degrees."""
    angle = math.radians(yaw)
    cos, sin = math.cos(angle), math.sin(angle)
    return np.array([cos, sin, 0.0]), np.array([sin, -cos, 0.0])


def _band(points, zmin, height, low, high):
    z = points[:, 2]
    return points[(z >= zmin + low * height) & (z <= zmin + high * height)]


def estimate_landmarks(verts) -> dict:
    """Sockets of an unrigged body, keyed like ``assemble_bones.bone_sockets``.

    Hands: the mean of the vertices within 0.03H of the outermost x in the arm
    band (max x is the left hand, min x the right). Chest, hips and head lie
    on the torso centre line at 0.72H, 0.5H and 0.12H under the top; each
    forearm point is 0.12H from its hand toward the chest.
    """
    points = _points(verts)
    zmin, top, height = body_extent(points)
    torso = _band(points, zmin, height, *TORSO_BAND)
    if not len(torso):
        torso = points
    cx, cy = float(torso[:, 0].mean()), float(torso[:, 1].mean())
    out = {
        "chest": np.array([cx, cy, zmin + 0.72 * height]),
        "hips": np.array([cx, cy, zmin + 0.5 * height]),
        "head": np.array([cx, cy, top - HEAD_DROP * height]),
    }
    arms = _band(points, zmin, height, *ARM_BAND)
    if not len(arms):
        arms = points
    for key, extreme in (("hand_l", arms[:, 0].max()), ("hand_r", arms[:, 0].min())):
        hand = arms[np.abs(arms[:, 0] - extreme) <= HAND_SLAB * height].mean(axis=0)
        towards = out["chest"] - hand
        length = float(np.linalg.norm(towards))
        unit = towards / length if length > 1e-9 else np.zeros(3)
        side = key[-1]
        out[key] = hand
        out[f"forearm_{side}"] = hand + unit * FOREARM_REACH * height
    return out


def eye_height(head, top: float) -> float:
    """Eye level: 45% of the way from the head socket up to the crown."""
    return float(head[2]) + EYE_FRACTION * (top - float(head[2]))


def head_width(verts, head, top: float, height: float, yaw: float) -> float:
    """The head's extent along the character's left axis at eye level.

    Vertices within 0.01H of eye height and 0.15H of the head's centre line
    count; a head with none there (a stub mesh) falls back to 0.1H.
    """
    points = _points(verts)
    head = np.asarray(head, dtype=float).reshape(3)
    level = eye_height(head, top)
    near = points[np.abs(points[:, 2] - level) < EYE_SLAB * height]
    if len(near):
        offset = near[:, :2] - head[:2]
        near = near[np.hypot(offset[:, 0], offset[:, 1]) <= HEAD_RADIUS * height]
    if len(near) < 2:
        return FALLBACK_HEAD_WIDTH * height
    left, _forward = yaw_axes(yaw)
    span = near @ left
    width = float(span.max() - span.min())
    return width if width > 1e-6 else FALLBACK_HEAD_WIDTH * height


def surface_query(slot: str, sockets: dict, top: float, height: float, yaw: float):
    """``(anchor, outward)`` for a surface slot, or None for hands and floats.

    The adapter casts from ``ray_start`` (inside the body) along ``outward``
    and ``outer_surface`` picks the body's surface on that side. BACK hangs
    from just under the chest, the hips and forearms face out sideways,
    HEAD_FRONT looks for the forehead and HEAD_TOP for the crown.
    """
    left, forward = yaw_axes(yaw)
    up = np.array([0.0, 0.0, 1.0])

    def socket(key):
        point = sockets.get(key)
        return None if point is None else np.asarray(point, dtype=float).reshape(3)

    if slot == "BACK":
        chest = socket("chest")
        return None if chest is None else (chest - up * BACK_DROP * height, -forward)
    if slot in {"HIP_L", "HIP_R"}:
        hips = socket("hips")
        return None if hips is None else (hips, left if slot == "HIP_L" else -left)
    if slot in {"FOREARM_L", "FOREARM_R"}:
        side = slot[-1].lower()
        forearm = socket(f"forearm_{side}")
        return None if forearm is None else (forearm, left if side == "l" else -left)
    head = socket("head")
    if head is None:
        return None
    if slot == "HEAD_FRONT":
        level = eye_height(head, top) + FOREHEAD_RISE * (top - float(head[2]))
        return np.array([head[0], head[1], level]), forward
    if slot == "HEAD_TOP":
        return np.array([head[0], head[1], top]), up
    return None


def ray_start(slot: str, sockets: dict, anchor) -> np.ndarray:
    """Where a surface ray starts: the anchor, inside the body -- except HEAD_TOP,
    whose crown-height anchor drops to the head socket straight below it."""
    start = np.array(anchor, dtype=float).reshape(3)
    if slot == "HEAD_TOP" and sockets.get("head") is not None:
        start[2] = float(np.asarray(sockets["head"], dtype=float).reshape(3)[2])
    return start


def crossings(cast, start, direction, height: float, limit: int = 8) -> list:
    """Distances from *start* of up to *limit* surface crossings along *direction*
    within one body height. ``cast(origin)`` returns the world point of the
    next crossing or None; each cast starts a nudge past the last crossing."""
    start, direction = np.asarray(start, dtype=float), np.asarray(direction, dtype=float)
    hits, travelled, nudge = [], 0.0, RAY_NUDGE * height
    for _ in range(limit):
        point = cast(start + direction * (travelled + nudge))
        if point is None:
            break
        travelled = max(float((np.asarray(point) - start) @ direction), travelled + nudge)
        if travelled > height:
            break
        hits.append(travelled)
    return hits


def outer_surface(distances, height: float):
    """Distance along an outward ray to the body's surface on that side, or None.

    The ray starts inside the body, so its first crossing is the body's own
    surface; crossings within ``LAYER_GAP`` * H of the previous one (clothing,
    a belt, hair) belong to it. A crossing past a wider gap -- an A-pose hand
    hanging beside the hip -- is not the surface.
    """
    hits = sorted(float(d) for d in distances if float(d) > 0.0)
    surface = hits[0] if hits else None
    for distance in hits[1:]:
        if distance - surface > LAYER_GAP * height:
            break
        surface = distance
    return surface

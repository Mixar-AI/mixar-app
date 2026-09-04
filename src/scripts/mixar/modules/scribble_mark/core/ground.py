# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Where a mark on empty space lands on the ground — pure, no ``bpy``.

A layout sketch is drawn on nothing: the user circles three spots on an empty
viewport and says "merry-go-round here, car there". The raycast resolver only
reports geometry it hits, so every one of those marks used to arrive as
"background" with no position at all — and a mark with no position cannot
place anything.

The honest fallback is the world ground plane. A ray that hits no object is
intersected with z = 0, which is where Blender's grid floor is and where an
empty scene's first objects go. The result is reported as a *plane* hit, kept
apart from a real surface hit so the agent knows nothing is built there yet.
"""

import math
from typing import Optional, Sequence, Tuple

from ..constants import GROUND_MAX_DISTANCE, GROUND_PLANE_Z

Point3 = Tuple[float, float, float]


def ray_plane_z(
    origin: Sequence[float],
    direction: Sequence[float],
    z: float = GROUND_PLANE_Z,
    max_distance: float = GROUND_MAX_DISTANCE,
) -> Optional[Point3]:
    """Intersection of a ray with the horizontal plane at height *z*, or None.

    None when the ray is parallel to the plane, points away from it (the
    user marked sky), or meets it only absurdly far away — a near-horizontal
    ray crosses z = 0 kilometres out, and reporting that as "where they
    pointed" would send an object to the horizon.
    """
    ox, oy, oz = (float(origin[0]), float(origin[1]), float(origin[2]))
    dx, dy, dz = (float(direction[0]), float(direction[1]), float(direction[2]))
    if abs(dz) < 1e-9:
        return None
    t = (z - oz) / dz
    if t <= 1e-6:
        return None
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    if length <= 1e-9 or t * length > max_distance:
        return None
    return (ox + dx * t, oy + dy * t, z)


def ground_footprint(points: Sequence[Point3]) -> Optional[dict]:
    """``{"center": [x, y, z], "size": [w, d, 0]}`` of ground hits, or None.

    The footprint is what tells the agent how BIG a spot the user circled,
    which is the difference between "put a bench here" and "the park goes
    here".
    """
    usable = [p for p in points if p is not None]
    if not usable:
        return None
    xs = [p[0] for p in usable]
    ys = [p[1] for p in usable]
    zs = [p[2] for p in usable]
    lo = (min(xs), min(ys), min(zs))
    hi = (max(xs), max(ys), max(zs))
    return {
        "center": [(lo[i] + hi[i]) / 2.0 for i in range(3)],
        "size": [hi[i] - lo[i] for i in range(3)],
    }

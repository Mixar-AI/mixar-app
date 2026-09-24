# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Placement of an appended collection (harness v3 scene-from-reference).

Workers build every piece at the world origin with its base on z = 0; the
plan decides where each piece lands. The backend's ``append_collection``
commit carries an optional ``placement`` that this module validates BEFORE
the append (so a bad value can never half-apply) and applies to the
TOP-LEVEL objects of the appended collection after it is linked, inside the
same publish window. Children follow their parents through Blender's own
parenting, so they are never touched directly.

Order of application per top-level object: scale about the world origin,
rotate about the world Z axis through the origin, then translate.
"""

from __future__ import annotations

import math
from typing import Iterable, Optional

MAX_COORD_M = 2000.0
MIN_SCALE, MAX_SCALE = 0.01, 100.0


class PlacementError(ValueError):
    pass


def _finite(v) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise PlacementError("placement values must be numbers")
    f = float(v)
    if not math.isfinite(f):
        raise PlacementError("placement values must be finite")
    return f


def parse_placement(raw) -> Optional[dict]:
    """Validated ``{"location": [x,y,z], "rotation_z_deg": r, "scale": s}`` or None.

    Missing keys default to no translation, no rotation, unit scale. Raises
    :class:`PlacementError` on anything out of bounds or mistyped.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise PlacementError("placement must be an object")
    loc_raw = raw.get("location", [0.0, 0.0, 0.0])
    if not isinstance(loc_raw, (list, tuple)) or len(loc_raw) != 3:
        raise PlacementError("placement.location must be [x, y, z]")
    location = [_finite(v) for v in loc_raw]
    if any(abs(v) > MAX_COORD_M for v in location):
        raise PlacementError(f"placement.location exceeds {MAX_COORD_M:.0f} m")
    rotation = _finite(raw.get("rotation_z_deg", 0.0))
    scale = _finite(raw.get("scale", 1.0))
    if not (MIN_SCALE <= scale <= MAX_SCALE):
        raise PlacementError(f"placement.scale must be within [{MIN_SCALE}, {MAX_SCALE}]")
    return {"location": location, "rotation_z_deg": rotation, "scale": scale}


def is_identity(placement: Optional[dict]) -> bool:
    return placement is None or (
        placement["location"] == [0.0, 0.0, 0.0]
        and placement["rotation_z_deg"] == 0.0
        and placement["scale"] == 1.0
    )


def top_level_objects(collection) -> list:
    """Objects of ``collection`` whose parent is None or outside the collection."""
    objs = list(collection.all_objects)
    members = {id(o) for o in objs}
    return [o for o in objs if getattr(o, "parent", None) is None or id(o.parent) not in members]


def apply_placement(objects: Iterable, placement: dict) -> int:
    """Scale → rotate (world Z) → translate each object. Returns the count moved."""
    s = float(placement["scale"])
    rad = math.radians(float(placement["rotation_z_deg"]))
    c, sn = math.cos(rad), math.sin(rad)
    tx, ty, tz = (float(v) for v in placement["location"])
    n = 0
    for obj in objects:
        x, y, z = (float(v) for v in obj.location)
        x, y, z = x * s, y * s, z * s
        if s != 1.0:
            sx, sy, sz = (float(v) for v in obj.scale)
            obj.scale = (sx * s, sy * s, sz * s)
        if rad != 0.0:
            x, y = x * c - y * sn, x * sn + y * c
            rot = obj.rotation_euler
            rot.z = float(rot.z) + rad
        obj.location = (x + tx, y + ty, z + tz)
        n += 1
    return n

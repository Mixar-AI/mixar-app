# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Resolving a mark against the live scene — the heart of the feature.

The backend cannot do this. It has a picture; the client has the depsgraph,
the view matrices, and ``scene.ray_cast``. Shipping a screen rectangle to a
model and asking it to work out what is underneath re-creates exactly the
guessing that a user pointing at something is supposed to end.

Five tiers, each degrading on its own. A failure at tier *n* still ships
everything below it, and **nothing here waits on the network**:

0. the frozen still (``freeze``) — always, and the only thing a VLM can read
1. the 2D region in localizer coordinates (``payload``) — always
2. an anchor raycast: world point, normal, and the object under it
3. a grid of raycasts inside the outline: which objects, and how much of each
4. a vertex group naming exactly the marked faces (``vertex_groups``)

A mark whose rays hit nothing is landed on the world ground plane instead
(``ground``): a layout sketch on an empty viewport is the commonest kind of
mark there is, and "background, no position" would leave it unusable.

Runs on the main thread, from an operator, while the user waits for a message
to send — so it is bounded by ``COVERAGE_GRID`` and by the vertex cap, and
every step is wrapped: a mark that cannot be resolved is reported as
unresolved, never allowed to fail the send.
"""

from __future__ import annotations

from mixar.config.logging_config import get_logger

from . import coverage as cov
from . import vertex_groups as vgroups
from .geometry import bbox as points_bbox, decimate
from .ground import ground_footprint, ray_plane_z
from .projection import project_object_bbox, ray_from_region, raycast
from ..constants import (
    COVERAGE_GRID,
    EMPTY_BACKGROUND,
    EMPTY_NO_HIT,
    GROUND_PLANE_Z,
    PARTIAL_COVERAGE_MAX,
    PLANE_GROUND,
    WORLD_DECIMALS,
)

logger = get_logger(__name__)


def resolve_mark(context, region, rv3d, reading, serial, write_vertex_group=True):
    """Everything the client can establish about one mark.

    Args:
        reading: a ``gesture.classify`` result, in region pixels.
        serial: the mark's stable id, used to name its vertex group.
        write_vertex_group: set False to measure without mutating the scene
            (the live overlay previews coverage on every stroke; it must not
            leave a trail of groups behind it).

    Returns the ``resolved`` block of the mark payload. Always a dict — an
    unresolvable mark reports why rather than vanishing.
    """
    scene = context.scene
    try:
        depsgraph = context.evaluated_depsgraph_get()
    except Exception as exc:  # noqa: BLE001
        # None, not _empty(): _empty means "we looked and there was nothing
        # there", which the agent is told to state as fact. A depsgraph we
        # could not reach is "we did not look", and the mark is stored with no
        # resolved block rather than a measurement that was never made.
        logger.warning("Scribble mark: no depsgraph, mark left unresolved: %s", exc)
        return None

    polygon = list(reading.get("polygon") or [])
    anchor = reading.get("anchor")

    # --- tier 2: the anchor -------------------------------------------
    anchor_hit, anchor_point, anchor_normal, anchor_obj = (False, None, None, None)
    if anchor:
        anchor_hit, anchor_point, anchor_normal, anchor_obj = raycast(
            scene, depsgraph, region, rv3d, anchor
        )

    # --- tier 3: coverage ---------------------------------------------
    samples = cov.grid_samples(polygon, grid=COVERAGE_GRID, anchor=anchor)
    hit_names = []
    hit_points = []
    objects_by_name = {}
    for sample in samples:
        ok, location, _normal, obj = raycast(scene, depsgraph, region, rv3d, sample)
        if ok and obj is not None:
            hit_names.append(obj.name)
            hit_points.append(location)
            objects_by_name.setdefault(obj.name, obj)
        else:
            hit_names.append(None)

    counts, hit_total, miss_total = cov.tally_hits(hit_names)
    hit, empty_reason = cov.resolve_status(hit_total, miss_total, len(samples))

    # The anchor is the one sample the user aimed deliberately. If the grid
    # found nothing but the anchor did, that is a real hit — a thin mark can
    # easily miss every lattice cell while sitting squarely on an object.
    if not hit and anchor_hit and anchor_obj is not None:
        counts = {anchor_obj.name: 1}
        objects_by_name[anchor_obj.name] = anchor_obj
        hit_points = [anchor_point]
        hit_total = 1
        hit, empty_reason = True, None

    if not hit:
        # A mark on nothing is usually a LAYOUT mark: "put it here". Land it
        # on the ground plane so it carries a position the agent can build
        # at, instead of arriving as "background" with no coordinates.
        if empty_reason == EMPTY_BACKGROUND:
            grounded = _ground_fallback(region, rv3d, polygon, anchor, len(samples))
            if grounded is not None:
                return grounded
        return _empty(empty_reason or EMPTY_NO_HIT)

    mark_bbox = points_bbox(polygon or ([anchor] if anchor else []))
    fractions = _object_fractions(region, rv3d, objects_by_name, mark_bbox)
    ranked = cov.rank_objects(counts, hit_total, fractions)

    # --- tier 4: the named selection ----------------------------------
    if write_vertex_group and ranked:
        _attach_vertex_group(region, rv3d, objects_by_name, ranked[0], polygon, serial)

    resolved = {
        "hit": True,
        "point": _round_vec(anchor_point if anchor_hit else _mean(hit_points)),
        "normal": _round_vec(anchor_normal) if anchor_normal else None,
        "objects": ranked,
        "world_bbox": _world_bbox(hit_points),
        "sample_count": len(samples),
        "hit_count": hit_total,
        "empty_reason": None,
    }
    return resolved


# =============================================================================
# Pieces
# =============================================================================

def _object_fractions(region, rv3d, objects_by_name, mark_bbox):
    """How much of each object's on-screen extent the mark covers.

    An object we cannot project is simply absent from the map, which
    ``rank_objects`` reports as ``partial`` — "we could not measure it" must
    never reach the agent as "the user selected all of it".
    """
    if mark_bbox is None:
        return {}
    fractions = {}
    for name, obj in objects_by_name.items():
        screen = project_object_bbox(region, rv3d, obj)
        if screen is None:
            continue
        fractions[name] = cov.rect_overlap_fraction(screen, mark_bbox)
    return fractions


def _attach_vertex_group(region, rv3d, objects_by_name, primary, polygon, serial):
    """Write the marked faces of the dominant object into a named group.

    Only for a PARTIAL selection. When the mark encloses the whole object,
    the object's own name is already the precise handle and an identical
    vertex group would be noise the agent has to reason about.
    """
    if not primary.get("partial"):
        return
    fraction = primary.get("object_fraction")
    if fraction is not None and fraction >= PARTIAL_COVERAGE_MAX:
        return

    obj = objects_by_name.get(primary.get("name"))
    if obj is None:
        return

    indices = vgroups.marked_vertex_indices(region, rv3d, obj, polygon)
    if indices is None:
        return

    written = vgroups.write_group(obj, vgroups.group_name(serial), indices)
    if written:
        primary["vertex_group"] = written
        primary["vertex_count"] = len(indices)


def _ground_fallback(region, rv3d, polygon, anchor, sample_count):
    """The mark's footprint on the world ground plane, or None.

    None when the anchor ray never meets the plane — the user marked sky, or
    the intersection is so far off it would be a lie — in which case the mark
    stays an honest "background" with no position.
    """
    anchor_point = _ground_hit(region, rv3d, anchor) if anchor else None
    if anchor_point is None:
        return None

    outline = decimate(list(polygon or []), 16)
    hits = [_ground_hit(region, rv3d, p) for p in outline]
    footprint = ground_footprint([h for h in hits if h is not None] or [anchor_point])

    return {
        "hit": False,
        "point": [round(c, WORLD_DECIMALS) for c in anchor_point],
        "normal": [0.0, 0.0, 1.0],
        "objects": [],
        "world_bbox": {
            "center": [round(c, WORLD_DECIMALS) for c in footprint["center"]],
            "size": [round(c, WORLD_DECIMALS) for c in footprint["size"]],
        },
        "sample_count": sample_count,
        "hit_count": 0,
        "empty_reason": EMPTY_BACKGROUND,
        "plane": PLANE_GROUND,
        "plane_z": GROUND_PLANE_Z,
    }


def _ground_hit(region, rv3d, point):
    origin, direction = ray_from_region(region, rv3d, point)
    if origin is None:
        return None
    return ray_plane_z(tuple(origin), tuple(direction))


def _world_bbox(points):
    """Axis-aligned world bounds of the surface the mark landed on."""
    if not points:
        return None
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    zs = [p.z for p in points]
    lo = (min(xs), min(ys), min(zs))
    hi = (max(xs), max(ys), max(zs))
    return {
        "center": [round((lo[i] + hi[i]) / 2.0, WORLD_DECIMALS) for i in range(3)],
        "size": [round(hi[i] - lo[i], WORLD_DECIMALS) for i in range(3)],
    }


def _mean(points):
    if not points:
        return None
    n = float(len(points))
    return (
        sum(p.x for p in points) / n,
        sum(p.y for p in points) / n,
        sum(p.z for p in points) / n,
    )


def _round_vec(vector):
    if vector is None:
        return None
    return [round(float(c), WORLD_DECIMALS) for c in tuple(vector)]


def _empty(reason):
    return {
        "hit": False,
        "point": None,
        "normal": None,
        "objects": [],
        "world_bbox": None,
        "sample_count": 0,
        "hit_count": 0,
        "empty_reason": reason,
    }

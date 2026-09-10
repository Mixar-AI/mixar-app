# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""World extents of the scene, for the aerial (top-down) view.

Pure functions over ``(matrix_world, bound_box)`` pairs so they run under
the ``bpy`` mock. The rule MIRRORS the C++ aerial map's
(`view3d_director_minimap_extents.cc`): visible, geometry-carrying objects'
world bounding boxes, padded by 10 % (at least 2 m), grown to include the
shot camera, an empty scene becoming a 20 x 20 m square; keep the two in
step.
"""

from __future__ import annotations

from typing import Iterable

PAD_FRACTION = 0.1
PAD_MIN = 2.0
EMPTY_HALF = 10.0
#: Object types that carry no geometry the map should trace.
HIDDEN_TYPES = frozenset({'CAMERA', 'LIGHT', 'SPEAKER', 'EMPTY', 'LIGHT_PROBE'})
#: Blender's view3d default sensor width (36 mm) x CAMERA_PARAM_ZOOM_INIT_PERSP (2):
#: an ortho view shows ``view_distance * 72 / lens`` world units along its
#: larger pixel axis (``BKE_camera_params_from_view3d`` + ``_compute_viewplane``).
ORTHO_VIEW_FACTOR = 72.0
#: Share of the viewport width the Cinema stage keeps clear of the columns
#: (two 245 px panels + margins on a 1798 px design); the aerial fit targets
#: it so the scene is not hidden under the cards.
STAGE_FRACTION = 0.6


def world_bounds(items: Iterable) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    """Union of ``(matrix_world, bound_box)`` corners in world space, or None."""
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    any_item = False
    for matrix, bound_box in items:
        for corner in bound_box:
            world = matrix @ _vec(corner)
            for axis in range(3):
                value = float(world[axis])
                lo[axis] = min(lo[axis], value)
                hi[axis] = max(hi[axis], value)
            any_item = True
    if not any_item:
        return None
    return (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])


def padded_xy(bounds, camera_xy=None) -> tuple[float, float, float, float]:
    """``(xmin, xmax, ymin, ymax)`` the map shows: padded bounds ∪ camera."""
    if bounds is None:
        xmin, xmax, ymin, ymax = -EMPTY_HALF, EMPTY_HALF, -EMPTY_HALF, EMPTY_HALF
    else:
        (xmin, ymin, _), (xmax, ymax, _) = bounds
        pad_x = max((xmax - xmin) * PAD_FRACTION, PAD_MIN)
        pad_y = max((ymax - ymin) * PAD_FRACTION, PAD_MIN)
        xmin, xmax, ymin, ymax = xmin - pad_x, xmax + pad_x, ymin - pad_y, ymax + pad_y
    if camera_xy is not None:
        # Union only, never padded after: the C++ map relies on the same
        # rule so a camera on the edge cannot keep pushing the edge out.
        xmin = min(xmin, camera_xy[0])
        xmax = max(xmax, camera_xy[0])
        ymin = min(ymin, camera_xy[1])
        ymax = max(ymax, camera_xy[1])
    return xmin, xmax, ymin, ymax


def aerial_view(rect_xy, z_mid, winx, winy, lens, stage_fraction=STAGE_FRACTION):
    """``(view_location, view_distance)`` for a top-down ORTHO view of *rect_xy*.

    The rect is fitted to the region's aspect (only the stage's share of the
    width counts), and the distance is the ortho scale that shows the fitted
    major side across the region's larger pixel axis.
    """
    xmin, xmax, ymin, ymax = rect_xy
    width = max(xmax - xmin, 1e-6)
    height = max(ymax - ymin, 1e-6)
    winx = max(float(winx), 1.0)
    winy = max(float(winy), 1.0)
    usable_x = winx * max(min(stage_fraction, 1.0), 0.1)
    # World size the whole region must span so the rect fits the usable part.
    span_x = width * winx / usable_x
    span_y = height
    major = max(winx, winy)
    size_major = max(span_x * major / winx, span_y * major / winy)
    distance = size_major * max(float(lens), 1.0) / ORTHO_VIEW_FACTOR
    location = ((xmin + xmax) * 0.5, (ymin + ymax) * 0.5, float(z_mid))
    return location, distance


def scene_bound_items(scene):
    """``(matrix_world, bound_box)`` for every visible geometry object of *scene*."""
    items = []
    for obj in getattr(scene, "objects", ()):
        if getattr(obj, "type", None) in HIDDEN_TYPES:
            continue
        visible = getattr(obj, "visible_get", None)
        if callable(visible) and not visible():
            continue
        bound_box = getattr(obj, "bound_box", None)
        if bound_box is None:
            continue
        items.append((obj.matrix_world, [tuple(corner) for corner in bound_box]))
    return items


def _vec(corner):
    """A ``mathutils.Vector`` for ``matrix @``; the bare tuple under a test double."""
    try:
        from mathutils import Vector

        vector = Vector(corner)
        if len(vector) == 3:
            return vector
    except Exception:  # noqa: BLE001 - mocked mathutils, or no mathutils at all
        pass
    return corner

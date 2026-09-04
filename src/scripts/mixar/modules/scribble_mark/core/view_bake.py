# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Baking the frozen view into a real camera.

A mark is only meaningful in the frame it was drawn on. Weeks later, or three
turns later after the user has orbited away, "the region they circled" needs a
viewpoint to be a region *of*. So arming a freeze bakes a camera matching the
viewport exactly, and every mark from that freeze names it.

That gives a lane one line to see what the user saw::

    scene.camera = bpy.data.objects["mixar_mark_view_0001"]

**This camera is not used to resolve marks.** Resolution raycasts through the
live region (``projection``), which is exact by construction for both
perspective and orthographic views. Reconstructing a camera from a viewport
means reasoning about lens, sensor fit and ortho scale, and getting it subtly
wrong is easy — so the reconstruction is confined to the thing whose failure
mode is cosmetic (the picture is framed slightly differently) rather than the
thing whose failure mode is silent and wrong (the agent edits the wrong
object).

The projection is derived from ``RegionView3D.window_matrix`` rather than
``SpaceView3D.lens``. The viewport's focal length is expressed against a
fixed notional sensor that does not match a camera datablock's, so copying
``lens`` across produces a visibly different framing; the projection matrix is
what the viewport actually drew with.
"""

from __future__ import annotations

import math

import bpy

from mixar.config.logging_config import get_logger

from ..constants import (
    MARK_CAMERA_PREFIX,
    MARK_COLLECTION,
    MARK_SERIAL_DIGITS,
)

logger = get_logger(__name__)


def camera_name(serial):
    """``mixar_mark_view_0001``."""
    return f"{MARK_CAMERA_PREFIX}{int(serial):0{MARK_SERIAL_DIGITS}d}"


def bake_view(context, area, region, serial):
    """``(camera_name_or_None, view_dict)`` for the current viewport.

    The view dict always describes the frame, even when the camera could not
    be created — the image size and perspective flag are what the payload's
    normalized coordinates are relative to, and they must travel regardless.
    """
    space = area.spaces.active
    rv3d = getattr(space, "region_3d", None)
    if rv3d is None:
        return None, _view_dict(None, region, None, None, True, space)

    is_perspective = bool(getattr(rv3d, "is_perspective", True))
    angle_x, ortho_scale = _projection_from_window_matrix(rv3d, is_perspective)

    name = None
    try:
        name = _create_camera(context, rv3d, serial, is_perspective,
                              angle_x, ortho_scale, space)
    except Exception as exc:  # noqa: BLE001 — a mark without a camera is
        # still a perfectly good mark; only re-rendering the exact view is lost
        logger.warning("Scribble mark: could not bake view camera: %s", exc,
                       exc_info=True)

    lens_mm = None
    if is_perspective and angle_x:
        # Reported against a 36mm sensor, the convention the camera datablock
        # is created with, so the number matches what a lane would read off it.
        lens_mm = round(18.0 / math.tan(angle_x / 2.0), 3)

    return name, _view_dict(name, region, lens_mm, ortho_scale,
                            is_perspective, space, rv3d)


# =============================================================================
# Projection
# =============================================================================

def _projection_from_window_matrix(rv3d, is_perspective):
    """``(angle_x, ortho_scale)`` — whichever applies, the other is None.

    For a symmetric perspective frustum ``P[0][0] == 1 / tan(fov_x / 2)``;
    for an orthographic one ``P[0][0] == 2 / width``. Both read straight off
    the matrix the viewport drew with, so the baked camera reproduces the
    framing instead of approximating it.
    """
    try:
        scale_x = float(rv3d.window_matrix[0][0])
    except Exception as exc:  # noqa: BLE001
        logger.debug("Scribble mark: window matrix unreadable: %s", exc)
        return None, None

    if abs(scale_x) < 1e-9:
        return None, None

    if is_perspective:
        return 2.0 * math.atan(1.0 / abs(scale_x)), None
    return None, 2.0 / abs(scale_x)


def _create_camera(context, rv3d, serial, is_perspective, angle_x, ortho_scale,
                   space):
    """Create the baked camera in the marks collection. Returns its name."""
    name = camera_name(serial)

    data = bpy.data.cameras.new(name)
    # HORIZONTAL fit, because the values above were derived from the matrix's
    # X scale. Under AUTO fit Blender switches the meaning of angle/ortho_scale
    # to the LONGER axis, so a portrait region would silently be framed by its
    # height and the mark's coordinates would no longer land where drawn.
    data.sensor_fit = "HORIZONTAL"
    data.sensor_width = 36.0

    if is_perspective and angle_x:
        data.type = "PERSP"
        data.angle_x = angle_x
    elif ortho_scale:
        data.type = "ORTHO"
        data.ortho_scale = ortho_scale

    if space is not None:
        # Generous, and clamped to something valid: the viewport's own near
        # plane can sit well in front of geometry the user marked, and a
        # render from this camera clipping away the marked object would defeat
        # the point of baking it.
        data.clip_start = max(1e-4, float(getattr(space, "clip_start", 0.1)) * 0.1)
        data.clip_end = max(data.clip_start * 10.0,
                            float(getattr(space, "clip_end", 1000.0)) * 10.0)

    camera = bpy.data.objects.new(name, data)
    camera.matrix_world = rv3d.view_matrix.inverted_safe()
    # A baked view is a bookmark, not scenery: it must never appear in a
    # render, an export, or a selection sweep the agent does over the scene.
    camera.hide_render = True
    camera.hide_select = True

    _marks_collection(context).objects.link(camera)
    camera.hide_viewport = True
    return camera.name


def _marks_collection(context):
    """The hidden collection baked cameras live in, created on demand."""
    collection = bpy.data.collections.get(MARK_COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(MARK_COLLECTION)
        collection.hide_render = True
        context.scene.collection.children.link(collection)
    elif collection.name not in context.scene.collection.children:
        try:
            context.scene.collection.children.link(collection)
        except RuntimeError:
            # Already linked somewhere deeper in the tree; that is fine.
            pass
    return collection


def _view_dict(name, region, lens_mm, ortho_scale, is_perspective, space,
               rv3d=None):
    """The payload's description of the frozen frame."""
    matrix = []
    if rv3d is not None:
        try:
            world = rv3d.view_matrix.inverted_safe()
            matrix = [round(float(v), 6) for row in world for v in row]
        except Exception:  # noqa: BLE001
            matrix = []

    return {
        "camera": name,
        "matrix_world": matrix,
        "lens_mm": lens_mm,
        "ortho_scale": round(ortho_scale, 6) if ortho_scale else None,
        "is_perspective": is_perspective,
        "image_w": int(region.width),
        "image_h": int(region.height),
        "shading": getattr(getattr(space, "shading", None), "type", None),
    }


def release(name):
    """Delete a baked camera and its data. Never raises."""
    if not name:
        return
    try:
        camera = bpy.data.objects.get(name)
        if camera is None:
            return
        data = camera.data
        bpy.data.objects.remove(camera)
        if data is not None and data.users == 0:
            bpy.data.cameras.remove(data)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Scribble mark: could not release view camera %s: %s",
                     name, exc)

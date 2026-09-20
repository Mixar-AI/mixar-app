# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Context reads for the camera-first Export to Moodboard surface.

The rules live in `render_request` (pure, unit-tested). This is the thin layer
that feeds them from the live scene, so the menu row, the popup and the
operator all reach the SAME plan — a surface that offered a button its
operator would refuse is exactly the confusion this feature exists to fix.
"""

from __future__ import annotations

import bpy

from .anim_curves import camera_key_frames
from .render_request import build_export_plan, resolve_export_camera


def export_settings(scene):
    return getattr(scene, "mixar_camera_export", None)


def scene_has_camera(scene) -> bool:
    """Cheap enough for a menu draw: stops at the first camera it finds."""
    return any(
        getattr(obj, "type", None) == 'CAMERA'
        for obj in getattr(scene, "objects", ())
    )


def resolve_camera(context, settings=None):
    scene = context.scene
    settings = settings or export_settings(scene)
    return resolve_export_camera(
        scene,
        override=getattr(settings, "camera_override", None),
        active=getattr(context, "active_object", None),
        selected=getattr(context, "selected_objects", ()) or (),
    )


def render_busy() -> bool:
    # Imported here, not at module scope: this module is pulled in by the UI
    # draw path, which has no reason to load the whole render stack up front.
    from .render_outputs import render_job_active

    if render_job_active():
        return True
    try:
        return bool(bpy.app.is_job_running("RENDER"))
    except Exception:
        # A mocked or partially initialised bpy must never claim "busy" and
        # disable the surface outright.
        return False


def current_plan(context, *, camera=None, settings=None):
    """The plan the surface draws and the operator starts — one definition."""
    scene = context.scene
    settings = settings or export_settings(scene)
    if settings is None:
        return None, None
    camera = camera if camera is not None else resolve_camera(context, settings)
    plan = build_export_plan(
        scene,
        camera,
        camera_key_frames(camera),
        settings.render_output_types,
        range_source=settings.range_source,
        render_busy=render_busy(),
    )
    return camera, plan

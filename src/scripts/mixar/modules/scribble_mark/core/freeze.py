# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Freezing the viewport so the user can draw on it.

Arming mark mode captures the 3D viewport to a still, packs it into the
.blend, and draws it back over the region while navigation is blocked. The
viewport visibly becomes a paused frame you can mark up.

Freezing is not decoration. It buys three things that a live viewport cannot:

* **the pixels the user marked are the pixels the agent sees.** The still is
  attached to the turn, so there is no window in which an orbit, a redraw or
  a depsgraph tick can put the mark somewhere other than what was on screen.
* **marks stay valid while they are being drawn.** Multiple marks across one
  freeze share one frame of reference, so "move THIS over THERE" is two marks
  in the same coordinate system rather than two guesses in drifting ones.
* **an accidental orbit cannot silently invalidate a mark.** Without the
  block, a stray middle-drag mid-gesture would leave marks describing a view
  that no longer exists, with nothing on screen to say so.

The still is packed rather than left on disk: it lives in ``bpy.app.tempdir``,
which is cleaned when Blender exits, and a mark referencing a vanished image
would lose the one thing a VLM can actually read.
"""

from __future__ import annotations

import os
import time

import bpy

from mixar.config.logging_config import get_logger

from ..constants import (
    ANNOTATED_IMAGE_NAME,
    FROZEN_IMAGE_NAME,
    MARK_SERIAL_DIGITS,
)

logger = get_logger(__name__)


def frame_name(serial):
    """``mixar_mark_frame_0007`` — one datablock per freeze, not one reused.

    A fixed name looks tidy and is wrong: the frame is attached to a chat
    message by NAME, so re-arming would silently repoint an image an earlier
    message (and the backend's ``attachment_names``) already refers to. The
    user scrolls back and sees a different picture than the one they marked.
    """
    return f"{FROZEN_IMAGE_NAME}_{int(serial):0{MARK_SERIAL_DIGITS}d}"


def annotated_name(serial):
    """``mixar_mark_frame_annotated_0007`` — same reasoning as above."""
    return f"{ANNOTATED_IMAGE_NAME}_{int(serial):0{MARK_SERIAL_DIGITS}d}"


def capture_region_still(context, window, area, region, name):
    """Render *region*'s view to a packed image datablock. Returns its name.

    Returns None on failure; the caller reports that and refuses to arm,
    because a mark mode with nothing frozen under it would let the user draw
    on a live viewport that then moves.
    """
    from mixar.modules.space_mixie_chat.core.image_utils import (
        get_mixar_screenshots_dir,
    )

    scene = context.scene
    path = os.path.join(
        get_mixar_screenshots_dir(),
        f"mixar_mark_{os.getpid()}_{int(time.time() * 1000)}.png",
    )

    render = scene.render
    settings = render.image_settings
    saved = {
        "filepath": render.filepath,
        "resolution_x": render.resolution_x,
        "resolution_y": render.resolution_y,
        "resolution_percentage": render.resolution_percentage,
        "file_format": settings.file_format,
        "media_type": getattr(settings, "media_type", None),
    }

    try:
        render.filepath = path
        render.resolution_x = max(1, int(region.width))
        render.resolution_y = max(1, int(region.height))
        # 100% or the still is a different size from the region the marks were
        # captured in, and every normalized coordinate shifts against it.
        render.resolution_percentage = 100
        # media_type BEFORE file_format: on Blender 5 a scene whose output is
        # FFMPEG rejects PNG outright until the media type is IMAGE, so arming
        # would die on any scene that has been through Director's guide render
        # or that the user simply configured for video. The Director render
        # path documents the same ordering.
        if saved["media_type"] is not None:
            settings.media_type = "IMAGE"
        settings.file_format = "PNG"

        # view_context=True renders THIS viewport's shading and framing rather
        # than the scene camera. The override must name the WINDOW as well as
        # the area: the area can live in a different window from the one the
        # operator was invoked in (the Agent Bubble is its own window), and an
        # area/region override that disagrees with the context window is not a
        # coherent context.
        with context.temp_override(window=window, area=area, region=region):
            bpy.ops.render.opengl(write_still=True, view_context=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Scribble mark: viewport capture failed: %s", exc, exc_info=True)
        return None
    finally:
        render.filepath = saved["filepath"]
        render.resolution_x = saved["resolution_x"]
        render.resolution_y = saved["resolution_y"]
        render.resolution_percentage = saved["resolution_percentage"]
        # Restore media_type BEFORE file_format, mirroring the set order: a
        # legacy FFMPEG scene rejects its own saved format while the media
        # type still says IMAGE.
        if saved["media_type"] is not None:
            settings.media_type = saved["media_type"]
        settings.file_format = saved["file_format"]

    if not os.path.exists(path):
        logger.warning("Scribble mark: capture produced no file at %s", path)
        return None

    return _load_packed(path, name)


def _load_packed(path, name):
    """Load *path* into ``bpy.data.images`` under *name*, packed.

    Goes through the shared ``load_image_from_file`` rather than repeating
    load/name/pack/clear-filepath here: that helper already sets the sRGB
    colorspace and clears the temp path (Blender otherwise tries to re-read a
    file we are about to delete), and a second copy of those four steps is a
    second place for them to drift.

    The previous frozen frame is released first: one freeze is live at a time,
    and keeping every past capture would grow the .blend without bound.
    """
    from mixar.modules.common.utils.image_utils import load_image_from_file

    release(name)
    try:
        return load_image_from_file(path, name).name
    except Exception as exc:  # noqa: BLE001
        logger.warning("Scribble mark: could not pack frozen frame: %s", exc)
        return None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def release(name):
    """Drop a frozen frame datablock if it exists. Never raises."""
    try:
        existing = bpy.data.images.get(name)
        if existing is not None:
            bpy.data.images.remove(existing)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Scribble mark: could not release frozen frame %s: %s",
                     name, exc)


def get_image(name):
    """A frozen frame datablock by name, or None."""
    return bpy.data.images.get(name) if name else None

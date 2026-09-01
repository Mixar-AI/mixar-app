# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Drawing the marks onto a copy of the frozen frame.

The agent gets the frame **twice**: clean, and with the marks on it. That
split is not tidiness — burning the annotation into the only image you send
is a real failure. Everything downstream that consumes an image consumes this
one, and a generation model handed a picture with a cyan loop drawn on it
will faithfully reproduce the loop. It is the same lesson the ordered
reference-image contract already encodes by keeping ``component_cutout``
beside ``selection_mask`` instead of merging them.

The annotated copy exists for the vision half of the agent: it is what lets a
model *see* what the user circled, in context, at a glance. The clean copy is
what any generation step should actually work from.

Ink is drawn as a dark casing under a bright core, because a single-colour
stroke that reads on a light clay render disappears on a dark material
preview, and the frozen frame can be either.
"""

from __future__ import annotations

import io
import os
import time

from mixar.config.logging_config import get_logger

from ..constants import ANNOTATED_IMAGE_NAME

logger = get_logger(__name__)

#: Bright core and dark casing, in PIL's 0-255 RGB.
INK_CORE = (92, 230, 220)
INK_CASING = (8, 24, 28)

#: Casing is this many pixels wider than the core on each side.
CASING_PAD = 2

#: Core stroke width at a 1080-tall frame; scaled with the frame so a 4K
#: capture does not get a hairline.
BASE_WIDTH = 3.0
REFERENCE_HEIGHT = 1080.0


def render_annotated(image, marks, name=ANNOTATED_IMAGE_NAME):
    """Draw *marks* over a copy of *image*. Returns the new datablock's name.

    Returns None on any failure — the marks' resolved data is the load-bearing
    part of the payload, and losing the illustration must never lose the turn.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        logger.info("Scribble mark: PIL unavailable, sending the clean frame only")
        return None

    source = _source_bytes(image)
    if not source:
        return None

    try:
        with Image.open(io.BytesIO(source)) as opened:
            frame = opened.convert("RGB")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Scribble mark: could not decode frozen frame: %s", exc)
        return None

    width, height = frame.size
    if width <= 0 or height <= 0:
        return None

    scale = max(1.0, height / REFERENCE_HEIGHT)
    core_width = max(2, int(round(BASE_WIDTH * scale)))
    casing_width = core_width + CASING_PAD * 2

    draw = ImageDraw.Draw(frame)
    for mark in marks:
        points = _mark_points(mark, width, height)
        if len(points) < 2:
            _draw_dot(draw, points, casing_width, core_width)
            continue
        # Casing first, core over it — one pass each, so the join between
        # segments does not show the casing through the core.
        draw.line(points, fill=INK_CASING, width=casing_width, joint="curve")
        draw.line(points, fill=INK_CORE, width=core_width, joint="curve")

    return _pack_result(frame, name)


def _mark_points(mark, width, height):
    """A mark's outline in PIL pixel coordinates.

    Two conversions at once, and both matter: normalized to pixels, and
    ``v`` bottom-up (the payload's convention, matching the backend
    localizer) to PIL's top-down rows. Skipping the flip draws every mark
    mirrored across the horizon.
    """
    region = mark.get("region") or {}
    polygon = region.get("polygon") or []

    if len(polygon) >= 2:
        source = polygon
        closed = mark.get("closed")
    else:
        anchor = region.get("anchor")
        source = [anchor] if anchor else []
        closed = False

    points = [
        (float(u) * width, (1.0 - float(v)) * height)
        for u, v in source
    ]
    if closed and len(points) >= 3:
        points.append(points[0])
    return points


def _draw_dot(draw, points, casing_width, core_width):
    """A tap: no outline to trace, so it is drawn as a ring."""
    if not points:
        return
    x, y = points[0]
    outer = casing_width * 2
    inner = core_width * 2
    draw.ellipse([x - outer, y - outer, x + outer, y + outer], outline=INK_CASING,
                 width=max(1, casing_width // 2))
    draw.ellipse([x - inner, y - inner, x + inner, y + inner], outline=INK_CORE,
                 width=max(1, core_width // 2))


def _source_bytes(image):
    """Encoded bytes of a packed image datablock, or None.

    Read from ``packed_file`` rather than ``image.pixels``: the frame is a
    full-screen capture, and a float ``foreach_get`` over it is tens of
    megabytes plus a re-encode for a picture we already have losslessly.
    """
    try:
        packed = getattr(image, "packed_file", None)
        if packed is not None and packed.data:
            return bytes(packed.data)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Scribble mark: packed frame unreadable: %s", exc)

    try:
        import bpy
        path = bpy.path.abspath(image.filepath_raw or image.filepath or "")
        if path and os.path.isfile(path):
            with open(path, "rb") as handle:
                return handle.read()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Scribble mark: frozen frame file unreadable: %s", exc)
    return None


def _pack_result(frame, name):
    """Write the annotated frame into ``bpy.data.images``, packed."""
    import bpy

    from mixar.modules.space_mixie_chat.core.image_utils import (
        get_mixar_screenshots_dir,
    )

    path = os.path.join(
        get_mixar_screenshots_dir(),
        f"mixar_mark_annotated_{os.getpid()}_{int(time.time() * 1000)}.png",
    )
    try:
        frame.save(path, format="PNG", optimize=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Scribble mark: could not write annotated frame: %s", exc)
        return None

    try:
        existing = bpy.data.images.get(name)
        if existing is not None:
            bpy.data.images.remove(existing)
        loaded = bpy.data.images.load(path, check_existing=False)
        loaded.name = name
        loaded.pack()
        loaded.filepath_raw = ""
        return loaded.name
    except Exception as exc:  # noqa: BLE001
        logger.warning("Scribble mark: could not pack annotated frame: %s", exc)
        return None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

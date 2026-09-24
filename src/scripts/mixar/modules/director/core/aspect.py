# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Aspect ratio as a RATIO, applied over the scene's current short side.

Director used to write an aspect as a pixel size (16:9 -> 1920x1080), which
made aspect and resolution fight each other: 2.39:1 wrote 2390x1000, whose
short side matched no tier, so the resolution segment lit nothing and the next
tier click reshaped the frame. Keeping the short side makes the two settings
orthogonal — the tier is the quality, the ratio is the shape.

Pure arithmetic lives in `resolution_for_ratio` so the rounding is pinned
without a running Blender.
"""

from __future__ import annotations

from math import gcd

#: Never let a ratio collapse the frame; Blender's own minimum is 4.
MIN_SIDE = 4


def normalise_ratio(width: int, height: int) -> tuple[int, int]:
    """The smallest integer pair with the same ratio."""
    width = max(1, int(width))
    height = max(1, int(height))
    divisor = gcd(width, height)
    return width // divisor, height // divisor


def scene_ratio(scene) -> tuple[int, int]:
    """The ratio the scene's render size currently has."""
    render = scene.render
    return normalise_ratio(render.resolution_x, render.resolution_y)


def resolution_for_ratio(
    ratio_w: int, ratio_h: int, current_w: int, current_h: int
) -> tuple[int, int]:
    """Render size with *ratio* at the short side *current* already has.

    The SHORT side is preserved, never the width: a portrait scene switched to
    16:9 must not become 1080x607 — it becomes 1920x1080, the same quality
    rotated. The result is rounded and clamped, never zero.
    """
    ratio_w = max(1, int(ratio_w))
    ratio_h = max(1, int(ratio_h))
    short = max(MIN_SIDE, min(int(current_w), int(current_h)))
    if ratio_w >= ratio_h:
        return max(MIN_SIDE, int(round(short * ratio_w / ratio_h))), short
    return short, max(MIN_SIDE, int(round(short * ratio_h / ratio_w)))


def apply_ratio(scene, ratio_w: int, ratio_h: int) -> tuple[int, int]:
    """Reshape the scene's output to *ratio*, keeping its short side."""
    render = scene.render
    width, height = resolution_for_ratio(
        ratio_w, ratio_h, render.resolution_x, render.resolution_y
    )
    render.resolution_x = width
    render.resolution_y = height
    # A director-facing aspect is the SHAPE OF THE FRAME; a non-square pixel
    # aspect would silently mean something else was also stretching it.
    render.pixel_aspect_x = 1.0
    render.pixel_aspect_y = 1.0
    return width, height


#: Above this, a reduced ratio stops reading as a ratio ("37:20") and the
#: cinema decimal form ("1.85:1") is what a director recognises.
_TIDY_DENOMINATOR = 16


def ratio_label(ratio_w: int, ratio_h: int) -> str:
    """"16:9", or the cinema decimal form for ratios that do not reduce tidily.

    1.85:1 reduces to 37:20 and 2.39:1 to 239:100 — both are the ratio and
    neither is how anyone says it. Mirrors `aspect_label` in
    `view3d_director_cinema_left.cc`; keep the two in step.
    """
    ratio_w, ratio_h = normalise_ratio(ratio_w, ratio_h)
    if min(ratio_w, ratio_h) <= _TIDY_DENOMINATOR:
        return f"{ratio_w}:{ratio_h}"
    if ratio_w >= ratio_h:
        return f"{ratio_w / ratio_h:.2f}:1"
    return f"1:{ratio_h / ratio_w:.2f}"


# -------------------------------------------------------------------------
# Per-camera aspect.
#
# Blender has exactly one render size, and it belongs to the scene — there is
# no per-camera resolution to bind to. A director works the other way round:
# the 2.39:1 hero shot and the 9:16 social cutdown are two cameras in one
# scene, and a ratio picked for one must not silently reshape the other.
#
# Director therefore REMEMBERS a ratio on each camera's data
# (`camera.mixar_director_output`) and writes it into `scene.render` whenever
# that camera becomes the live one. The scene stays the single source of truth
# for what will actually render; the camera just says what to put there.
#
# A camera that has never had a ratio picked is left alone: switching to it
# keeps whatever the scene has, rather than snapping the frame to a default
# nobody chose.


def camera_output(camera):
    """The per-camera aspect store on *camera*'s data, or ``None``."""
    data = getattr(camera, "data", None)
    return getattr(data, "mixar_director_output", None)


def camera_ratio(camera) -> tuple[int, int] | None:
    """The ratio *camera* remembers, or ``None`` when it has never had one."""
    output = camera_output(camera)
    if output is None or not output.configured:
        return None
    return normalise_ratio(output.aspect_x, output.aspect_y)


def remember_camera_ratio(camera, ratio_w: int, ratio_h: int) -> bool:
    """Record *ratio* as *camera*'s own. False when there is nowhere to put it."""
    output = camera_output(camera)
    if output is None:
        return False
    output.aspect_x, output.aspect_y = normalise_ratio(ratio_w, ratio_h)
    output.configured = True
    return True


def apply_camera_ratio(scene, camera) -> bool:
    """Reshape the scene to *camera*'s remembered ratio. False when it has none.

    Called when the live camera changes. Never raises: it runs from property
    update callbacks, which also fire during file load when the render
    settings may not be reachable yet.
    """
    try:
        ratio = camera_ratio(camera)
        if ratio is None:
            return False
        if scene_ratio(scene) == ratio:
            # Already the right shape; writing would dirty the file and push
            # an undo step for nothing.
            return False
        apply_ratio(scene, *ratio)
    except (AttributeError, ReferenceError, TypeError):
        return False
    return True

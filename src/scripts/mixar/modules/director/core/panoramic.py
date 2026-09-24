# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A panoramic lens is previewed in Cycles, in the Rendered viewport.

Blender draws a panoramic camera (equirectangular, fisheye, mirror ball, ...)
only through Cycles. EEVEE, Solid and Material Preview all show it as a plain
perspective, so picking Panoramic used to change nothing on screen and the
only hint was a caption in the lens popup. Choosing the lens now also chooses
what it takes to see it: the scene renders with Cycles and the Cinema
viewport shades Rendered.

Nothing is switched back when another lens is picked: both are ordinary
scene and viewport settings the director may want to keep.
"""

from __future__ import annotations

from mixar.config.logging_config import get_logger

from .viewport import find_view3d_context

logger = get_logger(__name__)

PANORAMIC_ENGINE = "CYCLES"
PANORAMIC_SHADING = 'RENDERED'


def show_panoramic_lens(context) -> list[str]:
    """Put the scene in Cycles and the Cinema viewport in Rendered shading.

    Returns what could not be done, for the operator to report. The engine
    comes first: Rendered shading without Cycles is EEVEE, which is exactly
    the plain perspective this exists to avoid, so the viewport is left
    alone when Cycles is unavailable (not built, or its add-on disabled).
    """
    render = context.scene.render
    if render.engine != PANORAMIC_ENGINE:
        try:
            render.engine = PANORAMIC_ENGINE
        except (TypeError, ValueError) as exc:
            logger.warning("Panoramic lens: Cycles is unavailable: %s", exc)
            return [
                "Cycles is not available, so the panoramic lens previews as a "
                "plain perspective"
            ]
    target = find_view3d_context(context)
    if target is None:
        return []
    _window, area, _region, space = target
    shading = getattr(space, "shading", None)
    if shading is not None and shading.type != PANORAMIC_SHADING:
        shading.type = PANORAMIC_SHADING
    area.tag_redraw()
    return []

# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Toast text metrics and placement in the uncovered viewport."""

import bpy
import blf

from .constants import TOAST_CORNER_OFFSET_X

_FONT_ID = 0

# The layout constants were authored on a Retina display where Blender's
# UI_SCALE_FAC (``preferences.system.ui_scale`` == ``U.scale_factor`` ==
# ``dpi / 72``, which folds in the native pixel size) is ~2.0. We normalise
# by that so the toast keeps its authored size on Retina and scales down on
# lower-DPI external monitors — matching how every native Blender widget
# scales. Without this the toast draws at fixed pixels and looks oversized
# when the window moves to a display with a different scale factor.
_AUTHORED_SCALE = 2.0


def _scale() -> float:
    """Current UI scale relative to the authored (Retina) baseline."""
    try:
        return float(bpy.context.preferences.system.ui_scale) / _AUTHORED_SCALE
    except Exception:  # noqa: BLE001 — preferences unavailable (headless/tests)
        return 1.0


def _fsize(base: float, s: float) -> int:
    """Scale a font point size, clamped to a sane minimum."""
    return max(1, int(round(base * s)))


def _wrap_text(text: str, font_size: int, max_width: float) -> list[str]:
    """Word-wrap text to fit within max_width pixels using BLF metrics.

    Explicit newlines in *text* are honored as hard line breaks — each is
    wrapped independently — so callers can force a new line with ``\\n``.
    """
    blf.size(_FONT_ID, font_size)

    lines: list[str] = []
    for segment in text.split("\n"):
        words = segment.split()
        if not words:
            continue

        current_line = words[0]
        for word in words[1:]:
            test = current_line + " " + word
            w, _ = blf.dimensions(_FONT_ID, test)
            if w <= max_width:
                current_line = test
            else:
                lines.append(current_line)
                current_line = word

        lines.append(current_line)

    return lines



def toast_right_edge(region, area, wm, scale):
    """Use native region bounds so the drawer/sidebar cannot paint over toasts.

    The drawer reserves its full region for the duration of its slide. Its
    open amount gates that reservation; no canvas geometry is reconstructed.
    """
    edge = region.x + region.width
    drawer_open = getattr(wm, "mixar_moodboard_drawer_amount", 0.0) > 0.0
    for overlay in area.regions:
        if overlay.width <= 1 or overlay.x <= region.x:
            continue
        if overlay.type == 'UI' or (overlay.type == 'TOOL_PROPS' and drawer_open):
            edge = min(edge, overlay.x)
    return edge - region.x - TOAST_CORNER_OFFSET_X * scale

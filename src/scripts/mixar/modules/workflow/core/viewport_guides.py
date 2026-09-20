# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Zen Mode viewport guides: grid, relationship lines and object extras.

The floating shading strip's neighbour chip flips the floor/ortho grid,
axis lines, relationship lines, and the object extras that draw lights,
cameras and empties together, so the calm canvas stays one decision
rather than several overlay flags. The chip paints pressed when any of
those guides are visible; a click settles every flag onto the opposite
answer so a mixed overlay state never survives a toggle.
"""

from __future__ import annotations

# Floor + axes + fixed-plane ortho grid (Top/Right/Front) + parenting lines
# + object extras (the light, camera and empty helpers). `show_extras` is
# the drawing flag only: lights keep lighting the scene, so a Rendered or
# Material Preview viewport is unchanged by the chip.
_GUIDE_FLAGS = (
    "show_floor",
    "show_axis_x",
    "show_axis_y",
    "show_ortho_grid",
    "show_relationship_lines",
    "show_extras",
)


def guides_shown(space) -> bool:
    """Whether any grid / relationship guide the chip controls is visible."""
    overlay = getattr(space, "overlay", None)
    if overlay is None:
        return False
    return bool(
        getattr(overlay, "show_floor", False)
        or getattr(overlay, "show_relationship_lines", False)
    )


def toggle_guides(space) -> bool:
    """Flip grid, relationship lines and extras together; return the new state."""
    overlay = getattr(space, "overlay", None)
    if overlay is None:
        return False
    shown = not guides_shown(space)
    for name in _GUIDE_FLAGS:
        if hasattr(overlay, name):
            setattr(overlay, name, shown)
    return shown
